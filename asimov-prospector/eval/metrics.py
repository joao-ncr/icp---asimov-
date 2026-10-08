"""Metricas de ranking. Grades: excelente=4, bom=3, mediano=2, ruim=1, sem_fit=0. Relevante = grade >= 3."""
from __future__ import annotations
import math, random

GRADES = {"excelente": 4, "bom": 3, "mediano": 2, "ruim": 1, "sem_fit": 0}
REL_MIN = 3


def precision_at_k(grades: list[int], k: int) -> float:
    top = grades[:k]
    return sum(g >= REL_MIN for g in top) / max(1, len(top))


def recall_at_k(grades: list[int], k: int, total_relevant: int | None = None) -> float:
    tr = total_relevant if total_relevant is not None else sum(g >= REL_MIN for g in grades)
    return sum(g >= REL_MIN for g in grades[:k]) / tr if tr else 0.0


def ndcg_at_k(grades: list[int], k: int) -> float:
    def dcg(gs): return sum((2 ** g - 1) / math.log2(i + 2) for i, g in enumerate(gs[:k]))
    ideal = dcg(sorted(grades, reverse=True))
    return dcg(grades) / ideal if ideal else 0.0


def fp_fn_rates(grades: list[int], k: int) -> dict:
    top, rest = grades[:k], grades[k:]
    return {"false_positive_rate@k": sum(g < REL_MIN for g in top) / max(1, len(top)),
            "false_negative_rate@k": sum(g >= REL_MIN for g in rest) / max(1, sum(g >= REL_MIN for g in grades))}


def bootstrap_diff_ci(g_a: list[int], g_b: list[int], k: int, n: int = 2000, seed: int = 7) -> tuple[float, float]:
    """IC95% de P@k(A) - P@k(B) por bootstrap sobre os itens (indicativo; amostras pequenas => IC largo)."""
    rnd = random.Random(seed)
    idx = range(len(g_a))
    diffs = []
    for _ in range(n):
        sample = [rnd.choice(idx) for _ in idx]
        pa = precision_at_k([g_a[i] for i in sample], k)
        pb = precision_at_k([g_b[i] for i in sample], k)
        diffs.append(pa - pb)
    diffs.sort()
    return diffs[int(0.025 * n)], diffs[int(0.975 * n)]
