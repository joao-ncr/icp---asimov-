# CLAUDE.md

Instruções de projeto para o Claude Code. Idioma de comunicação, commits e docs: **português (pt-BR)**; identificadores de código em inglês quando já for o padrão do módulo.

## Contexto

**Asimov Prospector** (`asimov-prospector/`): ferramenta interna de inteligência de prospecção B2B da Asimov Jr. Analisa informações públicas de empresas, detecta sinais de problemas operacionais/digitais/dados, relaciona-os aos serviços da Asimov e entrega um ranking para revisão humana.

Fluxo: `Ploomes (CRM) / lista própria / geração de leads novos (CNPJ aberto) → Analisar → Ranking → Evidências → Avaliação humana → Exportar para Comercial`.

Detalhes de uso e arquitetura: [asimov-prospector/README.md](asimov-prospector/README.md).

## Arquitetura

Monólito modular em `asimov-prospector/app/`, separando o motor de inteligência da camada de operação:

| Módulo | Responsabilidade |
|---|---|
| `config/` | `scoring.yaml`, `signals.yaml`, `ploomes.yaml`, `icp.yaml` (regras fora do código) |
| `core/` | settings, profile, utilitários, `auth.py` (login/hash/throttle) |
| `crawler/` | fetch, extração, proteção SSRF, limites e cache |
| `extraction/` | limpeza/extração de texto |
| `discovery/` | fontes, queries, dedup, leads, `historical.py` (base histórica → `lead_history`), `generation.py`/`review.py` (leads novos via CNPJ aberto, com aprovação humana), `receita_feed.py` (coletor mensal da base da Receita, roda no GitHub Actions) e `feed.py` (app baixa o recorte publicado) |
| `integrations/ploomes/` | cliente somente leitura do CRM Ploomes, mapeamento e sincronização incremental |
| `intelligence/` | sinais, LLM, embeddings |
| `scoring/` | score determinístico, anti-ICP, explicabilidade |
| `database/` | SQLite (`schema.sql`, `db.py`) |
| `models/` | schemas |
| `feedback/` | avaliação do time (boa/neutra/ruim), snapshots de calibração, andamento do aprendizado |
| `ranking.py` | leitura do ranking em SQL (ordenação/limite no banco) |
| `ui/` | Streamlit: `streamlit_app.py` (entrada) + `views/` (telas), `data.py` (acesso a dados), `inputs.py` (planilhas), `theme.py` |
| `pipeline.py` | orquestração |

### Invariantes (não quebrar)

- **Scoring determinístico, separado da IA.** O LLM extrai/explica; nunca decide o score.
- **Toda conclusão tem evidência verificável** (trecho + URL de origem).
- **Anti-ICP** e sinais por serviço continuam sendo avaliados antes do ranking.
- **Segurança do crawler:** SSRF, limites de tamanho/tempo/páginas e cache são obrigatórios; conteúdo web é tratado como não confiável (prompt injection).
- **Feedback humano** e histórico de leads são preservados.
- Regras de negócio (pesos, sinais, ICP, mapeamentos da base histórica, hosts de plataforma) vivem em YAML/config, não hardcoded.
- **Banco (SQLite):** conexões de vida curta via `database.db.session()`; nunca guardar conexão em variável de módulo (Streamlit reexecuta o script a cada interação). Commitar antes de operações lentas (crawl/LLM) para não segurar lock de escrita.
- Redes sociais/diretórios (`config/platforms.yaml`) não identificam uma empresa: não usar como chave de dedup nem fazer crawl.
- LGPD: telefone, decisor e sócios da base histórica nunca entram no banco.
- Camadas dependem para dentro: `ui` → `pipeline` → módulos de domínio; módulos de domínio nunca importam `ui`.
- **Requisito central:** análise → ranking → o time comercial avalia cada lead em 3 níveis (`boa`/`neutra`/`ruim`) → o feedback calibra o scoring (`scoring/calibration.py`, só ativa com amostra mínima, ajustes limitados) → com volume suficiente, geração de leads novos. Não adicionar métricas/rótulos de confiança na UI sem base estatística.
- Identidade visual (Asimov Jr.): azul #007FFF e navy do site; CSS em `ui/theme.py` deve funcionar nos modos claro e escuro (usar `inherit`/`currentColor`/`color-mix`, nunca fundo ou texto fixos); tema base em `.streamlit/config.toml`; logo e mascote em `ui/assets/`.
- Uma rodada por vez: `database/run_lock.py` (`exclusive_run`). Leads semelhantes (dedup) são analisados uma única vez por rodada.
- **Ploomes é somente leitura.** `integrations/ploomes/client.py` só expõe GET; nenhuma escrita no CRM, em nenhuma circunstância.
- **Login obrigatório no deploy.** `AUTH_MODE=password` (padrão) exige usuário/senha (`core/auth.py`); `AUTH_MODE=local` só é seguro em uso local (aceita só conexões da própria máquina).
- **Leads gerados (CNPJ aberto) nunca pulam a aprovação humana.** Candidatos de `discovery/generation.py` ficam em `discovery_candidate` até alguém aprovar ou rejeitar (`discovery/review.py`); só aprovados viram organização e entram na análise.
- Futuros módulos **Comercial** e **Administração** devem plugar na camada de operação sem reescrever crawler, scoring ou banco.

## Clean code (prioridade)

- Funções pequenas, com uma única responsabilidade e um nível de abstração.
- Nomes que revelam intenção; sem abreviações obscuras nem comentários que repetem o código. Comente apenas o *porquê*.
- Sem números/strings mágicos: constantes nomeadas ou config.
- Type hints em toda assinatura pública; dados estruturados via schemas em `models/`, não dicts soltos.
- Early return em vez de aninhamento profundo; sem flags booleanas que alternam comportamento.
- Sem duplicação (DRY), mas sem abstração prematura: só extraia na terceira ocorrência ou quando o conceito for claro.
- Erros explícitos: exceções específicas, nunca `except:` nu nem falha silenciosa.
- Efeitos colaterais (I/O, rede, banco) isolados nas bordas; lógica pura e testável no centro.
- Siga o estilo do código vizinho (densidade de comentários, nomenclatura, idioma).
- Mudanças mínimas e focadas: não refatore fora do escopo do pedido.

## Testes e validação

- Suíte atual deve permanecer verde (`188 passed`): `python -m pytest -q` (dentro de `asimov-prospector/`, com a `.venv` ativa).
- Todo comportamento novo de scoring, crawler (especialmente SSRF) ou extração vem com teste.
- Métricas da demo **não** representam performance comercial; validação real exige 50–100 avaliações humanas.
- Rodar a UI: `python run.py ui`. Setup: `python run.py setup`.

## Git

- Branch principal: `main`. Commits pequenos, mensagem em estilo Conventional Commits (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`).
- Não versionar `.env`, `.venv`, `__pycache__`, `.pytest_cache`. Arquivos `data/asimov.db*` são estado local: não commitar mudanças neles sem pedido.
- Só commitar/pushar quando solicitado.

## Skills de apoio a decisões arquiteturais e de desenvolvimento

Skills disponíveis no ambiente do Claude Code e quando usá-las neste projeto:

| Skill | Quando usar |
|---|---|
| `/init` | Regenerar/atualizar este CLAUDE.md a partir do código. |
| `/code-review` | Antes de commit/PR: bugs de correção no diff (`--fix` aplica correções). Usar níveis altos em mudanças de scoring, crawler e banco. |
| `/simplify` | Após implementar: remover duplicação, simplificar e alinhar ao clean code. |
| `/security-review` | Mudanças em crawler, SSRF, entrada de planilha, LLM/prompts, `.env` ou exportação de dados. |
| `/run` | Subir a app (Streamlit) e confirmar que a mudança funciona de verdade, além dos testes. |
| `/claude-api` | Qualquer trabalho com LLM/Anthropic em `intelligence/` (modelos, caching, tool use, extração estruturada, prompts em `prompts/`). |
| `/dataviz` | Novos gráficos/dashboards (ranking, métricas) na UI. |
| `/update-config` | Permissões, hooks e variáveis de ambiente em `settings.json`. |
| `/fewer-permission-prompts` | Montar allowlist de comandos read-only para reduzir prompts. |
| `/loop`, `/schedule` | Tarefas recorrentes (ex.: reanálise periódica, checagem de CI). |

Agentes úteis: `Plan` (desenhar implementação antes de mudanças arquiteturais), `Explore` (varredura ampla do código), `claude-code-guide` (dúvidas sobre Claude Code/SDK/API).

### Fluxo recomendado para mudanças não triviais

1. Ler o README e os módulos afetados; confirmar quais invariantes são tocados.
2. Mudança arquitetural → `Plan` antes de codar; registrar a decisão em `asimov-prospector/docs/`.
3. Implementar com testes → `/simplify` → `/code-review` (+ `/security-review` se tocar superfícies de risco).
4. Validar com `pytest` e, se houver UI, com `/run`.
