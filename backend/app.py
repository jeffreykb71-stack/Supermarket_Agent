"""
app.py
------
Zero-dependency local server for the Supermarket Smart Assist kiosk.

Run with:
    python app.py

Then open http://localhost:8000 in a browser.
"""

import csv
import json
import mimetypes
import os
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
from urllib.parse import parse_qs, urlparse

import inventory_store as store
from agent import run_query

INVENTORY = store.load_inventory()
FEEDBACK_LOG = os.path.join(os.path.dirname(__file__), "data", "feedback_log.csv")
FRONTEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))

SESSIONS: dict[str, dict] = {}


def get_session(session_id: str) -> dict:
    if session_id not in SESSIONS:
        SESSIONS[session_id] = {"customer_name": "", "cart": [], "history": []}
    return SESSIONS[session_id]


def _cart_response(session: dict) -> dict:
    rows = []
    for name in session["cart"]:
        match = next((row for row in INVENTORY if row["Product Name"] == name), None)
        if match is not None:
            rows.append(
                {
                    "Product Name": match["Product Name"],
                    "Aisle": match["Aisle"],
                    "Aisle Number": int(match["Aisle Number"]),
                    "Stock Status": match["Stock Status"],
                    "Price": float(match["Price"]),
                }
            )
    route = store.optimize_route(rows)
    total = round(sum(item["Price"] for item in rows), 2)
    return {"items": route, "count": len(route), "total_price": total}


class KioskRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path

        if path.startswith("/api/"):
            self._handle_api_get(path, parsed.query)
            return

        self._serve_static(path)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path

        if path.startswith("/api/"):
            self._handle_api_post(path)
            return

        self._send_json({"detail": "Not found"}, status=404)

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return

    def _handle_api_get(self, path: str, query_string: str) -> None:
        if path == "/api/health":
            self._send_json({"status": "ok", "products": len(INVENTORY), "time": datetime.now().isoformat()})
            return

        if path == "/api/categories":
            counts: dict[str, int] = {}
            for row in INVENTORY:
                counts[row["Category"]] = counts.get(row["Category"], 0) + 1
            payload = [{"category": category, "count": count} for category, count in sorted(counts.items())]
            self._send_json(payload)
            return

        if path == "/api/deals":
            self._send_json(store.get_deals(INVENTORY))
            return

        if path == "/api/trending":
            params = parse_qs(query_string)
            limit = int(params.get("limit", [5])[0])
            self._send_json(store.trending.top(limit))
            return

        if path == "/api/inventory":
            params = parse_qs(query_string)
            category = params.get("category", [None])[0]
            if category:
                rows = [row for row in INVENTORY if row["Category"] == category]
            else:
                rows = INVENTORY
            self._send_json(rows)
            return

        if path.startswith("/api/session/"):
            session_id = path.split("/", 3)[-1]
            self._send_json(get_session(session_id))
            return

        if path.startswith("/api/cart/"):
            session_id = path.split("/", 3)[-1]
            self._send_json(_cart_response(get_session(session_id)))
            return

        self._send_json({"detail": "Not found"}, status=404)

    def _handle_api_post(self, path: str) -> None:
        body = self._read_json_body()
        if path == "/api/query":
            session_id = body.get("session_id", "")
            session = get_session(session_id)
            if body.get("customer_name"):
                session["customer_name"] = body["customer_name"]
            store.trending.record(body.get("message", ""))
            result = run_query(
                INVENTORY,
                customer_name=session.get("customer_name") or "Guest",
                query=body.get("message", ""),
                language=body.get("language") or "en",
            )
            session["history"].append(
                {"query": body.get("message", ""), "found": result.get("found"), "time": datetime.now().isoformat()}
            )
            self._send_json(result)
            return

        if path == "/api/cart/add":
            session_id = body.get("session_id", "")
            session = get_session(session_id)
            product_name = body.get("product_name", "")
            match = next((row for row in INVENTORY if row["Product Name"] == product_name), None)
            if match is None:
                self._send_json({"detail": "Product not found"}, status=404)
                return
            if product_name not in session["cart"]:
                session["cart"].append(product_name)
            self._send_json(_cart_response(session))
            return

        if path == "/api/cart/remove":
            session_id = body.get("session_id", "")
            session = get_session(session_id)
            product_name = body.get("product_name", "")
            session["cart"] = [name for name in session["cart"] if name != product_name]
            self._send_json(_cart_response(session))
            return

        if path == "/api/feedback":
            os.makedirs(os.path.dirname(FEEDBACK_LOG), exist_ok=True)
            is_new = not os.path.exists(FEEDBACK_LOG)
            with open(FEEDBACK_LOG, "a", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                if is_new:
                    writer.writerow(["timestamp", "session_id", "query", "rating"])
                writer.writerow([datetime.now().isoformat(), body.get("session_id", ""), body.get("query", ""), body.get("rating", "")])
            self._send_json({"status": "recorded"})
            return

        if path == "/api/session/new":
            session_id = str(uuid.uuid4())
            get_session(session_id)
            self._send_json({"session_id": session_id})
            return

        self._send_json({"detail": "Not found"}, status=404)

    def _read_json_body(self) -> dict:
        content_length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(content_length).decode("utf-8") if content_length else "{}"
        try:
            return json.loads(body) if body else {}
        except json.JSONDecodeError:
            return {}

    def _serve_static(self, path: str) -> None:
        if path in {"", "/"}:
            path = "/index.html"
        normalized = path.lstrip("/")
        if normalized and os.path.exists(os.path.join(FRONTEND_DIR, normalized)):
            file_path = os.path.join(FRONTEND_DIR, normalized)
        else:
            file_path = os.path.join(FRONTEND_DIR, "index.html")

        if os.path.isfile(file_path):
            content_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"
            with open(file_path, "rb") as handle:
                payload = handle.read()
            self._send_bytes(payload, content_type=content_type)
            return

        self._send_json({"detail": "Not found"}, status=404)

    def _send_json(self, payload, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self._send_bytes(body, content_type="application/json; charset=utf-8", status=status)

    def _send_bytes(self, payload: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(payload)


def main() -> None:
    port = int(os.environ.get("PORT", "8000"))
    server = ThreadingHTTPServer(("127.0.0.1", port), KioskRequestHandler)
    print(f"Supermarket kiosk running at http://127.0.0.1:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
