# Arquitetura (resumo executivo das decisoes)

```
Perfil Asimov (YAML) ─► ICPs ─► queries por problema ─► candidatos (seeds / CNPJ aberto / SearXNG)
  ─► dedup ─► cruzamento com leads (anti-ICP) ─► crawler seguro ─► texto limpo
  ─► sinais (regras + LLM opcional, TODA evidencia verificada) ─► score por servico (codigo)
  ─► ranking + explicacao (template) ─► revisao humana ─► feedback ─► avaliacao B0/B1/B2
```

## Decisoes-chave
1. **Problema ordena; setor/porte/regiao filtram.** O score B1 (so setor/porte) e calculado para todo candidato e e o *controle* do experimento: a hipotese "problema > setor" so se sustenta se B2 (sinais) bater B1 nos rotulos humanos (`python run.py eval`).
2. **O LLM propoe, o codigo decide.** Backend `heuristic` (regras PT-BR, default, offline) e `ollama` (opcional). Em ambos, evidencia = trecho literal verificado; score = funcao deterministica de `app/config/*.yaml`.
3. **Score = (50% melhor servico + 15% servicos secundarios + 20% viabilidade + 15% lacuna de oportunidade) × multiplicador de evidencia (0,5–1,0) × multiplicador de segmento.** Evidencia entra como multiplicador (nao como soma) para que pouca evidencia nao seja compensada por outros itens. Fit por servico = noisy-OR dos sinais; um unico sinal fraco limita o fit a 0,35.
4. **Ausencia nao e fato.** "Sem viewport", "sem formulario", "site fora do ar" sao `absence_inference` com confianca moderada.
5. **Status por empresa:** `ranked`, `excluded` (cliente/concorrente/anti-ICP), `inconclusive` (pouco texto/nenhum sinal), `blocked` (robots/403/rede), `error`. Bloqueio nunca vira "sem site".
6. **Tabelas:** `service, case_study, icp, search_run, search_query, organization, page, company_profile, signal, analysis, evidence, opportunity, score, human_feedback, known_lead` (ver `app/database/schema.sql`). Cada `analysis` guarda versao de modelo, hash do prompt e hash dos pesos (reprodutibilidade).
7. **Embeddings** (TF-IDF por padrao; sentence-transformers opcional) so servem a similaridade com cases — informativo, fora do score.

## Experimento (criterio de sucesso)
Rotule uma amostra **sorteada** do universo (>= 100; 2 avaliadores; kappa em `eval/run_eval.py`) com `python run.py export-labels` (planilha cega, B1+B2 em pool). Rode `python run.py eval --labels ...`. Meta inicial do MVP: **P@10 >= 50% e >= 1,5x o P@10 de B1**, repetido em 2 lotes; metrica principal P@10, secundaria NDCG@20. Com n pequeno, o IC e largo (`bootstrap_diff_ci`). Compare tambem com a taxa de acerto da prospeccao atual (0/6 no funil ativo da planilha).

## Pontos de evolucao (nao implementados)
PostgreSQL, workers/fila, crawler distribuido, Playwright isolado, LLM maior/API, frontend dedicado, ajuste de pesos por regressao com o feedback acumulado, fontes alternativas (vagas, redes) para ICPs D/B.
