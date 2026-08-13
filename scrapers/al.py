from __future__ import annotations

import re
from typing import Iterable
from urllib.parse import urljoin

from playwright.sync_api import Page, Playwright

from scrapers.common import (
    click_next,
    run_for_keywords,
    save_download,
    scrape_with_playwright,
)


STATE = "AL"
URL = "https://diario.imprensaoficial.al.gov.br/"


def _download_current_page(
    page: Page,
    keyword: str,
    date_value: str,
    seen_issues: set[str],
) -> int:
    downloads = page.get_by_role("link", name=re.compile(r"^Download$", re.I))
    saved = 0

    for index in range(downloads.count()):
        try:
            download_link = downloads.nth(index)
            href = download_link.get_attribute("href") or ""
            issue_key = urljoin(page.url, href) if href else f"{page.url}#download-{index}"
            if issue_key in seen_issues:
                continue
            with page.expect_download(timeout=30_000) as download_info:
                download_link.click()
            save_download(
                download_info.value,
                STATE,
                keyword,
                date_value=date_value,
            )
            seen_issues.add(issue_key)
            saved += 1
        except Exception as error:
            print(f"[{STATE}] falha ao baixar resultado {index + 1}: {error}")
    return saved


def search(page: Page, keyword: str, date_value: str) -> None:
    page.goto(URL, wait_until="domcontentloaded")

    search_type = page.locator("#selectBuscaTipo")
    try:
        search_type.locator("input[aria-label='Search for option']").click()
        page.get_by_text("Frase exata", exact=True).last.click()
    except Exception as error:
        print(f"[{STATE}] não foi possível confirmar busca por frase exata: {error}")
    page.locator("#inputPalavraChave").fill(keyword)
    page.locator("#inputPeriodoInicial").fill(date_value)
    page.locator("#inputPeriodoFinal").fill(date_value)
    page.get_by_role("button", name="Buscar").click()
    page.wait_for_timeout(750)

    next_page = page.get_by_role("menuitem", name="Go to next page")
    if not next_page.count():
        next_page = page.get_by_text("Próximo", exact=True)

    seen_issues: set[str] = set()
    for _ in range(10_000):
        _download_current_page(page, keyword, date_value, seen_issues)
        if not click_next(next_page):
            break


def scrape(
    playwright: Playwright | None = None,
    keywords: Iterable[str] | None = None,
    date_value: object | None = None,
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
