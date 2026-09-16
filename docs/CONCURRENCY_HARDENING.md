# Concurrency & Crash-Recovery Hardening — Phase 2 Findings

Three risks were called out as untested in the original build. Here's what
was actually found for each, and what changed.

## 1. Worker crash mid-job (restart recovery)

**Verdict: already correct.** Every `app/services.py` function follows the
same pattern — one atomic transaction per node, with a guard at the top that
makes re-invocation a no-op if the work is already done (`if line.dropped:
return`, `if order.status == "ready_for_fulfillment": return`, etc.). This
means even if the process is killed between a node's DB commit and
LangGraph's own checkpoint commit (two separate transactions, not
coordinated), replaying that node on the next worker is safe.

This already had a real test — `tests/test_workflow.py::
test_worker_recovers_after_effect_commits_before_checkpoint` — which
simulates exactly that crash window (monkeypatches `create_offer` to raise
*after* its internal commit) and asserts no duplicate offer, no duplicate
outbox row, and the retry counter resets to 0 once it succeeds. It passes.

No code changes were needed here — this was a design-quality finding, not a
bug.

## 2. DB-unavailable / retry visibility

**Verdict: found a real gap, fixed it.** The retry/backoff bookkeeping
itself (`app/worker.py::process_one`) was already solid — attempts increment,
`last_error` is recorded, backoff is exponential, and it gives up after 5
tries. But once it gives up (`job.pending = False`), **nothing surfaced
that anywhere.** `order.status` doesn't change when a job fails — the order
just sits in whatever state it was in, invisible to `/dashboard` and the
`/orders/pending` worklist added in phase 1.

**Fix:** `/orders/pending?kind=failed` now queries the `jobs` table directly
(not `order.status`) for `pending=False, attempts>=5`, returning each order
plus its `job.attempts` / `job.last_error` / `job.available_at`. Covered by
`tests/test_new_features.py::test_orders_pending_failed_surfaces_exhausted_retries`,
which also confirms `POST /orders/{id}/retry` (already existed) correctly
clears it back off that list.

## 3. Concurrent last-unit stock race

**Verdict: can't be verified in this environment — needs your Neon DB.**
SQLite (what the pytest suite runs on) doesn't have real concurrent
row-locking the way Postgres does, so no amount of test-suite work here
proves `SELECT ... FOR UPDATE` actually prevents overselling under real
concurrent load. `scripts/pg_concurrency_check.py` is a standalone script
that races 8 real threads/connections for the last unit of a throwaway
probe product against your actual database, and reports pass/fail.

**Run it yourself:**
```
python -m scripts.pg_concurrency_check
```
It's safe against your dev DB — it creates and cleans up its own product row
(ID 999001) and never touches your demo catalog or real orders. If it
reports FAIL, that's a genuine finding worth investigating before this code
sees real traffic; if it reports PASS, the existing `lock_catalog()` pattern
is doing its job.
