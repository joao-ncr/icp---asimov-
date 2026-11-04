# Criterios v2 do ranking (portfolio ampliado da Asimov Jr.)

Decisao arquitetural. Escopo: **somente** o algoritmo de ranking (taxonomia de sinais, score, explicacao). A metodologia de busca de padroes (sinais com evidencia literal + score deterministico + calibracao pelo feedback humano) foi mantida.

## Diagnostico do v1 (o que existia)
- Sinais (`config/signals.yaml`) → fit por servico (noisy-OR) → score = 50% melhor servico + 15% secundarios + 20% viabilidade + 15% lacuna, × multiplicador de evidencia × segmento × calibracao.
- Quatro servicos: `site`, `aplicativo`, `software`, `dados`. Nao havia lugar para automacao/LLM em engenharia nem para colaboracao entre areas.
- Calibracao (`scoring/calibration.py`): multiplicador por sinal/segmento aprendido das avaliacoes boa/neutra/ruim, so com amostra minima, limitado a 0,8–1,2.
- No banco local (snapshot de 2026-10-30): 42 avaliacoes (19 boa / 8 neutra / 15 ruim), 67 analises `ranked`, 352 leads historicos. Nenhum sinal de automacao/engenharia de dados existia, portanto nenhum rotulo humano cobre essas categorias.

## O que mudou (tudo em config, exceto a mecanica abaixo)
| Item | v1 | v2 |
|---|---|---|
| Servicos | site, aplicativo, software, dados | + `automacao` (Engenharia e automacao inteligente) |
| Colaboracao entre areas | inexistente | eixo proprio `colaboracao` (nao e servico; tem score, filtro e explicacao proprios) |
| Sinais novos | – | `DATA_MANUAL_TRANSFER`, `DATA_SYSTEMS_FRAGMENTED`, `AUTOMATION_REPETITIVE`, `ENGINEERING_TECHNICAL_DOCS`, `MOBILE_FIELD_FORMS`, `SOFTWARE_CUSTOM_NEED`, `COLLABORATION_CROSS_AREA` |
| Presenca x necessidade | so o teto de “1 sinal fraco” | `concreteness: contextual` + `evidence.contextual_fit_cap` (0,4) |
| Segmentos | – | `agronegocio`, `energia_saneamento` (ja citados em `profile/icps.yaml`) |
| Versao | – | `criteria_version: 2` gravado em cada `analysis.result` (ausente = 1) |

### Presenca de atividade nao e oportunidade
Cada sinal novo e `concrete` (descreve uma dor: “digitacao manual”, “sistemas diferentes”, “retrabalho”) ou `contextual` (so descreve a atividade: “laudos tecnicos”, “projetos eletricos”). Um servico sustentado **apenas** por sinais contextuais tem fit limitado a 0,4 e a explicacao avisa “compatibilidade superficial”. Sinais antigos continuam `concrete` por padrao (comportamento preservado).

### Colaboracao entre areas (eixo independente)
`collaboration_score` combina por noisy-OR: (a) sinais **explicitos** (`collaboration` no YAML, ex.: “multidisciplinar”, “comunicacao entre areas”) e (b) **amplitude**: disciplinas (aplicativo/software/dados/automacao) com fit ≥ 0,4 e ao menos um sinal “primario” (peso ≥ 0,5), sustentadas por ≥ 2 sinais distintos. Um unico sinal nao infla varias disciplinas. A amplitude sozinha chega a no maximo 0,65; so evidencia explicita leva o eixo ao topo. Marca `multidisciplinary` a partir de 0,5.

### Consistencia e comparabilidade
- Os quatro pesos (soma 1,0) nao mudaram. A colaboracao **so soma** ao score-base, com teto de 5% (`collaboration.max_bonus`): sem colaboracao o score e igual ao v1, exceto pelo servico `automacao` ser avaliado como secundario.
- Regressao medida nos 9 leads do demo (`tests/test_ranking_v2.py`): a ordem do ranking v1 foi mantida e o maior deslocamento foi +3,2 pontos.
- `weights_hash` ja muda com o YAML; `criteria_version` separa analises antigas das novas.

## Historico e treinamento
- Nenhuma analise, avaliacao ou calibracao existente foi alterada ou reclassificada; o schema do banco nao mudou (`seed_db` apenas insere o servico/sinais novos no start).
- Os rotulos atuais foram dados sobre analises v1. `labeled_leads` continua lendo os sinais da **analise que o avaliador viu**; logo, rotulos antigos so informam sinais/segmentos que existiam naquelas analises. Sinais novos so ganham multiplicador quando houver `min_group_n` avaliacoes de leads **v2** com e sem o sinal, e o ajuste continua limitado a 0,8–1,2.
- Multiplicadores de **segmento** aprendidos no v1 seguem valendo para analises v2 (hipotese razoavel, mas nao verificada; ver limitacoes).
- A base historica (`lead_history.suggested_service`) nao tem rotulo de automacao/colaboracao; portanto nao foi usada como rotulo para essas categorias.

## Validacao
`tests/test_ranking_v2.py`: deteccao de dores (e nao de vocabulario), eixos novos, teto de contexto, bonus limitado de colaboracao, regressao v1, historico/feedback preservados. Fixtures novos: `dados-integra`, `campo-multi`, `engenharia-vitrine`.

## Limitacoes / evolucao
- Pesos e padroes novos sao **hipoteses** (como os existentes); validar com 50–100 avaliacoes humanas de leads v2, incluindo as categorias novas. Metricas do demo nao medem desempenho comercial.
- Padroes de texto em PT-BR sao heuristicos; o LLM (opcional) so ajuda a achar os mesmos codigos, sempre com citacao literal.
- Sinais antigos de mera atividade (`OPERATIONAL_LOGISTICS`, `DATA_REPORTING`) continuam `concrete` para nao alterar o v1; reclassifica-los como `contextual` e a proxima melhoria, mas exige reavaliar o historico.
- Dores de automacao/dados raramente aparecem em sites publicos (baixa observabilidade); fontes como vagas e redes (ICPs D/B) ampliariam o recall.
- `profile/icps.yaml` e o gerador de queries nao foram alterados (fora do escopo); incluir ICPs de automacao/integracao de dados ampliaria a descoberta.
