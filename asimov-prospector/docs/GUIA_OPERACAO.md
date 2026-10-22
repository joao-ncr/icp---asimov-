# Guia de Operação — Asimov Prospector

## Para quem não é técnico

Você não precisa saber Python, programação, banco de dados ou IA para usar o Prospector.

O fluxo é:

1. Abra `scripts/Iniciar_Asimov_Prospector.bat`.
2. Na primeira vez, aguarde a instalação automática.
3. Baixe o **modelo de planilha** dentro da tela `Nova prospecção`.
4. Preencha pelo menos `empresa` e `site`.
5. Importe a planilha.
6. Clique em **Analisar empresas**.
7. Vá para `Resultados` e revise primeiro o Top 10.
8. Abra cada empresa em `Detalhar empresa`.
9. Marque sua avaliação.
10. Exporte `Resultados` para o Comercial.

## Planilha

Colunas obrigatórias:

- `empresa`: nome da organização.
- `site`: endereço público do site, por exemplo `https://empresa.com.br`.

Colunas opcionais:

- `municipio`
- `uf`
- `segmento`

O sistema aceita `.xlsx` e `.csv`.

## Como interpretar o resultado

### Pontuação

É uma nota de compatibilidade com uma oportunidade para a Asimov. **Não é probabilidade de fechamento.**
O ranking mostra só o que é verificável (pontuação, oportunidade, hipótese e evidências); rótulos de "confiança" foram retirados
até haver avaliações suficientes para sustentá-los estatisticamente.

### Sua avaliação (3 níveis)

Para cada empresa do ranking, o time comercial responde: **👍 Boa oportunidade**, **😐 Neutra** ou **👎 Ruim**.
Essas respostas ficam gravadas e alimentam o aprendizado do sistema.

### Aprendizado do ranking

Com 30 avaliações (ao menos 5 "boas" e 5 "ruins") o sistema passa a ajustar, de forma limitada e auditável, o peso dos sinais e
segmentos que o time aprovou ou rejeitou. Depois de cada nova avaliação ativa, a tela **Ranking** oferece
"Aplicar aprendizado ao ranking" (reprocessa sem acessar os sites). A geração de leads novos com os parâmetros aprendidos
fica para quando houver 100 avaliações.

### Uma análise por vez

Só uma rodada roda de cada vez (mesmo com várias abas abertas). Leads de nome ou site muito parecidos são analisados uma única vez.

### Hipótese comercial

É uma hipótese, não uma afirmação sobre a empresa. Antes de qualquer contato comercial, a equipe deve confirmar se o problema realmente existe.

## Como começar

Para o primeiro piloto, use 20–50 empresas. Não tente começar com centenas.

A métrica mais importante não é quantidade de empresas encontradas. É:

> **Quantas das 10 primeiras empresas realmente parecem boas oportunidades para a Asimov?**

Esse julgamento humano será armazenado como feedback para futuras calibrações.

## O que o sistema não faz

- Não envia e-mail.
- Não envia WhatsApp.
- Não aborda empresas automaticamente.
- Não usa dados privados.
- Não declara que uma empresa é cliente.
- Não substitui a decisão comercial.

## Se algo der errado

Feche a interface e execute novamente `scripts/Iniciar_Asimov_Prospector.bat`.

Para suporte técnico, preserve a mensagem de erro exibida na tela.


## Tratamento de HTTPS/SSL

O crawler valida certificados TLS normalmente. Em Windows e redes corporativas, a versao atual tenta usar a cadeia de certificados do sistema (`truststore`) e possui fallback para `certifi`.

Um erro SSL, timeout, DNS ou transporte em uma empresa e tratado como falha daquela empresa e **nao interrompe o lote**. A analise segue para as empresas seguintes. O erro fica registrado no run para auditoria.
