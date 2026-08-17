# E-Commerce Presentation & Insights MCP Server

**[English](#english) | [Türkçe](#türkçe)**

An MCP server for Claude Desktop that scrapes e-commerce product pages and category links to generate structured presentation payloads, product comparisons, and market insights.

---

## English

A **Model Context Protocol (MCP)** server built with Python (`FastMCP`) that lets Claude Desktop scrape and clean e-commerce product and category pages into structured JSON, enabling Claude to build presentation slides, market analysis reports, and competitive product comparisons.

### Features

**1. `extract_product_presentation_data(url: str)`**
Fetches a single product page and returns:
- Page title (`<title>`)
- Up to 6 product images — detected first via `og:image`/`twitter:image` meta tags, falling back to `<img>` tags filtered by exclusion keywords (logo, icon, sprite, etc.) and minimum size; all URLs resolved with `urljoin`
- Clean text with `script`, `style`, `header`, `footer`, `nav`, `noscript` tags stripped, lines shorter than 3 characters removed, capped at the first 150 lines

**2. `extract_structured_product_schema(url: str)`**
Extracts machine-readable structured data instead of freeform text:
- All `<script type="application/ld+json">` blocks, parsed into JSON (this is the same schema.org `Product` data Google uses for rich snippets — reliable price, stock, brand, and rating fields when the site provides it)
- All `og:*` and `product:*` OpenGraph meta tags as a flat key-value map

Useful when you need exact, structured fields (price, SKU, availability) rather than a text summary — most modern e-commerce platforms (Shopify, Trendyol, WooCommerce, etc.) publish this data even when they don't want to be scraped in other ways.

**3. `get_category_presentation_data(url: str)`**
Fetches a category/listing page and returns:
- Page title
- Up to 8 unique products from links whose `href` contains `-p-`, `/product/`, `/urun/`, `-pm-`, or `/p-`, with link text longer than 10 characters (name + full URL)

All three tools return `{"error": "Hata oluştu: ..."}` on failure instead of raising an exception.

### Fetch Strategy

Every tool goes through a shared two-stage fetch (`_fetch_soup`):
1. **Fast path** — a plain `httpx` request.
2. **Fallback path** — if the fast path returns a blocking status code (`403`/`429`/`503`), *or* returns `200 OK` with a page that looks like a bot-check (title/body matching patterns like "security check", "captcha", "verify you are human", or suspiciously short content — see `_looks_blocked`), the tool retries with a headless Playwright browser (randomized viewport, `tr-TR` locale, hidden `navigator.webdriver` flag).

This is enough to handle most JS-rendering and basic bot-detection cases, but it is not a stealth/evasion toolkit — see Known Limitations below for what it doesn't get past.

Error handling is centralized in a `@handle_fetch_errors` decorator wrapping all three tools, so each tool function only contains its own parsing logic — no repeated `try/except` blocks. Timeouts, HTTP errors, connection errors, and missing Playwright are each caught once and turned into a consistent `{"error": "..."}` JSON response.

### Known Limitations

As of the latest update, this server is largely **platform-agnostic**:
- Relative links in `get_category_presentation_data` are resolved with Python's built-in `urllib.parse.urljoin(base_url, href)`, so they correctly resolve against **any** target domain.
- Product images are detected via `og:image` / `twitter:image` meta tags first (a standard nearly all e-commerce sites use), falling back to `<img>` tags filtered by exclusion keywords (logo, icon, sprite, etc.) and minimum size — not tied to any single CDN.
- Product-link detection matches common patterns (`-p-`, `/product/`, `/urun/`, `-pm-`, `/p-`) used across Turkish and international e-commerce platforms.

Remaining limitations:
- **Hepsiburada is not reliably supported.** It runs enterprise-grade bot protection that blocks both plain HTTP requests and a headless Playwright browser (with a randomized User-Agent, disabled automation flags, and a hidden `navigator.webdriver`) — the site returns a 200 OK "security check" page instead of product content either way. Tested and confirmed as of this writing; not expected to change without significantly more invasive evasion techniques, which this project intentionally does not pursue.
- No `robots.txt` check or rate limiting between requests.
- Not yet tested against every major e-commerce platform — edge cases on unfamiliar sites are possible.

### Requirements

- Python 3.10+
- [Claude Desktop](https://claude.ai/download)

Dependencies (`requirements.txt`):
```
fastmcp
httpx
beautifulsoup4
playwright
```

After installing, download the Playwright browser binary once:
```bash
playwright install chromium
```

### Installation

```bash
git clone https://github.com/odrdgi-create/ecommerce-insight-mcp.git
cd ecommerce-insight-mcp
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### Claude Desktop Setup

Add the following block to your Claude Desktop config file
(macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`,
Windows: `%APPDATA%\Claude\claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "ecommerce-insight": {
      "command": "python",
      "args": ["/full/path/to/ecommerce-insight-mcp/ecommerce_mcp.py"]
    }
  }
}
```

> If using a venv, point `"command"` to the venv's Python binary (e.g. `/full/path/to/ecommerce-insight-mcp/venv/bin/python`).

Save the file and restart Claude Desktop. The "E-Commerce HTML Summarizer" server should appear in the tools list.

### Usage Example

Ask Claude something like:

> "Analyze this product page for a presentation: https://www.trendyol.com/..."

Claude calls `extract_product_presentation_data` and receives:

```json
{
  "type": "single_product_presentation",
  "url": "https://www.trendyol.com/...",
  "title": "Product Name",
  "product_images": ["https://cdn.dsmcdn.com/..."],
  "extracted_content": "Clean product description, specs, etc..."
}
```

For a category page:

> "Compare the featured products in this category: https://www.trendyol.com/..."

```json
{
  "type": "category_showcase_presentation",
  "category_title": "Category Name",
  "category_url": "https://www.trendyol.com/...",
  "top_products": [
    {"name": "Product 1", "url": "https://www.trendyol.com/..."}
  ]
}
```

For exact structured fields:

> "Get me the exact price and stock status for this product: https://www.trendyol.com/..."

Claude calls `extract_structured_product_schema` and receives the site's raw JSON-LD and OpenGraph data, from which it can read fields like price, currency, and availability directly.

### Project Structure

```
ecommerce-insight-mcp/
├── ecommerce_mcp.py     # MCP server and tool definitions
├── requirements.txt     # Python dependencies
├── .gitignore
└── README.md
```

### Roadmap (suggested)

- [x] Dynamic relative-URL resolution based on target domain (`urljoin`)
- [x] Platform-agnostic image detection (`og:image` + filtered `<img>` fallback)
- [x] Structured data extraction (JSON-LD + OpenGraph) via `extract_structured_product_schema`
- [x] Playwright fallback for JS-rendered / bot-checked pages, with soft-block (200 OK block page) detection
- [x] Centralized error handling via a `@handle_fetch_errors` decorator (removed repeated try/except blocks)
- [ ] `robots.txt` compliance and request throttling
- [ ] Unit tests
- [ ] Pin dependency versions in `requirements.txt`

### License

Not specified — consider adding an open-source license (e.g. MIT).

---

## Türkçe

Python (`FastMCP`) ile yazılmış bir **Model Context Protocol (MCP)** sunucusu. Claude Desktop'ın e-ticaret ürün ve kategori sayfalarındaki ham HTML'i temizleyip yapılandırılmış JSON verisine dönüştürmesini sağlar; bu sayede Claude sunum slaytları, pazar analizi raporları ve rakip ürün karşılaştırmaları üretebilir.

### Özellikler

**1. `extract_product_presentation_data(url: str)`**
Tek bir ürün sayfasını çeker ve şunları döndürür:
- Sayfa başlığı (`<title>`)
- En fazla 6 ürün görseli — önce `og:image`/`twitter:image` meta etiketlerinden tespit edilir, bulunamazsa dışlama anahtar kelimeleri (logo, icon, sprite vb.) ve minimum boyut filtresiyle `<img>` etiketlerine düşülür; tüm URL'ler `urljoin` ile çözümlenir
- `script`, `style`, `header`, `footer`, `nav`, `noscript` etiketleri ayıklanmış, 3 karakterden uzun satırlarla sınırlı, ilk 150 satıra kırpılmış temiz metin

**2. `extract_structured_product_schema(url: str)`**
Serbest metin yerine makine tarafından okunabilir yapısal veri çeker:
- Tüm `<script type="application/ld+json">` bloklarını JSON'a çevirir (bu, Google'ın zengin snippet'ler için kullandığı aynı schema.org `Product` verisidir — site sağladığında güvenilir fiyat, stok, marka ve puan alanları verir)
- Tüm `og:*` ve `product:*` OpenGraph meta etiketlerini düz bir key-value haritası olarak döndürür

Metin özeti yerine kesin, yapılandırılmış alanlara (fiyat, SKU, stok durumu) ihtiyacın olduğunda kullanışlıdır — çoğu modern e-ticaret platformu (Shopify, Trendyol, WooCommerce vb.) diğer scraping yollarını engellese bile bu veriyi yayınlar.

**3. `get_category_presentation_data(url: str)`**
Bir kategori/liste sayfasını çeker ve şunları döndürür:
- Sayfa başlığı
- `href` içinde `-p-`, `/product/`, `/urun/`, `-pm-` veya `/p-` geçen linklerden, metni 10 karakterden uzun olan ve tekrar etmeyen ilk 8 ürün (isim + tam URL)

Üç tool da hata durumunda `{"error": "Hata oluştu: ..."}` formatında JSON döndürür, exception fırlatmaz.

### Veri Çekme Stratejisi

Her tool ortak, iki aşamalı bir çekme mekanizmasından (`_fetch_soup`) geçer:
1. **Hızlı yol** — düz bir `httpx` isteği.
2. **Yedek yol** — hızlı yol engelleyici bir statü kodu (`403`/`429`/`503`) döndürürse *veya* `200 OK` ile birlikte bot-kontrolüne benzeyen bir sayfa dönerse (başlık/gövdede "güvenlik kontrolü", "captcha", "robot değilsiniz" gibi ifadeler ya da şüpheli derecede kısa içerik — bkz. `_looks_blocked`), tool headless Playwright tarayıcısıyla (rastgele viewport, `tr-TR` dili, gizlenmiş `navigator.webdriver` bayrağı) tekrar dener.

Bu, çoğu JS-render ve temel bot-tespit durumunu ele almaya yetiyor, ama bir stealth/atlatma araç seti değil — nelerin aşılamadığını aşağıdaki Bilinen Sınırlamalar'da görebilirsin.

Hata yönetimi, üç tool'u da saran tek bir `@handle_fetch_errors` decorator'ında toplanmıştır — her tool fonksiyonu artık sadece kendi parse mantığını içerir, tekrar eden `try/except` blokları yoktur. Zaman aşımı, HTTP hataları, bağlantı hataları ve eksik Playwright kurulumu tek bir yerde yakalanır ve tutarlı bir `{"error": "..."}` JSON yanıtına çevrilir.

### Bilinen Sınırlamalar

Son güncellemeyle birlikte bu sunucu artık büyük ölçüde **platform-bağımsız**:
- `get_category_presentation_data` içindeki relative linkler Python'un yerleşik `urllib.parse.urljoin(base_url, href)` fonksiyonuyla çözümlenir — hangi hedef domain olursa olsun **doğru URL** üretilir.
- Ürün görselleri önce `og:image` / `twitter:image` meta etiketlerinden tespit edilir (neredeyse tüm e-ticaret sitelerinin kullandığı standart bir yapı), bulunamazsa dışlama anahtar kelimeleri (logo, icon, sprite vb.) ve minimum boyut filtresiyle `<img>` etiketlerine düşülür — artık tek bir CDN'e bağlı değildir.
- Ürün linki tespiti, hem Türkiye hem uluslararası e-ticaret platformlarında yaygın olan pattern'leri (`-p-`, `/product/`, `/urun/`, `-pm-`, `/p-`) kapsar.

Kalan sınırlamalar:
- **Hepsiburada güvenilir şekilde desteklenmiyor.** Kurumsal seviyede bot koruması kullanıyor; bu koruma hem düz HTTP isteklerini hem de headless Playwright tarayıcısını (rastgele User-Agent, otomasyon bayrakları kapatılmış, `navigator.webdriver` gizlenmiş halde) engelliyor — site her durumda ürün içeriği yerine 200 OK statüsüyle bir "güvenlik kontrolü" sayfası döndürüyor. Bu yazı itibarıyla test edilip doğrulanmıştır; çok daha agresif atlatma teknikleri olmadan değişmesi beklenmiyor — bu proje bilinçli olarak o yönde ilerlemiyor.
- `robots.txt` kontrolü veya istekler arası gecikme (rate limiting) yoktur.
- Henüz her büyük e-ticaret platformunda test edilmedi — alışılmadık sitelerde uç durumlar (edge case) çıkabilir.

### Gereksinimler

- Python 3.10+
- [Claude Desktop](https://claude.ai/download)

Bağımlılıklar (`requirements.txt`):
```
fastmcp
httpx
beautifulsoup4
playwright
```

Kurulumdan sonra Playwright'ın tarayıcı ikilisini bir kereliğine indirin:
```bash
playwright install chromium
```

###  Kurulum

```bash
git clone https://github.com/odrdgi-create/ecommerce-insight-mcp.git
cd ecommerce-insight-mcp
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### Claude Desktop Entegrasyonu

Claude Desktop'ın konfigürasyon dosyasına (macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`, Windows: `%APPDATA%\Claude\claude_desktop_config.json`) aşağıdaki bloğu ekleyin:

```json
{
  "mcpServers": {
    "ecommerce-insight": {
      "command": "python",
      "args": ["/tam/yol/ecommerce-insight-mcp/ecommerce_mcp.py"]
    }
  }
}
```

> `venv` kullanıyorsanız `"command"` alanına venv içindeki Python'un tam yolunu (örn. `/tam/yol/ecommerce-insight-mcp/venv/bin/python`) yazın.

Dosyayı kaydedip Claude Desktop'ı yeniden başlatın. Araç çubuğunda "E-Commerce HTML Summarizer" sunucusunu görmelisiniz.

### Kullanım Örneği

Claude'a şu şekilde bir istekte bulunabilirsiniz:

> "Şu ürün sayfasını analiz edip sunum için özetler misin: https://www.trendyol.com/..."

Claude, `extract_product_presentation_data` tool'unu çağırır ve şuna benzer bir payload alır:

```json
{
  "type": "single_product_presentation",
  "url": "https://www.trendyol.com/...",
  "title": "Ürün Adı",
  "product_images": ["https://cdn.dsmcdn.com/..."],
  "extracted_content": "Ürün özellikleri, açıklama vb. temiz metin..."
}
```

Kategori sayfası için:

> "Bu kategorideki öne çıkan ürünleri karşılaştır: https://www.trendyol.com/..."

```json
{
  "type": "category_showcase_presentation",
  "category_title": "Kategori Adı",
  "category_url": "https://www.trendyol.com/...",
  "top_products": [
    {"name": "Ürün 1", "url": "https://www.trendyol.com/..."}
  ]
}
```

Kesin yapısal alanlar için:

> "Bu ürünün tam fiyatını ve stok durumunu getir: https://www.trendyol.com/..."

Claude, `extract_structured_product_schema` tool'unu çağırır ve sitenin ham JSON-LD ile OpenGraph verisini alır, buradan fiyat, para birimi, stok durumu gibi alanları doğrudan okuyabilir.

### Proje Yapısı

```
ecommerce-insight-mcp/
├── ecommerce_mcp.py     # MCP sunucu ve üç tool tanımı
├── requirements.txt     # Python bağımlılıkları
├── .gitignore
└── README.md
```

### Yol Haritası (öneri)

- [x] Relative URL tamamlamayı hedef domain'e göre dinamikleştirme (`urljoin`)
- [x] Platform-agnostik görsel tespiti (`og:image` + filtrelenmiş `<img>` fallback'i)
- [x] Yapısal veri çıkarma (JSON-LD + OpenGraph) — `extract_structured_product_schema`
- [x] JS-render'lı / bot-kontrollü sayfalar için Playwright yedek mekanizması, soft-block (200 OK engelleme sayfası) tespitiyle birlikte
- [x] `@handle_fetch_errors` decorator'ı ile merkezi hata yönetimi (tekrar eden try/except blokları kaldırıldı)
- [ ] `robots.txt` kontrolü ve istekler arası gecikme
- [ ] Birim testleri
- [ ] `requirements.txt` içinde sürüm pinleme

### Lisans

Belirtilmemiş — bir açık kaynak lisansı (örn. MIT) eklemeniz önerilir.
