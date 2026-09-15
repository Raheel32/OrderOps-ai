# OrderOps AI — Grocery Dashboard and Autonomous Resolution

**New:** Screenshot-based grocery dashboard is included. Start FastAPI and open the root `/` page. See [dashboard setup](docs/DASHBOARD_SETUP.md) for upgrading your existing Neon project and demo/live modes.

Complete build guide: [docs/STEP_BY_STEP_GUIDE.md](docs/STEP_BY_STEP_GUIDE.md).

This runnable learning MVP implements the post-checkout workflow:
FastAPI + LangGraph + PostgreSQL + SQLAlchemy + Alembic. Separate worker orders ko
processes orders; the graph resumes when a customer or auditor responds.

**Scope:** one discounted alternative is selected for each missing line; the workflow
repeats for every missing line in a multi-line order. Rejection, expiry, or no
alternative cancels the full order. Email, SMS, refunds, and warehouse calls are
stored as local outbox records. Real integrations are not connected. Fraud score is
trusted demo input. Selection is deterministic by default; an optional Ollama
adapter is available.

## Quick start

Use Python 3.12 or newer. Docker Compose is optional when using Neon.

Windows PowerShell with Docker Compose:

```bat
py -3.12 -m venv .venv
.venv\Scripts\activate.bat
copy .env.example .env
python -m pip install -r requirements.lock.txt
docker compose up -d --wait db
python -m alembic upgrade head
python -m scripts.init_checkpoints
python -m scripts.seed
python -m uvicorn app.main:app --reload
```

Second terminal, same folder and activated environment:

```bat
python -m app.worker
```

Third terminal:

```bat
python -m scripts.demo
python -m pytest -q
```

Swagger: <http://127.0.0.1:8000/docs>. Click **Authorize** and enter the
`ADMIN_API_KEY` value from `.env`.

## File map

| File | Purpose |
|---|---|
| `app/main.py` | API, authentication, callbacks, metrics |
| `app/config.py`, `app/db.py` | Settings, engine and sessions |
| `app/models.py`, `app/schemas.py` | Tables and input validation |
| `app/policy.py` | Compatibility, discounts, template message |
| `app/agent.py` | Optional local LLM candidate ranking with validation |
| `app/services.py` | Stock holds, offers, order updates, outbox, audit |
| `app/graph.py` | LangGraph nodes, branches, interrupts, loop |
| `app/worker.py` | Durable jobs, recovery, expiry and bounded retries |
| `migrations/` | Explicit versioned application schema |
| `scripts/` | Checkpoint setup, fictional seed data, HTTP demo |
| `tests/` | Workflow, API and policy tests |
| `docs/EXAMPLES.http` | Copyable API requests |
| `docs/STEP_BY_STEP_GUIDE.md` | Ordered build/setup and extension guide |
| `docs/VALIDATION.md` | What was actually tested and what remains unverified |

Read the guide's production integration steps before connecting a real store.
