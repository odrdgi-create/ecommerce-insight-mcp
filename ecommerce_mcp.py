import json
import httpx
from bs4 import BeautifulSoup
from fastmcp import FastMCP

# Sunucu Tanımlaması
mcp = FastMCP("E-Commerce HTML Summarizer")


@mcp.tool()
def extract_product_presentation_data(url: str) -> str:
    """Tek bir ürün sayfasının linkinden sunum için detaylı ürün bilgilerini ve görselleri çeker."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        response = httpx.get(url, headers=headers, follow_redirects=True, timeout=12.0)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        title = soup.title.string.strip() if soup.title else "Ürün Detayı"

        images = []
        for img in soup.find_all("img", src=True):
            src = img["src"]
            if any(k in src for k in ["cdn.dsmcdn.com", "product", "images", "mnresize"]):
                if src.startswith("//"):
                    src = "https:" + src
                if src not in images and len(images) < 6:
                    images.append(src)

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

    except Exception as e:
        return json.dumps({"error": f"Hata oluştu: {str(e)}"})


@mcp.tool()
def get_category_presentation_data(url: str) -> str:
    """Kategori/Liste sayfasından sunum hazırlamak üzere öne çıkan ürünleri toplar."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        response = httpx.get(url, headers=headers, follow_redirects=True, timeout=12.0)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        title = soup.title.string.strip() if soup.title else "Kategori Analizi"

        products = []
        links = soup.find_all("a", href=True)

        for link in links:
            href = link["href"]
            if "-p-" in href or "/product/" in href:
                text = link.get_text(strip=True)
                full_url = (
                    href
                    if href.startswith("http")
                    else f"https://www.trendyol.com{href}"
                )

                if (
                    text
                    and len(text) > 10
                    and not any(p["url"] == full_url for p in products)
                ):
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

    except Exception as e:
        return json.dumps({"error": f"Hata oluştu: {str(e)}"})


if __name__ == "__main__":
    mcp.run()
