# OrderOps AI — Grocery Dashboard + Autonomous Resolution

**New:** Screenshot-based grocery dashboard is included. Start FastAPI and open the root `/` page. See [dashboard setup](docs/DASHBOARD_SETUP.md) for upgrading your existing Neon project and demo/live modes.

Roman Urdu mein complete build guide: [docs/STEP_BY_STEP_GUIDE.md](docs/STEP_BY_STEP_GUIDE.md).

Ye runnable learning MVP aap ke BRD ka post-checkout workflow implement karta hai:
FastAPI + LangGraph + PostgreSQL + SQLAlchemy + Alembic. Separate worker orders ko
process karta hai; customer/auditor ke jawab par graph resume hota hai.

**Scope:** ek missing line ke liye ek discounted alternative; multi-line order mein
har missing line par workflow repeat hota hai. Reject, expiry, ya no alternative par
poora order cancel hota hai. Email/SMS, refunds aur warehouse calls local outbox
records hain. Real integrations connected nahi hain. Fraud score trusted demo
input hai. Default selection deterministic hai; optional Ollama adapter available hai.

## Quick start

Python 3.12 aur Docker Compose chahiye. ZIP extract karke `orderops-ai` folder kholen.

Windows Command Prompt:

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

Swagger: <http://127.0.0.1:8000/docs>. Click **Authorize** and enter `.env` ka
`ADMIN_API_KEY`. Linux/macOS setup aur manual testing guide mein hai.

## File map

| File | Zimmedari |
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
