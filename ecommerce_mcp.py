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

# Sayfa alınabildi ama içerik eksik geldiğinde döndürülen uyarı.
# Trendyol gibi bazı siteler bulut sunucularının IP'sine, tarayıcıdan görülenden
# farklı ve içeriksiz bir sayfa servis ediyor. Bu ne TLS parmak izi ne de
# JavaScript sorunu olduğu için sunucu tarafında aşılamıyor.
DEGRADED_WARNING = (
    "Bu site, bulut sunucusunun IP adresine eksik içerik gösteriyor "
    "(Trendyol bunu yapıyor). Sonuçlar eksik olabilir. Tam veri için sunucuyu "
    "kendi bilgisayarınızda çalıştırın — bkz. README, 'Yerel kurulum'."
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
                f"Site bu sunucudan gelen isteği engelledi ({reason}). "
                "Tam veri için sunucuyu kendi bilgisayarınızda çalıştırın — "
                "bkz. README, 'Yerel kurulum'."
            ) from e
        html = await _fetch_html_playwright(url)

    return BeautifulSoup(html, "html.parser"), warning


def _iter_schema_images(node, depth: int = 0):
    """JSON-LD ağacındaki 'image' alanlarından görsel adreslerini toplar.

    Şemalar bu alanı üç ayrı biçimde yazıyor: düz metin, metin listesi ya da
    {"@type": "ImageObject", "contentUrl": ...} nesnesi. Ürün varyantları
    (hasVariant) iç içe geçtiği için ağaç sınırlı derinlikte geziliyor.
    """
    if depth > 4:
        return
    if isinstance(node, str):
        if node.startswith(("http://", "https://", "//")):
            yield node
    elif isinstance(node, list):
        for item in node:
            yield from _iter_schema_images(item, depth + 1)
    elif isinstance(node, dict):
        for key in ("image", "contentUrl", "primaryImageOfPage"):
            if key in node:
                yield from _iter_schema_images(node[key], depth + 1)
        for key in ("hasVariant", "isRelatedTo", "@graph"):
            if key in node:
                yield from _iter_schema_images(node[key], depth + 1)


def _extract_images(soup: BeautifulSoup, base_url: str, limit: int = 6) -> list[str]:
    images = []

    for meta_prop in ["og:image", "og:image:secure_url", "twitter:image"]:
        tag = soup.find("meta", property=meta_prop) or soup.find("meta", attrs={"name": meta_prop})
        if tag and tag.get("content"):
            src = urljoin(base_url, tag["content"])
            if src not in images:
                images.append(src)

    # JSON-LD, ürün fotoğraflarını taşıyan en güvenilir kaynak: <img> etiketlerinin
    # aksine sayfa çerçevesine ait görsel içermez ve JS ile sonradan yüklenen
    # kareler de burada hazır durur.
    for script in soup.find_all("script", type="application/ld+json"):
        if not script.string or len(script.string) > 100_000:
            continue
        try:
            data = json.loads(script.string)
        except json.JSONDecodeError:
            continue
        for src in _iter_schema_images(data):
            src = urljoin(base_url, src)
            if src not in images:
                images.append(src)

    if len(images) >= limit:
        return images[:limit]

    EXCLUDE_KEYWORDS = [
        "logo", "icon", "sprite", "placeholder", "avatar", "banner", "loading",
        # Sayfa çerçevesine ait görseller: güven damgaları, footer/header afişleri.
        "footer", "header", "stamp", "badge",
    ]

    def identity(src: str) -> str:
        """Aynı fotoğrafın farklı boyutlarını tek sayar.

        CDN'ler aynı görseli ölçü ön ekleriyle sunuyor (ör. Trendyol'da
        .../mnresize/620/920/<yol> ile .../<yol> aynı fotoğraf). Yolun son iki
        parçası (klasör + dosya adı) görselin gerçek kimliğini verir, bu yüzden
        sunumda aynı kare üç kez görünmez.
        """
        segments = [seg for seg in urlparse(src).path.split("/") if seg]
        return "/".join(segments[-2:])

    seen = {identity(src) for src in images}

    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src")
        if not src or src.startswith("data:"):
            continue

        src = urljoin(base_url, src)

        # Ürün fotoğrafı hiçbir zaman SVG olmaz; SVG'ler arayüz ikonudur
        # (arama, sepet, ok vb.) ve sunum çıktısını kirletiyorlar.
        if src.lower().split("?")[0].endswith(".svg"):
            continue

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

        key = identity(src)
        if key not in seen:
            seen.add(key)
            images.append(src)

        if len(images) >= limit:
            break

    return images[:limit]


# --- SATICI GÜVEN SİNYALLERİ ---

# Trendyol'un ürün sayfasına gömdüğü durum nesnesi. Satıcı puanı, resmi unvan,
# kargo tipi ve iade edilebilirlik gibi karar verdiren alanlar burada duruyor;
# JSON-LD bunların hiçbirini taşımıyor.
_TRENDYOL_STATE_MARKER = '__envoy__SHARED_PROPS'

# Kargoyu kimin yaptığı, kargo/iade riskinin en iyi vekil göstergesi:
# pazaryeri satıcısı kendi gönderiyorsa risk, platform deposundan çıkana göre yüksek.
_FULFILMENT_LABELS = {
    "mp": "Satıcı kendi gönderiyor (pazaryeri)",
    "ty": "Trendyol deposundan gönderiliyor",
    "tyf": "Trendyol deposundan gönderiliyor",
    "fbt": "Trendyol deposundan gönderiliyor",
}


def _find_trendyol_state(soup: BeautifulSoup) -> dict | None:
    """Sayfaya gömülü Trendyol durum nesnesini çıkarır; yoksa None."""
    for script in soup.find_all("script"):
        text = script.string
        if not text or _TRENDYOL_STATE_MARKER not in text:
            continue
        start = text.find("{", text.find(_TRENDYOL_STATE_MARKER))
        if start == -1:
            continue
        try:
            # Süslü parantezleri elle saymak yerine JSON çözücünün kendi
            # tarayıcısını kullan: bloktan sonra JS devam etse bile doğru biter.
            data, _ = json.JSONDecoder().raw_decode(text[start:])
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and "product" in data:
            return data
    return None


def _signals_from_trendyol(state: dict) -> dict:
    """Gömülü Trendyol verisini ortak sinyal biçimine çevirir."""
    product = state.get("product") or {}
    listing = product.get("merchantListing") or {}
    merchant = listing.get("merchant") or {}
    variant = listing.get("winnerVariant") or {}
    rating = product.get("ratingScore") or {}
    score = merchant.get("sellerScore") or {}
    price = variant.get("price") or {}

    fulfilment = variant.get("fulfilmentType")

    return {
        "source": "trendyol_embedded",
        "product": {
            "name": product.get("name"),
            "brand": (product.get("brand") or {}).get("name"),
            "rating": rating.get("averageRating"),
            "review_count": rating.get("commentCount"),
            "favorite_count": product.get("favoriteCount"),
            "in_stock": product.get("inStock"),
            "running_out": variant.get("isRunningOut"),
            "price": (price.get("discountedPrice") or {}).get("text"),
        },
        "seller": {
            "name": merchant.get("name"),
            "official_name": merchant.get("officialName"),
            "city": merchant.get("cityName"),
            "score": score.get("value"),
            "score_scale": 10 if score.get("value") is not None else None,
            "tax_number": merchant.get("taxNumber"),
        },
        "logistics": {
            "fulfilled_by": _FULFILMENT_LABELS.get(
                str(fulfilment).lower(), fulfilment
            ),
            "free_shipping": variant.get("freeCargo"),
            "long_term_delivery": listing.get("isLongTermDelivery"),
            "refundable": product.get("isRefundable"),
            "max_installment": product.get("maxInstallment"),
        },
    }


def _signals_from_json_ld(soup: BeautifulSoup) -> dict:
    """Siteden bağımsız temel: JSON-LD'deki offers.seller ve aggregateRating.

    Çoğu site burada yalnızca satıcı adını yayınlar; Trendyol'daki zenginlikte
    veri beklenmemeli.
    """
    signals = {
        "source": "json_ld",
        "product": {},
        "seller": {},
        "logistics": {},
    }

    def walk(node, depth=0):
        if depth > 4 or not isinstance(node, (dict, list)):
            return
        if isinstance(node, list):
            for item in node:
                walk(item, depth + 1)
            return

        if not signals["product"].get("name") and node.get("name"):
            if str(node.get("@type", "")).startswith("Product"):
                signals["product"]["name"] = node["name"]
                brand = node.get("brand")
                signals["product"]["brand"] = (
                    brand.get("name") if isinstance(brand, dict) else brand
                )

        agg = node.get("aggregateRating")
        if isinstance(agg, dict) and not signals["product"].get("rating"):
            signals["product"]["rating"] = agg.get("ratingValue")
            signals["product"]["review_count"] = agg.get("reviewCount") or agg.get(
                "ratingCount"
            )

        offers = node.get("offers")
        if isinstance(offers, (dict, list)):
            for offer in offers if isinstance(offers, list) else [offers]:
                if not isinstance(offer, dict):
                    continue
                seller = offer.get("seller")
                if isinstance(seller, dict) and not signals["seller"].get("name"):
                    signals["seller"]["name"] = seller.get("name")
                    seller_rating = seller.get("aggregateRating")
                    if isinstance(seller_rating, dict):
                        signals["seller"]["score"] = seller_rating.get("ratingValue")
                        signals["seller"]["score_scale"] = seller_rating.get(
                            "bestRating"
                        )
                elif isinstance(seller, str) and not signals["seller"].get("name"):
                    signals["seller"]["name"] = seller
                if not signals["product"].get("price"):
                    signals["product"]["price"] = offer.get("price")
                if offer.get("availability") and "in_stock" not in signals["product"]:
                    signals["product"]["in_stock"] = "InStock" in str(
                        offer["availability"]
                    )

        for key in ("hasVariant", "@graph", "isRelatedTo", "mainEntity"):
            if key in node:
                walk(node[key], depth + 1)

    for script in soup.find_all("script", type="application/ld+json"):
        if not script.string or len(script.string) > 100_000:
            continue
        try:
            walk(json.loads(script.string))
        except json.JSONDecodeError:
            continue

    return signals


def _build_decision_summary(signals: dict) -> dict:
    """Sinyalleri sunumda kullanılabilir gerekçelere çevirir.

    Amaç tek bir 'iyi/kötü' etiketi değil: hangi sinyalin kararı desteklediğini,
    hangisinin uyarı olduğunu ve neyin bilinemediğini ayrı ayrı göstermek.
    """
    product = signals.get("product") or {}
    seller = signals.get("seller") or {}
    logistics = signals.get("logistics") or {}

    strengths, concerns = [], []

    score = seller.get("score")
    if isinstance(score, (int, float)):
        scale = seller.get("score_scale") or 10
        normalized = score / scale * 10
        if normalized >= 9:
            strengths.append(f"Satıcı puanı {score}/{scale} — çok yüksek.")
        elif normalized >= 8:
            strengths.append(f"Satıcı puanı {score}/{scale} — iyi.")
        elif normalized >= 7:
            concerns.append(f"Satıcı puanı {score}/{scale} — orta; alternatif satıcıya bakın.")
        else:
            concerns.append(f"Satıcı puanı {score}/{scale} — düşük.")

    rating, reviews = product.get("rating"), product.get("review_count")
    if isinstance(rating, (int, float)):
        if isinstance(reviews, int) and reviews < 10:
            concerns.append(
                f"Ürün puanı {rating} ama yalnızca {reviews} yoruma dayanıyor — "
                "istatistiksel olarak zayıf."
            )
        elif isinstance(reviews, int) and reviews >= 100 and rating >= 4.5:
            strengths.append(f"Ürün puanı {rating} ve {reviews} yoruma dayanıyor — güçlü sinyal.")
        else:
            strengths.append(f"Ürün puanı {rating} ({reviews} yorum).")

    fulfilled = logistics.get("fulfilled_by")
    if isinstance(fulfilled, str):
        if "deposundan" in fulfilled:
            strengths.append("Kargo platform deposundan çıkıyor — gecikme ve iade riski düşük.")
        elif "pazaryeri" in fulfilled:
            concerns.append(
                "Kargoyu satıcı kendi yapıyor — kargo ve iade süreci satıcının "
                "performansına bağlı."
            )

    if logistics.get("refundable") is True:
        strengths.append("Ürün iade edilebilir.")
    elif logistics.get("refundable") is False:
        concerns.append("Ürün iade edilemiyor.")

    if logistics.get("long_term_delivery"):
        concerns.append("Uzun tedarik süresi işaretli — teslimat gecikebilir.")
    if logistics.get("free_shipping") is True:
        strengths.append("Kargo ücretsiz.")
    if product.get("running_out"):
        concerns.append("Stok tükeniyor — fiyat ve bulunurluk değişebilir.")

    if isinstance(product.get("favorite_count"), int) and product["favorite_count"] >= 100:
        strengths.append(f"{product['favorite_count']} favori — talep görüyor.")

    notes = []
    if not strengths and not concerns:
        # Boş sonuç "satıcı kötü" değil "site bu veriyi yayınlamıyor" demek;
        # aradaki farkı sunumda karıştırmamak için açıkça yazılıyor.
        notes.append(
            "Bu sayfada karar verdirecek satıcı/ürün sinyali bulunamadı. "
            "Site bu verileri yayınlamıyor olabilir — sonucu 'satıcı zayıf' "
            "diye yorumlamayın."
        )

    return {
        "strengths": strengths,
        "concerns": concerns,
        "notes": notes,
        # Bu üçü hiçbir pazaryerinde satıcı bazında yayınlanmıyor. Satıcı puanı
        # zaten platformun bunlardan hesapladığı bileşke; sunumda "veri yok" ile
        # "sorun yok" karıştırılmasın diye açıkça yazılıyor.
        "unknowns": [
            "Kargoda hasar/kayıp oranı satıcı bazında yayınlanmıyor.",
            "Müşteri hizmetleri yanıt kalitesi yayınlanmıyor.",
            "İade taleplerinde ulaşılabilirlik yayınlanmıyor.",
            "Satıcı puanı bu üçünün platform tarafından hesaplanmış bileşkesidir.",
        ],
    }


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


@mcp.tool()
@handle_fetch_errors
async def extract_seller_trust_signals(url: str) -> str:
    """Ürün sayfasından satıcı ve ürün güven sinyallerini çıkarır: satıcı puanı,
    resmi unvan, kargoyu kimin yaptığı, iade edilebilirlik, ürün puanının kaç
    yoruma dayandığı. Sunumda 'hangi ürünü ve satıcıyı neden seçmeli' kararını
    gerekçelendirmek için kullanılır.
    """
    soup, warning = await _fetch_soup(url)

    state = _find_trendyol_state(soup)
    if state:
        signals = _signals_from_trendyol(state)
    else:
        signals = _signals_from_json_ld(soup)

    payload = {
        "type": "seller_trust_signals",
        "url": url,
        # Hangi kaynaktan geldiği önemli: JSON-LD tabanlı çıktı çok daha incedir,
        # boş alanlar "satıcı kötü" değil "site yayınlamıyor" demektir.
        "source": signals["source"],
        "product": signals["product"],
        "seller": signals["seller"],
        "logistics": signals["logistics"],
        "decision_summary": _build_decision_summary(signals),
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
    "seller": extract_seller_trust_signals,
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


@mcp.custom_route("/api/seller", methods=["GET"])
async def api_seller(request: Request) -> Response:
    return await _run_tool_route(request, "seller")


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
      <button data-tool="seller">Satıcı Güveni</button>
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