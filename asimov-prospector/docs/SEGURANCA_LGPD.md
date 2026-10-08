# Seguranca e LGPD (analise tecnica; nao e aconselhamento juridico)

## Controles implementados (e onde)
| Ameaca | Controle | Arquivo / teste |
|---|---|---|
| SSRF | so http/https; portas 80/443; bloqueio de localhost/.local/.internal; **todos** os IPs resolvidos precisam ser publicos (`is_global`); IP literal/decimal/hex normalizados; sem credenciais na URL | `crawler/ssrf.py`, `tests/test_ssrf_fetcher.py` |
| Redirect para rede interna | redirects tratados manualmente (max 4) e **revalidados a cada salto** | `crawler/fetcher.py` |
| DNS rebinding | apos conectar, confere o IP efetivo do socket (`server_addr`) antes de ler o corpo | `crawler/fetcher.py` |
| Resposta enorme / bomba | leitura em stream com teto (2 MB), allowlist de content-type, timeout | idem |
| Abuso do alvo | robots.txt (4xx=permitido, 5xx=bloqueado), atraso por dominio, retry com backoff, cache, UA identificavel, **nao contorna 403/429** | idem |
| Prompt injection indireta | texto externo = dado nao confiavel; frases com padroes de injection **nao geram evidencia**; texto oculto (display:none etc.) removido e sinalizado; penalidade no multiplicador de evidencia; **score calculado em codigo, nunca pelo LLM**; saida do LLM restrita a JSON schema; citacao do LLM verificada contra o texto | `crawler/extract.py`, `intelligence/llm.py`, `pipeline.py`, `tests/test_llm_guard.py` |
| Alucinacao | evidencia so vale se o trecho existe literalmente na pagina citada; fato/inferencia/hipotese/ausencia em tipos distintos | `extraction/text.py` |
| Segredos | `.env` fora do git; sem API key obrigatoria; logs sem HTML bruto | `.env.example`, `.gitignore` |

**Limites conhecidos:** a protecao anti-rebinding detecta *apos* conectar (nao fixa o IP na conexao); rode o crawler em maquina/rede sem acesso a recursos internos sensiveis. Playwright nao esta implementado no MVP (se adicionar, isole em container sem acesso a rede interna). Um site pode *mentir* de forma plausivel: isso nao e injection e e tratado pela revisao humana. Detector de injection e baseado em padroes (PT/EN) e nao cobre todos os ataques.

## LGPD — decisoes de design
- **Minimizacao:** o programa trabalha com dados da empresa. Nao armazena socios, CPFs, e-mails ou telefones de pessoas. O carregador de CNPJ aberto le apenas razao/fantasia, CNAE, UF, municipio, porte e situacao.
- **Pessoas fisicas nos leads:** pseudonimizadas; vendedores nao importados.
- **Finalidade:** avaliar compatibilidade comercial da oferta da Asimov. Qualquer contato futuro exigira base legal documentada (ex.: legitimo interesse com teste de balanceamento) e canal de oposicao — **valide com o encarregado/juridico da UNIFEI ou da federacao de EJs antes de abordar**.
- **Retencao:** texto das paginas e cache sao temporarios; `python run.py purge --days 90` remove paginas e cache antigos. Analises ficam enquanto uteis.
- **Transferencia internacional:** LLM e embeddings locais (default) evitam enviar dados a terceiros. Ao usar API externa, reavalie.
- **Acesso:** execucao local; interface Streamlit so em localhost; disco criptografado recomendado.
