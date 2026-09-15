from typing import TypedDict
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt
from app import services


class OrderState(TypedDict, total=False):
    order_id: str
    high_risk: bool
    audit_decision: str
    missing_line: int | None
    offer_id: str | None
    customer_decision: str


def build_graph(checkpointer):
    def fraud(s):
        return {"high_risk": services.risk_route(s["order_id"])}

    def manual(s):
        services.flag_audit(s["order_id"])  # Idempotent if node is replayed.
        decision = interrupt({"kind": "audit", "order_id": s["order_id"]})
        if decision not in {"approve", "reject"}:
            raise ValueError("Invalid audit decision")
        return {"audit_decision": decision}

    def check_stock(s):
        return services.inventory(s["order_id"])

    def offer(s):
        return services.create_offer(s["order_id"], s["missing_line"])

    def wait_customer(s):
        # No message sending here: code before interrupt runs again on resume.
        decision = interrupt({"kind": "customer", "offer_id": s["offer_id"]})
        if decision not in {"accept", "reject", "expired"}:
            raise ValueError("Invalid customer decision")
        return {"customer_decision": decision}

    def apply(s):
        services.apply_offer(s["order_id"], s["offer_id"])
        return {}

    def drop_line(s):
        # Rejected offer or no compatible alternative: exclude just this line
        # (partial fulfillment) instead of cancelling the whole order.
        services.drop_line(s["order_id"], s["missing_line"])
        return {}

    def fulfill(s):
        services.fulfill(s["order_id"])
        return {}

    def cancel(s):
        services.cancel(s["order_id"])
        return {}

    g = StateGraph(OrderState)
    for name, fn in [("fraud", fraud), ("manual", manual), ("inventory", check_stock),
                     ("offer", offer), ("wait_customer", wait_customer), ("apply", apply),
                     ("drop_line", drop_line), ("fulfill", fulfill), ("cancel", cancel)]:
        g.add_node(name, fn)
    g.add_edge(START, "fraud")
    g.add_conditional_edges("fraud", lambda s: "manual" if s["high_risk"] else "inventory")
    # Manual-review rejection cancels the whole order: nothing has been
    # reserved yet, so there is no "partial" to preserve.
    g.add_conditional_edges("manual", lambda s: "inventory" if s["audit_decision"] == "approve" else "cancel")
    g.add_conditional_edges("inventory", lambda s: "offer" if s["missing_line"] is not None
                            else ("cancel" if s.get("all_dropped") else "fulfill"))
    g.add_conditional_edges("offer", lambda s: "wait_customer" if s["offer_id"] else "drop_line")
    g.add_conditional_edges("wait_customer", lambda s: "apply" if s["customer_decision"] == "accept" else "drop_line")
    g.add_edge("apply", "inventory")  # Next missing line; bounded by <= 50 order lines.
    g.add_edge("drop_line", "inventory")  # Next missing line, or all_dropped -> cancel.
    g.add_edge("fulfill", END)
    g.add_edge("cancel", END)
    return g.compile(checkpointer=checkpointer)
