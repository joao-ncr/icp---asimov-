"""Tela "Como usar": manual do time comercial dentro do próprio app, em linguagem simples.

Só exibe texto. Não lê o banco nem dispara ações; os números citados vêm da configuração (não ficam duplicados aqui)."""
from __future__ import annotations
import streamlit as st
from app.core.auth import User
from app.feedback.store import LEVEL_LABELS
from app.integrations.ploomes.mapping import rules as ploomes_rules
from app.scoring.explain import SERVICE_NAMES
from app.scoring.score import cfg as scoring_cfg
from app.ui import theme
from app.ui.views.common import LEVEL_ICONS


def render(service: str, user: User) -> None:
    theme.hero("Como usar", "Tudo o que o time comercial precisa saber para usar o Prospector, sem precisar abrir o GitHub.")
    tabs = st.tabs(["🧭 Visão geral", "🪜 Passo a passo", "📊 Ranking e avaliação", "🔁 O que é automático", "❓ Dúvidas"])
    with tabs[0]:
        _overview()
    with tabs[1]:
        _step_by_step()
    with tabs[2]:
        _ranking_and_review()
    with tabs[3]:
        _automatic()
    with tabs[4]:
        _faq()


def _overview() -> None:
    st.markdown("""
### O que é o Prospector
Uma ferramenta que **pesquisa empresas na internet**, encontra sinais de que elas precisam de algo que a Asimov
oferece e entrega uma **lista em ordem de prioridade** para o time comercial avaliar.

**Quem decide continua sendo uma pessoa.** O sistema sugere; o time confirma.
""")
    a, b, c, d = st.columns(4)
    with a:
        theme.step(1, "Empresas entram", "Do Ploomes, da lista mensal de empresas novas ou de uma planilha.")
    with b:
        theme.step(2, "O sistema analisa", "Visita os sites e procura sinais ligados aos serviços da Asimov.")
    with c:
        theme.step(3, "Ranking", "As empresas aparecem em ordem de pontuação, com as evidências.")
    with d:
        theme.step(4, "O time avalia", "Cada avaliação ensina o sistema a sugerir melhor.")
    st.markdown("""
### De onde vêm as empresas
| Origem | O que é |
|---|---|
| **Ploomes** | As empresas e negócios que já estão no nosso CRM. O sistema **só lê**: nada é alterado no Ploomes. |
| **Leads novos** | Uma lista mensal de empresas da Receita Federal que se encaixam no nosso perfil de cliente ideal. **Nenhuma entra sem aprovação do time.** |
| **Lista própria** | Uma planilha enviada por você (empresa e site). |
| **Uma empresa só** | Para testar rapidamente o site de uma empresa. |

### O que o sistema **não** faz
- Não envia e-mail, WhatsApp ou qualquer mensagem às empresas.
- Não altera nada no Ploomes.
- Não guarda telefone, sócios ou decisores.
- Não garante que a empresa vai fechar: a pontuação indica **compatibilidade**, não chance de venda.
""")


def _step_by_step() -> None:
    st.markdown("""
### Analisar empresas do Ploomes
1. No menu à esquerda, abra **Nova análise**.
2. Em **📇 Empresas do Ploomes**, veja quantas empresas estão **aguardando análise**.
3. Escolha **quantas analisar agora** (comece com 20 a 50).
4. Clique em **🚀 Analisar próximas empresas** e **mantenha a aba aberta** até a barra de progresso terminar.
5. Abra **Ranking** para ver o resultado.

> A análise leva alguns minutos, porque cada site é visitado. Se for interrompida, o que já foi analisado fica salvo;
> é só clicar de novo para continuar de onde parou.

### Aprovar leads novos (lista mensal)
1. Em **Nova análise**, vá até **🧭 Gerar leads novos**.
2. Um **administrador** clica em **🧭 Buscar lista atualizada e gerar candidatos** (uma vez por mês, depois do dia 20).
3. Aparece a tabela de candidatos com o motivo de cada sugestão (**Por que foi sugerida**).
4. Marque as linhas e clique em **✅ Aprovar e analisar** ou **❌ Rejeitar**.

> Empresa rejeitada **não volta** para a fila. Na dúvida, aprove: a avaliação no ranking é que vai dizer se ela é boa.

### Usar uma planilha ou testar uma empresa
1. Em **Nova análise**, abra **Usar uma lista própria ou testar uma empresa**.
2. Baixe o **modelo de lista**, preencha as colunas **empresa** e **site** e envie o arquivo (.xlsx ou .csv).
3. Clique em **🚀 Iniciar análise da lista**.
4. Para uma empresa só, cole o endereço do site e clique em **Analisar uma empresa**.
""")


def _ranking_and_review() -> None:
    min_labels = scoring_cfg()["calibration"]["min_labels"]
    lead_min_labels = scoring_cfg()["calibration"]["lead_generation_min_labels"]
    levels = "\n".join(f"- **{LEVEL_ICONS[k]} {label}**" for k, label in LEVEL_LABELS.items())
    services = ", ".join(SERVICE_NAMES.values())
    st.markdown(f"""
### Lendo o ranking
| Coluna | O que significa |
|---|---|
| **#** | Posição no ranking. Comece pelo topo. |
| **Pontuação** | Compatibilidade com os serviços da Asimov. **Não é** probabilidade de fechar. |
| **Oportunidade** | O serviço da Asimov que mais combina com a empresa. |
| **Hipótese** | O possível problema da empresa, **a confirmar na conversa**. |
| **Avaliação** | Como o time avaliou (vazio = ainda não avaliada). |

- Marque **Mostrar só as que ainda não foram avaliadas** para ver o que falta.
- Use **Prioridade de serviço**, no menu à esquerda, para ordenar pensando em um serviço específico ({services}).
- **⬇️ Baixar Excel** ou **⬇️ Baixar CSV** exporta a lista para o Comercial.

### Avaliando uma empresa
1. No ranking, clique na linha da empresa e depois em **Avaliar →**.
2. Leia **💡 Hipótese comercial**, **🔎 O que foi observado** e **📚 Evidências**.
3. Responda: *esta empresa é uma boa oportunidade para a Asimov?*
{levels}
4. Se puder, escreva um **comentário** curto dizendo o porquê.
5. Clique em **Salvar e ir para a próxima**.

### Como ler as evidências
Toda conclusão vem com **o trecho do site e o endereço de onde ele foi tirado**, para você conferir.
- **Fato:** está escrito no site.
- **Inferência:** conclusão razoável a partir dos fatos.
- **Hipótese:** algo a **confirmar na conversa** antes de qualquer proposta.

### Por que avaliar é tão importante
Cada avaliação ensina o sistema. Com **{min_labels} avaliações**, ele começa a ajustar sozinho o peso do que o time
considera bom ou ruim (de forma limitada e sempre explicável). Com **{lead_min_labels} avaliações**, passa a usar esse
aprendizado para sugerir empresas novas. O progresso aparece no menu à esquerda.

Quando houver um aprendizado novo, o **Ranking** mostra o botão **Aplicar aprendizado ao ranking** (administrador).
""")


def _automatic() -> None:
    sync_hours = ploomes_rules()["api"]["auto_sync_after_hours"]
    st.markdown(f"""
### O que acontece sozinho
| O quê | Quando | Precisa de alguém? |
|---|---|---|
| Atualizar empresas e negócios do Ploomes | Ao abrir o app, se a última atualização tiver mais de {sync_hours} h | Não. Um administrador também pode clicar em **🔄 Sincronizar com o Ploomes** |
| Montar a lista de empresas novas da Receita | Todo **dia 20** | Não |
| Trazer essa lista para o app | Depois do dia 20 | **Sim:** um administrador clica em **Buscar lista atualizada** |
| Aprovar ou rejeitar os leads novos | Depois que a lista chega | **Sim:** o time |
| Analisar as empresas | Quando alguém pede | **Sim:** escolher o lote e clicar em analisar |
| Avaliar o ranking | Sempre que houver empresas novas | **Sim:** o time |
| Salvar tudo (análises, avaliações, histórico) | Automaticamente, alguns segundos após cada mudança | Não |

### Onde ficam os dados
Tudo fica salvo na nuvem. **Ninguém precisa deixar computador ligado.** Se o app ficar um tempo sem uso, ele
"dorme": quem abrir depois verá um botão para acordá-lo, e em cerca de um minuto tudo volta como estava.

### Quem pode fazer o quê
| Ação | Quem |
|---|---|
| Ver ranking, avaliar, analisar lotes, aprovar ou rejeitar leads novos | Qualquer pessoa com login |
| Sincronizar o Ploomes, buscar a lista mensal, aplicar aprendizado | Administrador |
""")


def _faq() -> None:
    questions = {
        "Apareceu \"Há uma tarefa em andamento\". O que faço?":
            "Só uma análise (ou atualização do Ploomes) roda por vez para todo o time. Espere alguns minutos e tente de novo. "
            "Ver o ranking e avaliar continuam funcionando normalmente.",
        "Várias pessoas podem usar ao mesmo tempo?":
            "Sim. Todos podem ver o ranking e avaliar ao mesmo tempo. Só a análise de empresas é uma por vez.",
        "Uma empresa deu erro na análise. Perdi o lote?":
            "Não. O erro afeta só aquela empresa (site fora do ar, lento ou bloqueado); as outras seguem normalmente.",
        "O app pediu para \"acordar\" (wake up). É normal?":
            "Sim. Sem uso por algumas horas, o app dorme para economizar. Clique no botão e espere cerca de um minuto.",
        "A pontuação é a chance de fechar negócio?":
            "Não. É a compatibilidade da empresa com os serviços da Asimov, a partir do que ela mostra publicamente. "
            "Quem confirma a oportunidade é a conversa comercial.",
        "Avaliei errado. Dá para corrigir?":
            "Sim. Abra a empresa em **Avaliar** de novo: a avaliação anterior aparece e você pode atualizá-la.",
        "Rejeitei um lead novo sem querer.":
            "Ele não volta para a fila. Se quiser analisá-lo, use **Usar uma lista própria ou testar uma empresa** em **Nova análise**.",
        "Os leads novos acabaram.":
            "A lista é mensal. Novos candidatos aparecem depois do próximo dia 20 ou quando o perfil de cliente ideal for ampliado.",
        "Uma empresa do Ploomes está \"sem site\".":
            "Ela foi importada sem site no CRM. Fica registrada, mas a análise depende do site: atualize o cadastro no Ploomes.",
        "Encontrei algo estranho ou um erro.":
            "Anote a tela e o horário e avise o responsável técnico do projeto. Nada que você faça no app altera o Ploomes.",
    }
    for question, answer in questions.items():
        with st.expander(question):
            st.markdown(answer)
