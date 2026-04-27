"""
kaspi.py — парсер позиций Kaspi.
Товары в HTML содержат атрибут data-product-id — это и есть артикул.
"""

import httpx
import logging
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

CITY_ID = "750000000"   # Алматы
MAX_PAGES = 84           # ищем до топ-1008 (как оригинальный бот)
ITEMS_PER_PAGE = 12      # товаров на странице

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


async def get_product_name(code: str) -> str | None:
    """Получаем название товара с его страницы на Kaspi."""
    url = f"https://kaspi.kz/shop/p/p-{code}/?c={CITY_ID}"
    try:
        async with httpx.AsyncClient(headers=HEADERS, timeout=15, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                # Пробуем найти заголовок товара
                title = (
                    soup.find("h1", {"class": lambda c: c and "title" in c})
                    or soup.find("h1")
                    or soup.find("meta", {"property": "og:title"})
                )
                if title:
                    if title.name == "meta":
                        return title.get("content", "").strip()
                    return title.get_text(strip=True)
    except Exception as e:
        logger.error(f"get_product_name({code}): {e}")
    return None


def make_search_query(name: str) -> str:
    """Берём первые 4 слова из названия для поискового запроса."""
    words = name.strip().split()
    return " ".join(words[:4])


async def get_page_product_ids(query: str, page: int) -> list[str]:
    """
    Загружает страницу поиска Kaspi и возвращает список артикулов.
    Артикулы находятся в атрибуте data-product-id карточек товаров.
    """
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
                logger.warning(f"Страница {page}: HTTP {resp.status_code}")
                return []

            soup = BeautifulSoup(resp.text, "html.parser")
            cards = soup.find_all(attrs={"data-product-id": True})
            ids = [card.get("data-product-id", "") for card in cards if card.get("data-product-id")]
            logger.info(f"Страница {page}: найдено {len(ids)} товаров")
            return ids

    except Exception as e:
        logger.error(f"get_page_product_ids page {page}: {e}")
        return []


async def find_position(code: str, query: str) -> dict | None:
    """Перебирает страницы поиска пока не найдёт нужный артикул."""
    for page in range(MAX_PAGES):
        ids = await get_page_product_ids(query, page)

        if not ids:
            logger.info(f"Пустая страница {page}, прекращаем поиск")
            break

        for idx, item_id in enumerate(ids):
            if str(item_id) == str(code):
                absolute = page * ITEMS_PER_PAGE + idx + 1
                return {
                    "position": absolute,
                    "page": page + 1,
                    "place_on_page": idx + 1,
                }

    return None


async def check_code(code: str) -> dict:
    """Полная проверка одного артикула — название + позиция."""
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
    query = make_search_query(name)
    logger.info(f"Ищу '{code}' по запросу '{query}'")

    pos = await find_position(code, query)
    if pos:
        result.update(pos)
        result["found"] = True

    return result
