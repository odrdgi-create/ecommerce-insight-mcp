import functools
import ipaddress
import json
import os
import socket
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response

# Sunucu Tanımlaması
mcp = FastMCP("E-Commerce HTML Summarizer")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

_CLIENT_LIMITS = {"follow_redirects": True, "max_redirects": 5, "timeout": 12.0}

# Bot korumasının tipik olarak döndürdüğü statü kodları
_BLOCKED_STATUS_CODES = {403, 429, 503}

# Soft-block tespit kelimeleri
_SOFT_BLOCK_PATTERNS = [
    "güvenlik kontrolü",
    "güvenlik doğrulaması",
    "erişim engellendi",
    "access denied",
    "captcha",
    "doğrulama gerekiyor",
    "verify you are human",
    "unusual traffic",
    "just a moment",
    "attention required",
    "robot değilsiniz",
    "checking your browser",
]

# Playwright yedeği. Render gibi tarayıcı binary'si olmayan / RAM'i dar olan
# ortamlarda ENABLE_PLAYWRIGHT=0 ile kapatılır; yerelde varsayılan olarak açıktır.
ENABLE_PLAYWRIGHT = os.getenv("ENABLE_PLAYWRIGHT", "1").lower() not in {"0", "false", "no"}

# Playwright kapalıyken bot koruması sezilirse kullanıcıya döndürülen uyarı.
DEGRADED_WARNING = (
    "Bot koruması sezildi; bu sunucuda tarayıcı yedeği kapalı olduğu için "
    "veriler eksik olabilir. Tam sonuç için yerel kurulumu kullanın "
    "(bkz. README: yerel stdio kurulumu)."
)


def playwright_available() -> bool:
    """Playwright'ın hem açık hem de import edilebilir olup olmadığını söyler."""
    if not ENABLE_PLAYWRIGHT:
        return False
    try:
        import playwright.async_api  # noqa: F401
    except ImportError:
        return False
    return True


def _assert_url_allowed(url: str) -> None:
    """SSRF freni: sadece public http/https adreslerine izin verir.

    Sunucu herkese açık bir adreste çalıştığı için, iç ağ (192.168.x.x),
    loopback (localhost) ve bulut metadata (169.254.169.254) adreslerine
    istek atılmasını engeller.
    """
    parsed = urlparse(url)

    if parsed.scheme not in {"http", "https"}:
        raise RuntimeError(f"Geçersiz şema: sadece http ve https destekleniyor ('{parsed.scheme}').")

    host = parsed.hostname
    if not host:
        raise RuntimeError("Geçersiz URL: sunucu adı bulunamadı.")

    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise RuntimeError(f"Sunucu adı çözümlenemedi: {host}") from e

    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise RuntimeError(f"Engellendi: '{host}' iç ağ adresine çözümleniyor ({ip}).")


def handle_fetch_errors(func):
    """Üç tool'un da tekrar eden try/except bloğunu tek yerde toplar.

    Herhangi bir tool fonksiyonu httpx/Playwright kaynaklı bir hata
    fırlattığında, burada yakalanıp tutarlı bir JSON hata payload'ına
    çevrilir — her fonksiyonun kendi try/except'ini yazmasına gerek kalmaz.
    """

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except httpx.TimeoutException:
            return json.dumps({"error": "Zaman aşımı: sayfa 12 saniye içinde yanıt vermedi."})
        except httpx.HTTPStatusError as e:
            return json.dumps(
                {"error": f"HTTP hatası: sunucu {e.response.status_code} kodu döndürdü."}
            )
        except httpx.RequestError as e:
            return json.dumps({"error": f"Bağlantı hatası: {str(e)}"})
        except RuntimeError as e:
            return json.dumps({"error": str(e)})
        except Exception as e:
            return json.dumps({"error": f"Beklenmeyen hata: {str(e)}"})

    return wrapper


def _looks_blocked(html: str) -> bool:
    """Statü kodu 200 olsa bile sayfanın bir bot-koruma ara sayfası olup
    olmadığını sezgisel olarak tespit eder."""
    soup = BeautifulSoup(html, "html.parser")

    title_text = soup.title.get_text(strip=True).lower() if soup.title else ""
    if any(pattern in title_text for pattern in _SOFT_BLOCK_PATTERNS):
        return True

    # script/style gövdeleri get_text()'e dahil olur; içlerinde "captcha" gibi
    # kelimeler geçtiği için (recaptcha yükleyen her sitede geçer) temizlenmeden
    # yapılan arama meşru sayfaları bloke sayıyordu.
    for element in soup(["script", "style", "noscript"]):
        element.decompose()

    body_text = soup.get_text(separator=" ", strip=True)
    if any(pattern in body_text.lower() for pattern in _SOFT_BLOCK_PATTERNS):
        return True

    if len(body_text) < 200:
        return True

    return False


async def _fetch_html_httpx(url: str) -> str:
    """Hızlı yol: düz HTTP isteğiyle sayfayı çek."""
    async with httpx.AsyncClient(headers=HEADERS, **_CLIENT_LIMITS) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.text


def impersonate_available() -> bool:
    """curl_cffi (Chrome TLS parmak izi taklidi) kullanılabilir mi."""
    try:
        import curl_cffi  # noqa: F401
    except ImportError:
        return False
    return True


async def _fetch_html_impersonate(url: str) -> str:
    """Birincil yol: Chrome'un TLS/JA3 parmak izini taklit ederek sayfayı çek.

    Cloudflare ve Akamai gibi bot korumaları istemciyi büyük ölçüde TLS
    el sıkışmasından tanır; httpx'in Python'a özgü parmak izi (JA4 t13d1712h1,
    HTTP/1.1) doğrudan ele veriyor. curl_cffi gerçek Chrome parmak izini
    (t13d1516h2, HTTP/2) sunduğu için tarayıcı çalıştırmadan bu kontrolleri geçer.

    Hatalar bilerek httpx sözlüğüne çevriliyor: çağıran taraftaki blok/timeout
    mantığı tek bir istisna ailesiyle çalışsın diye.
    """
    from curl_cffi import requests as cffi
    from curl_cffi.requests.exceptions import RequestException

    request = httpx.Request("GET", url)
    try:
        async with cffi.AsyncSession() as session:
            response = await session.get(
                url,
                impersonate="chrome",
                # UA ve Sec-Ch-Ua'yı curl_cffi'nin kendisi yönetsin; taklit
                # edilen sürümle tutarlı olmaları gerekiyor. Sadece dili ekliyoruz.
                headers={"Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8"},
                timeout=_CLIENT_LIMITS["timeout"],
                allow_redirects=True,
            )
    except RequestException as e:
        raise httpx.RequestError(str(e), request=request) from e

    if response.status_code >= 400:
        raise httpx.HTTPStatusError(
            f"{response.status_code} döndü",
            request=request,
            response=httpx.Response(response.status_code, request=request),
        )
    return response.text


async def _fetch_html_primary(url: str) -> str:
    """Mevcut en iyi HTTP yolunu seçer: varsa Chrome taklidi, yoksa düz httpx."""
    if impersonate_available():
        return await _fetch_html_impersonate(url)
    return await _fetch_html_httpx(url)


async def _fetch_html_playwright(url: str) -> str:
    """Yedek yol: gerçek bir headless tarayıcı ile sayfayı çek."""
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            context = await browser.new_context(
                user_agent=HEADERS["User-Agent"],
                viewport={"width": 1366, "height": 768},
                locale="tr-TR",
            )
            await context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
            page = await context.new_page()
            await page.goto(url, timeout=20_000, wait_until="domcontentloaded")
            # Ürün kartları çoğu e-ticaret sitesinde DOMContentLoaded'dan sonra
            # render ediliyor; ağ sakinleşene kadar kısa bir pay tanı.
            try:
                await page.wait_for_load_state("networkidle", timeout=6_000)
            except Exception:
                pass
            html = await page.content()
            return html
        finally:
            await browser.close()


async def _fetch_soup(url: str) -> tuple[BeautifulSoup, str | None]:
    """Önce Chrome TLS taklidiyle (yoksa düz httpx ile) dener; statü kodu ya da
    içerik bot koruması gösteriyorsa Playwright'a düşer.

    (soup, warning) döndürür. Playwright kapalı/kurulu değilken bot koruması
    sezilirse istek tamamen başarısız olmaz: httpx'ten gelen kısmi içerik ve
    kullanıcıyı yerel kuruluma yönlendiren bir uyarı döner.
    """
    _assert_url_allowed(url)

    warning = None
    try:
        html = await _fetch_html_primary(url)
        if _looks_blocked(html):
            if playwright_available():
                html = await _fetch_html_playwright(url)
            else:
                warning = DEGRADED_WARNING
    except (httpx.HTTPStatusError, httpx.TimeoutException) as e:
        # Timeout da bot korumasının yaygın bir belirtisi; o yüzden statü
        # kodları gibi tarayıcı yedeğini tetikler.
        is_blocked_status = (
            isinstance(e, httpx.HTTPStatusError)
            and e.response.status_code in _BLOCKED_STATUS_CODES
        )
        if not (is_blocked_status or isinstance(e, httpx.TimeoutException)):
            raise
        if not playwright_available():
            # Sayfa hiç alınamadı, kısmi veri döndürmek mümkün değil; en azından
            # çıplak "403" yerine ne yapılacağını söyleyen bir hata dön.
            reason = (
                f"sunucu {e.response.status_code} döndürdü"
                if is_blocked_status
                else "istek zaman aşımına uğradı"
            )
            raise RuntimeError(
                f"Site bu sunucudan gelen isteği engelledi ({reason}). {DEGRADED_WARNING}"
            ) from e
        html = await _fetch_html_playwright(url)

    return BeautifulSoup(html, "html.parser"), warning


def _extract_images(soup: BeautifulSoup, base_url: str, limit: int = 6) -> list[str]:
    images = []

    for meta_prop in ["og:image", "og:image:secure_url", "twitter:image"]:
        tag = soup.find("meta", property=meta_prop) or soup.find("meta", attrs={"name": meta_prop})
        if tag and tag.get("content"):
            src = urljoin(base_url, tag["content"])
            if src not in images:
                images.append(src)

    if len(images) >= limit:
        return images[:limit]

    EXCLUDE_KEYWORDS = ["logo", "icon", "sprite", "placeholder", "avatar", "banner", "loading"]

    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src")
        if not src or src.startswith("data:"):
            continue

        src = urljoin(base_url, src)

        if any(k in src.lower() for k in EXCLUDE_KEYWORDS):
            continue

        width = img.get("width")
        height = img.get("height")
        try:
            if width and int(width) < 100:
                continue
            if height and int(height) < 100:
                continue
        except ValueError:
            pass

        if src not in images:
            images.append(src)

        if len(images) >= limit:
            break

    return images[:limit]


# --- MCP TOOLS ---


@mcp.tool()
@handle_fetch_errors
async def extract_product_presentation_data(url: str) -> str:
    """Tek bir ürün sayfasının linkinden sunum için detaylı ürün bilgilerini ve görselleri çeker."""
    soup, warning = await _fetch_soup(url)

    title = soup.title.get_text(strip=True) if soup.title else "Ürün Detayı"

    images = _extract_images(soup, url)

    for element in soup(["script", "style", "header", "footer", "nav", "noscript"]):
        element.decompose()

    text_lines = [
        line.strip()
        for line in soup.get_text(separator="\n").splitlines()
        if len(line.strip()) > 3
    ]
    clean_text = "\n".join(text_lines[:150])

    payload = {
        "type": "single_product_presentation",
        "url": url,
        "title": title,
        "product_images": images,
        "extracted_content": clean_text,
    }
    if warning:
        payload["warning"] = warning
    return json.dumps(payload, ensure_ascii=False, indent=2)


@mcp.tool()
@handle_fetch_errors
async def extract_structured_product_schema(url: str) -> str:
    """E-ticaret sitelerindeki (Shopify, Trendyol, WooCommerce vb.) gizli JSON-LD
    ve OpenGraph yapısal verilerini çekerek fiyat, stok, marka ve değerlendirme
    puanlarını kesin veriler olarak döndürür.
    """
    soup, warning = await _fetch_soup(url)

    structured_data = []
    skipped_oversized = 0

    # 1. JSON-LD Kodlarını Tara (Google Rich Snippets Verisi)
    json_ld_scripts = soup.find_all("script", type="application/ld+json")
    for script in json_ld_scripts:
        if script.string:
            # Bazı siteler tüm katalogu tek JSON-LD bloğuna gömüyor; token
            # maliyetini patlatmamak için aşırı büyük blokları atla.
            if len(script.string) > 100_000:
                skipped_oversized += 1
                continue
            try:
                data = json.loads(script.string)
                structured_data.append(data)
            except json.JSONDecodeError:
                continue

    # 2. OpenGraph Meta Etiketlerini Tara (Sosyal Medya & E-Ticaret Meta Verisi)
    og_data = {}
    for meta in soup.find_all("meta"):
        prop = meta.get("property", "") or meta.get("name", "")
        if prop.startswith("og:") or prop.startswith("product:"):
            og_data[prop] = meta.get("content", "")

    payload = {
        "url": url,
        "json_ld_schemas": structured_data,
        "opengraph_metadata": og_data,
    }
    if skipped_oversized:
        payload["skipped_oversized_schemas"] = skipped_oversized
    if warning:
        payload["warning"] = warning

    return json.dumps(payload, ensure_ascii=False, indent=2)


@mcp.tool()
@handle_fetch_errors
async def get_category_presentation_data(url: str) -> str:
    """Kategori/Liste sayfasından sunum hazırlamak üzere öne çıkan ürünleri toplar."""
    soup, warning = await _fetch_soup(url)

    title = soup.title.get_text(strip=True) if soup.title else "Kategori Analizi"

    products = []
    links = soup.find_all("a", href=True)

    for link in links:
        href = link["href"].strip()

        full_url = urljoin(url, href)
        text = link.get_text(strip=True)

        is_product_link = any(
            pattern in href for pattern in ["-p-", "/product/", "/urun/", "-pm-", "/p-"]
        )

        if is_product_link and text and len(text) > 10:
            if not any(p["url"] == full_url for p in products):
                products.append({"name": text[:90], "url": full_url})

        if len(products) >= 8:
            break

    payload = {
        "type": "category_showcase_presentation",
        "category_title": title,
        "category_url": url,
        "top_products": products,
    }
    if warning:
        payload["warning"] = warning
    return json.dumps(payload, ensure_ascii=False, indent=2)


# --- MCP TOOLS SONU ---


# --- ERİŞİM KATMANI ---
# MCP protokolü (/mcp) curl ile doğrudan çağrılamaz: çift Accept başlığı,
# initialize/initialized handshake'i ve Mcp-Session-Id ister, yanıtı da SSE
# frame'i olarak verir. Aşağıdaki yollar aynı araçları düz HTTP ile açar.
# /mcp yoluna ve paylaşılan config JSON'ına dokunulmaz.

_TOOL_ROUTES = {
    "product": extract_product_presentation_data,
    "schema": extract_structured_product_schema,
    "category": get_category_presentation_data,
}


async def _run_tool_route(request: Request, tool_name: str) -> Response:
    """Ortak REST handler: ?url= parametresini alır, ilgili aracı çağırır."""
    url = request.query_params.get("url")
    if not url:
        return JSONResponse(
            {"error": "'url' parametresi zorunlu. Örnek: /api/product?url=https://..."},
            status_code=400,
        )

    raw = await _TOOL_ROUTES[tool_name](url)
    payload = json.loads(raw)
    status = 400 if "error" in payload else 200
    return JSONResponse(payload, status_code=status)


@mcp.custom_route("/api/product", methods=["GET"])
async def api_product(request: Request) -> Response:
    return await _run_tool_route(request, "product")


@mcp.custom_route("/api/schema", methods=["GET"])
async def api_schema(request: Request) -> Response:
    return await _run_tool_route(request, "schema")


@mcp.custom_route("/api/category", methods=["GET"])
async def api_category(request: Request) -> Response:
    return await _run_tool_route(request, "category")


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> Response:
    """Render health check'i ve uyuyan free-tier instance'ı uyandırmak için."""
    return JSONResponse(
        {
            "status": "ok",
            "server": "E-Commerce HTML Summarizer",
            "impersonate": impersonate_available(),
            "playwright": playwright_available(),
            "tools": sorted(_TOOL_ROUTES),
        }
    )


@mcp.custom_route("/", methods=["GET"])
async def index(request: Request) -> Response:
    """Terminal kullanmayanlar için tek sayfalık form."""
    return HTMLResponse(_INDEX_HTML)


_INDEX_HTML = """<!doctype html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>E-Commerce Insight</title>
<style>
  :root { color-scheme: light dark; --bg:#fbfaf9; --fg:#1a1a19; --mut:#6b6a67;
          --line:#e3e1dd; --card:#fff; --accent:#bd5d3a; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#1a1a19; --fg:#f0eee6; --mut:#9a9892; --line:#33322e;
            --card:#222220; --accent:#d97757; }
  }
  * { box-sizing: border-box; }
  body { margin:0; padding:2.5rem 1.25rem; background:var(--bg); color:var(--fg);
         font:16px/1.6 ui-sans-serif,-apple-system,"Segoe UI",system-ui,sans-serif; }
  main { max-width: 44rem; margin: 0 auto; }
  h1 { font-size:1.6rem; margin:0 0 .25rem; letter-spacing:-.02em; }
  p.sub { color:var(--mut); margin:0 0 2rem; }
  .card { background:var(--card); border:1px solid var(--line);
          border-radius:12px; padding:1.25rem; margin-bottom:1.25rem; }
  input { width:100%; padding:.7rem .85rem; font-size:1rem; border-radius:8px;
          border:1px solid var(--line); background:var(--bg); color:var(--fg); }
  input:focus { outline:2px solid var(--accent); outline-offset:1px; }
  .row { display:flex; gap:.6rem; flex-wrap:wrap; margin-top:.9rem; }
  button { flex:1 1 9rem; padding:.65rem 1rem; font-size:.95rem; font-weight:500;
           border-radius:8px; border:1px solid var(--line); background:var(--bg);
           color:var(--fg); cursor:pointer; }
  button:hover:not(:disabled) { border-color:var(--accent); color:var(--accent); }
  button:disabled { opacity:.5; cursor:default; }
  pre { background:var(--bg); border:1px solid var(--line); border-radius:8px;
        padding:1rem; overflow-x:auto; font-size:.82rem; margin:0;
        white-space:pre-wrap; word-break:break-word; max-height:26rem; overflow-y:auto; }
  h2 { font-size:.8rem; text-transform:uppercase; letter-spacing:.06em;
       color:var(--mut); margin:0 0 .7rem; font-weight:600; }
  code { font-size:.85rem; }
  a { color:var(--accent); }
</style>
</head>
<body>
<main>
  <h1>E-Commerce Insight</h1>
  <p class="sub">Bir ürün ya da kategori linki yapıştırın, veriyi çekelim.</p>

  <div class="card">
    <input id="url" type="url" placeholder="https://ornek.com/urun-linki" autocomplete="off">
    <div class="row">
      <button data-tool="product">Ürün Detayı</button>
      <button data-tool="schema">Yapısal Veri</button>
      <button data-tool="category">Kategori</button>
    </div>
  </div>

  <div class="card">
    <h2>Sonuç</h2>
    <pre id="out">Henüz bir sorgu çalıştırılmadı.</pre>
  </div>

  <div class="card">
    <h2>MCP client ile bağlanmak için</h2>
    <pre id="cfg"></pre>
  </div>

  <div class="card">
    <h2>Terminalden</h2>
    <pre id="curl"></pre>
  </div>
</main>
<script>
  const origin = location.origin;
  document.getElementById('cfg').textContent = JSON.stringify(
    { mcpServers: { "ecommerce-insight": { url: origin + "/mcp" } } }, null, 2);
  document.getElementById('curl').textContent =
    'curl "' + origin + '/api/schema?url=https://ornek.com/urun"';

  const out = document.getElementById('out');
  const buttons = [...document.querySelectorAll('button[data-tool]')];

  async function run(tool) {
    const url = document.getElementById('url').value.trim();
    if (!url) { out.textContent = 'Önce bir link girin.'; return; }
    buttons.forEach(b => b.disabled = true);
    out.textContent = 'Çekiliyor... (sunucu uykudaysa ilk istek 1 dakika sürebilir)';
    try {
      const res = await fetch('/api/' + tool + '?url=' + encodeURIComponent(url));
      out.textContent = JSON.stringify(await res.json(), null, 2);
    } catch (e) {
      out.textContent = 'İstek başarısız: ' + e.message;
    } finally {
      buttons.forEach(b => b.disabled = false);
    }
  }

  buttons.forEach(b => b.addEventListener('click', () => run(b.dataset.tool)));
  document.getElementById('url').addEventListener('keydown', e => {
    if (e.key === 'Enter') run('schema');
  });
</script>
</body>
</html>
"""


# ASGI/HTTP Uygulamasını Global Düzeyde Tanımlama (Render/Uvicorn için)
app = mcp.http_app()

if __name__ == "__main__":
    mcp.run()