# Grocery dashboard — screenshot-based update

The dashboard keeps your OrderOps reference layout with a Pakistani heritage background: headline, four metrics,
live pipeline, order form, orders table and activity stream. Products are Pakistani
groceries and all amounts are PKR. It includes a browser demo plus integration with
the existing FastAPI backend. No public deployment has been performed.

## Upgrade your existing project

1. Extract this ZIP into a **new folder** first. It contains the complete updated
   `orderops-ai` project, including the compiled dashboard.
2. Copy your existing `.env` into the new project folder. Keep your existing Neon
   URLs and `ADMIN_API_KEY`; do not replace them with the example values.
3. Use your Python environment and install `requirements.lock.txt` if needed.
4. From the new `orderops-ai` folder, start:

```powershell
python -m uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000/` in your browser. The dashboard starts in **Demo mode**.
The demo does not require a running database, Docker, Node.js or a model server.
Python packages must still be installed. Existing Swagger remains at `/docs`.

## Connect to your Neon/PostgreSQL database

Keep both `.env` database URLs pointed at the same database:

```dotenv
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST/DATABASE?sslmode=require
CHECKPOINT_DB_URL=postgresql://USER:PASSWORD@HOST/DATABASE?sslmode=require
```

These are placeholders. Use your copied direct Neon connection URL and preserve
its SSL/query parameters. Only change the SQLAlchemy driver's URL prefix.

Initialize an empty database, or apply pending migrations and insert missing seed products:

```powershell
python -m alembic upgrade head
python -m scripts.init_checkpoints
python -m scripts.seed
```

`seed` inserts missing products; it does not reset existing prices or stock. Product
IDs 6–10 add Shan, National, Shangrila, Young's and flour. If your own catalog already
uses those IDs, preserve it and map/import your grocery products deliberately.

Keep the API running. In a second terminal in this project, start the worker:

```powershell
python -m app.worker
```

On the dashboard, click **DEMO MODE**, enter your `.env` admin API key, and click
**Connect to API**. The key is held in page memory only, not local/session storage;
reload requires reconnecting. Requests go to the same FastAPI origin. A standalone
Vite preview only supports demo mode unless you configure a same-origin development
proxy to FastAPI yourself. No remote API URL or credentials are bundled.

The live view polls every 3 seconds and lists the 100 most recent orders. Cards use
all-order counts. `API CONNECTED` means the snapshot request succeeded; it is not
proof that the worker, model or external providers are healthy.

## Try the main workflows

- **Tapal Tea, low risk:** offer Vital Tea at Rs. 931; click Review, inspect the
  old/new item and total, then Simulate accept or Simulate reject.
- **Dalda Oil, low risk:** reserve stock and mark ready to fulfill.
- **Basmati Rice:** no eligible alternative; prepaid refund pending or COD cancelled.
- **High risk:** manual review; Audit opens Approve/Reject controls.
- **View icon:** inspect resolved order details.

The form creates one grocery line per test order. The backend still supports
multi-line intake; the dashboard displays those orders and sequential offers.
Demo data is fictional, resets on reload and never sends messages or payments.
Demo timing only illustrates pipeline stages; the line is not a throughput chart.

Live-mode acceptance controls **simulate the customer** using the starter's outbox
capability token. These are admin testing controls, not a production customer portal.
Real customer consent collection and outbound integrations are future work. The UI
uses `ready to fulfill` and `refund pending` because provider confirmation is absent.
An accepted cheaper prepaid replacement records a partial-refund intent.

Demo mode uses fixed sample stock, prices, risk threshold 0.8 and discount 5%; live
mode uses your actual database and server policy settings. Demo expiration is not
simulated; the real worker retains the existing offer-expiry logic.

## Files changed or added

| File | Purpose |
|---|---|
| `frontend/src/App.jsx` | React dashboard, demo/live modes, forms and dialogs |
| `frontend/src/styles.css` | Dark screenshot-matched responsive theme |
| `frontend/src/demo.js` | Isolated fictional grocery simulation |
| `frontend/public/assets/pakistani-heritage.png` | Emerald textile background with ajrak-inspired borders |
| `app/main.py` | Protected `/dashboard` snapshot and static UI serving |
| `app/static/` | Prebuilt dashboard; ready to run with FastAPI |
| `scripts/seed.py` | Expanded grocery sample catalog |
| `scripts/build_frontend.py` | Copy rebuilt assets into FastAPI |
| `tests/test_dashboard.py` | Snapshot authentication, redaction and empty state |

## Editing the frontend later

Node.js/npm is needed only to edit/rebuild the frontend:

```powershell
cd frontend
npm ci
npm run build
cd ..
python -m scripts.build_frontend
```

Restart FastAPI after the first asset copy. The checked-in source and prebuilt assets
are aligned in this ZIP. Do not expose your admin key in frontend code.

## Validation and limits

Python tests cover the existing workflow plus dashboard authentication, empty state,
product joins and token redaction. Browser tests cover demo order creation, replacement
acceptance/rejection, manual approval and mobile order processing. Details are in
`design-qa.md` and `docs/VALIDATION.md`.

Real PostgreSQL concurrency, Neon connection and provider integrations have not been
verified in this environment. The optional LLM is not enabled for the browser demo.
