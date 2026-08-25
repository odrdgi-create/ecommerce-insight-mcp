# E-Commerce Insight MCP

🇹🇷 [Türkçe](README.md) · **English**

An MCP server that pulls presentation-ready data out of product and category pages. It exposes three tools:

| Tool | What it does |
|---|---|
| `extract_product_presentation_data` | Title, images and cleaned text from a product page |
| `extract_structured_product_schema` | JSON-LD + OpenGraph: price, stock, brand, rating |
| `get_category_presentation_data` | Featured product list from a category page |
| `extract_seller_trust_signals` | Seller rating, who ships it, return policy + a reasoned decision summary |

Live server: **https://ecommerce-insight-mcp.onrender.com**

---

## Ways to use it

There are three. If you don't have an MCP client or don't use a terminal, option 1 is enough.

### 1. From a browser (no setup)

Open **https://ecommerce-insight-mcp.onrender.com**, paste a link, press a button.

> The server runs on a free tier and may need to wake up — **the first request can take up to a minute**, later ones are fast.

### 2. curl / Postman / n8n / Google Sheets

Plain `GET` endpoints returning JSON. No handshake, no session, no SSE:

```bash
curl "https://ecommerce-insight-mcp.onrender.com/api/product?url=https://example.com/product"
curl "https://ecommerce-insight-mcp.onrender.com/api/schema?url=https://example.com/product"
curl "https://ecommerce-insight-mcp.onrender.com/api/category?url=https://example.com/category"
curl "https://ecommerce-insight-mcp.onrender.com/api/seller?url=https://example.com/product"
```

To check whether the server is up:

```bash
curl https://ecommerce-insight-mcp.onrender.com/health
```

### 3. With an MCP client

```json
{
  "mcpServers": {
    "ecommerce-insight": {
      "url": "https://ecommerce-insight-mcp.onrender.com/mcp"
    }
  }
}
```

If your client doesn't support remote server URLs (older versions that only speak stdio), put a bridge in between:

```json
{
  "mcpServers": {
    "ecommerce-insight": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "https://ecommerce-insight-mcp.onrender.com/mcp"]
    }
  }
}
```

**Note:** the `/mcp` path cannot be called with plain curl. MCP Streamable HTTP requires the `Accept: application/json, text/event-stream` header, the `initialize` → `notifications/initialized` → `tools/call` sequence and an `Mcp-Session-Id` header, and it replies in SSE frames. Use option 2 from a terminal.

---

## Local setup

Running locally also enables the Playwright fallback. It is usually not needed for bot-protected sites (the TLS impersonation below already handles those), but it helps on JavaScript-rendered pages.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Optional, for JavaScript-rendered pages:
pip install playwright==1.62.0
playwright install chromium
```

MCP client config (stdio):

```json
{
  "mcpServers": {
    "ecommerce-insight": {
      "command": "/full/path/.venv/bin/python",
      "args": ["/full/path/ecommerce_mcp.py"]
    }
  }
}
```

To run it as an HTTP server:

```bash
.venv/bin/python -m uvicorn ecommerce_mcp:app --port 8000
```

Then open `http://localhost:8000`.

---

## Testing locally

### The quickest check

```bash
.venv/bin/python -m uvicorn ecommerce_mcp:app --port 8000
```

In another terminal:

```bash
curl -s http://localhost:8000/health
```

`impersonate` and `playwright` both `true` means everything is available:

```json
{"status":"ok","impersonate":true,"playwright":true,"tools":["category","product","schema"]}
```

### Presentation output

```bash
curl -s "http://localhost:8000/api/product?url=<PRODUCT_URL>" | python -m json.tool
```

Returns `title`, `product_images` (up to 6 distinct photos) and `extracted_content`.

For price, stock, brand and rating use the schema tool:

```bash
curl -s "http://localhost:8000/api/schema?url=<PRODUCT_URL>" | python -m json.tool
```

Note that not every site labels its schema `Product` — Trendyol, for instance, uses `ProductGroup` and puts prices under `hasVariant`.

For the seller decision:

```bash
curl -s "http://localhost:8000/api/seller?url=<PRODUCT_URL>" | python -m json.tool
```

### The browser form

Open `http://localhost:8000`, paste a link, press a button. Same data, no terminal.

### Testing the tools directly

`python test_local.py` calls all three tools with sample URLs and prints the raw JSON.

### Simulating the cloud environment

To reproduce how the server behaves on Render, start it with the browser fallback disabled:

```bash
ENABLE_PLAYWRIGHT=0 .venv/bin/python -m uvicorn ecommerce_mcp:app --port 8000
```

### Testing the MCP protocol

`/mcp` needs the full handshake. To verify it by hand:

```bash
# 1. initialize — grab the Mcp-Session-Id from the response headers
curl -i -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"test","version":"1"}}}'

# 2. list the tools (paste the session id from step 1)
curl -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Mcp-Session-Id: <SESSION_ID>" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}'
```

---

## Seller trust signals

The `extract_seller_trust_signals` tool exists to justify the question "which product and which seller should I pick, and why". Alongside the raw fields it returns a `decision_summary` split into **strengths**, **concerns** and **unknowns**.

Trendyol example:

```json
{
  "seller": {
    "name": "SuperStep",
    "official_name": "EREN PERAKENDE VE TEKSTİL ANONİM ŞİRKETİ",
    "city": "İstanbul",
    "score": 8.4, "score_scale": 10
  },
  "logistics": {
    "fulfilled_by": "Satıcı kendi gönderiyor (pazaryeri)",
    "refundable": true, "free_shipping": false, "max_installment": 12
  },
  "decision_summary": {
    "strengths": ["Satıcı puanı 8.4/10 — iyi.", "Ürün iade edilebilir."],
    "concerns": ["Ürün puanı 5 ama yalnızca 1 yoruma dayanıyor — istatistiksel olarak zayıf."]
  }
}
```

### What can and cannot be measured

Shipping damage/loss rates, customer-service response quality and reachability during returns are **not published per seller on any marketplace.** That is why the output carries an `unknowns` list — so a presentation never confuses "no data" with "no problem".

Two indicators stand in for those three:

- **`seller.score`** — the platform's composite, computed from exactly those factors.
- **`logistics.fulfilled_by`** — whether the platform's warehouse or the seller ships the item. When the seller ships it themselves, shipping and returns depend entirely on that seller's performance; this is the best published proxy for shipping risk.

Product ratings are also always read **together with the review count**: 5/5 from a single review is a weaker signal than 4.3 from 500.

### Source matters

The `source` field says where the data came from:

| Value | Meaning |
|---|---|
| `trendyol_embedded` | Data Trendyol embeds in the page — every field above is populated |
| `json_ld` | Site-agnostic JSON-LD `offers.seller` — usually just the seller name |

Empty fields under `json_ld` **do not mean the seller is weak**; they mean the site doesn't publish that data. If no signal is found at all, `decision_summary.notes` says so explicitly.

---

## Configuration

| Environment variable | Default | Description |
|---|---|---|
| `ENABLE_PLAYWRIGHT` | `1` | Set to `0` to disable the browser fallback. Playwright isn't installed on Render, so the code detects that on its own — you don't have to set this. |

The server only makes requests to public `http`/`https` addresses; loopback, private-network and cloud metadata addresses (`169.254.169.254`) are rejected.

---

## How bot protection is handled

Protections like Cloudflare (Trendyol) and Akamai (Hepsiburada) identify clients largely from the **TLS handshake**. Python's `httpx` leaves a distinctive fingerprint (JA4 `t13d1712h1`, HTTP/1.1) that gives it away immediately — combined with a datacenter IP, that means a 403.

The server therefore uses **`curl_cffi`** as its primary fetcher: it presents a real Chrome TLS fingerprint (JA4 `t13d1516h2`, HTTP/2). Measured difference, from the same IP with the same User-Agent:

| Site | `httpx` | `curl_cffi` |
|---|---|---|
| Hepsiburada | 403 (1.7 KB block page) | 200 (610 KB, JSON-LD included) |

Because it runs no browser, unlike Playwright it needs no extra RAM or Chromium binary; it works fine on a free tier.

Fetch order: **`curl_cffi` → `httpx` (if curl_cffi is missing) → Playwright (local only, for JS rendering)**.

### What cannot be worked around: IP-based content differences

Trendyol serves a **different page entirely** to the cloud server's IP. Measured — same URL (`https://www.trendyol.com/`), at the same moment:

| Request from | Page title | Product links found |
|---|---|---|
| Render (cloud) | "Online Alışveriş Sitesi, Türkiye'nin Trend Yolu \| Trendyol" | 0 |
| Local machine | "En Trend Ürünler Türkiye'nin Online Alışveriş Sitesi Trendyol'da" | 8 |

This is not a TLS fingerprint, cookie or JavaScript problem — the decision is made from the IP as the request arrives. So TLS impersonation, session cookies and Playwright **cannot** fix it; they all originate from the same IP.

**The fix for Trendyol: run the server locally.** The cloud server keeps returning full data for Hepsiburada, Amazon and unprotected stores. When Trendyol is requested it returns partial data plus an explanatory `warning` field rather than an error.
