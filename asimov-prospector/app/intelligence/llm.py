"""Backends de extracao. 'heuristic' = so regras (default, offline). 'ollama' = LLM local com saida em JSON schema.
O LLM so PROPOE sinais com citacao literal; tudo passa pelo verificador e o score e calculado em codigo."""
from __future__ import annotations
import httpx
from app.core.settings import Settings
from app.core.utils import sha
from app.intelligence.signals import taxonomy
from app.models.schemas import LLMExtraction


class HeuristicBackend:
    name, model = "heuristic", "rules-v1"
    prompt_hash = "n/a"

    def extract(self, chunk: dict) -> LLMExtraction:
        return LLMExtraction()      # as regras ja rodam em signals.py; este backend nao adiciona nada


class OllamaBackend:
    name = "ollama"

    def __init__(self, s: Settings):
        self.s, self.model = s, s.ollama_model
        self.template = (s.prompts_dir / "extract_facts.md").read_text(encoding="utf-8")
        self.prompt_hash = sha(self.template)[:12]
        self.client = httpx.Client(timeout=180)

    def extract(self, chunk: dict) -> LLMExtraction:
        codes = [c for c, v in taxonomy().items() if v["source"] == "text"]
        prompt = self.template.replace("{signal_codes}", ", ".join(codes)).replace("{url}", chunk["url"]).replace("{chunk}", chunk["text"][:3000])
        body = {"model": self.model, "stream": False, "options": {"temperature": 0},
                "format": LLMExtraction.model_json_schema(), "messages": [{"role": "user", "content": prompt}]}
        try:
            r = self.client.post(self.s.ollama_url + "/api/chat", json=body)
            r.raise_for_status()
            return LLMExtraction.model_validate_json(r.json()["message"]["content"])
        except Exception:
            return LLMExtraction()      # falha do LLM nunca derruba o pipeline (e e contada nas metricas)


def get_backend(s: Settings):
    return OllamaBackend(s) if s.llm_backend == "ollama" else HeuristicBackend()
