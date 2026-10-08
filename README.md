# 🎯 Asimov Prospector — Inteligência de Prospectamento B2B

O **Asimov Prospector** é um sistema de inteligência de vendas desenvolvido para a **Asimov Jr.** (Empresa Júnior de Tecnologia da UNIFEI). O objetivo principal é automatizar a identificação e a qualificação de potenciais clientes B2B.

Em vez de categorizar empresas apenas pelo setor de atuação (CNAE/Indústria), o sistema utiliza **Inteligência de Sinais Operacionais**. Ele analisa a presença digital, sites institucionais e páginas públicas de organizações para encontrar evidências reais de gargalos operacionais ou tecnológicos — correlacionando essas necessidades com o portfólio de soluções da Asimov Jr.

---

## 📌 Visão Geral da Solução

Atualmente, o sistema opera localmente via interface interativa em **Streamlit**. O fluxo processa listas e planilhas de empresas, analisa os sites públicos e devolve um **ranking de viabilidade de contato** acompanhado de justificativas comerciais para a equipe de vendas.

┌─────────────────┐     ┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│ Entrada de Leads│ ──► │ Coleta & Análise │ ──► │  Identificação   │ ──► │ Ranking & Score  │
│   (Planilha/URL)│     │  da Web (Sites)  │     │    de Sinais     │     │   (Streamlit)    │
└─────────────────┘     └──────────────────┘     └──────────────────┘     └──────────────────┘


---

## 🧠 Lógica do Motor de Inteligência (Problem-to-Solution)

O algoritmo cruza as informações capturadas no site do prospect com as competências da Asimov Jr., gerando pontuações específicas por categoria de serviço:

1. **Software Personalizado:** Identifica sinais de operação complexa, uso intensivo de planilhas, processos manuais, gestão descentralizada de unidades e múltiplos sistemas desconectados.
2. **Aplicativos Mobile:** Identifica sinais de equipes em campo, rotas de entrega, inspeções presenciais, relatórios de visita e necessidade de coleta de dados offline.
3. **Ciência & Análise de Dados:** Identifica sinais de alto volume transacional, múltiplos indicadores operacionais, relatórios manuais recorrentes e necessidade de acompanhamento em tempo real via Dashboards.
4. **Sites e Portais Web:** Identifica presença digital desatualizada, ausência de área do cliente/portal ou baixa capacidade de conversão de leads.

### Regra de Separação Rígida
Para evitar falsas promessas ou "alucinações", a ferramenta separa estritamente:
* **Fato Observado:** Dado literal encontrado no site (ex.: *"A empresa possui 15 unidades e equipes de inspeção"*).
* **Inferência:** Interpretação lógica do fato (ex.: *"A coleta de dados das inspeções pode ser descentralizada"*).
* **Hipótese Comercial:** A oportunidade sugerida para a Asimov (ex.: *"Oportunidade para aplicativo móvel de vistoria com sincronização offline"*).

---

## 🛠️ Tecnologias Utilizadas

* **Interface Visual:** Streamlit
* **Linguagem & Execução:** Python 3.10+
* **Banco de Dados Local:** SQLite (para guardar análises, histórico e feedbacks)
* **Web Scraping & Extraction:** BeautifulSoup, Playwright, HTTPX
* **Inteligência Artificial:** Modelos de Embeddings (`sentence-transformers`) e integração com LLMs locais (Ollama / Qwen / Llama 3)
* **Testes Automatizados:** Pytest

---

## 📂 Estrutura do Repositório

asimov-prospector/
├── app/                  # Código-fonte principal
│   ├── config/           # Definições de sinais, regras e pesos de scoring
│   ├── core/             # Configurações globais, utilitários e segurança (SSRF)
│   ├── crawler/          # Módulos de requisição, parsing e raspagem web
│   ├── database/         # Schema e manipulação do banco SQLite
│   ├── discovery/        # Motores de busca, deduplicação e entrada de leads
│   ├── extraction/       # Limpeza e tratamento de texto
│   ├── intelligence/     # Integração com LLMs, embeddings e extrator de sinais
│   ├── models/           # Schemas de dados e validação pydantic
│   ├── scoring/          # Calculador de match, explicação comercial e anti-ICP
│   └── ui/               # Interface em Streamlit
├── data/                 # Arquivos SQLite locais e bases de exemplo/seeds
├── docs/                 # Documentação técnica estendida (Arquitetura, Segurança, Operação)
├── eval/                 # Scripts de avaliação de métricas e benchmark
├── profile/              # Perfil da Asimov Jr., ICPs e regras de anotação
├── prompts/              # Prompts estruturados para extração e queries de IA
├── scripts/              # Scripts de inicialização rápida (.ps1, .sh, .bat)
├── tests/                # Suíte de testes unitários, integração e e2e
├── .env.example          # Modelo de variáveis de ambiente
├── requirements.txt      # Dependências do projeto
└── run.py                # Ponto de entrada para execução da aplicação
⚡ Manual de Instalação e Execução
Pré-requisitos
Python 3.10 ou superior instalado na máquina.

Git instalado.

1. Clonar o Repositório
Bash
git clone [https://github.com/seu-usuario/asimov-prospector.git](https://github.com/seu-usuario/asimov-prospector.git)
cd asimov-prospector
2. Configurar o Ambiente Virtual
No Windows:

Bash
python -m venv venv
.\venv\Scripts\activate
No Linux/Mac:

Bash
python3 -m venv venv
source venv/bin/activate
3. Instalar Dependências
Bash
pip install -r requirements.txt
(Opcional - caso utilize recursos dinâmicos do Playwright para scraping):

Bash
playwright install chromium
4. Executar a Aplicação
Opção Rápida no Windows:
Basta dar um duplo clique no arquivo scripts/Iniciar_Asimov_Prospector.bat localizado na raiz do projeto.

Via Terminal (Windows, Linux ou Mac):

Bash
python run.py
A interface interativa do Streamlit abrirá automaticamente no seu navegador pelo endereço http://localhost:8501.

🧪 Execução de Testes Automatizados
Para validar o funcionamento dos módulos de scoring, extrator de sinais, proteção contra injeção de prompt e conexões:

Bash
pytest
Para rodar os testes de avaliação com o conjunto de teste de acurácia:

Bash
python -m eval.run_eval
🛡️ Segurança e Proteção de Dados (LGPD)
Privacidade e LGPD: O sistema analisa exclusivamente dados públicos de Pessoas Jurídicas (empresas). Informações pessoais de pessoas físicas são descartadas durante o processo de extração.

Proteção contra Prompt Injection Indireto: Conteúdos baixados de sites terceiros são tratados como dados não confiáveis. Instruções maliciosas contidas em sites analisados são isoladas e ignoradas pelo motor de IA.

SSRF (Server-Side Request Forgery): O crawler bloqueia requisições a IPs internos ou redes locais (127.0.0.1, 10.x.x.x, etc.).

🔁 Evolução Futura do Projeto
Os dados de interações, diagnósticos de sites e avaliações manuais inseridas pelo time comercial através do painel Streamlit (Human-in-the-Loop) serão mantidos no banco local.

Essa base servirá para:

Dataset de Treinamento: Formar uma base anotada de alta qualidade para ajuste fino (fine-tuning) e otimização dos prompts dos modelos locais.

Prospecção Ativa Autônoma: Evoluir do formato de carregamento por planilha/lista para um módulo que descobre novos domínios web de forma totalmente automática a partir das necessidades identificadas no mercado.

Ajuste Fino de Pesos (Scoring): Rebalancear automaticamente a relevância dos sinais conforme a taxa de conversão real obtida nas abordagens comerciais da Asimov Jr.
