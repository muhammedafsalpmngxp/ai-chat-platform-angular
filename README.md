# AI Chat Platform (Angular + FastAPI + LangGraph)

A ChatGPT-style AI assistant with an **Angular** frontend and a **Python FastAPI** backend.
Every reply is produced by a **LangGraph** agent graph: safety checks, a router, fast chat,
verified web search, and live progress shown in the UI while the graph runs.

> **Status:** `dev-1.0` - phases 1-4 complete (see [Roadmap](#roadmap)).

---

## Features

**Chat**
- ChatGPT-like layout: sidebar with **New chat**, searchable **history** (Today / Yesterday /
  Previous 7 days…), rename and delete
- **Streaming** replies with a **Stop** button (the partial answer is kept)
- Markdown rendering with code blocks and one-click **copy** icons
- Automatic chat titles
- **Live LangGraph progress** next to the loading indicator, e.g.
  `input_guard ✓ → router ✓ → web_search ✓ → evidence…` with details such as "Comparing 8 sources"

**Knows "now"**
- Every prompt carries the user's **current date, time and timezone** (from the browser)
- The model is told its own knowledge may be outdated for anything that changes over time

**Web search you can trust**
- [Tavily](https://tavily.com) search, routed automatically for news, records, rankings, prices…
- **Research → evidence check → synthesizer**: up to two queries in parallel, every candidate
  compared across all sources (same basis: worldwide vs domestic, gross vs net), conflicts noted
- Clean answers (no `[1]` markers) with a collapsible **Sources** list and a
  **High / Medium / Low confidence** label
- Live data it can't fetch yet (weather, live scores, live prices) gets an honest *"I don't know that yet"*

**Safety**
- OpenAI Moderation on questions and answers; explicit requests get a clear refusal
- Adult domains blocked and every search result moderated before the model sees it
- Social / user-generated sites (Instagram, YouTube, Reddit…) excluded as fact sources

**Models & cost** (Claude-style picker under the message box)
- 🟢 **GPT-6 Luna** recommended and default · standard models · 💎 **premium** models ·
  🟡 older "not recommended" models with a warning
- Premium models show a cost warning and require **re-entering the password**
  (30-minute unlock, enforced by the backend)
- **Context-window meter** (tokens used, no limit) with an **estimated cost** per chat
- **Settings → Pricing** page generated from one config file

**Files**
- 📎 Upload, drag-and-drop or paste **images** (PNG, JPG, WEBP, GIF) and **documents**
  (PDF, DOCX, TXT, MD, CSV, JSON, code)
- Images are sent to the model; document text is extracted
- Limits: **10 MB per file, 3 files per chat**; file types are checked by content

**Accounts & security**
- JWT login (single user configured in `.env`), bcrypt password hash
- Lockout after repeated wrong passwords
- All data stored locally and git-ignored

---

## Tech stack

| Layer | Technology |
|---|---|
| Frontend | Angular 22 (standalone components, signals, zoneless), SCSS, marked + DOMPurify, Vitest |
| Backend | Python 3.11+, FastAPI, Pydantic v2, uvicorn (plain `venv` + `pip`) |
| Agents | LangGraph 1.x, LangChain OpenAI |
| LLM | OpenAI (chat models, moderation) |
| Web search | Tavily |
| Storage | Hidden JSON files + LangGraph `InMemorySaver` checkpointer (behind interfaces - swappable for a database later) |

---

## Quick start

### Requirements
- **Python 3.11 or newer** ([python.org](https://www.python.org/downloads/)) - 3.10 is not enough
  (LangGraph's live progress needs 3.11+ for async code)
- Node.js 20+ and npm
- An OpenAI API key (and a Tavily API key for web search)

### 1. Backend

Create a virtual environment and install the pinned dependencies:

```bash
cd backend
python -m venv .venv
```

Activate it:

- Windows (PowerShell): `.venv\Scripts\Activate.ps1`
- Windows (cmd): `.venv\Scripts\activate.bat`
- macOS / Linux: `source .venv/bin/activate`

```bash
pip install -r requirements-dev.txt
cp .env.example .env
```

(Windows PowerShell: `Copy-Item .env.example .env`)

If `python` on your machine is older than 3.11, create the venv with a specific version,
e.g. `py -3.11 -m venv .venv` on Windows or `python3.11 -m venv .venv` on macOS/Linux.
`requirements.txt` holds the app's dependencies; `requirements-dev.txt` adds the test tools.

Create your login password hash and a JWT secret:

```bash
python scripts/hash_password.py --secret
```

Paste the printed `APP_PASSWORD_HASH=...` and `JWT_SECRET=...` lines into `backend/.env`, set
`APP_USERNAME` / `APP_DISPLAY_NAME`, and add your keys:

```env
OPENAI_API_KEY=sk-...
TAVILY_API_KEY=tvly-...
```

Start the API:

```bash
uvicorn app.main:app --reload --port 8000
```

API docs: http://localhost:8000/docs

### 2. Frontend

```bash
cd frontend
npm install
npm start
```

Open **http://localhost:4200** and log in. The dev server proxies `/api` to
`http://localhost:8000` (see `frontend/proxy.conf.json`).

---

## How it works

### Agent graph (LangGraph)

```
START -> input_guard --explicit--> refusal -> END
                    \--safe--> router --chitchat----> chitchat -------------------------------> output_guard -> END
                                      --web_search--> web_search -> evidence -> synthesizer -/
                                      --realtime----> realtime -> END
```

| Node | What it does |
|---|---|
| `input_guard` | OpenAI Moderation on the question (skipped for greetings like "hi") |
| `refusal` | Fixed "explicit content" reply, no LLM call |
| `router` | Quick rules first (greetings, date/time questions, files → chitchat; weather / live prices → realtime); otherwise GPT-6 Luna classifies and writes 1-2 search queries |
| `chitchat` | Streams the answer from the selected model, including uploaded files |
| `web_search` | Research: Tavily queries in parallel, duplicates merged, blocked/low-trust sites dropped, every result moderated |
| `evidence` | Compares every candidate across all sources, notes conflicts and scope, rates confidence |
| `synthesizer` | Writes the final answer from the checked notes - direct answer first, no citation markers |
| `realtime` | Fixed "I don't know that yet" for live data |
| `output_guard` | Moderates the finished answer and replaces it if explicit |

- Graph code: [`backend/app/graph/`](backend/app/graph) - state `ChatState`; per-run settings
  (model, user, chat, timezone) are passed as LangGraph **runtime context** (`ChatContext`).
- Each chat is a LangGraph **thread** in the checkpointer; the JSON chat file is the durable
  copy and re-seeds the thread after a restart.
- The UI receives LangGraph's `messages`, `updates`, `tasks` and `custom` stream modes as
  Server-Sent Events (`start`, `step`, `token`, `replace`, `done`, `title`, `error`).
- Prompts are plain, versioned files in [`backend/app/prompts/`](backend/app/prompts).
- [`backend/langgraph.json`](backend/langgraph.json) exposes the graph to LangGraph tooling
  (`langgraph dev` / LangGraph Studio; needs `langgraph-cli[inmem]`).

### Models and pricing

Models, tiers and prices live in [`backend/config/models.yaml`](backend/config/models.yaml); the
picker, the pricing page and the cost estimate all read from it.

| Tier | Models | In the app |
|---|---|---|
| 💎 Premium | gpt-6.2-astra | Cost warning, then password re-check (30-min unlock, memory only) |
| Standard | gpt-6.2-sol, gpt-6.1-terra | Normal |
| 🟢 Recommended | gpt-6-luna (default) | Green badge |
| 🟡 Low | gpt-5.6-luna, gpt-5.4-mini | Yellow; "not recommended" warning before use |

Costs are estimated per turn with that turn's model, including cached-input pricing and the
small utility-model calls (router, evidence check).

---

## Configuration

All backend settings live in `backend/.env` (template: [`backend/.env.example`](backend/.env.example)).
The frontend has no secrets.

| Setting | Purpose | Default |
|---|---|---|
| `APP_USERNAME`, `APP_DISPLAY_NAME`, `APP_PASSWORD_HASH` | The login user | - |
| `JWT_SECRET`, `ACCESS_TOKEN_EXPIRE_MINUTES` | Login tokens | -, 720 |
| `OPENAI_API_KEY`, `TAVILY_API_KEY` | Model and search providers | - |
| `UTILITY_MODEL` | Cheap model for routing, evidence checks and titles | gpt-6-luna |
| `PREMIUM_UNLOCK_MINUTES` | How long a password re-check unlocks premium models | 30 |
| `MAX_PASSWORD_ATTEMPTS`, `PASSWORD_LOCKOUT_MINUTES` | Wrong-password lockout | 5, 5 |
| `SEARCH_DEPTH`, `SEARCH_MAX_QUERIES`, `SEARCH_VERIFY` | Search quality vs cost (about 4 Tavily credits per web question by default) | advanced, 2, true |
| `MAX_UPLOAD_MB`, `MAX_FILES_PER_CHAT` | Upload limits | 10, 3 |
| `HISTORY_MAX_TOKENS` | Older messages beyond this are not sent to the model | 60000 |
| `STORAGE_BACKEND` | `json` (survives restarts) or `memory` | json |
| `CORS_ORIGINS` | Frontend URLs allowed to call the API | http://localhost:4200 |

---

## Tests

```bash
cd backend
python -m pytest
```

(with the backend virtual environment activated)

```bash
cd frontend
npm test -- --watch=false
```

Backend tests use a fake LLM, moderator and search provider, so they need no API keys.

---

## API

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/auth/login` | Log in, returns a JWT |
| `GET` | `/api/auth/me` | Current user |
| `POST` | `/api/auth/reauth` | Re-enter password; returns a short-lived premium unlock token |
| `GET` / `POST` | `/api/chats` | List chats / create a chat |
| `GET` / `PATCH` / `DELETE` | `/api/chats/{id}` | Get, rename or delete a chat |
| `POST` | `/api/chats/{id}/messages` | Send a message (optional `model`, `attachment_ids`, `timezone`); streams the reply as SSE |
| `GET` / `POST` | `/api/chats/{id}/attachments` | List / upload files |
| `GET` / `DELETE` | `/api/chats/{id}/attachments/{file_id}` | Download / remove a not-yet-sent file |
| `GET` | `/api/models` | Model catalog with tiers and prices |
| `GET` | `/api/config` | Upload limits and accepted file types |
| `GET` | `/api/health` | Health check |

---

## Project structure

```
backend/
  app/
    api/          REST + SSE routes (auth, chats, messages, attachments, models, config)
    core/         settings, security (bcrypt, JWT), model catalog, rate limiting
    graph/        LangGraph state, nodes, routing rules, builder, prompt loader
    prompts/      system, router, evidence, synthesizer and title prompts; fixed replies
    services/     OpenAI model + moderation, Tavily search, text extraction, chat runner
    storage/      storage interfaces, JSON / in-memory chats, uploaded files
  config/models.yaml
  scripts/hash_password.py
  tests/
  requirements.txt, requirements-dev.txt, pytest.ini
frontend/
  src/app/
    core/         auth, chat list, chat session (streaming), models, uploads, SSE client, markdown
    layout/       shell and sidebar
    pages/        login, chat (composer toolbar: attach, context meter, model picker), settings
    shared/       premium password dialog
```

---

## Data, privacy and security

- Chats, uploads and `.env` are **git-ignored**; data lives under `backend/data/` and is only
  served to the logged-in owner. Deleting a chat deletes its files.
- Passwords are stored only as bcrypt hashes; tokens are signed JWTs.
- Model output is sanitized before rendering; uploaded files are type-checked by content.
- Run the backend with a **single worker** while JSON storage is used.

---

## Roadmap

| Phase | Scope | Status |
|---|---|---|
| 1 | Project setup, login, sidebar (new chat, history, rename, delete), JSON storage | ✅ Done |
| 2 | LangGraph core: guards, router, chat, streaming, stop, markdown, context meter | ✅ Done |
| 3 | Model picker, pricing page, premium password re-check, cost estimate | ✅ Done |
| 4 | Web search (research → evidence → synthesizer), live-data handling, date/time awareness, file uploads, live graph progress | ✅ Done |
| 5 | Memory across the last 5 chats (summaries + embeddings, retrieved per turn) | Planned |
| 6 | Polish: light theme, multi-user accounts, database storage, more tests | Planned |
