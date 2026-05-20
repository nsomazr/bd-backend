# bd-backend: Maisha Chat API

Django + DRF backend for **Maisha Chat**, a ChatGPT-like blood-donation assistant.

- Listens on port **8090** locally.
- Public URL: **https://api.maishachat.or.tz**.
- Auth: JWT (access + refresh) via `djangorestframework-simplejwt`.
- DB: SQLite (file at `bd-backend/db.sqlite3` by default; override with `DB_PATH`).
- LLM inference: HuggingFace Transformers in-process, **one active model at a time** (lazy swap).

## Models served

| Key            | Label          | HuggingFace ID                                          |
| -------------- | -------------- | ------------------------------------------------------- |
| `gemma4-e4b`   | Gemma 4 E4B    | `HMkumbo/blood-donation-gemma4-e4b-merged-16bit`        |
| `qwen3.5-4b`   | Qwen 3.5 4B    | `HMkumbo/blood-donation-qwen3.5-4b-merged-16bit`        |
| `llama3.2-3b`  | Llama 3.2 3B   | `HMkumbo/blood-donation-llama32-3b-merged-16bit`        |

The registry lives in `llm/registry.py`.

## Setup

> Note: the project-local virtualenv lives at `bd-backend/.env/`. Because that
> directory name collides with the conventional `.env` dotenv file, **runtime
> environment variables go in `.env.local`** (or `env.local`) instead.

1. Create / activate the project-local venv (`.env`) and install deps:
   ```bash
   python3 -m venv .env
   source .env/bin/activate
   pip install -r requirements.txt
   ```

2. (Optional) copy the env template if you need to tweak anything:
   ```bash
   cp env.example .env.local
   ```
   With defaults, no env file is required. SQLite will be created at
   `bd-backend/db.sqlite3` on the first migration.

## Local development

```bash
./start.sh
```

The script activates `llm_env`, exports `.env`, runs migrations, and starts
Django at `0.0.0.0:8090`.

## Production deploy (PM2 + gunicorn)

```bash
./deploy.sh
```

This installs deps, runs `migrate` and `collectstatic`, then
`pm2 startOrReload ecosystem.config.js`. The ecosystem file binds gunicorn to
`127.0.0.1:8090` with **1 worker / 4 threads / 600s timeout** (single worker
is required so we don't load the same multi-GB model in parallel).

Front-facing nginx should:
- forward `https://api.maishachat.or.tz` -> `127.0.0.1:8090`
- set `proxy_buffering off;` and `proxy_read_timeout 600s;` for SSE streaming.

## API surface

| Method | Path                                          | Description                                |
| ------ | --------------------------------------------- | ------------------------------------------ |
| GET    | `/api/health/`                                | Liveness probe                             |
| GET    | `/api/models/`                                | List available LLMs                        |
| POST   | `/api/auth/register/`                         | Create an account, returns access+refresh  |
| POST   | `/api/auth/login/`                            | Email + password login                     |
| POST   | `/api/auth/refresh/`                          | Refresh an access token                    |
| GET    | `/api/auth/me/`                               | Current user                               |
| GET    | `/api/conversations/`                         | List the user's conversations              |
| POST   | `/api/conversations/`                         | Create a conversation                      |
| GET    | `/api/conversations/<id>/`                    | Conversation + all messages                |
| PATCH  | `/api/conversations/<id>/`                    | Rename / change model_key                  |
| DELETE | `/api/conversations/<id>/`                    | Delete a conversation                      |
| GET    | `/api/conversations/<id>/messages/`           | Just the messages                          |
| POST   | `/api/conversations/<id>/complete/`           | Send a user message, returns SSE stream    |

### SSE stream events

```
event: start          { conversation_id, user_message_id, model_key }
event: model_ready    { model_key }
event: token          { delta: "..." }
event: done           { assistant_message_id, content }
event: error          { error: "..." }
```
