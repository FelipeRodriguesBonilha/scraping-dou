from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qs, unquote, urljoin, urlparse

from .common import (
    click_next,
    paginate,
    run_for_keywords,
    save_download,
    scrape_with_playwright,
)


STATE = "DF"
SEARCH_URL = "https://dodf.df.gov.br/"


class _ResponseDownload:
    def __init__(self, content: bytes, filename: str) -> None:
        self._content = content
        self.suggested_filename = filename

    def save_as(self, target: str | Path) -> None:
        Path(target).write_bytes(self._content)


def _issue_filename(response, pdf_url: str, issue_link) -> str:
    disposition = response.headers.get("content-disposition", "")
    match = re.search(
        r"filename\*?=(?:UTF-8'')?[\"']?([^;\"']+)", disposition, re.IGNORECASE
    )
    if match:
        filename = unquote(match.group(1)).strip()
        if filename:
            return filename

    filename = parse_qs(urlparse(pdf_url).query).get("arquivo", [""])[0].strip()
    if filename:
        return filename

    title = (issue_link.inner_text() or "").strip()
    return f"{title}.pdf" if title else "DODF.pdf"


def _download_issue(page, issue_link, keyword: str, date_value: str) -> bool:
    try:
        href = issue_link.get_attribute("href")
        if not href:
            raise RuntimeError("link do PDF sem URL")
        pdf_url = urljoin(page.url, href)

        response = page.context.request.get(pdf_url, timeout=60_000)
        content = response.body()
        if response.status != 200 or not content.startswith(b"%PDF"):
            raise RuntimeError(f"PDF do DODF indisponível (HTTP {response.status})")
        save_download(
            _ResponseDownload(content, _issue_filename(response, pdf_url, issue_link)),
            STATE,
            keyword,
            date_value=date_value,
        )
        return True
    except Exception as error:
        print(f"[{STATE}] falha ao baixar edição para '{keyword}': {error}")
        return False


def _process_results(
    page,
    keyword: str,
    date_value: str,
    seen_issues: set[str],
) -> int:
    issue_links = page.locator(
        "section.box-materia a[href*='/dodf/jornal/visualizar-pdf']"
    )
    total = issue_links.count()
    saved = 0
    for index in range(total):
        issue_link = issue_links.nth(index)
        href = issue_link.get_attribute("href") or ""
        issue_key = urljoin(page.url, href) if href else f"{page.url}#issue-{index}"
        if issue_key in seen_issues:
            continue
        if _download_issue(page, issue_link, keyword, date_value):
            seen_issues.add(issue_key)
            saved += 1
    return saved


def _go_to_next_page(page) -> bool:
    next_link = page.get_by_role("link", name=re.compile(r"^(>|\u00bb|pr\u00f3xima)$", re.I))
    return click_next(next_link)


def search(page, keyword: str, date_value: str) -> None:
    page.goto(SEARCH_URL, wait_until="domcontentloaded")

    page.locator('input[name="termo"]:visible').fill(keyword)
    page.locator("#btnFilter:visible").click()

    advanced_search = page.locator("#formBuscaAcessoDiv")
    advanced_search.locator('input[name="dtInicial"]').fill(date_value)
    advanced_search.locator('input[name="dtFinal"]').fill(date_value)

    advanced_search.locator('input[name="tpBusca"][value="exata"]').check(force=True)

    with page.expect_navigation(wait_until="domcontentloaded"):
        advanced_search.locator('button[form="formBuscaAcesso"]').click()

    try:
        page.wait_for_function(
            """() => document.querySelector('section.box-materia')
                || document.body.innerText.includes('NENHUM RESULTADO ENCONTRADO')""",
            timeout=30_000,
        )
    except Exception:
        return
    if not page.locator("section.box-materia").count():
        return

    seen_issues: set[str] = set()
    paginate(
        lambda _first_result: _process_results(
            page, keyword, date_value, seen_issues
        ),
        lambda: _go_to_next_page(page),
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
