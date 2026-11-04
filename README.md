# Asimov Prospector

Ferramenta interna de **inteligência de prospecção B2B** para a Asimov Jr.

O sistema traz empresas do CRM (Ploomes) e de geração de leads novos a partir de dados abertos de CNPJ, analisa
informações públicas de cada uma, identifica sinais de possíveis problemas operacionais/digitais/dados, relaciona
esses sinais aos serviços da Asimov e entrega um ranking para revisão humana. Uma lista própria (planilha) e o
teste de uma única empresa continuam disponíveis como contingência.

## Fluxo

```
Ploomes (CRM, somente leitura) ──┐
Geração de leads novos (CNPJ aberto → aprovação humana) ──┼──► Analisar ──► Ranking ──► Avaliar (boa/neutra/ruim) ──► Exportar
Lista própria / empresa única (contingência) ─────────────┘
```

A avaliação do time comercial retroalimenta o scoring (`scoring/calibration.py`): com amostra suficiente, o
sistema passa a ajustar, de forma limitada e auditável, o peso dos sinais e segmentos que o time aprovou ou
rejeitou.

## Para o usuário final

### Abrir o sistema (Windows)

Dê dois cliques em `INICIAR_ASIMOV.bat`, na raiz do projeto. Na primeira execução, o ambiente é preparado
automaticamente (pode levar alguns minutos); depois disso, a interface abre direto no navegador.

### Telas

- **Nova análise** — sincronize o Ploomes (administrador), gere e aprove leads novos a partir de um CSV de CNPJ
  aberto, ou use uma lista própria/teste uma empresa; escolha quantas analisar agora.
- **Ranking** — lista ordenada por pontuação, com exportação para Excel/CSV.
- **Avaliar** — evidências de cada empresa (fato/inferência/hipótese) e a sua avaliação em 3 níveis.

### Como interpretar o resultado

A **pontuação** é uma nota de compatibilidade com uma oportunidade para a Asimov — **não é probabilidade de
fechamento**. O ranking mostra só o que é verificável (pontuação, oportunidade, hipótese e evidências); não há
rótulos de "confiança" até haver avaliações suficientes para sustentá-los estatisticamente.

Para cada empresa, o time responde **👍 Boa oportunidade**, **😐 Neutra** ou **👎 Ruim**. Essas respostas alimentam
o aprendizado do sistema; com amostra mínima (ver `app/config/scoring.yaml`), a tela **Ranking** oferece "Aplicar
aprendizado ao ranking" (reprocessa sem acessar os sites de novo).

A hipótese comercial é uma hipótese, não uma afirmação sobre a empresa — confirme antes de qualquer contato.

### O que o sistema não faz

Não envia e-mail nem WhatsApp, não aborda empresas automaticamente, não usa dados pessoais e não declara que uma
empresa é cliente. Não substitui a decisão comercial: toda ação de contato continua humana. Negócios dos funis do
Ploomes que não fazem parte do mapeamento configurado são ignorados (apenas contados no relatório de sincronização).

### Primeiro piloto

Para o primeiro piloto, analise 20–50 empresas por vez, não centenas. A métrica mais importante não é quantidade
de empresas encontradas, e sim **quantas das 10 primeiras realmente parecem boas oportunidades**.

### Planilha (contingência)

Colunas obrigatórias: `empresa`, `site`. Opcionais: `municipio`, `uf`, `segmento`. A interface aceita `.xlsx` e
`.csv` e oferece um modelo para download.

### Se algo der errado

Um erro de SSL, timeout, DNS ou transporte numa empresa é tratado como falha daquela empresa e **não interrompe o
lote**; a análise segue para as demais e o erro fica registrado para auditoria. Feche a interface e abra
`INICIAR_ASIMOV.bat` novamente se precisar reiniciar.

## Acesso

- `AUTH_MODE=password` (padrão, usado no deploy): login obrigatório; usuários em `APP_USERS`, administradores em
  `APP_ADMINS`. Crie um usuário com `python run.py hash-password <usuario>`. Administradores sincronizam o
  Ploomes e geram leads novos; qualquer usuário logado analisa lotes e avalia.
- `AUTH_MODE=local`: sem login, só aceita conexões da própria máquina — use apenas para uso individual.

## Para equipe técnica

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\bootstrap.ps1
python run.py setup
python -m pytest -q
python run.py ui
```

Ou manualmente:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
python run.py setup
python -m pytest -q
python run.py ui
```

### Comandos alternativos de linha de comando

Fora da interface, `run.py` também cobre: `run --seeds data/seeds.csv [--cnpj-csv ... --cnae ... --uf ... --municipio ...]`
(rodada via CLI), `report --out data/prospects_report.csv` (exporta evidências e hipótese, sem dados de contato),
`analyze-url <url>` (valida uma hipótese isolada), `demo` (pipeline completo com fixtures offline, sem rede),
`export-labels`/`eval` (amostragem cega e avaliação P@10/NDCG contra rótulos humanos), `backtest-leads`,
`sync-ploomes --by <quem>` (mesma sincronização da tela, via terminal) e `purge --days N` (remove páginas/cache
antigos conforme a política de retenção).

## Arquitetura

Monólito modular: o motor de inteligência fica separado da camada de operação, para permitir construir Comercial
e Administração depois sem reescrever crawler, scoring ou banco. Resumo de decisões em `docs/ARQUITETURA.md`;
critérios do ranking em `docs/CRITERIOS_V2.md`; o que a base histórica de leads ensinou em `docs/LEADS_INSIGHTS.md`.

O núcleo preservado inclui:

- scoring determinístico, separado da IA;
- evidência verificável (fato/inferência/hipótese nunca se misturam);
- anti-ICP e sinais por serviço;
- integração com o Ploomes somente leitura (nunca escreve no CRM);
- geração de leads novos com aprovação humana obrigatória antes de qualquer análise;
- histórico de leads preservado;
- proteção contra SSRF e prompt injection;
- limites de crawler e cache;
- SQLite, com migrações aditivas;
- login obrigatório no deploy;
- testes automatizados;
- feedback humano.

## Segurança e LGPD

Ver `docs/SEGURANCA_LGPD.md` para o detalhamento de controles (SSRF, prompt injection, segredos, acesso) e das
decisões de minimização de dados pessoais.

## Validação

A suíte atual deve permanecer verde: `python -m pytest -q`. O desempenho comercial ainda precisa ser validado com
50–100 avaliações humanas; as métricas da demo (`python run.py demo`) não representam performance comercial.

## Próxima etapa

Depois de a Operação ser usada por pessoas reais, o próximo módulo é **Comercial**. O módulo de Administração vem
depois, para permitir manutenção de ICP, sinais, cases e permissões sem editar código.
