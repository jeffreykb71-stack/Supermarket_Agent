const API = ""; // same-origin, FastAPI serves this file too

let sessionId = localStorage.getItem("kiosk_session_id");
let idleTimer = null;

// ---------------------------------------------------------------- helpers
async function api(path, options) {
  const res = await fetch(API + path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) throw new Error(`API error ${res.status}`);
  return res.json();
}

function setStatus(text) {
  document.getElementById("statusText").textContent = text;
}

// ---------------------------------------------------------------- session
async function ensureSession() {
  if (sessionId) return sessionId;
  const data = await api("/api/session/new", { method: "POST" });
  sessionId = data.session_id;
  localStorage.setItem("kiosk_session_id", sessionId);
  return sessionId;
}

// ---------------------------------------------------------------- clock
function tickClock() {
  const now = new Date();
  document.getElementById("clock").textContent = now.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
  const hour = now.getHours();
  const greeting =
    hour < 12 ? "Good morning! What are you shopping for today?" :
    hour < 17 ? "Good afternoon! What are you shopping for today?" :
    "Good evening! What are you shopping for today?";
  const g = document.getElementById("greeting");
  if (!g.dataset.custom) g.textContent = greeting;
}
setInterval(tickClock, 1000);
tickClock();

// ---------------------------------------------------------------- deals ticker
async function loadDeals() {
  try {
    const deals = await api("/api/deals");
    const ticker = document.getElementById("dealsTicker");
    const attractDeals = document.getElementById("attractDeals");
    if (deals.length === 0) {
      ticker.innerHTML = "";
      attractDeals.innerHTML = "";
      return;
    }
    const text = deals
      .map((d) => `${d["Product Name"]} \u2014 ${d["Deal Discount"]}% off`)
      .join("    \u2022    ");
    ticker.innerHTML = `<span>\ud83c\udff7\ufe0f ${text}</span>`;
    attractDeals.innerHTML = deals
      .slice(0, 4)
      .map((d) => `<div>${d["Product Name"]} \u2014 ${d["Deal Discount"]}% off</div>`)
      .join("");
  } catch (e) {
    console.error(e);
  }
}

// ---------------------------------------------------------------- categories
async function loadCategories() {
  try {
    const cats = await api("/api/categories");
    const box = document.getElementById("categoryChips");
    box.innerHTML = "";
    cats.forEach((c) => {
      const chip = document.createElement("button");
      chip.className = "chip";
      chip.textContent = `${c.category} (${c.count})`;
      chip.onclick = () => {
        document.getElementById("queryInput").value = c.category;
        runSearch(c.category);
      };
      box.appendChild(chip);
    });
  } catch (e) {
    console.error(e);
  }
}

// ---------------------------------------------------------------- trending
async function loadTrending() {
  try {
    const items = await api("/api/trending?limit=5");
    const list = document.getElementById("trendingList");
    if (items.length === 0) {
      list.innerHTML = '<li class="muted">No searches yet.</li>';
      return;
    }
    list.innerHTML = items
      .map((i) => `<li><span>${i.query}</span><span class="count">${i.count}\u00d7</span></li>`)
      .join("");
  } catch (e) {
    console.error(e);
  }
}

// ---------------------------------------------------------------- search
let lastQuery = "";

async function runSearch(forcedQuery) {
  const query = forcedQuery || document.getElementById("queryInput").value.trim();
  if (!query) return;
  lastQuery = query;
  resetIdle();
  setStatus("Searching\u2026");

  await ensureSession();
  const name = document.getElementById("nameInput").value.trim();
  const language = document.getElementById("languageSelect").value;

  try {
    const result = await api("/api/query", {
      method: "POST",
      body: JSON.stringify({
        session_id: sessionId,
        message: query,
        customer_name: name || undefined,
        language,
      }),
    });
    renderResult(query, result);
    loadTrending();
    setStatus("Ready");
  } catch (e) {
    console.error(e);
    setStatus("Something went wrong \u2014 try again");
  }
}

function renderResult(query, result) {
  document.getElementById("emptyState").hidden = true;
  const card = document.getElementById("resultCard");
  card.hidden = false;

  const found = result.found;
  const product = result.product_details || {};

  document.getElementById("aisleBadge").textContent = found
    ? (product.aisle_number === 0 ? "P" : product.aisle_number)
    : "?";
  document.getElementById("productName").textContent = found ? product.name : `"${query}"`;
  document.getElementById("productLoc").textContent = found
    ? `${product.location} \u00b7 ${product.position}`
    : "Not in our digital directory";

  const pill = document.getElementById("stockPill");
  const stockMap = {
    in_stock: ["In stock", "in"],
    low_stock: ["Low stock", "low"],
    out_of_stock: ["Out of stock", "out"],
    not_found: ["Not found", "unknown"],
  };
  const [label, cls] = stockMap[result.stock_alert] || ["Unknown", "unknown"];
  pill.textContent = label;
  pill.className = `stock-pill ${cls}`;

  document.getElementById("responseText").textContent = result.response_text || "";
  document.getElementById("directionsBox").textContent = result.directions || "";

  const dealBox = document.getElementById("dealBanner");
  if (result.deal) {
    dealBox.hidden = false;
    dealBox.textContent = `\ud83c\udff7\ufe0f Deal: ${result.deal.name} is ${result.deal.discount}% off right now`;
  } else {
    dealBox.hidden = true;
  }

  const subsBox = document.getElementById("substitutesBox");
  const subsList = document.getElementById("substitutesList");
  if (result.substitutes && result.substitutes.length) {
    subsBox.hidden = false;
    subsList.innerHTML = "";
    result.substitutes.forEach((s) => {
      const chip = document.createElement("button");
      chip.className = "chip";
      chip.textContent = `${s["Product Name"]} \u00b7 ${s["Aisle"]}`;
      chip.onclick = () => {
        document.getElementById("queryInput").value = s["Product Name"];
        runSearch(s["Product Name"]);
      };
      subsList.appendChild(chip);
    });
  } else {
    subsBox.hidden = true;
  }

  const crossBox = document.getElementById("crossSellBox");
  const crossList = document.getElementById("crossSellList");
  if (result.cross_sell && result.cross_sell.length) {
    crossBox.hidden = false;
    crossList.innerHTML = "";
    result.cross_sell.forEach((s) => {
      const chip = document.createElement("button");
      chip.className = "chip";
      chip.textContent = `+ ${s["Product Name"]}`;
      chip.onclick = () => addToCart(s["Product Name"]);
      crossList.appendChild(chip);
    });
  } else {
    crossBox.hidden = true;
  }

  document.getElementById("addCartBtn").onclick = () => {
    if (found) addToCart(product.name);
  };
  document.getElementById("addCartBtn").disabled = !found;

  document.getElementById("thumbUp").onclick = () => sendFeedback(query, "up");
  document.getElementById("thumbDown").onclick = () => sendFeedback(query, "down");
}

async function sendFeedback(query, rating) {
  await ensureSession();
  await api("/api/feedback", {
    method: "POST",
    body: JSON.stringify({ session_id: sessionId, query, rating }),
  });
  setStatus(rating === "up" ? "Thanks for the feedback!" : "Thanks \u2014 we'll do better.");
}

// ---------------------------------------------------------------- cart
async function addToCart(productName) {
  await ensureSession();
  const data = await api("/api/cart/add", {
    method: "POST",
    body: JSON.stringify({ session_id: sessionId, product_name: productName }),
  });
  renderCart(data);
  setStatus(`Added ${productName} to your list`);
}

async function removeFromCart(productName) {
  const data = await api("/api/cart/remove", {
    method: "POST",
    body: JSON.stringify({ session_id: sessionId, product_name: productName }),
  });
  renderCart(data);
}

function renderCart(data) {
  const list = document.getElementById("cartList");
  if (!data.items.length) {
    list.innerHTML = '<li class="muted">List is empty.</li>';
  } else {
    list.innerHTML = data.items
      .map(
        (item, idx) => `
      <li>
        <span><span class="step">${idx + 1}</span>${item["Product Name"]}</span>
        <button class="remove" onclick="removeFromCart('${item["Product Name"].replace(/'/g, "\\'")}')">&times;</button>
      </li>`
      )
      .join("");
  }
  document.getElementById("cartTotal").textContent = `$${data.total_price.toFixed(2)}`;
}

async function refreshCart() {
  await ensureSession();
  const data = await api(`/api/cart/${sessionId}`);
  renderCart(data);
}

document.getElementById("clearCartBtn").onclick = async () => {
  const list = await api(`/api/cart/${sessionId}`);
  for (const item of list.items) {
    await removeFromCart(item["Product Name"]);
  }
};

// ---------------------------------------------------------------- attract / idle mode
function resetIdle() {
  document.getElementById("attract").classList.add("hidden");
  clearTimeout(idleTimer);
  idleTimer = setTimeout(() => {
    document.getElementById("attract").classList.remove("hidden");
  }, 90000); // 90s idle -> attract screen
}
["click", "keydown", "input"].forEach((evt) =>
  document.addEventListener(evt, resetIdle)
);
document.getElementById("attract").addEventListener("click", resetIdle);

// ---------------------------------------------------------------- wiring
document.getElementById("searchBtn").onclick = () => runSearch();
document.getElementById("queryInput").addEventListener("keydown", (e) => {
  if (e.key === "Enter") runSearch();
});
document.getElementById("nameInput").addEventListener("input", (e) => {
  const g = document.getElementById("greeting");
  if (e.target.value.trim()) {
    g.dataset.custom = "1";
    g.textContent = `Hi ${e.target.value.trim()}! What are you shopping for today?`;
  } else {
    delete g.dataset.custom;
    tickClock();
  }
});

// ---------------------------------------------------------------- init
(async function init() {
  await ensureSession();
  loadDeals();
  loadCategories();
  loadTrending();
  refreshCart();
  resetIdle();
  setInterval(loadDeals, 60000);
  setInterval(loadTrending, 15000);
})();
