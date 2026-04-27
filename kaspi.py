"""
kaspi.py — парсер позиций Kaspi.
"""

import httpx
import logging
import html
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

CITY_ID = "750000000"
MAX_PAGES = 84
ITEMS_PER_PAGE = 12

HEADERS_HTML = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Referer": "https://kaspi.kz/shop/",
}

HEADERS_JSON = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ru-RU,ru;q=0.9",
    "Referer": "https://kaspi.kz/shop/",
}


async def get_product_name(code: str) -> str | None:
    """
    Получаем название товара.
    Метод 1: og:title из страницы товара (самый надёжный).
    Метод 2: поиск по коду на странице поиска.
    """
    # Метод 1: страница товара через og:title
    url = f"https://kaspi.kz/shop/p/p-{code}/?c={CITY_ID}"
    try:
        async with httpx.AsyncClient(headers=HEADERS_HTML, timeout=15, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                # og:title самый надёжный — всегда содержит полное название
                og = soup.find("meta", {"property": "og:title"})
                if og and og.get("content"):
                    return html.unescape(og["content"].strip())
                # Запасной — h1
                h1 = soup.find("h1")
                if h1:
                    return html.unescape(h1.get_text(strip=True))
    except Exception as e:
        logger.error(f"get_product_name method1 ({code}): {e}")

    # Метод 2: ищем товар в поиске по коду
    try:
        search_url = "https://kaspi.kz/shop/search/"
        params = {
            "text": code,
            "q": ":availableInZones:Magnum_ZONE1",
            "sort": "relevance",
        }
        async with httpx.AsyncClient(headers=HEADERS_HTML, timeout=15, follow_redirects=True) as client:
            resp = await client.get(search_url, params=params)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                # Ищем карточку с нашим артикулом
                card = soup.find(attrs={"data-product-id": str(code)})
                if card:
                    name_el = card.find(class_=lambda c: c and "name" in c.lower())
                    if name_el:
                        return html.unescape(name_el.get_text(strip=True))
    except Exception as e:
        logger.error(f"get_product_name method2 ({code}): {e}")

    return None


def make_queries(name: str) -> list[str]:
    """Генерируем варианты поискового запроса от короткого к длинному."""
    words = name.strip().split()
    queries = []
    for n in [2, 3, 4]:
        if len(words) >= n:
            q = " ".join(words[:n])
            if q not in queries:
                queries.append(q)
    return queries


async def get_page_product_ids(query: str, page: int) -> list[str]:
    """Загружает страницу поиска и возвращает список артикулов."""
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
        async with httpx.AsyncClient(headers=HEADERS_HTML, timeout=20, follow_redirects=True) as client:
            resp = await client.get(url, params=params)
            if resp.status_code != 200:
                logger.warning(f"Страница {page}: HTTP {resp.status_code}")
                return []

            soup = BeautifulSoup(resp.text, "html.parser")
            cards = soup.find_all(attrs={"data-product-id": True})
            ids = [card.get("data-product-id", "") for card in cards if card.get("data-product-id")]
            logger.info(f"'{query}' стр.{page}: {len(ids)} товаров")
            return ids

    except Exception as e:
        logger.error(f"get_page_product_ids('{query}', {page}): {e}")
        return []


async def find_position(code: str, queries: list[str]) -> dict | None:
    """Пробуем каждый запрос, для каждого перебираем страницы."""
    for query in queries:
        logger.info(f"Ищу по запросу: '{query}'")
        for page in range(MAX_PAGES):
            ids = await get_page_product_ids(query, page)
            if not ids:
                break
            for idx, item_id in enumerate(ids):
                if str(item_id) == str(code):
                    absolute = page * ITEMS_PER_PAGE + idx + 1
                    return {
                        "position": absolute,
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
        logger.warning(f"Товар {code} — название не получено")
        return result

    result["name"] = name
    queries = make_queries(name)
    logger.info(f"{code}: '{name}' → запросы: {queries}")

    pos = await find_position(code, queries)
    if pos:
        result.update(pos)
        result["found"] = True
    else:
        logger.info(f"Не найден в топ-{MAX_PAGES * ITEMS_PER_PAGE}: {code}")

    return result
