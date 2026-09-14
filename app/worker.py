"""Durable polling worker. Run separately: python -m app.worker."""
import logging
import time
from datetime import timedelta
from sqlalchemy import select
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.types import Command
from app.config import settings
from app.db import SessionLocal
from app.graph import build_graph
from app.models import Job, Offer, Order, utcnow
from app.services import aware, audit

log = logging.getLogger(__name__)


def drive(graph, order_id):
    config = {"configurable": {"thread_id": order_id}, "recursion_limit": 350}
    snapshot = graph.get_state(config)
    if not snapshot.values:
        graph.invoke({"order_id": order_id}, config)
        return
    if not snapshot.next:
        return  # Completed graph; a duplicate job has no effects.
    interrupts = [i for task in snapshot.tasks for i in task.interrupts]
    if interrupts:
        request = interrupts[0].value
        with SessionLocal() as db:
            decision = (db.get(Order, order_id).manual_decision if request["kind"] == "audit"
                        else db.get(Offer, request["offer_id"]).decision)
        if decision is None:
            return
        graph.invoke(Command(resume=decision), config)
    else:
        graph.invoke(None, config)  # Recover unfinished nodes after a process failure.


def process_one(graph):
    # A separate jobs row stays locked while graph nodes use their own transactions.
    # Never lock the order here: nodes need to acquire its lock themselves.
    with SessionLocal.begin() as db:
        job = db.scalar(select(Job).where(Job.pending.is_(True), Job.available_at <= utcnow())
                        .order_by(Job.available_at, Job.order_id)
                        .with_for_update(skip_locked=True).limit(1))
        if job is None:
            return False
        try:
            drive(graph, job.order_id)
            job.pending = False
            job.attempts = 0
            job.last_error = None
        except Exception as exc:
            job.attempts += 1
            job.last_error = type(exc).__name__  # No customer details/secrets in logs.
            job.pending = job.attempts < 5
            job.available_at = utcnow() + timedelta(seconds=min(2 ** job.attempts, 60))
            log.warning("Order %s failed with %s, attempt %s", job.order_id,
                        type(exc).__name__, job.attempts)
        return True


def expire_offers():
    with SessionLocal() as db:
        ids = list(db.scalars(select(Offer.id).where(Offer.status == "pending",
                              Offer.decision.is_(None), Offer.expires_at <= utcnow())))
    for offer_id in ids:
        with SessionLocal() as db:
            order_id = db.get(Offer, offer_id).order_id
        with SessionLocal.begin() as db:
            job = db.scalar(select(Job).where(Job.order_id == order_id)
                            .with_for_update(skip_locked=True))
            if job is None:
                continue
            offer = db.get(Offer, offer_id, with_for_update=True)
            if offer.decision is None and offer.status == "pending" and aware(offer.expires_at) <= utcnow():
                offer.decision = "expired"
                job.pending, job.attempts, job.available_at = True, 0, utcnow()
                audit(db, order_id, "offer_expired", offer_id=offer_id)


def main():
    logging.basicConfig(level=logging.INFO)
    with PostgresSaver.from_conn_string(settings.checkpoint_db_url) as saver:
        graph = build_graph(saver)
        while True:
            try:
                expire_offers()
                if not process_one(graph):
                    time.sleep(settings.worker_poll_seconds)
            except Exception as exc:
                log.error("Worker database/checkpoint error: %s", type(exc).__name__)
                time.sleep(settings.worker_poll_seconds)


if __name__ == "__main__":
    main()
