"""Mapeamento PURO Ploomes -> schemas do Prospector (sem rede, sem banco; testavel isoladamente).

So campos de empresa e de negocio sao lidos; nenhum dado de pessoa entra (LGPD). Regras em config/ploomes.yaml."""
from __future__ import annotations
import re
from functools import lru_cache
from app.core.settings import get_settings
from app.core.utils import identity_domain, load_yaml, norm_text
from app.discovery.historical import is_cnpj_suspect
from app.integrations.ploomes.client import ODataQuery, PloomesContractError
from app.models.schemas import Candidate, PloomesCompany, PloomesDeal
from app.scoring.score import canonical_segment

CNPJ_DIGITS = 14
CUSTOM_VALUE_KEYS = ("StringValue", "BigStringValue", "ObjectValueName")
CONTACT_SELECT = ("Id", "Name", "LegalName", "Website", "CNPJ", "TypeId", "LastUpdateDate")
CONTACT_EXPAND_BASE = "City($select=Name),State($select=Short),LineOfBusiness($select=Name)"
DEAL_SELECT = ("Id", "ContactId", "PipelineId", "StageId", "StatusId", "LossReasonId", "Amount", "CreateDate", "LastUpdateDate")
DEAL_EXPAND_BASE = "Contact($select=Id,TypeId,CompanyId),Stage($select=Name),LossReason($select=Name)"


@lru_cache
def rules() -> dict:
    return load_yaml(get_settings().config_dir / "ploomes.yaml")


def forbidden_fields() -> frozenset[str]:
    return frozenset(rules()["forbidden_fields"])


def allowed_pipelines() -> dict[int, str]:
    return {int(k): v for k, v in rules()["pipelines"].items()}


def _other_properties_expand(field_keys: list[str]) -> str:
    keys = " or ".join(f"FieldKey eq '{k}'" for k in field_keys)
    return f"OtherProperties($filter={keys};$select=FieldKey,{','.join(CUSTOM_VALUE_KEYS)})"


def _since_filter(since: str | None) -> str:
    return f" and LastUpdateDate ge {since}" if since else ""


def pipelines_filter() -> str:
    return "(" + " or ".join(f"PipelineId eq {p}" for p in allowed_pipelines()) + ")"


def company_query(contact_field_keys: dict[str, str], since: str | None = None) -> ODataQuery:
    return ODataQuery("Contacts", CONTACT_SELECT, f"TypeId eq {rules()['company_type_id']}{_since_filter(since)}",
                      f"{CONTACT_EXPAND_BASE},{_other_properties_expand(list(contact_field_keys.values()))}")


def deal_query(deal_field_keys: dict[str, str], since: str | None = None) -> ODataQuery:
    return ODataQuery("Deals", DEAL_SELECT, f"{pipelines_filter()}{_since_filter(since)}",
                      f"{DEAL_EXPAND_BASE},{_other_properties_expand(list(deal_field_keys.values()))}", order_by="LastUpdateDate,Id")


def resolve_field_keys(fields: list[dict]) -> tuple[dict[str, str], dict[str, str]]:
    """Nomes configurados -> FieldKey real da conta. Campo ausente e erro explicito (contrato quebrado)."""
    by_entity = {1: {f["Name"]: f["Key"] for f in fields if f.get("EntityId") == 1},
                 2: {f["Name"]: f["Key"] for f in fields if f.get("EntityId") == 2}}
    resolved = []
    for entity_id, section in ((1, "contact"), (2, "deal")):
        wanted = rules()["custom_fields"][section]
        missing = [name for name in wanted.values() if name not in by_entity[entity_id]]
        if missing:
            raise PloomesContractError(f"Campos personalizados não encontrados no Ploomes ({section}): {', '.join(missing)}")
        resolved.append({use: by_entity[entity_id][name] for use, name in wanted.items()})
    return resolved[0], resolved[1]


def custom_value(row: dict, field_key: str) -> str | None:
    for prop in row.get("OtherProperties") or []:
        if prop.get("FieldKey") != field_key:
            continue
        for key in CUSTOM_VALUE_KEYS:
            value = prop.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _name_of(row: dict, relation: str, attribute: str = "Name") -> str | None:
    value = (row.get(relation) or {}).get(attribute)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _cnpj(value) -> str | None:
    digits = re.sub(r"\D", "", str(value or ""))
    return digits if len(digits) == CNPJ_DIGITS else None


def company_from_api(row: dict, contact_field_keys: dict[str, str]) -> PloomesCompany:
    alert = custom_value(row, contact_field_keys["registration_alert"])
    suspect = is_cnpj_suspect(alert)
    segment_label = _name_of(row, "LineOfBusiness")
    city = _name_of(row, "City")
    name = (row.get("Name") or row.get("LegalName") or f"Empresa Ploomes #{row['Id']}").strip()
    return PloomesCompany(
        contact_id=row["Id"],
        candidate=Candidate(name=name, domain=identity_domain(row.get("Website")), cnpj=None if suspect else _cnpj(row.get("CNPJ")),
                            municipio=city.title() if city else None, uf=_name_of(row, "State", "Short"),
                            segment=canonical_segment(segment_label), source="ploomes"),
        segment_label=segment_label, registration_alert=alert, cnpj_suspect=suspect, last_update=row.get("LastUpdateDate"))


def outcome_of(status_id: int | None) -> str | None:
    return {v: k for k, v in rules()["deal_status"].items()}.get(status_id)


def loss_category(reason: str | None) -> str:
    return rules()["loss_categories"].get(norm_text(reason or ""), rules()["default_loss_category"])


def company_contact_of(row: dict) -> int | None:
    """Empresa dona do negocio. Negocio de pessoa so vale se a pessoa estiver vinculada a uma empresa."""
    contact = row.get("Contact") or {}
    if contact.get("TypeId") == rules()["company_type_id"]:
        return contact.get("Id")
    return contact.get("CompanyId")


def deal_from_api(row: dict, deal_field_keys: dict[str, str]) -> PloomesDeal | None:
    """None quando o negocio nao tem empresa identificavel ou status desconhecido (ignorado e contado pelo chamador)."""
    company = company_contact_of(row)
    outcome = outcome_of(row.get("StatusId"))
    if company is None or outcome is None:
        return None
    reason = _name_of(row, "LossReason") if outcome == "lost" else None
    created = row.get("CreateDate") or ""
    return PloomesDeal(
        deal_id=row["Id"], company_contact_id=company, outcome=outcome,
        funnel=rules()["pipeline_funnel"].get(row.get("PipelineId"), str(row.get("PipelineId"))),
        stage=_name_of(row, "Stage"), amount=float(row.get("Amount") or 0.0),
        loss_reason=reason, loss_category=loss_category(reason) if outcome == "lost" else None,
        best_offer=custom_value(row, deal_field_keys["best_offer"]), priority=custom_value(row, deal_field_keys["priority"]),
        segment_label=custom_value(row, deal_field_keys["segment"]),
        created_month=created[:7] or None, last_update=row.get("LastUpdateDate"))
