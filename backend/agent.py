"""
agent.py
--------
Simple rule-based agent for the kiosk. It preserves the original flow
(intake -> urgency -> inventory -> router -> substitutes -> cross-sell ->
deals -> directions -> compose) without requiring the optional LangGraph
or LLM packages.
"""

from __future__ import annotations

import os
from typing import Optional, TypedDict

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - optional dependency
    def load_dotenv() -> bool:
        return False

import inventory_store as store

load_dotenv()

GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
_HAS_GROQ_KEY = bool(os.environ.get("GROQ_API_KEY"))

_llm = None
if _HAS_GROQ_KEY:
    try:
        from langchain_groq import ChatGroq

        _llm = ChatGroq(model=GROQ_MODEL, temperature=0.4)
    except Exception:
        _llm = None


class SupermarketState(TypedDict, total=False):
    customer_name: str
    query: str
    language: str
    category: str
    reasoning: str
    found: bool
    product_details: dict
    stock_alert: str
    substitutes: list
    cross_sell: list
    deal: Optional[dict]
    urgent: bool
    directions: str
    response_text: str
    speech_text: str


def _fmt_product(row) -> dict:
    return {
        "name": row["Product Name"],
        "category": row["Category"],
        "location": row["Aisle"],
        "aisle_number": int(row["Aisle Number"]),
        "position": row["Shelf Position"],
        "status": row["Stock Status"],
        "quantity": int(row["Quantity Available"]),
        "price": float(row["Price"]),
        "deal_discount": int(row["Deal Discount"]),
    }


def intake_node(state: SupermarketState) -> SupermarketState:
    return {
        **state,
        "language": state.get("language") or "en",
        "found": False,
        "product_details": {},
        "substitutes": [],
        "cross_sell": [],
        "deal": None,
    }


def urgency_node(state: SupermarketState) -> SupermarketState:
    return {**state, "urgent": store.is_urgent(state["query"])}


def inventory_node(state: SupermarketState) -> SupermarketState:
    inventory = state["_inventory"]
    match = store.search_product(state["query"], inventory)

    if match is None:
        return {**state, "found": False, "product_details": {}, "stock_alert": "not_found"}

    details = _fmt_product(match)
    status = match["Stock Status"]
    if status == "Out of Stock":
        alert = "out_of_stock"
    elif status == "Low Stock":
        alert = "low_stock"
    else:
        alert = "in_stock"

    return {
        **state,
        "found": True,
        "category": details["category"],
        "product_details": details,
        "stock_alert": alert,
        "reasoning": "Matched directly against the live inventory catalog.",
    }


def router_node(state: SupermarketState) -> SupermarketState:
    if state.get("found"):
        return state

    query = state["query"]
    keyword_hit = store.classify_by_keywords(query)
    if keyword_hit:
        return {**state, "category": keyword_hit, "reasoning": "Matched by keyword guardrail."}

    if _llm is not None:
        from langchain_core.messages import HumanMessage, SystemMessage

        categories = ", ".join(store.CATEGORY_KEYWORDS.keys())
        prompt = (
            "You are a supermarket floor assistant. Categorize the customer's request "
            f"into exactly one of these categories: {categories}. "
            "Respond with ONLY the category name, nothing else."
        )
        try:
            resp = _llm.invoke([SystemMessage(content=prompt), HumanMessage(content=f"Item: {query}")])
            category = resp.content.strip()
            if category not in store.CATEGORY_KEYWORDS:
                category = "Household"
            return {**state, "category": category, "reasoning": "AI classified based on product type."}
        except Exception:
            pass

    return {**state, "category": "Household", "reasoning": "Default fallback category."}


def substitute_node(state: SupermarketState) -> SupermarketState:
    needs_subs = (not state.get("found")) or state.get("stock_alert") in ("out_of_stock", "low_stock")
    if not needs_subs:
        return {**state, "substitutes": []}
    inventory = state["_inventory"]
    product_row = None
    if state.get("found"):
        product_row = next((row for row in inventory if row["Product Name"] == state["product_details"]["name"]), None)
    subs = store.find_substitutes(product_row, inventory, state.get("category", ""), n=3)
    return {**state, "substitutes": subs}


def cross_sell_node(state: SupermarketState) -> SupermarketState:
    if not state.get("found"):
        return {**state, "cross_sell": []}
    inventory = state["_inventory"]
    picks = store.get_cross_sell(state["category"], inventory)
    return {**state, "cross_sell": picks}


def deal_node(state: SupermarketState) -> SupermarketState:
    if state.get("found") and state["product_details"].get("deal_discount", 0) > 0:
        product = state["product_details"]
        return {**state, "deal": {"name": product["name"], "discount": product["deal_discount"]}}

    inventory = state["_inventory"]
    category_deals = [row for row in inventory if row["Category"] == state.get("category", "") and row["Deal Discount"] > 0]
    if category_deals:
        row = category_deals[0]
        return {**state, "deal": {"name": row["Product Name"], "discount": int(row["Deal Discount"])} }
    return {**state, "deal": None}


def directions_node(state: SupermarketState) -> SupermarketState:
    aisle_number = state["product_details"].get("aisle_number") if state.get("found") else None
    return {**state, "directions": store.compute_directions(aisle_number, state.get("urgent", False))}


def _template_response(state: SupermarketState) -> str:
    name = state.get("customer_name") or "there"
    if state.get("found"):
        product = state["product_details"]
        status_line = {
            "in_stock": f"Good news, {name} — {product['name']} is in stock and ready for pickup.",
            "low_stock": f"Heads up, {name} — only {product['quantity']} left of {product['name']}, grab it soon.",
            "out_of_stock": f"Sorry {name}, {product['name']} is currently out of stock.",
        }[state["stock_alert"]]
        return f"{status_line} You'll find it in {product['location']}, {product['position']}. {state['directions']}"
    return (
        f"I couldn't find an exact match for '{state['query']}' in our directory, {name}, "
        f"but the {state.get('category', 'Household')} section is your best bet. {state['directions']}"
    )


def compose_node(state: SupermarketState) -> SupermarketState:
    if _llm is not None:
        from langchain_core.messages import HumanMessage, SystemMessage

        lang = state.get("language", "en")
        lang_instruction = "" if lang == "en" else f" Respond in {lang}."
        sys_prompt = (
            "You are an upbeat, concise supermarket kiosk assistant. In 2-3 short sentences, "
            "tell the customer whether we have their item, where to find it, and mention any "
            "substitute or deal ONLY if relevant. Be warm but efficient — this is a screen, "
            "not a chat app." + lang_instruction
        )
        context = {
            "customer_name": state.get("customer_name"),
            "query": state["query"],
            "found": state.get("found"),
            "product": state.get("product_details"),
            "stock_alert": state.get("stock_alert"),
            "substitutes": state.get("substitutes"),
            "cross_sell": state.get("cross_sell"),
            "deal": state.get("deal"),
            "directions": state.get("directions"),
            "urgent": state.get("urgent"),
        }
        try:
            resp = _llm.invoke([SystemMessage(content=sys_prompt), HumanMessage(content=str(context))])
            text = resp.content.strip()
            return {**state, "response_text": text, "speech_text": text}
        except Exception:
            pass

    text = _template_response(state)
    return {**state, "response_text": text, "speech_text": text}


def run_query(inventory, customer_name: str, query: str, language: str = "en") -> dict:
    state = {
        "_inventory": inventory,
        "customer_name": customer_name,
        "query": query,
        "language": language,
    }
    state = intake_node(state)
    state = urgency_node(state)
    state = inventory_node(state)
    state = router_node(state)
    state = substitute_node(state)
    state = cross_sell_node(state)
    state = deal_node(state)
    state = directions_node(state)
    state = compose_node(state)
    state.pop("_inventory", None)
    return state
