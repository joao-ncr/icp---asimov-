"""Embeddings: TF-IDF (default, offline) ou sentence-transformers. Uso: similaridade com cases (informativo)."""
from __future__ import annotations
import numpy as np


class Embedder:
    def __init__(self, backend: str = "tfidf", st_model: str = ""):
        self.backend, self.st = backend, None
        if backend == "st":
            try:
                from sentence_transformers import SentenceTransformer
                self.st = SentenceTransformer(st_model)
            except Exception:
                self.backend = "tfidf"

    def similarities(self, query: str, docs: list[str]) -> list[float]:
        if not docs or not query.strip():
            return [0.0] * len(docs)
        if self.st is not None:
            v = self.st.encode([query] + docs, normalize_embeddings=True)
            return [float(x) for x in v[1:] @ v[0]]
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.metrics.pairwise import cosine_similarity
        m = TfidfVectorizer(strip_accents="unicode", lowercase=True).fit_transform([query] + docs)
        return [float(x) for x in cosine_similarity(m[0], m[1:])[0]]
