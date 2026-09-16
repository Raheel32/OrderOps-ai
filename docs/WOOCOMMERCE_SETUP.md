# WooCommerce Order-Intake Webhook — Setup Guide

## What this does

When a real order is placed on your WooCommerce store, WordPress sends the
order data to OrderOps AI automatically (`POST /webhooks/woocommerce/order-created`).
OrderOps then maps the order's line items to your product catalog by SKU,
computes a real fraud risk score from the order + customer history, and
starts the usual fraud → inventory → offer/resolution pipeline — exactly as
if you'd called `POST /orders` yourself.

## Prerequisite: your API needs a public URL

WordPress runs on your live store's server; it cannot reach
`localhost:8000` on your own machine. You need one of:

- **Easiest for testing:** a tunnel tool like [ngrok](https://ngrok.com/) —
  run `ngrok http 8000` on your machine while `uvicorn` is running, and it
  gives you a temporary public URL (e.g. `https://abcd1234.ngrok-free.app`)
  that forwards to your local server.
- **For anything beyond testing:** deploy the FastAPI app somewhere with a
  real public URL (a VPS, Render, Railway, etc.) — that's a separate,
  bigger step outside this guide.

## Step 1 — Set a webhook secret

In your `.env` file, set a real secret (not the placeholder default):
```
WOOCOMMERCE_WEBHOOK_SECRET=<a long random string, e.g. from `openssl rand -hex 32`>
```
Restart `uvicorn` after changing `.env`.

## Step 2 — Map your products by SKU

Every WooCommerce product has a SKU (WP Admin > Products > edit a product >
Inventory tab > SKU field — set one if it's blank). For each demo product in
OrderOps you want to accept real orders for, run:
```
python -m scripts.set_sku <product_id> <the-real-sku>
```
Example: `python -m scripts.set_sku 3 DALDA-OIL-1L`

Any order line item whose SKU isn't mapped will be **rejected with a 422** —
on purpose, so an unmapped product doesn't silently get lost instead of
resolved. WooCommerce's webhook logs (see Step 4) will show you the
rejection reason if this happens.

## Step 3 — Create the webhook in WordPress

1. WP Admin > **WooCommerce > Settings > Advanced > Webhooks**
2. **Add webhook**
3. Fill in:
   - **Name:** OrderOps AI — order intake
   - **Status:** Active
   - **Topic:** Order created
   - **Delivery URL:** `https://<your-public-url>/webhooks/woocommerce/order-created`
   - **Secret:** the exact same value as `WOOCOMMERCE_WEBHOOK_SECRET` in your `.env`
   - **API version:** WP REST API Integration v3 (default)
4. **Save webhook**

## Step 4 — Test it

Place a real (or test) order on your store, then check:
- **WooCommerce side:** WooCommerce > Settings > Advanced > Webhooks > click
  your webhook > scroll to **Logs** — shows the delivery, the response code,
  and OrderOps' response body (useful for seeing a 422 rejection reason).
- **OrderOps side:** `GET /orders/pending`, or query the order directly once
  you have its `order_id` from the webhook log's response body.

## Notes / things to double check for your store

- **Payment method mapping** (`app/integrations/woocommerce.py`) currently
  treats WooCommerce's `"cod"` gateway id as Cash on Delivery and *everything
  else* (Stripe, PayPal, bank transfer, etc.) as already-paid ("prepaid").
  If your store has another gateway that should behave like COD, edit that
  mapping.
- **Fraud thresholds** (`FRAUD_*` in `.env`) are starting points, not a
  calibrated model — the "3x average order value", "PKR 15,000 first-order
  threshold", and "3 orders per hour" numbers are reasonable guesses, not
  numbers derived from your actual customers. Watch `/orders/pending?kind=audit`
  for a week or two and adjust if it's flagging too much or too little.
- **Duplicate deliveries:** WooCommerce retries a webhook delivery if your
  server doesn't respond in time or returns an error. This is handled — the
  webhook hashes the WooCommerce order ID into `external_id`, so a retried
  delivery of the same order returns the existing order (`"duplicate":
  true`) instead of creating a second one.
