import functools
import json
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from fastmcp import FastMCP

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


async def _fetch_html_playwright(url: str) -> str:
    """Yedek yol: gerçek bir headless tarayıcı ile sayfayı çek."""
    try:
        from playwright.async_api import async_playwright
    except ImportError as e:
        raise RuntimeError(
            "Playwright kurulu değil. Yedek mekanizmanın çalışması için "
            "'pip install playwright && playwright install chromium' çalıştırın."
        ) from e

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
            html = await page.content()
            return html
        finally:
            await browser.close()


async def _fetch_soup(url: str) -> BeautifulSoup:
    """Önce httpx dener; statü kodu ya da içerik bot koruması gösteriyorsa
    Playwright'a düşer."""
    try:
        html = await _fetch_html_httpx(url)
        if _looks_blocked(html):
            html = await _fetch_html_playwright(url)
    except httpx.HTTPStatusError as e:
        if e.response.status_code in _BLOCKED_STATUS_CODES:
            html = await _fetch_html_playwright(url)
        else:
            raise

    return BeautifulSoup(html, "html.parser")


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
    soup = await _fetch_soup(url)

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
    return json.dumps(payload, ensure_ascii=False, indent=2)


@mcp.tool()
@handle_fetch_errors
async def extract_structured_product_schema(url: str) -> str:
    """E-ticaret sitelerindeki (Shopify, Trendyol, WooCommerce vb.) gizli JSON-LD
    ve OpenGraph yapısal verilerini çekerek fiyat, stok, marka ve değerlendirme
    puanlarını kesin veriler olarak döndürür.
    """
    soup = await _fetch_soup(url)

    structured_data = []

    # 1. JSON-LD Kodlarını Tara (Google Rich Snippets Verisi)
    json_ld_scripts = soup.find_all("script", type="application/ld+json")
    for script in json_ld_scripts:
        if script.string:
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

    return json.dumps(payload, ensure_ascii=False, indent=2)


@mcp.tool()
@handle_fetch_errors
async def get_category_presentation_data(url: str) -> str:
    """Kategori/Liste sayfasından sunum hazırlamak üzere öne çıkan ürünleri toplar."""
    soup = await _fetch_soup(url)

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
    return json.dumps(payload, ensure_ascii=False, indent=2)


# --- MCP TOOLS SONU ---

# ASGI/HTTP Uygulamasını Global Düzeyde Tanımlama (Render/Uvicorn için)
app = mcp.http_app()

if __name__ == "__main__":
    mcp.run()
