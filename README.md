# E-Commerce Insight MCP

**Türkçe** · 🇬🇧 [English](README.en.md)

Ürün ve kategori sayfalarından sunum için veri çeken bir MCP sunucusu. Üç araç sunar:

| Araç | Ne yapar |
|---|---|
| `extract_product_presentation_data` | Ürün sayfasından başlık, görseller ve temizlenmiş metin |
| `extract_structured_product_schema` | JSON-LD + OpenGraph: fiyat, stok, marka, puan |
| `get_category_presentation_data` | Kategori sayfasından öne çıkan ürün listesi |
| `extract_seller_trust_signals` | Satıcı puanı, kargoyu kimin yaptığı, iade durumu + gerekçeli karar özeti |
| `get_presentation_style_guide` | Sabit sunum paleti, tipografi ve grafik kuralları |
| **`analyze_category`** | **Birden çok pazaryerinin kategorisi + tüm ürünler tek çağrıda** — sunum için giriş noktası |
| **`build_slide_visual`** | **Tema-sadık SVG görseller**: yolculuk haritası, halka, waffle, konumlandırma, sıralı bar |

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
curl "https://ecommerce-insight-mcp.onrender.com/api/seller?url=https://ornek.com/urun"
curl "https://ecommerce-insight-mcp.onrender.com/api/analyze?url=https://ornek.com/kategori&limit=8"
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

---

## Yerel test

### En hızlı kontrol

```bash
.venv/bin/python -m uvicorn ecommerce_mcp:app --port 8000
```

Başka bir terminalde:

```bash
curl -s http://localhost:8000/health
```

`impersonate` ve `playwright` ikisi de `true` ise her şey hazır:

```json
{"status":"ok","impersonate":true,"playwright":true,"tools":["category","product","schema"]}
```

### Sunum çıktısı

```bash
curl -s "http://localhost:8000/api/product?url=<ÜRÜN_LİNKİ>" | python -m json.tool
```

`title`, `product_images` (en fazla 6 farklı fotoğraf) ve `extracted_content` döner.

Fiyat, stok, marka ve puan için şema aracını kullanın:

```bash
curl -s "http://localhost:8000/api/schema?url=<ÜRÜN_LİNKİ>" | python -m json.tool
```

Her site şemasını `Product` diye etiketlemiyor — Trendyol örneğin `ProductGroup` kullanıyor ve fiyatları `hasVariant` altına koyuyor.

Satıcı kararı için:

```bash
curl -s "http://localhost:8000/api/seller?url=<ÜRÜN_LİNKİ>" | python -m json.tool
```

### Tarayıcı formu

`http://localhost:8000` adresini açın, linki yapıştırın, butona basın. Aynı veri, terminal yok.

### Araçları doğrudan test etmek

`python test_local.py` üç aracı da örnek linklerle çağırıp ham JSON'u basar.

### Bulut ortamını taklit etmek

Sunucunun Render'da nasıl davrandığını yerelde görmek için tarayıcı yedeğini kapatarak başlatın:

```bash
ENABLE_PLAYWRIGHT=0 .venv/bin/python -m uvicorn ecommerce_mcp:app --port 8000
```

### MCP protokolünü test etmek

`/mcp` tam handshake ister. Elle doğrulamak için:

```bash
# 1. initialize — yanıt başlıklarındaki Mcp-Session-Id'yi not edin
curl -i -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"test","version":"1"}}}'

# 2. araçları listele (1. adımdaki session id'yi yapıştırın)
curl -X POST http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Mcp-Session-Id: <SESSION_ID>" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}'
```

---

## Satıcı güven sinyalleri

`extract_seller_trust_signals` aracı "hangi ürünü ve satıcıyı neden seçmeli" sorusunu gerekçelendirmek için tasarlandı. Ham alanların yanında `decision_summary` döndürür: **strengths** (kararı destekleyen), **concerns** (uyarı) ve **unknowns** (bilinemeyen).

Trendyol örneği:

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
    "strengths": ["Satıcı puanı 8.4/10 — iyi.", "Ürün iade edilebilir.", "629 favori — talep görüyor."],
    "concerns": [
      "Ürün puanı 5 ama yalnızca 1 yoruma dayanıyor — istatistiksel olarak zayıf.",
      "Kargoyu satıcı kendi yapıyor — kargo ve iade süreci satıcının performansına bağlı.",
      "Stok tükeniyor — fiyat ve bulunurluk değişebilir."
    ]
  }
}
```

### Neyin ölçülebildiği, neyin ölçülemediği

Kargo hasar/kayıp oranı, müşteri hizmetleri yanıt kalitesi ve iade taleplerinde ulaşılabilirlik **hiçbir pazaryerinde satıcı bazında yayınlanmıyor.** Bu yüzden çıktıda `unknowns` listesi var — sunumda "veri yok" ile "sorun yok" karışmasın diye.

Bu üçünün yerine geçen iki gösterge var:

- **`seller.score`** — platformun tam olarak bu faktörlerden hesapladığı bileşke puan.
- **`logistics.fulfilled_by`** — kargoyu platform deposu mu yoksa satıcı mı yapıyor. Satıcı kendi gönderiyorsa kargo ve iade süreci tamamen o satıcının performansına bağlıdır; bu, kargo riskinin en iyi yayınlanan vekil göstergesidir.

Ayrıca ürün puanı **her zaman yorum sayısıyla birlikte** değerlendirilir: 1 yoruma dayanan 5/5, 500 yoruma dayanan 4.3'ten zayıf bir sinyaldir.

### Kaynak farkı

`source` alanı verinin nereden geldiğini söyler:

| Değer | Anlamı |
|---|---|
| `trendyol_embedded` | Trendyol'un sayfaya gömdüğü veri — yukarıdaki tüm alanlar dolu gelir |
| `json_ld` | Siteden bağımsız JSON-LD `offers.seller` — genelde yalnızca satıcı adı |

`json_ld` kaynağında alanların boş gelmesi **satıcının zayıf olduğu anlamına gelmez**, site o veriyi yayınlamıyor demektir. Hiç sinyal bulunamazsa `decision_summary.notes` bunu açıkça söyler.

---

## Tool kullanım sınırına takılmamak

Kategori analizi için ürün başına ayrı ayrı `extract_*` çağırmak client'ın tool kullanım sınırını doldurur. 8 ürünlük bir analiz bu şekilde **25 tool çağrısı ve ~66.000 token** demekti; en büyük pay ham JSON-LD dökümündendi (tek üründe 23 KB, bunun 8 KB'ı `hasVariant`).

İki değişiklikle çözüldü:

**1. `analyze_category` — tek çağrı.** Kategoriyi ve içindeki ürünleri eşzamanlı çeker, yalnızca sunuma giren alanları döndürür.

```bash
curl -s "http://localhost:8000/api/analyze?url=<KATEGORİ_LİNKİ>&limit=8" | python -m json.tool
```

**Birden çok pazaryeri tek çağrıda.** `url` virgülle ayrılmış birden çok adres alır; her ürün hangi pazaryerinden geldiğiyle döner:

```bash
curl -s -G "http://localhost:8000/api/analyze" \
  --data-urlencode "url=https://www.trendyol.com/<kategori>,https://www.hepsiburada.com/ara?q=<terim>,https://www.amazon.com.tr/s?k=<terim>" \
  --data-urlencode "limit=4" | python -m json.tool
```

Ölçüldü: üç pazaryeri, 12 ürün, **7.3 saniye, tek çağrı**. Bir kaynak okunamazsa `sources` içinde hatasıyla görünür ve diğerleri devam eder; hiçbiri okunamazsa araç hata döndürür.

**2. Ham şema budandı.** `extract_structured_product_schema` artık `key_facts` (ad, marka, fiyat, puan, yorum sayısı, stok) döndürüyor; ham şemadan `hasVariant`, `isRelatedTo`, `additionalProperty` gibi alanlar çıkarılıyor.

Ölçülen fark:

| | Önce | Sonra |
|---|---|---|
| Şema aracı (tek ürün) | 23.474 karakter (~6.700 token) | 4.983 karakter (~1.423 token) |
| 8 ürünlük kategori analizi | 25 çağrı, ~66.000 token | **1 çağrı, ~1.261 token** |

`analyze_category` çıktısındaki `summary.average_rating` yalnızca **yorumu olan** ürünlerden hesaplanır; kaç ürüne dayandığı `rated_product_count` alanında verilir. Yorum almamış ürünün `0` puanı ortalamaya katılmaz.

---

## Slayt görselleri

`build_slide_visual` sunum görsellerini **tema içinde** üretir: renk ve yazı tipi seçimi çağırana bırakılmaz, hepsi sabit paletten gelir. Dönen SVG kendi kendine yeter (harici font/asset yok) ve hem HTML sunumlara hem PowerPoint'e gömülebilir.

| Tip | Ne için |
|---|---|
| `journey_map` | Müşteri yolculuğu haritası — aşamalar, her aşamada ölçü ve not |
| `donut` | Tek ölçülü halka göstergeleri — çok dilimli pastanın modern karşılığı |
| `quadrant` | Fiyat–puan konumlandırma; daire büyüklüğü yorum sayısı |
| `waffle` | 100 kareli oran ızgarası — pastanın okunabilir alternatifi |
| `ranked_bars` | Büyükten küçüğe sıralı yatay bar |

```bash
curl -s -G "http://localhost:8000/api/visual" \
  --data-urlencode "kind=donut" \
  --data-urlencode 'data={"rings":[{"label":"Ortalama puan","value":4.2,"max":5,"display":"4.2","caption":"3 üründen"}]}' \
  --data-urlencode "title=Kategori Sağlık Göstergeleri" > gorsel.svg
```

### Pasta grafik kuralı — bilinçli revizyon

Tasarım sistemi önce **tüm pasta ve halka grafikleri** yasaklıyordu. Bu kural şöyle inceltildi:

- **Yasak kalan:** çok dilimli pasta (`multi_slice_pie`) ve çok serili halka. Okuyucu dilim açılarını gözle kıyaslayamaz — asıl sorun buydu.
- **Serbest olan:** tek ölçülü halka (`donut`). Tek bir oranı gösterir, kıyaslama sorunu doğurmaz; modern sunum araçlarının KPI göstergesi budur.
- **Oran dağılımı için:** `waffle`. Okuyucu kare sayar, açı tahmin etmez.

### Çarpık fiyat verisi

`quadrant` görselinde fiyat ekseni için `"x_scale": "log"` verin. Kategori fiyatları tipik olarak çarpık dağılır (1.290 TL ile 44.500 TL bir arada); doğrusal eksende noktalar sola yığılır, logaritmik eksen segmentleri ayırır. Eksen etiketine "(log ölçek)" notu otomatik eklenir.

---

## Sonuç bölümü zorunludur

Sunum, **"Yapay Zekâ Özeti ve Sonuç"** slaytıyla biter. Veriyi gösterip yorumsuz bırakmak, çıkarımı okuyucuya bırakmak demektir.

`analyze_category` çıktısındaki **`findings`** bu bölümün ham maddesidir — veriden doğrudan türetilmiş, elle doğrulanabilir gözlemler:

```
* 12 üründen 7 tanesinin hiç yorumu yok; kategori ortalaması yalnızca
  yorumu olan ürünlerden hesaplandı.
* Fiyat aralığı 1.290 TL – 68.500 TL; en pahalı ürün en ucuzun 53 katı.
  Kategori tek bir segment değil.
* 'Rosem Ahsap' listedeki 4 üründe satıcı konumunda — satıcı yoğunlaşması var.
* 4 üründe kargoyu satıcı kendi yapıyor; teslimat ve iade deneyimi satıcıya bağlı.
```

Sonuç slaytının kuralları (`get_presentation_style_guide` → `conclusion`):

- Koyu zeminde (`#1E293B`), sunumun **son** slaytı.
- Önce 2-3 cümlelik özet paragrafı, ardından 01-04 numaralı 3-4 eyleme dönük öneri.
- Her öneri hangi bulguya dayandığını söyler: *"X olduğu için Y yap."*
- Özet yalnızca `findings` ve sunumda gösterilen sayılardan türetilir — yeni veri uydurulmaz.
- Okunamayan kaynak varsa sonuçta açıkça belirtilir.

---

## Sunum tasarım sistemi

Sunumlar arasında görünüm tutarlılığını sağlamak için palet, tipografi ve grafik kuralları sunucuda sabitlenmiştir. Onaylanan referans sunumdan ölçülerek çıkarıldı.

### Palet

| Rol | Renk |
|---|---|
| Yüzey | `#FFFFFF` · `#F1F5F9` · `#F7F5F2` |
| Çizgi | `#E2E8F0` · `#CBD5E1` |
| Metin | `#1E293B` · `#334155` · `#6B7280` · `#94A3B8` |
| Koyu zemin | `#1E293B` · `#24334A` |
| **Vurgu seti** | **`#D97706`** amber · **`#0F766E`** teal · **`#DC5F4E`** terracotta · **`#15803D`** yeşil |

Kategorik ayrım gereken yerde vurgu seti **sırayla** kullanılır; beşinci renk eklenmez. Mavi ton yoktur — lacivert yalnızca koyu slayt zemini ve metin rengidir. Kapak ve bölüm ayracı koyu, içerik slaytları açık zemindedir.

### Yerleşim — metin çakışmasını önleme

Alt başlık, başlığa **sabit dikey ofsetle değil**, başlık kutusunun alt kenarına göre konumlandırılır. Başlık kutusu için her zaman iki satırlık yükseklik ayrılır. Başlık 45 karakteri aşarsa metin kısaltılır — punto küçültülmez. Bu kural, başlığın iki satıra taşıp alt başlığın üstüne binmesini önlemek için eklendi.

### Tipografi

Başlık **Georgia**, gövde **Calibri**. Başlık 28pt · bölüm 16pt · alt başlık 13pt · gövde 11pt · açıklama 9pt. Gövde 11pt'nin altına düşürülmez — sığmıyorsa içerik azaltılır, punto değil.

### Grafikler

İzin verilen: **bar, yatay bar, tablo, KPI kutusu.** Yasak: **pasta, halka, 3D, radar, alan.** Oran göstermek için yatay bar kullanılır — gözle kıyaslaması pastadan kolaydır. Seri rengi tek: `#D97706` ya da `#0F766E`; ızgara `#E2E8F0`.

### Yoğunluk

Slayt başına en fazla 11 şekil, sunum başına en fazla 4 daire/halka biçimi, dekoratif görsel yok. Görsel yalnızca ürün fotoğrafı olarak, veriyi gösterdiği yerde kullanılır.

### Nasıl uygulanır

Üç yoldan da aynı veri gelir:

```bash
curl -s http://localhost:8000/api/style | python -m json.tool
```

- **Araç:** `get_presentation_style_guide` — model veriyi çekerken stili de okuyabilsin diye.
- **Kaynak:** `style://presentation`
- **Prompt:** `sunum_hazirla(url)` — veri çekme + stile uyma talimatını tek adımda verir.

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
