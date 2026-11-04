"""Coletor da base de CNPJ da Receita (app/discovery/receita_feed.py) contra um compartilhamento falso (MockTransport),
sem rede. Cobre o filtro por ICP no layout posicional da Receita, a minimizacao LGPD (sem contato, sem empresario
individual), a retomada de download e o contrato com a geracao de candidatos do app."""
import io
import zipfile
import httpx
import pytest
from app.discovery import generation as gen
from app.discovery import receita_feed as rf
from app.discovery import review

ICPS = [{"id": "ind", "cnae_prefixes": ["25"], "uf": "MG", "municipios": ["itajuba"]}]
MUNICIPIOS = {"4647": "ITAJUBA", "5049": "POUSO ALEGRE"}
PHONE, EMAIL = "35999990000", "contato@alfa.com.br"
SHARE = "https://receita.test/dav/CNPJ"


def _est(basico: str, uf: str = "MG", municipio: str = "4647", cnae: str = "2512800", situacao: str = "02") -> list[str]:
    fields = [""] * 30
    fields[0:3] = [basico, "0001", "44"]
    fields[4], fields[5], fields[11], fields[19], fields[20] = f"Fantasia {basico}", situacao, cnae, uf, municipio
    fields[22], fields[27] = PHONE, EMAIL                   # telefone e e-mail existem na base, nunca na saida
    return fields


def _emp(basico: str, natureza: str = "2062", porte: str = "03") -> list[str]:
    return [basico, f"Razao {basico} LTDA", natureza, "49", "1000,00", porte, ""]


def _zip(rows: list[list[str]]) -> bytes:
    text = "".join(";".join(f'"{v}"' for v in row) + "\n" for row in rows)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("K3241.K03200Y0.D61010.ESTABELE", text.encode("latin-1"))
    return buf.getvalue()


def test_only_active_establishments_inside_some_icp_are_selected():
    rows = [_est("11111111"), _est("22222222", situacao="08"), _est("33333333", uf="SP"),
            _est("44444444", cnae="4711300"), _est("55555555", municipio="5049")]
    selected = list(rf.select_establishments(rows, ICPS, MUNICIPIOS))
    assert [r["cnpj"] for r in selected] == ["11111111000144"]
    assert selected[0]["municipio"] == "ITAJUBA" and selected[0]["situacao"] == "ATIVA"


def test_icp_without_uf_does_not_drop_other_states():
    icps = [{"id": "br", "cnae_prefixes": ["25"]}]
    assert len(list(rf.select_establishments([_est("1", uf="SP"), _est("2")], icps, MUNICIPIOS))) == 2


def test_join_fills_company_data_and_drops_individual_entrepreneurs():
    establishments = list(rf.select_establishments([_est("11111111"), _est("22222222"), _est("33333333")], ICPS, MUNICIPIOS))
    companies = rf.select_companies([_emp("11111111"), _emp("22222222", natureza="2135")], {"11111111", "22222222", "33333333"})
    rows = rf.join_feed(establishments, companies, {"2135"})
    assert [(r["cnpj"], r["razao_social"], r["porte"]) for r in rows] == [("11111111000144", "Razao 11111111 LTDA", "EMPRESA DE PEQUENO PORTE")]


def test_latest_month_picks_newest_folder():
    xml = ("<d:href>/dav/CNPJ/2026-09/</d:href><d:href>/dav/CNPJ/2026-10/</d:href>"
           "<d:href>/dav/CNPJ/cnpj.tar.gz</d:href>")
    assert rf.latest_month(xml) == "2026-10"
    with pytest.raises(rf.FeedBuildError):
        rf.latest_month("<d:multistatus/>")


class _DroppedStream(httpx.SyncByteStream):
    def __iter__(self):
        yield b"abc"
        raise httpx.ReadError("conexao derrubada")


def test_download_resumes_from_where_the_connection_dropped(tmp_path):
    ranges = []

    def handler(request: httpx.Request) -> httpx.Response:
        ranges.append(request.headers.get("Range"))
        if len(ranges) == 1:
            return httpx.Response(200, stream=_DroppedStream())
        return httpx.Response(206, content=b"def")

    target = tmp_path / "Estabelecimentos0.zip"
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        rf.download(client, f"{SHARE}/2026-10/Estabelecimentos0.zip", target, sleep=lambda s: None)
    assert target.read_bytes() == b"abcdef"
    assert ranges == [None, "bytes=3-"]


def test_truncated_body_without_network_error_is_completed(tmp_path):
    ranges = []

    def handler(request: httpx.Request) -> httpx.Response:
        ranges.append(request.headers.get("Range"))
        if len(ranges) == 1:
            return httpx.Response(200, headers={"Content-Length": "6"}, stream=httpx.ByteStream(b"abc"))
        return httpx.Response(206, headers={"Content-Range": "bytes 3-5/6"}, content=b"def")

    target = tmp_path / "Empresas0.zip"
    target.write_bytes(b"sobra de uma execucao anterior")      # nunca e reaproveitado
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        rf.download(client, f"{SHARE}/2026-10/Empresas0.zip", target, sleep=lambda s: None)
    assert target.read_bytes() == b"abcdef"
    assert ranges == [None, "bytes=3-"]


def test_download_gives_up_after_the_last_attempt(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("servidor fora")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client, pytest.raises(rf.FeedBuildError, match="servidor fora"):
        rf.download(client, f"{SHARE}/2026-10/Empresas0.zip", tmp_path / "Empresas0.zip", sleep=lambda s: None)


def _fake_share() -> httpx.MockTransport:
    files = {"Municipios.zip": _zip([[code, name] for code, name in MUNICIPIOS.items()]),
             "Estabelecimentos0.zip": _zip([_est("11111111"), _est("22222222"), _est("33333333", uf="SP")]),
             "Empresas3.zip": _zip([_emp("11111111"), _emp("22222222", natureza="2135"), _emp("99999999")])}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "PROPFIND":
            return httpx.Response(207, text="<d:href>/dav/CNPJ/2026-09/</d:href><d:href>/dav/CNPJ/2026-10/</d:href>")
        month, name = request.url.path.split("/")[-2:]
        assert month == "2026-10"
        return httpx.Response(200, content=files.get(name, _zip([])))

    return httpx.MockTransport(handler)


def _build(tmp_path):
    cfg = {"icps": ICPS, "receita": {"share_url": SHARE, "exclude_naturezas": ["2135"]}}
    with httpx.Client(transport=_fake_share()) as client:
        month, rows = rf.build_feed(client, cfg)
    out = tmp_path / "cnpj_icp.csv"
    rf.write_feed(rows, out)
    return month, out


def test_build_feed_end_to_end_without_contact_data(tmp_path):
    month, out = _build(tmp_path)
    text = out.read_text(encoding="utf-8")
    assert month == "2026-10"
    assert text.splitlines()[0] == ",".join(rf.FEED_COLUMNS)
    assert "11111111000144" in text and "22222222000144" not in text and "33333333000144" not in text
    assert PHONE not in text and EMAIL not in text
    assert list(tmp_path.glob("*.zip")) == []


def test_feed_output_is_accepted_by_lead_generation(conn, tmp_path):
    _, out = _build(tmp_path)
    with open(out, "rb") as f:
        report = gen.run_generation(conn, f, out.name, "actions")
    assert report.new_candidates == 1
    assert review.pending_candidates(conn)[0]["cnpj"] == "11111111000144"
