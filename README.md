# E-Commerce Insight MCP

Ürün ve kategori sayfalarından sunum için veri çeken bir MCP sunucusu. Üç araç sunar:

| Araç | Ne yapar |
|---|---|
| `extract_product_presentation_data` | Ürün sayfasından başlık, görseller ve temizlenmiş metin |
| `extract_structured_product_schema` | JSON-LD + OpenGraph: fiyat, stok, marka, puan |
| `get_category_presentation_data` | Kategori sayfasından öne çıkan ürün listesi |

Canlı sunucu: **https://ecommerce-insight-mcp.onrender.com**

---

## Kullanım yolları

Üç ayrı yol var. MCP client'ınız yoksa ya da terminal kullanmıyorsanız 1. yol yeterli.

### 1. Tarayıcıdan (kurulum gerekmez)

**https://ecommerce-insight-mcp.onrender.com** adresini açın, linki yapıştırın, butona basın.

> Sunucu ücretsiz katmanda çalıştığı için uykudan uyanması gerekebilir — **ilk istek 1 dakikaya kadar sürebilir**, sonrakiler hızlıdır.

### 2. curl / Postman / n8n / Google Sheets

Düz `GET` endpoint'leri, JSON döner. Handshake, session, SSE yok:

```bash
curl "https://ecommerce-insight-mcp.onrender.com/api/product?url=https://ornek.com/urun"
curl "https://ecommerce-insight-mcp.onrender.com/api/schema?url=https://ornek.com/urun"
curl "https://ecommerce-insight-mcp.onrender.com/api/category?url=https://ornek.com/kategori"
```

Sunucunun ayakta olup olmadığını kontrol etmek için:

```bash
curl https://ecommerce-insight-mcp.onrender.com/health
```

### 3. MCP client ile

```json
{
  "mcpServers": {
    "ecommerce-insight": {
      "url": "https://ecommerce-insight-mcp.onrender.com/mcp"
    }
  }
}
```

Client'ınız uzak sunucu URL'sini desteklemiyorsa (yalnızca stdio destekleyen eski sürümler), araya köprü koyun:

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

**Not:** `/mcp` yolu doğrudan curl ile çağrılamaz. MCP Streamable HTTP protokolü `Accept: application/json, text/event-stream` başlığını, `initialize` → `notifications/initialized` → `tools/call` sırasını ve `Mcp-Session-Id` başlığını ister; yanıtı da SSE frame'i olarak verir. Terminalden kullanmak için 2. yolu tercih edin.

---

## Yerel kurulum

Yerel kurulum, Playwright yedeğini de açar. Bot korumalı siteler için genellikle gerekmez (aşağıdaki TLS taklidi bunu zaten hallediyor), ama JavaScript ile render edilen sayfalarda işe yarar.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Bot korumalı siteler için:
pip install playwright==1.62.0
playwright install chromium
```

MCP client config'i (stdio):

```json
{
  "mcpServers": {
    "ecommerce-insight": {
      "command": "/tam/yol/.venv/bin/python",
      "args": ["/tam/yol/ecommerce_mcp.py"]
    }
  }
}
```

HTTP sunucusu olarak çalıştırmak için:

```bash
.venv/bin/python -m uvicorn ecommerce_mcp:app --port 8000
```

Ardından `http://localhost:8000` adresini açın.

Araçları doğrudan test etmek için: `python test_local.py`

---

## Yapılandırma

| Ortam değişkeni | Varsayılan | Açıklama |
|---|---|---|
| `ENABLE_PLAYWRIGHT` | `1` | `0` yapıldığında tarayıcı yedeği kapanır. Render'da kurulu olmadığı için kod bunu kendiliğinden tespit eder; ayarlamak zorunda değilsiniz. |

Sunucu yalnızca public `http`/`https` adreslerine istek atar; loopback, iç ağ ve bulut metadata adresleri (`169.254.169.254`) reddedilir.

---

## Bot koruması nasıl aşılıyor

Cloudflare (Trendyol) ve Akamai (Hepsiburada) gibi korumalar istemciyi büyük ölçüde **TLS el sıkışmasından** tanır. Python'un `httpx`'i kendine özgü bir parmak izi bırakır (JA4 `t13d1712h1`, HTTP/1.1) ve bu doğrudan ele verir — datacenter IP'siyle birleşince 403 gelir.

Sunucu bu yüzden birincil çekici olarak **`curl_cffi`** kullanır: gerçek Chrome'un TLS parmak izini (JA4 `t13d1516h2`, HTTP/2) sunar. Ölçülen fark, aynı IP ve aynı User-Agent ile:

| Site | `httpx` | `curl_cffi` |
|---|---|---|
| Hepsiburada | 403 (1.7 KB blok sayfası) | 200 (610 KB, JSON-LD dahil) |

Tarayıcı çalıştırmadığı için Playwright'ın aksine ek RAM ya da Chromium binary'si istemez; ücretsiz katmanda sorunsuz çalışır.

Çekim sırası: **`curl_cffi` → `httpx` (curl_cffi yoksa) → Playwright (yalnızca yerel, JS render için)**.

### Aşılamayan durum: IP bazlı içerik ayrımı

Trendyol, bulut sunucusunun IP'sine **içerik olarak farklı bir sayfa** servis ediyor. Ölçüm — aynı URL (`https://www.trendyol.com/`), aynı anda:

| İstek nereden | Sayfa başlığı | Bulunan ürün linki |
|---|---|---|
| Render (bulut) | "Online Alışveriş Sitesi, Türkiye'nin Trend Yolu \| Trendyol" | 0 |
| Yerel makine | "En Trend Ürünler Türkiye'nin Online Alışveriş Sitesi Trendyol'da" | 8 |

Bu ne TLS parmak izi, ne çerez, ne de JavaScript sorunu — sunucu daha isteği karşılarken IP'ye bakıp karar veriyor. Dolayısıyla TLS taklidi, oturum çerezi ya da Playwright bunu **çözmez**; hepsi aynı IP'den çıkar.

**Trendyol için çözüm: sunucuyu yerelde çalıştırın.** Bulut sunucusu Hepsiburada, Amazon ve korumasız mağazalarda tam veri vermeye devam eder. Trendyol istendiğinde hata değil, kısmi veri + açıklayıcı `warning` alanı döner.
