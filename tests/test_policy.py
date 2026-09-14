from types import SimpleNamespace as P
import httpx
from app import agent
from app.config import settings
from app.policy import choose_alternative, offer_price


def test_substitution_rejects_wrong_group_expensive_and_empty():
    original = P(id=1, substitution_group="tea-450g")
    candidates = [P(id=2, substitution_group="oil-1L", price_paisa=10, stock=10, brand="X"),
                  P(id=3, substitution_group="tea-450g", price_paisa=200000, stock=10, brand="X"),
                  P(id=4, substitution_group="tea-450g", price_paisa=90000, stock=0, brand="X")]
    assert choose_alternative(candidates, original, 1, 100000, [], 500) is None


def test_money_rounding_never_exceeds_discount():
    assert offer_price(999, 500) == 950
    assert offer_price(98000, 500) == 93100


def test_llm_invalid_candidate_falls_back(monkeypatch):
    monkeypatch.setattr(settings, "agent_mode", "ollama")
    monkeypatch.setattr(settings, "ollama_model", "test-model")
    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(200,
        request=httpx.Request("POST", "http://localhost"),
        json={"message": {"content": '{"product_id":999}'}}))
    original = P(id=1, name="Tea", substitution_group="tea")
    candidate = P(id=2, name="Other Tea", brand="X", substitution_group="tea", price_paisa=100, stock=10)
    assert agent.recommend([candidate], original, 1, 100, []) is None
