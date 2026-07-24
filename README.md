# Smart Assist — Supermarket Kiosk Agent

A from-scratch rebuild of the original `Supermarket_Agent.ipynb` notebook as a
real, runnable kiosk app: a **FastAPI + LangGraph backend** and a **standalone
HTML/CSS/JS kiosk frontend**. Built for running on a laptop right now — you
can adapt sizing/touch targets for an actual kiosk screen later.

## What changed vs. the notebook

The notebook was a single-turn, terminal-only script (`input()` prompts,
`print()` output, a 10-row inline CSV, one Groq call to classify category).
This version keeps the same LangGraph spirit but turns it into a real
product:

| Notebook | This app |
|---|---|
| `input()` / `print()` in a Colab cell | REST API + full kiosk UI |
| 10-item inline CSV | 49-item catalog with categories, prices, deals |
| Category guessed by keywords or one LLM call | Category grounded in the **actual product match** first, LLM/keywords only as fallback for "not found" items |
| No handling of out-of-stock items | **Substitute suggestions** pulled from the same category |
| No related items | **Cross-sell ("you might also need")** engine |
| No promotions | **Deals engine** + scrolling deals ticker + attract-screen |
| No navigation help | **Aisle-based walking directions**, sped up when urgency is detected in the query (“I'm in a hurry”) |
| No multi-item support | **Shopping list** with **route optimization** (sorted by aisle so you walk the store once) |
| English only | Optional **response language** selector (LLM-translated) |
| No memory of what people search for | **Trending searches** panel (in-memory, resets daily) |
| No feedback loop | 👍/👎 feedback logged to `backend/data/feedback_log.csv` |
| Breaks without an API key | **Fully functional without `GROQ_API_KEY`** — falls back to rule-based classification and templated (still friendly) responses. The AI key just makes the category-guessing and the written responses smarter/more natural. |

## Project structure

```
supermarket_kiosk_agent/
├── backend/
│   ├── app.py              # FastAPI app: routes, sessions, cart, serves the frontend
│   ├── agent.py             # LangGraph state machine (the "agent")
│   ├── inventory_store.py   # catalog loading, fuzzy search, substitutes, deals, directions
│   ├── requirements.txt
│   ├── .env.example
│   └── data/
│       └── inventory.csv
├── frontend/
│   ├── index.html
│   ├── style.css
│   └── app.js
└── README.md
```

## Running it

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# optional — enables smarter classification + natural language responses
cp .env.example .env
# then edit .env and paste your GROQ_API_KEY

uvicorn app:app --reload --port 8000
```

Open **http://localhost:8000** — that's it. FastAPI serves the frontend
directly, so there's no separate frontend server or build step.

## API surface

| Method | Path | What it does |
|---|---|---|
| POST | `/api/query` | Runs the LangGraph agent on one message, returns product match, stock alert, substitutes, cross-sell, deal, directions, and a written response |
| POST | `/api/cart/add` / `/api/cart/remove` | Manage the session's shopping list |
| GET | `/api/cart/{session_id}` | Cart contents, sorted into an optimized walking route |
| GET | `/api/categories` | Category list with item counts (powers the quick-filter chips) |
| GET | `/api/deals` | Active promotions (powers the ticker + attract screen) |
| GET | `/api/trending` | Today's most-searched terms |
| POST | `/api/feedback` | Logs a 👍/👎 for a given query |
| GET | `/api/health` | Basic liveness check |

## Notes for VS Code

Every file here is plain Python/HTML/CSS/JS — open the `supermarket_kiosk_agent`
folder directly in VS Code, no notebook runtime required. `backend/agent.py`
is the best starting point to see how the LangGraph graph is wired.
