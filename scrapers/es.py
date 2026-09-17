from __future__ import annotations

from .common import run_for_keywords, scrape_with_playwright
from .ionews import search_ionews


STATE = "ES"
BASE_URL = "https://ioes.dio.es.gov.br"


def search(page, keyword: str, date_value: str) -> None:
    search_ionews(page, keyword, date_value, state=STATE, base_url=BASE_URL)


def scrape(playwright=None, *, keywords=None, date_value=None, headless=True) -> None:
    if playwright is None:
        scrape_with_playwright(
            STATE,
            search,
            keywords=keywords,
            date_value=date_value,
            headless=headless,
        )
        return
    run_for_keywords(
        playwright,
        STATE,
        search,
        keywords=keywords,
        date_value=date_value,
        headless=headless,
    )


if __name__ == "__main__":
    scrape()
