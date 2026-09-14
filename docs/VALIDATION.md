# Validation record

Environment: Python 3.12. Dependency versions are recorded in `requirements.lock.txt`.

## Executed

- `python -m pytest -q`: **20 passed**.
- Initial Alembic migration applied successfully to a disposable SQLite database.
- Tests cover in-stock fulfillment intent, customer acceptance, price difference
  refund intent, rejection/full refund intent, release of all holds, audit approval
  and rejection, no alternative, multiple missing-line loops, duplicate intake,
  callback token verification, repeated/conflicting decisions, expiry, timely
  acceptance processed after expiry, sequential shared-stock allocation, invalid
  input and authentication, money/compatibility rules, invalid LLM candidate fallback.
- Simulated crash after offer transaction commit and before graph checkpoint:
  retry produces one offer/outbox record and a single stock deduction.

The test run emitted one third-party Starlette/AnyIO deprecation warning; no test failed.

## Grocery dashboard checks

- Final production frontend build succeeded; compiled assets copied to `app/static`.
- FastAPI served the compiled HTML, JavaScript, CSS, ambient image and Swagger with
  HTTP 200, without connecting to a database.
- Added snapshot tests cover authentication, product/offer name joins, token
  redaction and empty state.
- Browser demo checks passed: order creation, replacement acceptance/rejection,
  manual approval, in-stock groceries and unavailable COD cancellation.
- Desktop screenshot comparison and 390px mobile layout inspection passed.
  See `../design-qa.md` and `qa/` evidence.

## Not executed here

- Real PostgreSQL `FOR UPDATE`/`SKIP LOCKED` concurrency semantics and multi-worker races.
- PostgreSQL-backed checkpoint setup, crash/restart durability, or Neon deployment.
- Live Ollama inference.
- Any real email/SMS, payment gateway, store webhook, warehouse integration or delivery.
- External API smoke demo against a running PostgreSQL-backed API and worker.

Unit tests use SQLite and LangGraph `InMemorySaver`; they establish business-flow
behavior but do not establish PostgreSQL concurrency or persistence correctness.
Use the guide's PostgreSQL restart/concurrency checks before deployment. The starter
is a learning MVP, with real provider adapters and operational hardening described
as the next implementation phase.
