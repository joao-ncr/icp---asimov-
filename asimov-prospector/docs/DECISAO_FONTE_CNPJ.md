# Decisão: fonte automática de CNPJ para leads novos

**Data:** 2026-11-04 · **Status:** aceita (MVP)

## Contexto

A geração de leads novos exigia que um administrador baixasse a base da Receita e enviasse um CSV na tela. Isso
deixava o processo semiautomático e custoso. As restrições do MVP são orçamento zero, nenhuma máquina dedicada (o
app roda em notebook, em horários combinados) e repositório privado.

Nenhuma API pública gratuita faz *descoberta* (listar empresas por CNAE/UF). BrasilAPI, OpenCNPJ e ReceitaWS
consultam um CNPJ já conhecido, e as APIs com busca por filtro (CNPJá, CNPJ.ws) são pagas. A descoberta exige a base
completa da Receita (~7 GB/mês, publicada em `arquivos.receitafederal.gov.br`, compartilhamento Nextcloud com uma
pasta `AAAA-MM` por mês).

## Decisão

Separar o trabalho pesado do app:

```
GitHub Actions (dia 20, mensal)                  App (Streamlit)
 baixa a base da Receita (retomável)              botão "Buscar lista atualizada"
 filtra pelos ICPs de icp.yaml (streaming)  ───►  GET na release (token somente leitura)
 descarta contato, sócios e MEI                   dedup + candidatos pendentes
 publica cnpj_icp.csv na release cnpj-feed        aprovação humana (inalterada)
```

- `app/discovery/receita_feed.py` é o coletor, que roda no Actions. A regra de ICP é a mesma do app
  (`sources.matches_icp`).
- `app/discovery/feed.py` busca a release no app. Usa host fixo, tamanho limitado e somente leitura.
- O upload manual de CSV continua disponível como contingência.
- `max_candidates_per_run` passou a limitar candidatos **novos**. Antes ele cortava antes da dedup, e uma lista
  mensal repetida não traria ninguém novo depois da primeira geração.

## Alternativas descartadas (por enquanto)

- **Processar a base no próprio app:** exige máquina sempre ligada e vários GB de disco.
- **API paga com busca por filtro:** tem custo recorrente. Pode entrar depois como outra fonte, sem mudar o fluxo.
- **Scraping de sites de consulta:** viola os termos de uso.

## Consequências

- Custo zero: cerca de 1 a 2 h de runner por mês, dentro da cota gratuita de repositório privado.
- A lista tem até um mês de defasagem, o que é aceitável para prospecção.
- Se a Receita mudar o link ou o layout, o workflow falha de forma visível na aba Actions. A correção é
  `receita.share_url` em `icp.yaml` ou as posições de coluna em `receita_feed.py`.
- **Revisar** quando houver servidor dedicado (fase de uso contínuo). Nesse caso o coletor pode rodar no próprio
  servidor por cron, sem GitHub.
