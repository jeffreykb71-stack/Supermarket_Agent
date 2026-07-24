"""
inventory_store.py
-------------------
Pure-Python inventory helpers for the kiosk. This version avoids pandas and
LangGraph so the app can run locally with the standard library only.
"""

from __future__ import annotations

import csv
import difflib
import os
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

CSV_PATH = os.path.join(os.path.dirname(__file__), "data", "inventory.csv")

CROSS_SELL_MAP: dict[str, list[str]] = {
    "Bakery": ["Unsalted Butter", "Crunchy Peanut Butter", "Organic Whole Milk"],
    "Dairy": ["Whole Wheat Bread", "Ground Coffee 500g", "Chocolate Chip Cookies"],
    "Frozen": ["Diet Cola 12-Pack", "Potato Chips Party Size"],
    "Pharmacy": ["Adhesive Bandages", "Hand Sanitizer 250ml"],
    "Oils & Condiments": ["Whole Wheat Bread", "Boneless Chicken Breast"],
    "Produce": ["Greek Yogurt Tub", "Trail Mix Bag"],
    "Beverages": ["Potato Chips Party Size", "Trail Mix Bag"],
    "Household": ["Multi-Surface Cleaner", "Trash Bags (40ct)"],
    "Snacks": ["Diet Cola 12-Pack", "Sparkling Water 6-Pack"],
    "Meat & Seafood": ["Extra Virgin Olive Oil", "Roma Tomatoes"],
    "Personal Care": ["Adhesive Bandages"],
    "Cleaning": ["Dishwasher Pods (30ct)", "Paper Towels (6 Rolls)"],
}

CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "Pharmacy": ["pill", "medicine", "paracetamol", "ibuprofen", "cough", "bandage", "syrup"],
    "Cleaning": ["clean", "detergent", "laundry", "glass cleaner"],
    "Personal Care": ["soap", "shampoo", "toothpaste", "deodorant", "sanitizer"],
    "Produce": ["fruit", "veg", "banana", "apple", "spinach", "tomato", "avocado"],
    "Dairy": ["milk", "cheese", "yogurt", "butter", "egg"],
    "Bakery": ["bread", "bagel", "croissant", "loaf"],
    "Frozen": ["frozen", "ice cream", "pizza"],
    "Beverages": ["cola", "soda", "juice", "coffee", "tea", "water"],
    "Household": ["paper towel", "foil", "trash bag", "dishwasher"],
    "Snacks": ["chips", "cookie", "popcorn", "trail mix"],
    "Meat & Seafood": ["chicken", "beef", "salmon", "fish", "meat"],
    "Oils & Condiments": ["oil", "ketchup", "sauce", "peanut butter"],
}

URGENCY_KEYWORDS = ["quick", "hurry", "asap", "fast", "in a rush", "running late", "urgent"]


def load_inventory() -> list[dict]:
    with open(CSV_PATH, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        inventory = []
        for row in reader:
            row["Aisle Number"] = int(row["Aisle Number"])
            row["Quantity Available"] = int(row["Quantity Available"])
            row["Price"] = float(row["Price"])
            row["Deal Discount"] = int(row["Deal Discount"])
            inventory.append(row)
    return inventory


@dataclass
class TrendingTracker:
    """Simple in-memory counter of what customers search for today."""

    counts: Counter = field(default_factory=Counter)
    day: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))

    def record(self, query: str) -> None:
        today = datetime.now().strftime("%Y-%m-%d")
        if today != self.day:
            self.counts.clear()
            self.day = today
        cleaned = query.strip().lower()
        if cleaned:
            self.counts[cleaned] += 1

    def top(self, n: int = 5) -> list[dict]:
        return [{"query": q, "count": c} for q, c in self.counts.most_common(n)]


trending = TrendingTracker()


def search_product(query: str, inventory: list[dict]) -> Optional[dict]:
    """Fuzzy-match a free-text query against product names."""
    q = query.strip().lower()
    if not q:
        return None

    substring_hits = [row for row in inventory if q in row["Product Name"].lower()]
    if substring_hits:
        in_stock = [row for row in substring_hits if row["Stock Status"] != "Out of Stock"]
        return in_stock[0] if in_stock else substring_hits[0]

    names = [row["Product Name"] for row in inventory]
    close = difflib.get_close_matches(query, names, n=1, cutoff=0.5)
    if close:
        return next(row for row in inventory if row["Product Name"] == close[0])

    best_score, best_row = 0.0, None
    for row in inventory:
        score = difflib.SequenceMatcher(None, q, row["Product Name"].lower()).ratio()
        if score > best_score:
            best_score, best_row = score, row
    if best_score >= 0.45:
        return best_row
    return None


def find_substitutes(product_row: Optional[dict], inventory: list[dict], category: str, n: int = 3) -> list[dict]:
    pool = [row for row in inventory if row["Category"] == category]
    if product_row is not None:
        pool = [row for row in pool if row["Product Name"] != product_row["Product Name"]]
    pool = [row for row in pool if row["Stock Status"] != "Out of Stock"]
    pool = sorted(pool, key=lambda row: row["Quantity Available"], reverse=True)
    return pool[:n]


def get_cross_sell(category: str, inventory: list[dict]) -> list[dict]:
    names = CROSS_SELL_MAP.get(category, [])
    matches = [row for row in inventory if row["Product Name"] in names]
    return [{"Product Name": row["Product Name"], "Aisle": row["Aisle"], "Price": row["Price"]} for row in matches]


def get_deals(inventory: list[dict]) -> list[dict]:
    deals = [row for row in inventory if row["Deal Discount"] > 0]
    return [
        {
            "Product Name": row["Product Name"],
            "Aisle": row["Aisle"],
            "Price": row["Price"],
            "Deal Discount": row["Deal Discount"],
        }
        for row in deals
    ]


def classify_by_keywords(query: str) -> Optional[str]:
    q = query.lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in q for kw in keywords):
            return category
    return None


def is_urgent(query: str) -> bool:
    q = query.lower()
    return any(kw in q for kw in URGENCY_KEYWORDS)


def compute_directions(aisle_number: Optional[int], urgent: bool = False) -> str:
    """Generate simple, plausible turn-by-turn directions from the entrance."""
    if aisle_number is None:
        return "Ask any team member on the floor — they'll walk you right over."

    if aisle_number == 0:
        base = "Head straight in from the main entrance — Produce is the first section on your right."
    else:
        steps = max(aisle_number * 12, 12)
        base = (
            f"From the entrance, walk straight past the produce island, then turn into "
            f"Aisle {aisle_number}. It's roughly {steps} steps in."
        )
    if urgent:
        base += " Fastest route: skip the side aisles and cut straight down the main walkway."
    return base


def optimize_route(product_rows: list[dict]) -> list[dict]:
    """Sort a shopping list by aisle number so the customer walks the store in one efficient pass."""
    return sorted(product_rows, key=lambda row: row.get("Aisle Number", 999))
