from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable
from urllib.parse import quote, urljoin, urlparse

from playwright.sync_api import Page, Playwright

from scrapers.common import (
    click_next,
    is_enabled,
    paginate,
    run_for_keywords,
    save_download,
    scrape_with_playwright,
)


STATE = "PR"
SEARCH_URL = "https://dioe.pr.gov.br/buscanova/"


class _ResponseDownload:
    def __init__(self, content: bytes, filename: str) -> None:
        self._content = content
        self.suggested_filename = filename

    def save_as(self, target: str | Path) -> None:
        Path(target).write_bytes(self._content)


def _get_pdf(page: Page, url: str, filename: str) -> _ResponseDownload:
    response = page.context.request.get(url, timeout=60_000)
    content = response.body()
    if response.status != 200 or not content.startswith(b"%PDF"):
        raise RuntimeError(f"PDF indisponível (HTTP {response.status})")
    return _ResponseDownload(content, filename)


def _issue_url(page_url: str) -> tuple[str, str] | None:
    parts = urlparse(page_url).path.rstrip("/").split("/")
    if len(parts) < 2 or not parts[-2].isdigit() or not parts[-1].isdigit():
        return None
    return page_url.rsplit("/", 1)[0], parts[-2]


def _process_results(
    page: Page,
    keyword: str,
    date_value: str,
    seen_issues: set[str],
) -> int:
    page_links = page.locator("a.link.pdf-page[href]")
    saved = 0
    for index in range(page_links.count()):
        href = page_links.nth(index).get_attribute("href") or ""
        parts = _issue_url(urljoin(page.url, href))
        if parts is None:
            continue
        issue_url, issue_id = parts
        if issue_url in seen_issues:
            continue
        try:
            save_download(
                _get_pdf(
                    page,
                    issue_url,
                    f"DIOEPR-{date_value}-edicao-{issue_id}.pdf",
                ),
                STATE,
                keyword,
                date_value=date_value,
            )
            seen_issues.add(issue_url)
            saved += 1
        except Exception as error:
            print(f"[{STATE}] falha ao baixar edição para '{keyword}': {error}")
    return saved


def _go_to_next_page(page: Page) -> bool:
    next_link = page.get_by_role("link", name=re.compile(r"^(>|»|próxima)$", re.I))
    if not is_enabled(next_link):
        return False
    try:
        with page.expect_response(
            lambda response: "/busca/busca/buscar/" in response.url,
            timeout=60_000,
        ):
            return click_next(next_link, wait_ms=0)
    except Exception:
        return False


def search(page: Page, keyword: str, date_value: str) -> None:
    compact_date = date_value.replace("-", "")
    phrase = keyword.strip().strip('"')
    exact_keyword = f'"{phrase}"' if phrase else keyword
    search_url = (
        f"{SEARCH_URL}#/p=1&q={quote(exact_keyword, safe='')}"
        f"&di={compact_date}&df={compact_date}"
    )
    with page.expect_response(
        lambda response: "/busca/busca/buscar/" in response.url,
        timeout=60_000,
    ):
        page.goto(search_url, wait_until="domcontentloaded")
    page.wait_for_timeout(300)

    seen_issues: set[str] = set()
    paginate(
        lambda _first_result: _process_results(page, keyword, date_value, seen_issues),
        lambda: _go_to_next_page(page),
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
