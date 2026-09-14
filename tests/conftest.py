import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app import main, services, worker
from app.config import settings
from app.graph import build_graph
from app.models import Base, Product
from scripts.seed import PRODUCTS


@pytest.fixture
def env(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    @event.listens_for(engine, "connect")
    def enable_fks(conn, _):
        conn.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    for module in (main, services, worker):
        monkeypatch.setattr(module, "SessionLocal", factory)
    monkeypatch.setattr(settings, "agent_mode", "rules")
    with factory.begin() as db:
        for p in PRODUCTS:
            db.add(Product(**p))
    client = TestClient(main.app)
    client.headers["X-API-Key"] = settings.admin_api_key
    graph = build_graph(InMemorySaver())
    yield client, factory, graph
    engine.dispose()
