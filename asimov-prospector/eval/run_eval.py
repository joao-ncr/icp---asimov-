"""Compara rankings B0 (aleatorio), B1 (setor/porte) e B2 (sistema completo) contra rotulos humanos.
labels.csv: domain,label[,rater]   (label em excelente|bom|mediano|ruim|sem_fit)"""
from __future__ import annotations
import csv, random
from pathlib import Path
from eval.metrics import GRADES, fp_fn_rates, ndcg_at_k, precision_at_k, recall_at_k


def load_labels(path: Path) -> dict[str, int]:
    by: dict[str, list[int]] = {}
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if r["label"].strip().lower() in GRADES:
                by.setdefault(r["domain"].strip().lower(), []).append(GRADES[r["label"].strip().lower()])
    return {d: round(sum(v) / len(v)) for d, v in by.items()}      # media simples quando ha 2 avaliadores


def evaluate(rank_rows: list[dict], labels: dict[str, int], ks=(5, 10), seed: int = 1) -> dict:
    rows = [r for r in rank_rows if (r["domain"] or "").lower() in labels]
    rnd = random.Random(seed)
    b0 = rows[:]; rnd.shuffle(b0)
    b1 = sorted(rows, key=lambda r: -r["b1"])
    b2 = sorted(rows, key=lambda r: -r["final"])
    out = {"n_labeled_ranked": len(rows), "relevant_total": sum(labels[(r["domain"] or "").lower()] >= 3 for r in rows)}
    for name, order in (("B0_random", b0), ("B1_sector_size", b1), ("B2_signals", b2)):
        g = [labels[(r["domain"] or "").lower()] for r in order]
        res = {}
        for k in ks:
            kk = min(k, len(g))
            res[f"P@{k}"] = round(precision_at_k(g, kk), 3)
            res[f"NDCG@{k}"] = round(ndcg_at_k(g, kk), 3)
            res[f"R@{k}"] = round(recall_at_k(g, kk), 3)
        res.update({k: round(v, 3) for k, v in fp_fn_rates(g, min(10, len(g))).items()})
        out[name] = res
    return out


def kappa(pairs: list[tuple[int, int]]) -> float:
    """Cohen's kappa simples (binario relevante/nao) para concordancia entre avaliadores."""
    if not pairs: return 0.0
    a = [x >= 3 for x, _ in pairs]; b = [y >= 3 for _, y in pairs]
    n = len(pairs); po = sum(x == y for x, y in zip(a, b)) / n
    pa, pb = sum(a) / n, sum(b) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    return (po - pe) / (1 - pe) if pe < 1 else 1.0
