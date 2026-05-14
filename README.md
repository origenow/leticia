# leticia

Letícia Ambrósio — agente pré-vendedor (SDR) que prospecta lojistas de marketplaces
via WhatsApp, qualifica leads e entrega oportunidades pro Nathan fechar.

Stack: **Python 3.12 · Django 5 / DRF · Supabase Postgres · Evolution API (WhatsApp)
· Anthropic Claude · Slack Bolt (Socket Mode) · Railway**.

---

## Arquitetura em 30 segundos

```
        WhatsApp do lead
              │
              ▼
   ┌───────────────────────┐         ┌────────────────────┐
   │  Evolution API        │ ──────▶ │  /webhook/evolution│  (Django web)
   │  (instância Letícia)  │         │   POST              │
   └───────────────────────┘         └────────────────────┘
              ▲                                │
              │                                ▼
       send_text(phone)                ┌──────────────────┐
              │                        │ orchestrator      │
              │                        │  • guardrails    │
              │                        │  • Claude reply  │
              │                        │  • split balões  │
              │                        └────────┬─────────┘
              │                                  │
              └──────────────────────────────────┘
                                                 │
                                                 ▼
                                    ┌──────────────────────┐
                                    │ Supabase (schema=leticia) │
                                    │ leads, conversations,│
                                    │ messages, opt_outs,  │
                                    │ escalations, log     │
                                    └──────────────────────┘

   Slack #leticia-teste                Railway worker
   ────────────────────                ──────────────
   /start /stop /send ─── Socket Mode ▶ run_slack_bot ─▶ orchestrator
   (notificações de opt-out, escalação) ◀── slack_notify.post
```

Dois processos no Railway:

- **web** (`gunicorn`): recebe webhook do Evolution, expõe `/health/`.
- **worker** (`python manage.py run_slack_bot`): conecta no Slack via Socket Mode,
  recebe comandos do canal `#leticia-teste`.

---

## Setup completo (passo a passo)

### 0. Pré-requisitos

- Python 3.12 local (recomendado um venv)
- Conta Supabase, Railway, Anthropic, Slack (workspace + app), Evolution rodando

### 1. Supabase

1. Crie um projeto novo (ou reutilize um existente).
2. Em **SQL Editor**, cole o conteúdo de [`supabase/schema.sql`](supabase/schema.sql) e rode.
3. Em **Project Settings → Database** copie a **Connection string (Transaction pooler)**
   — vai ficar parecido com:
   ```
   postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:6543/postgres
   ```
   Esse é seu `DATABASE_URL`.

### 2. Slack App

1. Vá em <https://api.slack.com/apps> → **Create New App** → **From scratch** → nome `Letícia`.
2. **OAuth & Permissions**:
   - Bot Token Scopes: `chat:write`, `channels:history`, `groups:history`,
     `im:history`, `mpim:history`, `app_mentions:read`, `conversations.connect:read`,
     `users:read`, `channels:read`.
   - Install no workspace.
   - Copie o **Bot User OAuth Token** (`xoxb-...`) → `SLACK_BOT_TOKEN`.
3. **Socket Mode**: enable.
4. **Basic Information → App-Level Tokens → Generate**:
   - Scopes: `connections:write`, `authorizations:read`.
   - Copie o token (`xapp-1-...`) → `SLACK_APP_TOKEN`.
5. **Event Subscriptions**: enable; subscreva `message.channels`, `message.im`,
   `app_mention`.
6. Convide o bot pro `#leticia-teste`: `/invite @Letícia`.

### 3. Evolution API

Configure o webhook da instância pra apontar pro Railway. Pela API:

```bash
curl -X POST "$EVOLUTION_BASE_URL/webhook/set/$EVOLUTION_INSTANCE" \
  -H "apikey: $EVOLUTION_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "webhook": {
      "url": "https://<seu-app>.up.railway.app/webhook/evolution/?token=<EVOLUTION_WEBHOOK_TOKEN>",
      "enabled": true,
      "events": ["MESSAGES_UPSERT"]
    }
  }'
```

Gere um token aleatório (qualquer string longa) e use o mesmo em `EVOLUTION_WEBHOOK_TOKEN`
do Railway — assim a gente rejeita webhooks falsos.

### 4. Railway

1. **New Project → Deploy from GitHub** → escolha o repo `origenow/leticia`.
2. **Variables**: cole tudo do `.env.example` preenchido (não comite o `.env`).
3. **Add Service** pro worker do Slack:
   - O mesmo repo, mas Start Command: `python manage.py run_slack_bot`.
4. **Networking**: gere domínio público pro serviço `web` (pra ser o destino do webhook
   Evolution).

### 5. Rodar local pra testar

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS/Linux

pip install -r requirements.txt
cp .env.example .env            # preencha as chaves

# rodar a web (sem migrations — schema vive no Supabase)
python manage.py runserver 0.0.0.0:8000

# em outro terminal: o worker do Slack
python manage.py run_slack_bot
```

Pra expor o `/webhook/evolution/` pro Evolution em ambiente local use `ngrok`:

```bash
ngrok http 8000
```

---

## Comandos no Slack (`#leticia-teste`)

No Slack, `/` é reservado pra slash commands registrados no app. Pra falar com a
Letícia, **mencione a bot** (`@Letícia <cmd>`) — ou digite o comando direto no canal
sem mencionar, que também funciona.

| Comando                                  | Efeito |
|------------------------------------------|--------|
| `@Letícia start`                         | Liga autonomia GLOBAL (Letícia responde sozinha) |
| `@Letícia stop`                          | Desliga autonomia GLOBAL (mensagens entram só pra revisão) |
| `@Letícia start <fone>`                  | Liga autonomia só pra esse número |
| `@Letícia stop <fone>`                   | Desliga autonomia só pra esse número |
| `@Letícia send <fone> <texto>`           | Letícia envia mensagem manualmente |
| `@Letícia status`                        | Snapshot: leads, conversas ativas, opt-outs, escalações |
| `@Letícia history <fone>`                | Últimas 10 mensagens da conversa |
| `@Letícia optout <fone> [motivo]`        | Adiciona número à lista de bloqueio permanente |
| `@Letícia help`                          | Mostra a ajuda |

O bot só aceita comandos no canal `#leticia-teste` — ignora qualquer outro.

### Notificações automáticas que ela posta sozinha

- `:no_entry:` opt-out detectado (lead pediu pra parar)
- `:rotating_light:` escalação (lead falou Procon / advogado / processo / etc.)
- `:pause_button:` chegou mensagem mas autonomia está OFF (precisa de resposta manual)
- `:warning:` erro processando (Claude falhou, Evolution caiu, etc.)

---

## Guardrails (proteção)

- **Opt-out**: regex em `bot/services/guardrails.py`. Lead que diz "para", "não quero",
  "remove", "descadastra", etc. é adicionado a `leticia.opt_outs` e nunca mais é abordado.
- **Escalação**: palavras como "Procon", "Reclame Aqui", "advogado", "processo",
  "denúncia", "justiça" → grava em `leticia.escalations`, fecha autonomia daquela
  conversa, e o Nathan recebe ping no Slack.
- **Pergunta de identidade**: "você é IA?", "é robô?", "isso é automático?" →
  resposta honesta padronizada em `guardrails.IDENTITY_REPLY`. Nunca mascarar a
  natureza dela.
- **Toda mensagem** (inbound e outbound) é logada em `leticia.messages` pra auditoria.
- **Todo comando Slack** é logado em `leticia.command_log` (quem rodou, o quê, quando).

---

## Persona da Letícia

System prompt completo em [`bot/services/leticia_persona.py`](bot/services/leticia_persona.py).

Resumo: empática, sagaz, levemente engraçadinha. Mensagens curtas (1-2 linhas),
linguagem humanizada (`tá`, `pra`, `né`), reage ao que o lead falou antes de pitchar.
Mensagens longas são quebradas em 2-3 balões com o token `<<SPLIT>>` — o
`message_dispatcher` envia cada balão com delay de 2-8s simulando digitação.

---

## Layout do código

```
.
├── leticia_agent/          # Django project
│   ├── settings.py         # tudo via env vars
│   ├── urls.py             # /health/ e /webhook/
│   └── wsgi.py
├── bot/                    # Django app
│   ├── models.py           # managed=False (schema vive no Supabase)
│   ├── views.py            # webhook Evolution
│   ├── urls.py
│   ├── services/
│   │   ├── evolution.py            # cliente HTTP Evolution + parser webhook
│   │   ├── anthropic_client.py     # Claude com prompt caching
│   │   ├── leticia_persona.py      # system prompt
│   │   ├── guardrails.py           # opt-out / escalação / identidade
│   │   ├── message_dispatcher.py   # split balões + delay
│   │   ├── slack_notify.py         # poster pro #leticia-teste
│   │   └── orchestrator.py         # core: handle_inbound + cmd_*
│   └── management/commands/
│       └── run_slack_bot.py        # Slack Socket Mode worker
├── supabase/
│   └── schema.sql          # rode no SQL editor do Supabase
├── requirements.txt
├── Procfile
├── railway.json
├── runtime.txt
└── .env.example
```

---

## Próximos passos (v2)

- Outbound (cold outreach): comando `/prospect <lista>` que dispara abordagem inicial
  numa lista de leads carregada via CSV ou query no Supabase.
- Janela horária: só falar entre 9h e 19h dia útil. Fora disso, fila pra manhã seguinte.
- Templates aprovados pra primeira abordagem (compliance WhatsApp Business).
- Integração Robin Hood (enriquecimento de dado do lojista antes de gerar mensagem).
- Dashboards no Supabase (Studio ou Metabase) com taxa de resposta, taxa de
  escalação pro Nathan, taxa de fechamento.

---

## Operação no dia-a-dia

- **Pausar tudo**: `/stop` no Slack.
- **Pausar um lead**: `/stop 5511999998888`.
- **Mensagem fora do script**: `/send 5511999998888 "Olá fulano, ..."` (já registra na
  conversa, fica no transcript).
- **Investigar um lead**: `/history 5511999998888`.
- **Adicionar ao opt-out manualmente** (ex: ele pediu por outro canal):
  `/optout 5511999998888 pediu por email`.

Logs do Railway mostram cada inbound, cada chamada do Claude, e cada envio. Em caso
de bug, comece por lá.
