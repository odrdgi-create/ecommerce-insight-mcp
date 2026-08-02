# 🛒 E-Commerce Presentation & Insights MCP Server

A custom **Model Context Protocol (MCP)** server built with Python (`FastMCP`) that empowers **Claude Desktop** to scrape, clean, and extract structured e-commerce data directly from product and category URL links (e.g., Trendyol, Hepsiburada, e-commerce stores).

It transforms raw HTML content into clean, JSON-structured payloads—enabling Claude to automatically build visual presentation slides, market analysis reports, and competitive product comparisons.

---

## ✨ Key Features & Capabilities

* **📦 Single Product Presentation Extractor (`extract_product_presentation_data`)**
  * Fetches product page HTML while ignoring code noise (scripts, headers, footers, styles).
  * Extracts high-resolution product image URLs from CDN sources.
  * Cleans core product descriptions, titles, and specifications for instant slide creation.

* **📊 Category & Market Analyzer (`get_category_presentation_data`)**
  * Scrapes e-commerce category/showcase pages.
  * Identifies top-featured products, brand variations, and product direct links.
  * Provides Claude with structured data to generate competitive matrix tables and market overview presentations.

* **🧹 Smart HTML Sanitization & Token Optimization**
  * Filters out navigational clutter and limits raw text output to preserve context windows and speed up execution.

* **⚙️ FastMCP Powered & Lightweight**
  * Seamlessly connects to Claude Desktop via standard MCP configuration.
