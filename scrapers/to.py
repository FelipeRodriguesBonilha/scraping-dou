from __future__ import annotations

import re

from scrapers.common import (
    run_for_keywords,
    save_download,
    scrape_with_playwright,
)


STATE = "TO"
URL = "https://diariooficial.to.gov.br/"


def _download_results(
    page,
    keyword: str,
    date_value: str,
    saved_editions: set[str],
) -> int:
    links = page.locator("a[href*='doe.to.gov.br/diario/'][href$='/download']")
    downloaded = 0
    for index in range(links.count()):
        link = links.nth(index)
        href = link.get_attribute("href")
        if not href or href in saved_editions:
            continue
        try:
            with page.expect_download() as download_info:
                page.evaluate(
                    """url => {
                        const link = document.createElement('a');
                        link.href = url;
                        document.body.appendChild(link);
                        link.click();
                        link.remove();
                    }""",
                    href,
                )
            save_download(download_info.value, STATE, keyword, date_value=date_value)

            saved_editions.add(href)
            downloaded += 1
        except Exception as error:
            print(f"[{STATE}] falha no resultado {index + 1}: {error}")
    return downloaded


def search(page, keyword: str, date_value: str) -> None:
    page.goto(URL, wait_until="domcontentloaded")
    page.locator(".search-btn").click()
    page.locator("#texto-exato").wait_for()
    page.locator("#texto-exato").fill(keyword)
    page.locator("#data-inicial").fill(date_value)
    page.locator("#data-final").fill(date_value)

    page.locator("#formportexto button.search-submit").click()
    page.wait_for_load_state("domcontentloaded")

    saved_editions: set[str] = set()
    while True:
        results = page.locator("a[href*='doe.to.gov.br/diario/'][href$='/download']")
        if not results.count():
            break
        before_url = page.url
        _download_results(page, keyword, date_value, saved_editions)
        next_page = page.locator("a[rel='next'], a[title*='Próxima']").first
        if not next_page.count():
            next_page = page.locator(".pagination a").filter(
                has_text=re.compile(r"^(›|»|Próxima)$", re.I)
            ).first
        if not next_page.count() or not next_page.is_visible():
            break
        try:
            next_page.click()
            page.wait_for_function(
                "url => location.href !== url",
                arg=before_url,
            )
            page.wait_for_load_state("domcontentloaded")
        except Exception:
            break


def scrape(playwright=None, keywords=None, date_value=None, headless: bool = True) -> None:
    if playwright is None:
        return scrape_with_playwright(
            STATE, search, keywords=keywords, date_value=date_value, headless=headless
        )
    return run_for_keywords(
        playwright, STATE, search, keywords=keywords, date_value=date_value, headless=headless
    )

if __name__ == "__main__":
    scrape()
