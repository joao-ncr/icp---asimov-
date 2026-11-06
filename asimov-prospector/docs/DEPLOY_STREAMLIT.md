# Deploy no Streamlit Community Cloud

## O problema que isto resolve

O Streamlit Community Cloud **apaga o disco do app a cada reinício**: deploy novo (push), app dormindo por falta de uso,
"Reboot" ou reciclagem do contêiner. O banco `data/asimov.db` (avaliações do time, análises, histórico do Ploomes)
sumiria junto. Além disso, `data/*.db` e as planilhas de leads não vão para o repositório (LGPD), então o primeiro
deploy começa com o banco vazio.

## Como funciona

| Momento | O que acontece | Onde |
|---|---|---|
| App sobe com o disco vazio (ou a release tem uma cópia diferente da que o disco representa) | baixa a cópia mais recente do banco da release `db-backup` do repositório privado | `database/backup.py` (`restore_if_missing`) |
| Qualquer gravação no banco | ~30 s depois, envia uma cópia nova (gravações seguidas viram um único envio); mantém as 3 últimas | `database/backup.py` (`BackupScheduler`), `config/backup.yaml` |
| App sobe e o Ploomes não é sincronizado há mais de 12 h | sincroniza sozinho em segundo plano (somente leitura) | `ui/data.py` (`start_ploomes_auto_sync`), `config/ploomes.yaml` (`auto_sync_after_hours`) |
| Restauração falha (GitHub fora, token errado) | **nenhuma cópia é enviada** nesse processo, para o banco vazio não sobrescrever a cópia boa; a próxima subida tenta de novo | marcador `asimov.db.restore-pending` |

Decisão: por que release do GitHub e não um banco externo (Turso/Postgres). O código usa recursos do `sqlite3`
(`sqlite3.Row`, `executescript`, `BEGIN IMMEDIATE`) em dezenas de pontos; portar seria uma reescrita da camada de
dados. O Community Cloud roda **um único contêiner**, ou seja, um único processo escrevendo, então a cópia do arquivo
é suficiente, sem custo e sem dependência nova. Janela de perda: as gravações dos últimos ~30 s antes de um
encerramento abrupto (num encerramento normal, o envio pendente é feito antes de sair). Se o app passar a rodar em
mais de uma instância, essa decisão precisa ser revista.

Uso local: sem `DB_BACKUP_TOKEN` no `.env`, nada disso liga. **Não coloque o token no `.env` local**: o banco da
sua máquina passaria a sobrescrever a cópia do deploy.

## Passo a passo

### 1. Token do GitHub (cópia do banco)
GitHub → Settings → Developer settings → Personal access tokens → **Fine-grained tokens** → Generate new token:
- Repository access: **Only select repositories** → `icp---asimov-`
- Permissions → Repository permissions → **Contents: Read and write** (é o que permite criar/atualizar releases)
- Expiração: anote a data; ao expirar, a cópia para de ser enviada (aviso na barra lateral para administradores)

### 2. Secrets do app
share.streamlit.io → o app → ⋮ → **Settings → Secrets**. Todas as chaves no **nível de cima** (sem `[seção]`):

```toml
AUTH_MODE = "password"
APP_USERS = "joao=pbkdf2_sha256$...;outro=pbkdf2_sha256$..."   # python run.py hash-password <usuario>
APP_ADMINS = "joao"                                             # quem pode sincronizar o Ploomes
PLOOMES_USER_KEY = "..."                                        # chave de integração do Ploomes
DB_BACKUP_TOKEN = "github_pat_..."                              # token do passo 1
CNPJ_FEED_TOKEN = "github_pat_..."                              # opcional: lista mensal de CNPJ
```

Salvar reinicia o app.

### 3. Primeira carga
Entre como administrador → **Nova análise**. A sincronização automática do Ploomes já começa ao subir; se quiser,
clique em **🔄 Sincronizar com o Ploomes**. A barra lateral mostra "Cópia de segurança do banco: <horário>" depois do
primeiro envio. Confira em GitHub → Releases → `db-backup` que existe um arquivo `asimov-db-....sqlite.gz`.

### 4. Opcional: levar o banco local para o deploy
Para levar as avaliações e análises já feitas na sua máquina, em `asimov-prospector/` (PowerShell), com o token só
neste terminal:

```powershell
$env:DB_BACKUP_TOKEN = "github_pat_..."; python run.py backup-push
```

Depois, em share.streamlit.io, **Reboot app**. Ao subir, o app vê que a cópia mais nova da release não é a que o
disco dele representa (`asimov.db.backup-version`) e a restaura. Faça isso com ninguém usando o app: avaliações
gravadas no deploy entre o envio e o reboot ficam de fora.

## Para voltar a uma cópia anterior
Em GitHub → Releases → `db-backup`, apague as cópias mais novas que a desejada e faça **Reboot app**: o app restaura a
mais nova que restou.
