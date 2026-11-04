"""Monta a lista de CNPJ do ICP a partir dos dados abertos da Receita (compartilhamento publico SERPRO+/Nextcloud).

Roda fora do app, todo mes, no GitHub Actions (.github/workflows/cnpj-feed.yml): a base completa tem ~7 GB, entao cada
zip e baixado, lido em streaming e apagado antes do proximo; so o recorte do ICP (alguns MB) sai daqui. O app apenas
baixa esse recorte (app/discovery/feed.py) e segue o fluxo normal, com aprovacao humana.

LGPD: socios, telefone e e-mail nunca sao lidos para a saida; empresario individual (nome + CPF na razao social) e
descartado pela natureza juridica (config/icp.yaml, receita.exclude_naturezas).

Uso: python -m app.discovery.receita_feed --out cnpj_icp.csv"""
from __future__ import annotations
import argparse, csv, io, re, tempfile, time, zipfile
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
import httpx
from app.core.settings import get_settings
from app.core.utils import load_yaml
from app.discovery.sources import matches_icp

FEED_COLUMNS = ["cnpj", "razao_social", "nome_fantasia", "cnae", "uf", "municipio", "porte", "situacao"]
SHARD_COUNT = 10                         # Estabelecimentos0..9.zip e Empresas0..9.zip
ACTIVE = "02"
PORTE = {"01": "MICRO EMPRESA", "03": "EMPRESA DE PEQUENO PORTE", "05": "DEMAIS"}
# Posicoes no layout da Receita (arquivos sem cabecalho, separador ';', latin-1)
EST_CNPJ_BASICO, EST_CNPJ_ORDEM, EST_CNPJ_DV, EST_NOME_FANTASIA, EST_SITUACAO = 0, 1, 2, 4, 5
EST_CNAE, EST_UF, EST_MUNICIPIO = 11, 19, 20
EMP_CNPJ_BASICO, EMP_RAZAO_SOCIAL, EMP_NATUREZA, EMP_PORTE = 0, 1, 2, 5
CNPJ_BASICO_LEN = 8
MONTH_FOLDER = re.compile(r"/(\d{4}-\d{2})/</d:href>")
DOWNLOAD_ATTEMPTS = 5
RETRY_BACKOFF_S = 15
TIMEOUT_S = 120


class FeedBuildError(RuntimeError):
    pass


@dataclass(frozen=True)
class Company:
    razao_social: str
    natureza: str
    porte: str


# --- regras puras (testaveis sem rede) ---------------------------------------------------------------------------
def latest_month(propfind_xml: str) -> str:
    """Pasta AAAA-MM mais recente na listagem WebDAV do compartilhamento."""
    months = MONTH_FOLDER.findall(propfind_xml)
    if not months:
        raise FeedBuildError("Nenhuma pasta mensal encontrada no compartilhamento da Receita (o link mudou?).")
    return max(months)


def parse_municipios(rows: Iterable[list[str]]) -> dict[str, str]:
    return {fields[0]: fields[1] for fields in rows if len(fields) >= 2}


def _icp_ufs(icps: list[dict]) -> set[str] | None:
    """UFs que interessam; None quando algum ICP nao restringe UF (todas servem)."""
    ufs = {(icp.get("uf") or "").upper() for icp in icps}
    return None if "" in ufs else ufs


def _establishment_row(fields: list[str], municipios: dict[str, str]) -> dict:
    return {"cnpj": fields[EST_CNPJ_BASICO] + fields[EST_CNPJ_ORDEM] + fields[EST_CNPJ_DV], "razao_social": "",
            "nome_fantasia": fields[EST_NOME_FANTASIA].strip(), "cnae": fields[EST_CNAE], "uf": fields[EST_UF],
            "municipio": municipios.get(fields[EST_MUNICIPIO], ""), "porte": "", "situacao": "ATIVA"}


def select_establishments(rows: Iterable[list[str]], icps: list[dict], municipios: dict[str, str]) -> Iterator[dict]:
    """Estabelecimentos ativos que casam com algum ICP. Situacao e UF sao checadas antes de montar o dict porque a
    base tem dezenas de milhoes de linhas."""
    ufs = _icp_ufs(icps)
    for fields in rows:
        if len(fields) <= EST_MUNICIPIO or fields[EST_SITUACAO] != ACTIVE:
            continue
        if ufs is not None and fields[EST_UF] not in ufs:
            continue
        row = _establishment_row(fields, municipios)
        if any(matches_icp(row, icp["cnae_prefixes"], icp.get("uf"), icp.get("municipios")) for icp in icps):
            yield row


def select_companies(rows: Iterable[list[str]], cnpj_basicos: set[str]) -> dict[str, Company]:
    return {fields[EMP_CNPJ_BASICO]: Company(fields[EMP_RAZAO_SOCIAL].strip(), fields[EMP_NATUREZA], PORTE.get(fields[EMP_PORTE], ""))
            for fields in rows if len(fields) > EMP_PORTE and fields[EMP_CNPJ_BASICO] in cnpj_basicos}


def join_feed(establishments: list[dict], companies: dict[str, Company], exclude_naturezas: set[str]) -> list[dict]:
    """Completa razao social e porte; descarta estabelecimento sem empresa na base ou com natureza excluida."""
    out = []
    for row in establishments:
        company = companies.get(row["cnpj"][:CNPJ_BASICO_LEN])
        if not company or company.natureza in exclude_naturezas:
            continue
        out.append({**row, "razao_social": company.razao_social, "porte": company.porte})
    return out


# --- I/O: compartilhamento da Receita ----------------------------------------------------------------------------
def download(client: httpx.Client, url: str, target: Path, sleep: Callable[[float], None] = time.sleep) -> None:
    """Baixa com retomada (Range) e confere o tamanho final: o servidor da Receita costuma derrubar conexoes longas.
    Sempre comeca do zero - pedir Range a partir do fim de um arquivo ja completo trava o servidor."""
    target.unlink(missing_ok=True)
    expected = None
    for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
        try:
            expected = _fetch_into(client, url, target) or expected
            size = target.stat().st_size
            if expected is None or size >= expected:
                return
            problem = f"arquivo incompleto ({size} de {expected} bytes)"
        except httpx.HTTPError as exc:
            problem = str(exc)
        if attempt == DOWNLOAD_ATTEMPTS:
            raise FeedBuildError(f"Falha ao baixar {url}: {problem}")
        print(f"  tentativa {attempt} falhou ({problem}); retomando em {attempt * RETRY_BACKOFF_S} s", flush=True)
        sleep(attempt * RETRY_BACKOFF_S)


def _fetch_into(client: httpx.Client, url: str, target: Path) -> int | None:
    """Uma tentativa: continua de onde o arquivo parou. Devolve o tamanho total anunciado pelo servidor, se houver."""
    offset = target.stat().st_size if target.exists() else 0
    with client.stream("GET", url, headers={"Range": f"bytes={offset}-"} if offset else {}) as response:
        response.raise_for_status()
        resumed = response.status_code == httpx.codes.PARTIAL_CONTENT
        with open(target, "ab" if resumed else "wb") as f:
            for chunk in response.iter_bytes():         # sem buffer: o que chegou fica no disco se a conexao cair
                f.write(chunk)
    return _announced_size(response.headers, resumed)


def _announced_size(headers: httpx.Headers, resumed: bool) -> int | None:
    if resumed:
        total = headers.get("Content-Range", "").rpartition("/")[2]       # "bytes 3-5/6"
        return int(total) if total.isdigit() else None
    length = headers.get("Content-Length", "")
    return int(length) if length.isdigit() else None


def zip_rows(path: Path) -> Iterator[list[str]]:
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            with archive.open(name) as raw:
                yield from csv.reader(io.TextIOWrapper(raw, encoding="latin-1", newline=""), delimiter=";")


def _remote_zip_rows(client: httpx.Client, url: str, workdir: Path) -> Iterator[list[str]]:
    path = workdir / url.rsplit("/", 1)[-1]
    print(f"baixando {path.name}", flush=True)
    download(client, url, path)
    try:
        yield from zip_rows(path)
    finally:
        path.unlink(missing_ok=True)       # libera o disco antes do proximo zip


def _shard_rows(client: httpx.Client, base_url: str, prefix: str, workdir: Path) -> Iterator[list[str]]:
    for index in range(SHARD_COUNT):
        yield from _remote_zip_rows(client, f"{base_url}/{prefix}{index}.zip", workdir)


def _latest_month_url(client: httpx.Client, share_url: str) -> tuple[str, str]:
    response = client.request("PROPFIND", share_url + "/", headers={"Depth": "1"})
    response.raise_for_status()
    month = latest_month(response.text)
    return month, f"{share_url}/{month}"


def build_feed(client: httpx.Client, cfg: dict) -> tuple[str, list[dict]]:
    """Devolve (mes da base, linhas do recorte do ICP no formato do extrato)."""
    month, base_url = _latest_month_url(client, cfg["receita"]["share_url"].rstrip("/"))
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        municipios = parse_municipios(_remote_zip_rows(client, f"{base_url}/Municipios.zip", workdir))
        establishments = list(select_establishments(_shard_rows(client, base_url, "Estabelecimentos", workdir), cfg["icps"], municipios))
        print(f"{len(establishments)} estabelecimento(s) casaram com algum ICP", flush=True)
        basicos = {row["cnpj"][:CNPJ_BASICO_LEN] for row in establishments}
        companies = select_companies(_shard_rows(client, base_url, "Empresas", workdir), basicos)
    return month, join_feed(establishments, companies, set(cfg["receita"].get("exclude_naturezas", [])))


def write_feed(rows: list[dict], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FEED_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Gera o recorte do ICP a partir da base de CNPJ da Receita.")
    parser.add_argument("--out", type=Path, required=True, help="CSV de saida (um resumo .txt e gravado ao lado)")
    args = parser.parse_args(argv)
    settings = get_settings()
    cfg = load_yaml(settings.config_dir / "icp.yaml")
    with httpx.Client(timeout=TIMEOUT_S, follow_redirects=True, headers={"User-Agent": settings.user_agent}) as client:
        month, rows = build_feed(client, cfg)
    write_feed(rows, args.out)
    summary = f"Base da Receita {month}: {len(rows)} empresa(s) dentro dos ICPs de config/icp.yaml."
    args.out.with_suffix(".txt").write_text(summary + "\n", encoding="utf-8")
    print(summary)


if __name__ == "__main__":
    main()
