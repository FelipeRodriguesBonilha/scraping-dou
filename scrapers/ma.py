from __future__ import annotations

import re
from typing import Iterable
from urllib.parse import urlencode

from playwright.sync_api import Page, Playwright

from scrapers.common import (
    is_enabled,
    run_for_keywords,
    save_download,
    scrape_with_playwright,
)


STATE = "MA"
URL = "https://diariooficial.ma.gov.br/index.php"
MAX_LOAD_MORE = 10_000


def _close_modal(page: Page) -> None:
    close_button = page.locator("#gridSystemModal [data-dismiss='modal']").last
    try:
        if close_button.is_visible():
            close_button.click()
            page.wait_for_timeout(200)
    except Exception:
        pass


def _download_result(page: Page, result, keyword: str, date_value: str) -> None:
    result.click()
    download_button = page.locator("#downloadPDF")
    download_button.wait_for(state="visible", timeout=15_000)

    existing_pages = set(page.context.pages)
    try:
        with page.expect_download(timeout=30_000) as download_info:
            download_button.click()
        save_download(
            download_info.value,
            STATE,
            keyword,
            date_value=date_value,
        )
    finally:
        for popup in page.context.pages:
            if popup not in existing_pages:
                popup.close()
        _close_modal(page)


def _issue_key(result, index: int) -> str:
    values = re.findall(r"'([^']*)'", result.get_attribute("onclick") or "")
    if len(values) >= 3 and values[2]:
        return values[2]
    href = result.get_attribute("href") or ""
    return href or f"resultado-{index}"


def _wait_for_first_batch(page: Page) -> None:
    page.wait_for_function(
        """() => document.querySelectorAll('a.btnVermais').length > 0
            || document.body.innerText.includes('Nada encontrado')""",
        timeout=30_000,
    )


def search(page: Page, keyword: str, date_value: str) -> None:
    query = urlencode(
        {
            "page": "busca",
            "termo": keyword,
            "tipo": "",
            "dti": date_value,
            "dtf": date_value,
        }
    )
    page.goto(f"{URL}?{query}", wait_until="domcontentloaded")
    _wait_for_first_batch(page)

    seen_issues: set[str] = set()
    processed = 0
    for _ in range(MAX_LOAD_MORE):
        results = page.locator("a.btnVermais")
        total = results.count()
        for index in range(processed, total):
            result = results.nth(index)
            issue_key = _issue_key(result, index)
            if issue_key in seen_issues:
                continue
            try:
                _download_result(page, result, keyword, date_value)
                seen_issues.add(issue_key)
            except Exception as error:
                print(f"[{STATE}] falha ao baixar resultado {index + 1}: {error}")
                _close_modal(page)
        processed = total

        load_more = page.locator("#btnList")
        if not is_enabled(load_more):
            break
        load_more.click()
        page.wait_for_function(
            """previous => {
                const button = document.querySelector('#btnList');
                return document.querySelectorAll('a.btnVermais').length > previous
                    || !button || button.disabled;
            }""",
            arg=processed,
            timeout=30_000,
        )


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
