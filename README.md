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
- Product images — up to 6 `<img>` tags whose `src` contains `cdn.dsmcdn.com`, `product`, `images`, or `mnresize`; protocol-relative URLs (`//...`) are normalized to `https:`
- Clean text with `script`, `style`, `header`, `footer`, `nav`, `noscript` tags stripped, lines shorter than 3 characters removed, capped at the first 150 lines

**2. `get_category_presentation_data(url: str)`**
Fetches a category/listing page and returns:
- Page title
- Up to 8 unique products from links whose `href` contains `-p-` or `/product/`, with link text longer than 10 characters (name + full URL)

Both tools return `{"error": "Hata oluştu: ..."}` on failure instead of raising an exception.

###  Known Limitations

This version is **still Trendyol-leaning** in one respect, though the URL handling is now generic:
- The image filter relies on `cdn.dsmcdn.com` (Trendyol's CDN) — it may not find product images on other sites.
- Relative links in `get_category_presentation_data` are resolved with Python's built-in `urllib.parse.urljoin(base_url, href)`, so they correctly resolve against **any** target domain, not just Trendyol.
- Uses a single fixed `User-Agent`; sites with bot protection may reject requests.
- No `robots.txt` check or rate limiting between requests.

Adapt the image filter before relying on it for sites other than Trendyol.

### Requirements

- Python 3.10+
- [Claude Desktop](https://claude.ai/download)

Dependencies (`requirements.txt`):
```
fastmcp
httpx
beautifulsoup4
```

###  Installation

```bash
git clone https://github.com/odrdgi-create/ecommerce-insight-mcp.git
cd ecommerce-insight-mcp
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### ⚙️ Claude Desktop Setup

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

### Project Structure

```
ecommerce-insight-mcp/
├── ecommerce_mcp.py     # MCP server and tool definitions
├── requirements.txt     # Python dependencies
├── .gitignore
└── README.md
```

### Roadmap (suggested)

- [ ] Platform-agnostic image detection (currently keyed to Trendyol's CDN)
- [x] Dynamic relative-URL resolution based on target domain (`urljoin`)
- [ ] `robots.txt` compliance and request throttling
- [ ] Unit tests
- [ ] Pin dependency versions in `requirements.txt`

###  License

Not specified — consider adding an open-source license (e.g. MIT).

---

## Türkçe

Python (`FastMCP`) ile yazılmış bir **Model Context Protocol (MCP)** sunucusu. Claude Desktop'ın e-ticaret ürün ve kategori sayfalarındaki ham HTML'i temizleyip yapılandırılmış JSON verisine dönüştürmesini sağlar; bu sayede Claude sunum slaytları, pazar analizi raporları ve rakip ürün karşılaştırmaları üretebilir.

### Özellikler

**1. `extract_product_presentation_data(url: str)`**
Tek bir ürün sayfasını çeker ve şunları döndürür:
- Sayfa başlığı (`<title>`)
- Ürün görselleri — `cdn.dsmcdn.com`, `product`, `images`, `mnresize` gibi anahtar kelimeleri içeren `<img>` etiketlerinden en fazla 6 tanesi, protokolsüz (`//...`) linkler otomatik `https:` ile tamamlanır
- `script`, `style`, `header`, `footer`, `nav`, `noscript` etiketleri ayıklanmış, 3 karakterden uzun satırlarla sınırlı, ilk 150 satıra kırpılmış temiz metin

**2. `get_category_presentation_data(url: str)`**
Bir kategori/liste sayfasını çeker ve şunları döndürür:
- Sayfa başlığı
- `href` içinde `-p-` veya `/product/` geçen linklerden, metni 10 karakterden uzun olan ve tekrar etmeyen ilk 8 ürün (isim + tam URL)

Her iki tool da hata durumunda `{"error": "Hata oluştu: ..."}` formatında JSON döndürür, exception fırlatmaz.

###  Bilinen Sınırlamalar

Bu sürüm URL yönetimi tarafında artık genel amaçlı, ama görsel filtresi hâlâ **Trendyol'a özel**:
- Görsel filtresi `cdn.dsmcdn.com` (Trendyol CDN'i) anahtar kelimesine dayanır — başka sitelerde ürün görseli bulamayabilir.
- `get_category_presentation_data` içindeki relative linkler artık Python'un yerleşik `urllib.parse.urljoin(base_url, href)` fonksiyonuyla çözümlenir — bu sayede hangi hedef domain olursa olsun **doğru URL** üretilir, sadece Trendyol'a özel değildir.
- Tek bir sabit `User-Agent` kullanılır; bot koruması olan sitelerde istek reddedilebilir.
- `robots.txt` kontrolü veya istekler arası gecikme (rate limiting) yoktur.

Trendyol dışındaki sitelerde görsel filtresine güvenmeden önce onu uyarlamanız gerekir.

###  Gereksinimler

- Python 3.10+
- [Claude Desktop](https://claude.ai/download)

Bağımlılıklar (`requirements.txt`):
```
fastmcp
httpx
beautifulsoup4
```

###  Kurulum

```bash
git clone https://github.com/odrdgi-create/ecommerce-insight-mcp.git
cd ecommerce-insight-mcp
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

###  Claude Desktop Entegrasyonu

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

###  Kullanım Örneği

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

### Proje Yapısı

```
ecommerce-insight-mcp/
├── ecommerce_mcp.py     # MCP sunucu ve iki tool tanımı
├── requirements.txt     # Python bağımlılıkları
├── .gitignore
└── README.md
```

###  Yol Haritası (öneri)

- [ ] Platform-agnostik görsel tespiti (şu an Trendyol CDN'ine bağlı)
- [x] Relative URL tamamlamayı hedef domain'e göre dinamikleştirme (`urljoin`)
- [ ] `robots.txt` kontrolü ve istekler arası gecikme
- [ ] Birim testleri
- [ ] `requirements.txt` içinde sürüm pinleme

###  Lisans

 MIT eklendi.
