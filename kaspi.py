import httpx
import logging
import html
import re
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

CITY_ID = "750000000"
MAX_PAGES = 84
ITEMS_PER_PAGE = 12

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Referer": "https://kaspi.kz/shop/",
}


def clean_name(raw: str) -> str:
    """
    Убираем мусор из og:title:
    'Купить Пароочиститель Stardom PRO+ золотистый в Алматы – Магазин на Kaspi.kz'
    → 'Пароочиститель Stardom PRO+ золотистый'
    """
    name = html.unescape(raw.strip())
    # Убираем всё после " в Алматы" или " – " или " | "
    for sep in [" в Алматы", " – ", " | ", " - Kaspi", " на Kaspi"]:
        if sep in name:
            name = name[:name.index(sep)]
    # Убираем "Купить " в начале
    name = re.sub(r'^Купить\s+', '', name, flags=re.IGNORECASE)
    return name.strip()


def make_queries(name: str) -> list[str]:
    """Варианты поискового запроса — от короткого к длинному."""
    words = name.strip().split()
    queries = []
    for n in [2, 3, 4]:
        if len(words) >= n:
            q = " ".join(words[:n])
            if q not in queries:
                queries.append(q)
    return queries


async def get_product_name(code: str) -> str | None:
    """Получаем название товара через og:title и чистим его."""
    url = f"https://kaspi.kz/shop/p/p-{code}/?c={CITY_ID}"
    try:
        async with httpx.AsyncClient(headers=HEADERS, timeout=15, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                og = soup.find("meta", {"property": "og:title"})
                if og and og.get("content"):
                    return clean_name(og["content"])
                h1 = soup.find("h1")
                if h1:
                    return clean_name(h1.get_text(strip=True))
    except Exception as e:
        logger.error(f"get_product_name({code}): {e}")
    return None


async def get_page_product_ids(query: str, page: int) -> list[str]:
    """Загружает страницу поиска, возвращает список data-product-id."""
    url = "https://kaspi.kz/shop/search/"
    params = {
        "text": query,
        "q": ":availableInZones:Magnum_ZONE1:category:ALL",
        "sort": "relevance",
        "sc": "",
        "filteredByCategory": "false",
        "page": page,
    }
    try:
        async with httpx.AsyncClient(headers=HEADERS, timeout=20, follow_redirects=True) as client:
            resp = await client.get(url, params=params)
            if resp.status_code != 200:
                return []
            soup = BeautifulSoup(resp.text, "html.parser")
            cards = soup.find_all(attrs={"data-product-id": True})
            ids = [c.get("data-product-id", "") for c in cards if c.get("data-product-id")]
            logger.info(f"'{query}' стр.{page}: {len(ids)} товаров")
            return ids
    except Exception as e:
        logger.error(f"get_page_product_ids: {e}")
        return []


async def find_position(code: str, queries: list[str]) -> dict | None:
    """Перебираем запросы и страницы пока не найдём артикул."""
    for query in queries:
        logger.info(f"Запрос: '{query}'")
        for page in range(MAX_PAGES):
            ids = await get_page_product_ids(query, page)
            if not ids:
                break
            for idx, item_id in enumerate(ids):
                if str(item_id) == str(code):
                    return {
                        "position": page * ITEMS_PER_PAGE + idx + 1,
                        "page": page + 1,
                        "place_on_page": idx + 1,
                        "query": query,
                    }
    return None


async def check_code(code: str) -> dict:
    """Полная проверка одного артикула."""
    result = {
        "code": code,
        "name": None,
        "position": None,
        "page": None,
        "place_on_page": None,
        "found": False,
    }

    name = await get_product_name(code)
    if not name:
        return result

    result["name"] = name
    queries = make_queries(name)
    logger.info(f"{code}: '{name}' → {queries}")

    pos = await find_position(code, queries)
    if pos:
        result.update(pos)
        result["found"] = True

    return result
