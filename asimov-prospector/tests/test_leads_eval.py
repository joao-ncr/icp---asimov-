from openpyxl import Workbook
from app.discovery.leads import categorize, parse_rows
from app.scoring import antiicp
from eval.metrics import ndcg_at_k, precision_at_k, recall_at_k


def _xlsx(tmp_path):
    wb = Workbook(); ws = wb.active
    ws.append(["Título", "Cliente", "Responsável", "Valor", "Estágio"])
    ws.append(["Acme", "Acme", "Fulano", 5000.0, "Negociação", 10.0, "quarta-feira, 11 de fevereiro de 2026", "Funil Passivo", "x", 1.0, 2.0, "Ganha"])
    # linha perdida com motivo em posicao deslocada
    ws.append(["Beta", "Beta", "Fulano", 0.0, "Sem resposta", 96.0, "Está fora do ICP", "domingo, 8 de fevereiro de 2026", "Funil Passivo", "y", 1.0, 2.0, "Perdida"])
    ws.append(["Lucas Arante Araujo", "Lucas Arante Araujo", "Fulano", 1000.0, "Negociação", 70.0, "quarta-feira, 24 de junho de 2026", "Funil Passivo", "z", 1.0, 0.0, "Ganha"])
    p = tmp_path / "l.xlsx"; wb.save(p); return p


def test_parse_shifted_columns_and_pseudonymization(tmp_path):
    rows = parse_rows(_xlsx(tmp_path))
    by = {r["name"]: r for r in rows}
    assert by["Acme"]["outcome"] == "won" and by["Acme"]["funnel"] == "passivo"
    assert by["Beta"]["loss_category"] == "outside_icp"          # prioridade sobre 'sem resposta'
    assert "Lucas" not in " ".join(by) and any(r["is_person"] for r in rows)


def test_category_priority():
    assert categorize(["Sem resposta", "Não possui orçamento"]) == "no_budget"


def test_known_lead_matching(conn):
    conn.execute("INSERT INTO known_lead(name,name_norm,outcome,loss_category,is_person) VALUES('Helibras','helibras','lost','no_solvable_pain',0)")
    conn.execute("INSERT INTO known_lead(name,name_norm,outcome,loss_category,is_person) VALUES('Diavicon','diavicon','won',NULL,0)")
    k = antiicp.match_known_lead(conn, "Helibras Helicopteros do Brasil S.A.", None)
    assert k and antiicp.precheck(k)[0]
    assert antiicp.precheck(antiicp.match_known_lead(conn, "Diavicon", None)) == (True, "ja e cliente")
    assert antiicp.match_known_lead(conn, "Empresa Totalmente Diferente", None) is None


def test_metrics():
    g = [4, 3, 0, 1, 3]
    assert precision_at_k(g, 2) == 1.0 and precision_at_k(g, 5) == 0.6
    assert abs(recall_at_k(g, 2) - 2 / 3) < 1e-9
    assert ndcg_at_k([4, 3, 3, 1, 0], 5) == 1.0 and ndcg_at_k([0, 1, 3, 3, 4], 5) < 0.8
