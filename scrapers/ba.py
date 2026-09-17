from __future__ import annotations

from collections.abc import Iterable

from scrapers.common import run_for_keywords, scrape_with_playwright
from scrapers.public_reader import search_public_reader


STATE = "BA"
BASE_URL = "https://egbanet.egba.ba.gov.br"
READER_BASE_URL = "https://do.ba.gov.br"


def search(page, keyword: str, date_value: str) -> None:
    search_public_reader(
        page,
        keyword,
        date_value,
        state=STATE,
        base_url=BASE_URL,
        viewer="html",
        reader_base_url=READER_BASE_URL,
    )


def scrape(
    playwright=None,
    keywords: Iterable[str] | None = None,
    date_value=None,
    headless: bool = True,
) -> None:
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
