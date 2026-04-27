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
                title = (
                    soup.find("h1", {"class": lambda c: c and "title" in c})
                    or soup.find("h1")
                    or soup.find("meta", {"property": "og:title"})
                )
                if title:
                    if title.name == "meta":
                        name = title.get("content", "").strip()
                    else:
                        name = title.get_text(strip=True)
                    # Декодируем HTML entities: &#43; → +, &amp; → &
                    return html.unescape(name)
    except Exception as e:
        logger.error(f"get_product_name({code}): {e}")
    return None


def make_queries(name: str) -> list[str]:
    """
    Генерируем несколько вариантов поискового запроса.
    Пробуем от короткого к длинному — разные варианты дают разную выдачу.
    """
    words = name.strip().split()
    queries = []

    # Вариант 1: бренд + тип товара (первые 2 слова)
    if len(words) >= 2:
        queries.append(" ".join(words[:2]))

    # Вариант 2: первые 3 слова
    if len(words) >= 3:
        queries.append(" ".join(words[:3]))

    # Вариант 3: первые 4 слова
    if len(words) >= 4:
        queries.append(" ".join(words[:4]))

    # Убираем дубли сохраняя порядок
    seen = set()
    result = []
    for q in queries:
        if q not in seen:
            seen.add(q)
            result.append(q)

    return result


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
        async with httpx.AsyncClient(headers=HEADERS, timeout=20, follow_redirects=True) as client:
            resp = await client.get(url, params=params)
            if resp.status_code != 200:
                logger.warning(f"Страница {page}: HTTP {resp.status_code}")
                return []

            soup = BeautifulSoup(resp.text, "html.parser")
            cards = soup.find_all(attrs={"data-product-id": True})
            ids = [card.get("data-product-id", "") for card in cards if card.get("data-product-id")]
            logger.info(f"Запрос '{query}' страница {page}: {len(ids)} товаров")
            return ids

    except Exception as e:
        logger.error(f"get_page_product_ids('{query}', {page}): {e}")
        return []


async def find_position(code: str, queries: list[str]) -> dict | None:
    """
    Пробуем каждый запрос по очереди.
    Для каждого запроса перебираем страницы.
    """
    for query in queries:
        logger.info(f"Пробую запрос: '{query}'")
        for page in range(MAX_PAGES):
            ids = await get_page_product_ids(query, page)

            if not ids:
                logger.info(f"Пустая страница {page} для '{query}', следующий запрос")
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
        return result

    result["name"] = name
    queries = make_queries(name)
    logger.info(f"Код {code}: '{name}' → запросы: {queries}")

    pos = await find_position(code, queries)
    if pos:
        result.update(pos)
        result["found"] = True
        logger.info(f"Найден {code} → #{pos['position']} по запросу '{pos['query']}'")
    else:
        logger.info(f"Не найден в топ-{MAX_PAGES * ITEMS_PER_PAGE}: {code}")

    return result
