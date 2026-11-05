# Asimov Prospector

Ferramenta interna de **inteligência de prospecção B2B** da Asimov Jr.

Em uma frase: o sistema encontra empresas com potencial para a Asimov, analisa o que elas mostram publicamente
(site, serviços, sinais de problemas operacionais, digitais ou de dados), relaciona isso aos serviços da Asimov e
entrega uma **lista ordenada para o time comercial avaliar**. Quem decide continua sendo uma pessoa.

## Sumário

1. [Visão geral](#visão-geral)
2. [Guia rápido: da lista de empresas ao ranking](#guia-rápido-da-lista-de-empresas-ao-ranking)
3. [Prospecção automatizada (GitHub Actions)](#prospecção-automatizada-github-actions)
4. [Usando o sistema no dia a dia](#usando-o-sistema-no-dia-a-dia)
5. [Como interpretar o resultado](#como-interpretar-o-resultado)
6. [Dúvidas e problemas comuns](#dúvidas-e-problemas-comuns)
7. [Acesso e segurança](#acesso-e-segurança)
8. [Para a equipe técnica](#para-a-equipe-técnica)

---

## Visão geral

### De onde vêm as empresas

| Origem | Como funciona | Quem usa |
|---|---|---|
| **Ploomes (CRM)** | O sistema *lê* as empresas e negócios do CRM. Nunca escreve nada lá. | Administrador sincroniza |
| **Leads novos (CNPJ aberto)** | Uma lista mensal da Receita Federal, já filtrada pelo perfil de cliente ideal (ICP), gerada **automaticamente** pelo GitHub Actions. | Administrador gera; qualquer pessoa aprova |
| **Lista própria (planilha)** | Contingência: você sobe um `.xlsx` ou `.csv`. | Qualquer usuário |
| **Uma empresa só** | Contingência: teste rápido de um site. | Qualquer usuário |

### O fluxo completo

```
Ploomes (CRM, somente leitura) ──┐
Leads novos (CNPJ aberto → aprovação humana) ──┼──► Analisar ──► Ranking ──► Avaliar (boa/neutra/ruim) ──► Exportar
Lista própria / empresa única (contingência) ──┘
```

A avaliação do time comercial **ensina o sistema**: com avaliações suficientes, ele passa a ajustar, de forma
limitada e auditável, o peso dos sinais e segmentos que o time aprovou ou rejeitou.

### O que o sistema **não** faz

- Não envia e-mail nem WhatsApp e não aborda empresas sozinho: todo contato continua humano.
- Não usa dados pessoais (telefone, sócios e decisores da base da Receita nunca entram no sistema).
- Não escreve no Ploomes, em nenhuma circunstância.
- Não declara que uma empresa é cliente nem garante que ela vai fechar negócio.
- Não analisa leads novos sem que uma pessoa aprove antes.

---

## Guia rápido: da lista de empresas ao ranking

Este é o caminho mais comum, passo a passo. Cada etapa é detalhada nas seções seguintes.

| # | O que acontece | Quem faz | Onde |
|---|---|---|---|
| 1 | A lista do mês é montada a partir da base da Receita | **Automático** (GitHub Actions, dia 20) | GitHub |
| 2 | O app busca a lista pronta e gera os **candidatos** | Administrador | Tela *Nova análise* → botão **Buscar lista atualizada e gerar candidatos** |
| 3 | Os candidatos são revisados | Time comercial | Tela *Nova análise* → **Aprovar** ou **Rejeitar** |
| 4 | As aprovadas são analisadas (sites, sinais, pontuação) | Sistema | Automático após aprovar |
| 5 | O ranking aparece ordenado por pontuação | Sistema | Tela *Ranking* |
| 6 | Cada empresa recebe uma avaliação: 👍 boa, 😐 neutra, 👎 ruim | Time comercial | Tela *Avaliar* |
| 7 | O ranking é exportado para o Comercial | Qualquer usuário | Tela *Ranking* → Excel/CSV |

---

## Prospecção automatizada (GitHub Actions)

### O que é e por que existe

A Receita Federal publica todo mês uma base com **todas as empresas do Brasil** (cerca de 7 GB). É grande demais
para o notebook do time, então o trabalho pesado fica em um **robô gratuito do GitHub**, o *GitHub Actions*:

```
GitHub Actions (todo dia 20)                    Aplicativo (na sua máquina)
  1. baixa a base da Receita                      1. você clica em "Buscar lista atualizada"
  2. separa só as empresas do nosso ICP    ───►   2. o app baixa o recorte pronto (poucos MB)
  3. remove dados pessoais e MEIs                 3. o time aprova ou rejeita cada candidato
  4. guarda o resultado (a "release")             4. as aprovadas são analisadas
```

O que isso significa na prática:

- **Custo zero:** o robô usa cerca de 1 a 2 horas por mês, dentro da cota gratuita do GitHub.
- **Ninguém precisa baixar nada da Receita.** O upload manual de CSV existe só como plano B.
- **A lista tem até um mês de defasagem**, o que é aceitável para prospecção.
- **O recorte já vem filtrado** pelo perfil de cliente ideal (veja [Quais empresas entram na lista](#quais-empresas-entram-na-lista)).
- **Nada entra na análise sem aprovação humana.**

### Glossário rápido

| Termo | Significa |
|---|---|
| **Repositório** | A "pasta" do projeto no GitHub. |
| **Actions** | Aba do repositório onde o robô trabalha e onde se acompanha a execução. |
| **Workflow** | A receita que o robô segue. O nosso se chama **Lista de CNPJ (Receita)**. |
| **Release** | Onde o robô guarda o arquivo pronto (`cnpj_icp.csv`), na aba *Releases* do repositório. |
| **Token** | Uma "chave de acesso" que permite ao app buscar o arquivo no repositório privado. Só leitura. |
| **ICP** | Perfil de cliente ideal: setor, região e porte das empresas que queremos prospectar. |
| **Candidato** | Empresa sugerida que ainda aguarda aprovação humana. |

### Configuração inicial (uma única vez)

Feita por quem administra o repositório. Depois disso, o processo roda sozinho todo mês.

#### Passo 1 — Gerar a primeira lista

1. Abra o repositório no GitHub e clique na aba **Actions**.
2. No menu da esquerda, clique em **Lista de CNPJ (Receita)**.
3. Clique no botão **Run workflow** (à direita) e confirme em **Run workflow**.
4. Aguarde. **Leva de 1 a 2 horas**, porque o servidor da Receita é lento. Você pode fechar a página.
5. Quando terminar, a execução aparece com um ✅ verde.

> Se o botão **Run workflow** não aparecer, confirme que o arquivo `.github/workflows/cnpj-feed.yml` está na
> branch principal (`main`) do repositório.

#### Passo 2 — Criar o token de acesso para o app

O repositório é privado. Por isso o app precisa de uma chave de leitura para baixar o arquivo.

1. No GitHub, clique na sua foto → **Settings** → **Developer settings** → **Personal access tokens** →
   **Fine-grained tokens** → **Generate new token**.
2. Dê um nome (ex.: `asimov-prospector-leitura`) e escolha uma validade.
3. Em **Repository access**, selecione **Only select repositories** e escolha somente este repositório.
4. Em **Permissions** → **Repository permissions**, defina **Contents** como **Read-only**. Nenhuma outra permissão.
5. Clique em **Generate token** e **copie o código** (ele só aparece uma vez).

#### Passo 3 — Colocar o token no aplicativo

1. Na pasta `asimov-prospector`, abra o arquivo `.env` (criado automaticamente na primeira execução; se não
   existir, copie `.env.example` e renomeie para `.env`).
2. Preencha a linha:
   ```
   CNPJ_FEED_TOKEN=cole_o_token_aqui
   ```
3. Salve e reinicie o sistema (feche e abra `INICIAR_ASIMOV.bat`).

> **Cuidado:** o token é uma senha. Não envie por e-mail ou chat, não coloque no repositório e não compartilhe
> o arquivo `.env`. Ele dá acesso de **leitura** ao repositório.

Pronto. A partir de agora, o botão **Buscar lista atualizada e gerar candidatos** passa a funcionar.

### Rotina mensal

| Quando | O que acontece | Precisa agir? |
|---|---|---|
| **Dia 20 de cada mês, 6h (Brasília)** | O robô monta a lista do mês e publica. | Não |
| **Depois disso** | O administrador abre o app e busca a lista atualizada. | Sim, 1 clique |
| **Em seguida** | O time aprova ou rejeita os candidatos e a análise roda. | Sim |

Um e-mail do GitHub avisa se a execução automática **falhar** (se as notificações da conta estiverem ativas).

### Como gerar candidatos no aplicativo (administrador)

1. Abra o sistema e vá para **Nova análise**.
2. Na seção **Gerar leads novos (dados abertos de CNPJ)**, clique em **Buscar lista atualizada e gerar candidatos**.
3. O app baixa a lista e mostra um resumo, por exemplo: *"120 linhas casaram com algum ICP; 35 candidatos novos
   para aprovar (85 já conhecidos, 0 sem CNPJ)"*.

Entendendo o resumo:

- **Casaram com algum ICP:** empresas da lista que se encaixam no perfil.
- **Candidatos novos:** as que ainda não conhecíamos, aguardando aprovação.
- **Já conhecidos:** já estão no Ploomes, no histórico ou foram aprovadas/rejeitadas antes. Não voltam à fila.

Regras de proteção:

- A geração pode ser feita **no máximo uma vez a cada 24 horas**. Se tentar antes, o app avisa.
- Cada geração traz **no máximo 500 candidatos novos**.
- Só **uma rodada de análise por vez**: se alguém já estiver analisando, o app avisa e você tenta depois.

### Como aprovar ou rejeitar candidatos (time comercial)

Abaixo do botão aparece a tabela de candidatos, com empresa, CNPJ, município, UF e **"Por que foi sugerida"**.

1. Marque uma ou mais linhas.
2. Clique em **✅ Aprovar e analisar** (a empresa entra na análise) ou **❌ Rejeitar** (ela sai da fila e não volta).

Dica: aprove em lotes de 20 a 50 empresas no começo. Veja [Primeiro piloto](#primeiro-piloto).

### Quais empresas entram na lista

Hoje, dois perfis (ICPs) estão configurados:

| Perfil | Setor (CNAE) | Região |
|---|---|---|
| Indústria — Sul de Minas | Indústria (metalurgia e máquinas/equipamentos) | Itajubá, Pouso Alegre, Varginha, Poços de Caldas, Santa Rita do Sapucaí e Lavras (MG) |
| Serviços técnicos — Sul de Minas | Construção especializada, engenharia/arquitetura e manutenção | As mesmas cidades |

Empresários individuais e MEI ficam de fora de propósito: a razão social deles traz nome e CPF de pessoas
(LGPD) e o porte foge do perfil.

**Para mudar setor, cidades ou criar um novo perfil**, edite `asimov-prospector/app/config/icp.yaml` (peça apoio da
equipe técnica). A mudança vale a partir da **próxima execução do robô**; para ver o efeito antes, rode o workflow
manualmente (Passo 1).

### Acompanhando e rodando manualmente

- **Ver se o robô rodou:** repositório → aba **Actions** → **Lista de CNPJ (Receita)**. ✅ verde = ok; ❌ vermelho =
  falhou (clique na execução para ver o motivo); 🟡 amarelo = em andamento.
- **Ver o arquivo gerado:** repositório → lateral direita **Releases** → **Lista de CNPJ (ICP)**. A descrição
  mostra o resumo da última geração.
- **Rodar fora do dia 20:** aba Actions → *Lista de CNPJ (Receita)* → **Run workflow**. Útil quando o ICP muda
  ou quando a execução automática falhou.

### Se a automação falhar

| Sintoma | Provável causa | O que fazer |
|---|---|---|
| App diz *"A lista de CNPJ ainda não foi publicada"* | O robô ainda não rodou ou falhou | Rode o workflow (Passo 1) e espere o ✅ |
| App diz *"Token do GitHub inválido ou sem acesso"* | Token expirou, foi digitado errado ou sem permissão **Contents: Read-only** | Gere um novo token (Passo 2) e atualize o `.env` |
| App diz *"Busca automática não configurada"* | `CNPJ_FEED_TOKEN` vazio no `.env` | Preencha o token (Passo 3) e reinicie o app |
| App diz *"Sem conexão com o GitHub"* | Internet instável | Tente de novo em instantes |
| Execução ❌ na aba Actions | A Receita mudou o link ou o formato da base, ou ficou fora do ar | Rode novamente mais tarde; se persistir, acione a equipe técnica (ver [Para a equipe técnica](#para-a-equipe-técnica)) |
| Aparece o botão de **enviar CSV** em vez do botão automático | O token não está configurado | Preencha `CNPJ_FEED_TOKEN`, ou use o CSV como contingência |

> **Tokens têm validade.** Anote a data de expiração escolhida no Passo 2 e gere um novo antes de vencer, para a
> busca não parar de funcionar sem aviso.

### Plano B: enviar um CSV manualmente

Se a automação estiver fora do ar, o administrador pode, na mesma tela, abrir **Enviar um CSV manualmente
(contingência)** e subir um extrato de CNPJ com as colunas
`cnpj, razao_social, nome_fantasia, cnae, uf, municipio, porte, situacao`. O filtro por ICP e a aprovação humana
valem do mesmo jeito.

---

## Usando o sistema no dia a dia

### Abrir o sistema (Windows)

Dê dois cliques em `INICIAR_ASIMOV.bat`, na pasta `asimov-prospector`. Na primeira execução, o ambiente é preparado
automaticamente (pode levar alguns minutos; é necessário ter o Python 3.11 ou superior instalado). Depois disso, a
interface abre direto no navegador.

### As três telas

- **Nova análise** — escolha a origem das empresas: sincronizar o Ploomes (administrador), gerar e aprovar leads
  novos (seção acima), subir uma lista própria ou testar uma empresa; depois escolha quantas analisar agora.
- **Ranking** — empresas ordenadas por pontuação, com exportação para Excel/CSV.
- **Avaliar** — evidências de cada empresa (fato / inferência / hipótese) e a sua avaliação em 3 níveis.

### Primeiro piloto

Analise **20 a 50 empresas por vez**, não centenas. A métrica mais importante não é quantas empresas foram
encontradas, e sim **quantas das 10 primeiras realmente parecem boas oportunidades**.

### Lista própria (planilha)

Colunas obrigatórias: `empresa`, `site`. Opcionais: `municipio`, `uf`, `segmento`. A interface aceita `.xlsx` e
`.csv` e oferece um modelo para download.

---

## Como interpretar o resultado

A **pontuação** é uma nota de compatibilidade com uma oportunidade para a Asimov — **não é probabilidade de
fechamento**. O ranking mostra só o que é verificável (pontuação, oportunidade, hipótese e evidências); não há
rótulos de "confiança" até haver avaliações suficientes para sustentá-los estatisticamente.

Cada conclusão vem com **evidência**: um trecho do site e o endereço de onde ele foi tirado. As evidências são
classificadas em três tipos que nunca se misturam:

- **Fato:** está escrito no site.
- **Inferência:** conclusão razoável a partir de fatos.
- **Hipótese:** algo a confirmar na conversa. **Confirme antes de qualquer contato.**

Para cada empresa, o time responde **👍 Boa oportunidade**, **😐 Neutra** ou **👎 Ruim**. Essas respostas alimentam
o aprendizado do sistema; com amostra mínima (ver `app/config/scoring.yaml`), a tela **Ranking** oferece **Aplicar
aprendizado ao ranking** (reprocessa sem acessar os sites de novo).

Negócios dos funis do Ploomes que não fazem parte do mapeamento configurado são ignorados (apenas contados no
relatório de sincronização).

---

## Dúvidas e problemas comuns

**Uma empresa deu erro na análise. Perdi o lote?**
Não. Erros de SSL, tempo esgotado, DNS ou transporte afetam só aquela empresa; a análise segue para as demais e o
erro fica registrado para auditoria. Se precisar reiniciar, feche a interface e abra `INICIAR_ASIMOV.bat` de novo.

**O app diz que há outra rodada em andamento.**
Só uma análise roda por vez. Aguarde a outra terminar e tente novamente.

**A geração de candidatos disse que é cedo demais.**
Há um intervalo mínimo de 24 horas entre gerações. Tente de novo mais tarde.

**Os candidatos novos acabaram. Por quê?**
A lista é mensal, e quem já foi gerado (aprovado ou rejeitado) não volta. Novos candidatos aparecem quando a Receita
atualiza a base ou quando o ICP é ampliado.

**Rejeitei uma empresa sem querer.**
Rejeitadas não voltam à fila. Se precisar, inclua a empresa por lista própria ou teste de empresa única.

**Quem pode fazer o quê?**
Administradores sincronizam o Ploomes e geram leads novos. Qualquer usuário logado analisa lotes, aprova
candidatos e avalia empresas.

---

## Acesso e segurança

- `AUTH_MODE=password` (padrão, usado no deploy): **login obrigatório**; usuários em `APP_USERS`, administradores
  em `APP_ADMINS`. Crie um usuário com `python run.py hash-password <usuario>`.
- `AUTH_MODE=local`: sem login, só aceita conexões da própria máquina — use apenas para uso individual.
- Segredos (token do GitHub, chave do Ploomes) ficam no `.env`, que **nunca** vai para o repositório.
- Detalhes dos controles (proteção contra acesso a endereços internos, injeção de instruções via conteúdo de sites,
  minimização de dados pessoais) em `asimov-prospector/docs/SEGURANCA_LGPD.md`.

---

## Para a equipe técnica

### Instalação e execução

Dentro de `asimov-prospector/`:

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

### Como a automação funciona por dentro

- **Workflow:** `.github/workflows/cnpj-feed.yml`. Dispara por `cron` (`0 9 20 * *`, dia 20, 6h de Brasília) e por
  `workflow_dispatch` (manual). Timeout de 300 min e `concurrency` para impedir duas execuções simultâneas.
- **Coletor:** `app/discovery/receita_feed.py` baixa a base (retomável), filtra em streaming com a mesma regra de
  ICP do app (`sources.matches_icp`), descarta contato, sócios e MEI, e publica `cnpj_icp.csv` na release
  `cnpj-feed`. Instala só `httpx`, `PyYAML` e `pydantic` no runner.
- **Cliente no app:** `app/discovery/feed.py` consulta a API do GitHub com o token somente leitura. Host fixo,
  tamanho limitado por `feed.max_mb` e nenhuma URL vinda do usuário (sem superfície de SSRF).
- **Configuração:** `app/config/icp.yaml` define `receita.share_url` (link da Receita), `feed.*` (repositório,
  release e arquivo), `max_candidates_per_run` e `min_generation_interval_hours`.
- **Se a Receita mudar o link:** ajuste `receita.share_url`. **Se mudar o layout:** ajuste as posições de coluna em
  `receita_feed.py`. Falhas aparecem de forma visível na aba Actions.
- **Testar o coletor localmente:** `python -m app.discovery.receita_feed --out data/cnpj_icp.csv`.
- Decisão e alternativas descartadas: `docs/DECISAO_FONTE_CNPJ.md`. Quando houver servidor dedicado, o coletor pode
  rodar por cron nele, sem GitHub.

### Comandos de linha de comando

Fora da interface, `run.py` também cobre: `run --seeds data/seeds.csv [--cnpj-csv ... --cnae ... --uf ... --municipio ...]`
(rodada via CLI), `report --out data/prospects_report.csv` (exporta evidências e hipótese, sem dados de contato),
`analyze-url <url>` (valida uma hipótese isolada), `demo` (pipeline completo com fixtures offline, sem rede),
`export-labels`/`eval` (amostragem cega e avaliação P@10/NDCG contra rótulos humanos), `backtest-leads`,
`sync-ploomes --by <quem>` (mesma sincronização da tela, via terminal) e `purge --days N` (remove páginas/cache
antigos conforme a política de retenção).

### Arquitetura

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

### Validação

A suíte atual deve permanecer verde: `python -m pytest -q`. O desempenho comercial ainda precisa ser validado com
50–100 avaliações humanas; as métricas da demo (`python run.py demo`) não representam performance comercial.

### Próxima etapa

Depois de a Operação ser usada por pessoas reais, o próximo módulo é **Comercial**. O módulo de Administração vem
depois, para permitir manutenção de ICP, sinais, cases e permissões sem editar código.
