# Roadmap: ICP por area de servico

Status: **proposta** (nada implementado). Documento de intencao para orientar a proxima evolucao do algoritmo de ranking e as decisoes de negocio que ela exige.
Data: 2026-11-05. Relaciona-se com [CRITERIOS_V2.md](CRITERIOS_V2.md) e [LEADS_INSIGHTS.md](LEADS_INSIGHTS.md).

## 1. Ponto de partida: o que ja funciona e se mantem

O Prospector chegou a uma base solida, e esta proposta **refina** em vez de substituir:

- **Deteccao de dor por servico.** Cada sinal de `config/signals.yaml` ja tem pesos proprios por area (site, aplicativo, software, dados, automacao). O motor sabe dizer *qual dor a empresa tem e qual area resolve*. O ICP por area e construido sobre isso.
- **Evidencia verificavel.** Toda conclusao tem trecho e URL. Isso vai continuar valendo para qualquer criterio novo.
- **Score deterministico e auditavel.** Pesos em YAML, IA fora da decisao. Essa separacao permite evoluir o ICP so com configuracao e testes de regressao.
- **Distincao entre necessidade e atividade** (`concreteness: contextual`, criterios v2). E ela que vai permitir tratar com honestidade areas de dor pouco observavel, como dados/ML.
- **Calibracao conservadora pelo feedback** (amostra minima, encolhimento, limites de 0,8 a 1,2). O mecanismo certo ja existe; falta alimenta-lo com o rotulo certo (secao 5.2).
- **Anti-ICP, base historica, Ploomes somente leitura e aprovacao humana de leads gerados.** Nada disso muda.

Os parametros atuais foram calibrados com o que havia: 21 leads com desfecho e cerca de 42 avaliacoes. Eles estavam corretos para a amostra e foram documentados como hipoteses. O refinamento abaixo e o proximo passo natural, e nao uma correcao de erro.

## 2. A dor de negocio

Cada area da Asimov atende, na pratica, um perfil de cliente diferente:

| Area | Perfil observado pelo time | Caracteristica comercial |
|---|---|---|
| **Sites** | Outras EJs, empresas em fase inicial, consultorios, escritorios, comercio local | Ticket baixo, ciclo curto, alto volume; porta de entrada para outros servicos |
| **Software** | EJs, empresas iniciantes, consultorios, PMEs com controles improvisados | Ticket medio; dor de processo interno |
| **Mobile** | Perfis variados, com foco em quem atende o **cliente final** (B2C) e em startups | Orcamento variavel; valor ligado a relacionamento com o usuario |
| **Dados** | Area nova e sem padrao consolidado. Hoje entrega dashboards, com potencial alto em ML e estatistica | Amplia margem e mercado: de consultorios a startups e empresas nacionais; ticket potencial maior |

Com cerca de **60 membros**, a Asimov tem capacidade de tocar muitos projetos em paralelo. O algoritmo deve abastecer **todas as areas** com leads adequados ao perfil de cada uma, e nao so as areas cuja dor e mais facil de enxergar num site.

## 3. Onde o algoritmo atual ainda e global

A deteccao de dor ja e separada por area. O que **ainda e unico para todas as areas** e a parte que diz quem e um bom cliente:

| Componente | Comportamento atual | Efeito sobre o perfil por area |
|---|---|---|
| `segment_multiplier.empresa_junior: 0.6` + `low_budget_penalty` + `sector_prior: 0.15` | EJ penalizada em todos os servicos (calibrado em 2 perdas) | Reduz leads que sao publico recorrente de sites e software |
| `viability.employees_sweet_spot: [5, 500]` | Um porte ideal para todas as areas | Empresas iniciantes (sites) nao ganham bonus; empresas grandes (dados/ML) sao penalizadas |
| `enterprise_penalty` (a partir de 1000 funcionarios) | Veio do caso Helibras (sem dor solucionavel) | Pode afastar o alvo de maior ticket em dados |
| `ticket_band_brl: [1000, 35000]` | Uma faixa unica | Site e ML tem faixas muito diferentes |
| `region.bonus` | O mesmo bonus regional para tudo | Dados e software podem ser entregues remotamente, para todo o pais |
| `config/icp.yaml` (geracao por CNPJ) | Apenas industria (CNAE 25, 28) e servicos tecnicos (43, 71, 33) no Sul de Minas | Nao gera leads para consultorios, EJs, B2C, startups ou dados |
| Ranking unico por `best_service_fit` | Todas as areas competem na mesma lista | Ver 3.1 |
| `human_feedback` | Avaliacao por lead, sem indicar a area | Ver 5.2 |

### 3.1 Vies de observabilidade

Sinais de site sao **tecnicos e deterministicos** (sem site, sem viewport, sem HTTPS, sem captacao), com observabilidade alta. Sinais de dados, automacao e mobile sao textuais e de observabilidade baixa, porque dor interna raramente aparece num site publico. Numa lista unica, "precisa de site" tende a dominar porque e o mais facil de comprovar, nao necessariamente porque e a melhor oportunidade. Esse vies prejudica justamente a area de maior potencial de margem (dados).

## 4. Visao-alvo

### 4.1 Perfis por area em configuracao

Um bloco `service_profiles` em `config/scoring.yaml` (esboco; os valores sao ilustrativos e serao definidos nas reunioes da secao 5.1):

```yaml
service_profiles:
  site:
    viability: {employees_sweet_spot: [1, 50], ticket_band_brl: [1000, 8000]}
    segment_multiplier: {empresa_junior: 1.0}
    new_company_bonus: 0.15          # CNPJ aberto ha pouco tempo
    region_scope: nacional
  software:
    segment_multiplier: {empresa_junior: 0.9}
  aplicativo:
    segment_prior: {fitness: 0.7, educacao: 0.65, comercio: 0.6, startup: 0.7}
  dados_bi:
    viability: {employees_sweet_spot: [10, 1000]}
  dados_ml:
    viability: {employees_sweet_spot: [10, 5000], enterprise_penalty: 0.1, ticket_band_brl: [8000, 60000]}
    region_scope: nacional
```

Sem perfil definido, uma area herda as regras globais atuais. Assim, o comportamento de hoje fica preservado por padrao.

### 4.2 Mecanica do score

- Cada area recebe seu score: `fit_area x viabilidade_area x segmento_area x evidencia`.
- O "melhor servico" passa a ser escolhido **depois** de aplicar o perfil da area.
- O score continua deterministico, explicavel e versionado (`criteria_version: 3`).

### 4.3 Ranking por area com cotas

- Uma visao por area (top-N de cada uma), alem da visao geral.
- As cotas refletem capacidade e estrategia de cada area (decisao de negocio, secao 5.1).
- Dados pode ter uma **cota exploratoria** declarada, sem simular precisao que a area ainda nao tem.

### 4.4 Sinais e fontes por area

| Area | Refinamento |
|---|---|
| Sites | Data de abertura do CNPJ como sinal de empresa em fase inicial; natureza juridica de associacao para identificar EJs |
| Mobile | CNAE como prior de B2C (varejo, academias, educacao, saude, delivery); sinais de startup (CNAE 62/63, abertura recente, "plataforma", "MVP") |
| Dados | Separar `dados_bi` (dashboard, relatorios; dor observavel) de `dados_ml` (previsao, estatistica). Sinais de volume ("milhares de clientes", "historico de") marcados como `contextual`: indicam que ha dados, nao que ha dor |
| Geracao (CNPJ) | ICPs de `config/icp.yaml` com campo `service` e recortes de CNAE por area |

## 5. Pre-requisitos

Nenhuma fase tecnica comeca antes que os pre-requisitos de negocio dela estejam resolvidos. Parametros sem decisao de negocio seriam so outro chute.

### 5.1 Negocio: reunioes com a diretoria

| # | Reuniao | Participantes | Decisoes esperadas | Saida |
|---|---|---|---|---|
| R1 | **Estrategia de portfolio** | Presidencia, diretoria de Projetos, diretoria Comercial | Papel de cada area: site e porta de entrada (upsell) ou receita propria? Dados/ML sera area prioritaria de crescimento? | Prioridade e papel de cada area |
| R2 | **Capacidade por area** | Diretoria de Projetos, gerentes de area | Membros, projetos simultaneos e tempo medio de entrega por area; capacidade ociosa atual | Cotas do ranking por area |
| R3 | **Perfil de cliente por area** | Gerentes de area, comercial, membros que tocaram projetos recentes | Segmentos, porte, faixa de ticket e regiao de cada area, com base em projetos reais (Ploomes) | Valores iniciais de `service_profiles` |
| R4 | **Politica para EJs como clientes** | Diretoria Comercial, Presidencia | Prospectar EJs? Para quais areas? Regras de preco e relacao com o MEJ/federacao | Multiplicador de EJ por area; canal (lista propria x CNPJ) |
| R5 | **Abrangencia geografica** | Diretoria Comercial, Projetos | Aceitar clientes fora do Sul de Minas? Para quais areas (dados, software, sites para EJs)? | `region_scope` por area |
| R6 | **Oferta de dados/ML** | Gerencia de dados, diretoria de Projetos | O que a area consegue entregar hoje e em 6 meses (BI, estatistica, ML)? Ha cases ou projetos-piloto? | Escopo de `dados_bi` e `dados_ml`; cota exploratoria |
| R7 | **Processo de avaliacao** | Comercial, responsavel pelo Prospector | Avaliacao passa a indicar a area; quem avalia, com que frequencia, meta de volume | Rito de avaliacao e meta de rotulos |

R1 e R2 vem antes das demais. R3 a R6 podem acontecer em paralelo. R7 e pre-requisito tecnico da fase 1.

### 5.2 Dados

1. **Avaliacao por area.** Hoje `human_feedback` registra `quality` por lead. Um lead pode ser "boa" para site e "ruim" para dados, e o rotulo atual nao distingue os dois casos. Sem a area na avaliacao, nenhum perfil por area pode ser calibrado. **E o pre-requisito de maior valor e de menor custo.**
2. **Historico de projetos por area.** Levantar no Ploomes (somente leitura) os projetos ganhos com area, segmento, porte, ticket e regiao. E a fonte mais confiavel para os valores iniciais de R3.
3. **Volume minimo de rotulos.** Cerca de 30 avaliacoes **por area** para ativar a calibracao por area, e cerca de 100 por area antes de usar parametros aprendidos na geracao de leads. Esses limiares seguem a logica atual de `calibration` e devem ser revistos em R7.
4. **Enriquecimento da base historica.** Completar `data/leads_enriched.csv` (dominio, segmento, porte, servico contratado), como ja indicado em LEADS_INSIGHTS.md.

### 5.3 Tecnicos

| Item | Detalhe | Toca invariante? |
|---|---|---|
| Campo `service` em `human_feedback` | Migracao aditiva (coluna nula para avaliacoes antigas); UI de avaliacao pede a area | Preserva feedback historico |
| `service_profiles` em `scoring.yaml` | Leitura com heranca das regras globais; validacao do YAML no start | Regras em config |
| `viability` parametrizada por area | Refatorar `viability()` para receber o perfil, mantendo a funcao pura | Scoring deterministico |
| Ranking por area | Consulta SQL por `service_id` em `ranking.py` (indice `ix_score_an_svc` ja existe); visao por area na UI | Ordenacao no banco |
| Divisao `dados` em `dados_bi` / `dados_ml` | Novo servico na taxonomia; mapear analises antigas de `dados` para `dados_bi` apenas na leitura | Historico preservado |
| Coluna de data de abertura no feed | `receita_feed.py`: incluir o campo do arquivo de estabelecimentos em `FEED_COLUMNS` | LGPD: dado cadastral da empresa, nao de pessoa |
| ICPs de geracao por area | Campo `service` em `config/icp.yaml`; novos recortes de CNAE | Aprovacao humana continua obrigatoria |
| Calibracao hierarquica | Ajuste area x segmento encolhido em direcao ao ajuste global do segmento ate ter amostra propria | Ajustes limitados, amostra minima |
| `criteria_version: 3` | Gravado em cada analise; comparacao v2 x v3 nos mesmos leads | Comparabilidade |
| Testes | Regressao (sem perfil = comportamento v2), perfil por area, heranca, cotas, migracao do feedback | Suite verde |

## 6. Fases

| Fase | Entrega | Pre-requisitos | Criterio de saida |
|---|---|---|---|
| **0. Alinhamento** | Reunioes R1 a R7; levantamento de projetos no Ploomes | — | Decisoes registradas em ata; valores iniciais por area |
| **1. Rotulo por area** | `service` na avaliacao; UI ajustada | R7 | Avaliacoes novas sempre com area |
| **2. Ranking por area** | Visao por area com cotas, sem mudar pesos | R2 | Cada area recebe leads proprios; nenhuma area com fila vazia |
| **3. Perfis por area** | `service_profiles` com os valores de R3 a R5; `criteria_version: 3` | Fase 1, R3 a R5 | Regressao verde; comparacao v2 x v3 revisada pelo comercial |
| **4. Geracao por area** | ICPs de CNPJ por area; data de abertura no feed | Fase 3, R4, R5 | Candidatos de cada area aprovados na revisao humana |
| **5. Dados BI x ML** | Divisao do servico; sinais de ML como `contextual`; cota exploratoria | R6 | Leads de dados avaliados separadamente |
| **6. Calibracao por area** | Calibracao hierarquica ativa | Cerca de 30 avaliacoes por area | Multiplicadores por area dentro dos limites, auditaveis em `calibration` |

As fases 1 e 2 entregam valor logo e quase nao dependem de parametros novos. As fases 3 a 6 so fazem sentido com as decisoes de negocio tomadas.

## 7. Riscos e cuidados

- **Amostra pequena para muitos parametros.** Cinco ou seis areas multiplicadas por segmentos deixam cada celula com pouca amostra. Mitigacao: heranca das regras globais, calibracao hierarquica e valores iniciais declarados como hipoteses.
- **Capacidade nao e demanda.** O gargalo medido e conversao: outbound converteu 0 de 6, inbound 27%. Mais leads so ajudam se o comercial tiver braco para abordar. As cotas devem considerar a capacidade comercial, nao so a de execucao.
- **Dados/ML sem historico.** Dor de ML raramente aparece em site publico. O algoritmo pode apontar *potencial* (volume de dados), mas a necessidade tende a ser criada na abordagem consultiva. Sem rotulos de confianca na UI enquanto nao houver base estatistica.
- **Ticket baixo em sites.** Volume alto de sites de baixo valor pode ocupar capacidade que renderia mais em outras areas. A decisao R1 (porta de entrada x receita) define o equilibrio.
- **Comparabilidade.** Analises v2 e v3 nao sao diretamente comparaveis; `criteria_version` separa as duas, e rotulos antigos (sem area) nao sao reclassificados.

## 8. O que nao muda

- Score deterministico; LLM so extrai e explica.
- Toda conclusao com evidencia verificavel (trecho e URL).
- Anti-ICP avaliado antes do ranking (com excecoes por area apenas se decididas em R4).
- Seguranca do crawler, LGPD, Ploomes somente leitura, aprovacao humana de leads gerados.
- Feedback e historico existentes preservados; nenhuma avaliacao antiga e reescrita.
- Regras de negocio em YAML.

## 9. Como saberemos que funcionou

- Todas as areas recebem leads em volume compativel com sua cota.
- A taxa de avaliacoes "boa" **por area** no v3 e maior que no v2, medida em pelo menos 50 a 100 avaliacoes por area.
- Leads de dados e mobile passam a aparecer no ranking com evidencia, e nao so leads de site.
- A conversao comercial por area (Ploomes) melhora em relacao a prospeccao tradicional. Essa e a validacao real; metricas do demo nao representam performance comercial.

## 10. Registro de decisoes

| Data | Reuniao | Decisao | Responsavel |
|---|---|---|---|
| | R1 | | |
| | R2 | | |
| | R3 | | |
| | R4 | | |
| | R5 | | |
| | R6 | | |
| | R7 | | |
