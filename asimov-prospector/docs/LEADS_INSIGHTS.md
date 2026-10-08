# O que a planilha de leads ensina (e o que ela NAO ensina)

Fonte: `leads.xlsx` (21 leads com situacao; 2 linhas em branco ignoradas). Amostra **pequena** — tudo abaixo e indicio, nao prova.

| Metrica | Valor |
|---|---|
| Ganhos / Perdidos | 4 / 17 (19% ganho) |
| Funil Passivo (inbound) | 4 ganhos em 15 (27%) |
| Funil Ativo (outbound) | **0 ganhos em 6** |
| Ticket ganho | R$ 1,0 mil a R$ 34,2 mil (mediana R$ 15,3 mil; total R$ 65,7 mil) |
| Propostas perdidas com valor | 10 (mediana R$ 12,2 mil; total R$ 112,1 mil) |

**Motivos de perda (17):** sem resposta/contato 6 · **sem orcamento 5** · nao e prioridade 2 · fora do ICP 1 · sem dor que conseguimos solucionar 1 · termo do contrato 1 · desqualificado 1.

## Como isso virou configuracao do programa
1. **Outbound converteu 0/6.** E exatamente o gargalo que o programa quer atacar; por isso a avaliacao exige comparar com baselines (B0 aleatorio, B1 setor/porte) e com a taxa de acerto da prospeccao tradicional.
2. **Orcamento e a causa qualificavel mais frequente (29% das perdas).** Entrou como dimensao propria de *viabilidade* (peso 20%): faixa de ticket `1k–35k`, porte, regiao, penalidade para grande porte e para segmentos de baixo orcamento. Leads antigos perdidos por orcamento recebem penalidade (`known_no_budget_penalty`).
3. **Helibras: "nao possui dor que conseguimos solucionar".** Grande porte com site rico nao implica fit. Regra anti-ICP + penalidade de grande porte (>= 1000 colaboradores citados).
4. **Empresas juniores (Apoio Consultoria Jr, Quimica Jr) perderam por orcamento/prioridade** → `segment_multiplier: empresa_junior = 0.6`. Atencao: o briefing diz que a Asimov *ja vendeu sites* a EJs; ajuste o multiplicador se o objetivo incluir sites de baixo ticket.
5. **Zapfit "fora do ICP"** e Helibras/lead desqualificado → excluidos automaticamente se reaparecerem (`exclude_known_loss_categories`).
6. **Perdidos por falta de resposta/prioridade (8)** nao sao excluidos: aparecem com a marca `[reativacao]` no ranking.
7. **Clientes atuais** (Diavicon, JMorais, Authana, pessoa fisica) sao excluidos da prospeccao.

## O que a planilha nao tem (lacunas que limitam a calibracao)
- **Sem setor, porte, dominio nem servico contratado** — 10 de 21 leads ficaram com segmento "desconhecido" (os demais foram *inferidos pelo nome*, confianca baixa).
- Logo, os pesos de `sector_prior` e de sinais sao **hipoteses**, nao estimativas. **Acao de maior valor:** preencher `data/leads_enriched.csv` (dominio, segmento, porte, servico contratado) e rodar `python run.py backtest-leads`. Os 4 ganhos devem sair bem ranqueados e Helibras/EJs mal; se nao, recalibrar `signals.yaml`/`scoring.yaml`.
- Colunas da exportacao do CRM estao deslocadas nas linhas "Perdida" (o motivo cai em posicoes variaveis). O importador classifica por tipo de celula; vale corrigir a exportacao na origem.

## Privacidade
Nomes de pessoas fisicas sao pseudonimizados (`Pessoa fisica #n`), e nomes de vendedores nao sao importados. O xlsx original nao vai no pacote (`data/leads.xlsx` esta no `.gitignore`); o seed e `data/leads_seed.csv`.
