# Asimov Prospector

Ferramenta interna de **inteligência de prospecção B2B** para a Asimov Jr.

O sistema analisa informações públicas de empresas, identifica sinais de possíveis problemas operacionais/digitais/dados, relaciona esses sinais aos serviços da Asimov e entrega um ranking para revisão humana.

## Para o usuário final

### Windows — caminho recomendado

Basta abrir:

`scripts/Iniciar_Asimov_Prospector.bat`

Na primeira execução, o sistema prepara o ambiente automaticamente. Depois abre a interface no navegador.

### Fluxo

`Planilha de empresas → Analisar → Ranking → Evidências → Avaliação humana → Exportar para Comercial`

Não é necessário conhecer Python ou usar terminal.

## Planilha

Obrigatório:

- `empresa`
- `site`

Opcional:

- `municipio`
- `uf`
- `segmento`

A interface aceita `.xlsx` e `.csv` e oferece um modelo para download.

## Para equipe técnica

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\bootstrap.ps1
.\scripts\start.ps1
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

## Arquitetura

O projeto é um **monólito modular**: o motor de inteligência existente fica separado da camada de operação. Isso permite construir Comercial e Administração depois sem reescrever crawler, scoring ou banco.

O núcleo preservado inclui:

- scoring determinístico separado da IA;
- evidência verificável;
- anti-ICP;
- histórico de leads;
- sinais por serviço;
- proteção contra SSRF e prompt injection;
- limites de crawler e cache;
- SQLite;
- testes automatizados;
- feedback humano.

## Validação

A suíte atual deve permanecer verde (`43 passed`). O desempenho comercial ainda precisa ser validado com 50–100 avaliações humanas; as métricas da demo não representam performance comercial.

## Próxima etapa

Depois de a Operação ser usada por pessoas reais, o próximo módulo é **Comercial**. O módulo de Administração vem depois, para permitir manutenção de ICP, sinais, cases e permissões sem editar código.
