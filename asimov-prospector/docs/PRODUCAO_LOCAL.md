# Operação local — Asimov Prospector

## Objetivo

Esta versão é um piloto operacional, não um SaaS e não um robô de outreach. O produto entrega uma fila de prospects com evidências públicas, sinais de necessidade, serviço provável e hipótese comercial.

## Instalação Windows

Abra PowerShell na pasta do projeto:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\bootstrap.ps1
.\scripts\start.ps1
```

A interface abre pelo Streamlit e usa `data/asimov.db`.

## Fluxo recomendado

### 1. Primeira inicialização

`bootstrap.ps1` cria o ambiente virtual, instala dependências, cria `.env`, importa `data/leads_reference.xlsx`, cria o banco e executa os testes.

### 2. Piloto assistido

Use 20–50 empresas reais em `data/seeds.csv`:

```csv
name,domain,municipio,uf,segment
Empresa A,https://empresa-a.com.br,Itajuba,MG,industria
Empresa B,https://empresa-b.com.br,Pouso Alegre,MG,servicos_tecnicos
```

Depois:

```powershell
.\.venv\Scripts\python.exe run.py run --seeds data/seeds.csv --top 20
.\.venv\Scripts\python.exe run.py report --top 20 --out data/prospects_report.csv
```

Ou carregue o CSV pela aba **Operar** da interface.

### 3. Análise individual

```powershell
.\.venv\Scripts\python.exe run.py analyze-url https://empresa.com.br --name "Empresa"
```

Use esse modo para validar uma hipótese antes de aumentar o lote.

### 4. Feedback

Na aba **Empresa**, classifique cada prospect. Os rótulos não alteram o score automaticamente: primeiro acumulam evidência para calibração. Isso evita overfitting em poucas observações.

## Critério de sucesso

Não medir sucesso por quantidade de empresas descobertas. A primeira métrica operacional é **Precision@10 humano**: entre os dez primeiros, quantos são considerados realmente interessantes pela equipe comercial/projetos.

Depois de 50–100 avaliações, revisar:

- pesos de `app/config/scoring.yaml`;
- taxonomia de `app/config/signals.yaml`;
- anti-ICP;
- templates de hipótese;
- similaridade com cases.

## Segurança

- conteúdo de sites é tratado como dado não confiável;
- SSRF e escopo de domínio são protegidos;
- limites de tamanho, páginas, timeout e atraso por domínio existem no crawler;
- evidência textual precisa ser verificável no conteúdo coletado;
- não há automação de contato;
- o cache e o banco são locais;
- `run.py purge --days 90` remove dados antigos conforme a política operacional configurada.

## O que não ativar ainda

Não adicionar Postgres, Redis, Celery, Kubernetes, CRM, WhatsApp, LinkedIn ou agentes autônomos antes de validar Precision@10. O gargalo atual é qualidade da descoberta e da priorização, não infraestrutura.

## Evolução após o piloto

1. 50–100 rótulos humanos.
2. Backtest com domínios reais dos leads históricos.
3. Ajuste dos pesos.
4. Incorporar similaridade entre problema identificado e cases verificados da Asimov.
5. Automatizar apenas a descoberta de candidatos em lote.
6. Manter revisão humana antes de qualquer ação comercial.
