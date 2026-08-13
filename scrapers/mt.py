from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable
from urllib.parse import quote, urljoin, urlparse

from .common import (
    click_next,
    filter_occurrence_pages,
    is_enabled,
    paginate,
    read_occurrence_download,
    run_for_keywords,
    save_download,
    save_occurrence_pages,
    save_occurrence_text,
    scrape_with_playwright,
)


STATE = "MT"
SEARCH_URL = "https://www.iomat.mt.gov.br/buscanova/"


def _error_message(error: Exception) -> str:
    return str(error).encode("ascii", errors="backslashreplace").decode("ascii")


class _ResponseDownload:
    def __init__(self, content: bytes, filename: str) -> None:
        self._content = content
        self.suggested_filename = filename

    def save_as(self, target: str | Path) -> None:
        Path(target).write_bytes(self._content)


def _get_pdf(page, url: str, filename: str) -> _ResponseDownload:
    response = page.context.request.get(url, timeout=60_000)
    content = response.body()
    if response.status != 200 or not content.startswith(b"%PDF"):
        raise RuntimeError(f"PDF indisponível (HTTP {response.status})")
    return _ResponseDownload(content, filename)


def _page_pdf_parts(page_url: str) -> tuple[str, str, str] | None:
    path_parts = urlparse(page_url).path.rstrip("/").split("/")
    if len(path_parts) < 2:
        return None
    issue_id, page_number = path_parts[-2:]
    if not issue_id.isdigit() or not page_number.isdigit():
        return None
    return page_url.rsplit("/", 1)[0], issue_id, page_number


def _save_page_result(
    page,
    page_url: str,
    keyword: str,
    date_value: str,
    saved_issues: dict[str, Path],
    seen_pages: set[str],
    native_occurrences: dict[str, list[tuple[int, str]]],
    failed_page_issues: set[str],
) -> bool:
    page_key = page_url.split("#", 1)[0]
    if page_key in seen_pages:
        return False
    parts = _page_pdf_parts(page_key)
    if parts is None:
        return False
    issue_url, issue_id, page_number = parts

    try:
        if issue_url not in saved_issues:
            saved_issues[issue_url] = save_download(
                _get_pdf(page, issue_url, f"IOMAT-{date_value}-edicao-{issue_id}.pdf"),
                STATE,
                keyword,
                date_value=date_value,
                extract_occurrences=False,
            )
        native_occurrences.setdefault(issue_url, []).extend(
            filter_occurrence_pages(
                read_occurrence_download(
                    _get_pdf(
                        page,
                        page_key,
                        f"IOMAT-{date_value}-edicao-{issue_id}-pagina-{page_number}.pdf",
                    ),
                    page_number=int(page_number),
                ),
                keyword,
            )
        )
        seen_pages.add(page_key)
        return True
    except Exception as error:
        failed_page_issues.add(issue_url)
        print(
            f"[{STATE}] falha ao baixar página da ocorrência: "
            f"{_error_message(error)}"
        )
        return False


def _save_full_result(
    page,
    issue_url: str,
    keyword: str,
    date_value: str,
    saved_issues: dict[str, Path],
) -> bool:
    issue_key = issue_url.split("#", 1)[0]
    if issue_key in saved_issues:
        return False
    issue_id = urlparse(issue_key).path.rstrip("/").split("/")[-1] or "edicao"

    try:
        saved_issues[issue_key] = save_download(
            _get_pdf(page, issue_key, f"IOMAT-{date_value}-edicao-{issue_id}.pdf"),
            STATE,
            keyword,
            date_value=date_value,
            extract_occurrences=False,
        )
        return True
    except Exception as error:
        print(
            f"[{STATE}] falha ao baixar edição para '{keyword}': "
            f"{_error_message(error)}"
        )
        return False


def _process_results(
    page,
    keyword: str,
    date_value: str,
    saved_issues: dict[str, Path],
    seen_pages: set[str],
    native_occurrences: dict[str, list[tuple[int, str]]],
    failed_page_issues: set[str],
) -> int:
    page_links = page.locator("a.link.pdf-page[href]")
    saved = 0
    if page_links.count():
        for index in range(page_links.count()):
            href = page_links.nth(index).get_attribute("href") or ""
            if _save_page_result(
                page,
                urljoin(page.url, href),
                keyword,
                date_value,
                saved_issues,
                seen_pages,
                native_occurrences,
                failed_page_issues,
            ):
                saved += 1
        return saved

    full_links = page.locator("a.link.pdf-full[href]")
    for index in range(full_links.count()):
        href = full_links.nth(index).get_attribute("href") or ""
        if href and _save_full_result(
            page,
            urljoin(page.url, href),
            keyword,
            date_value,
            saved_issues,
        ):
            saved += 1
    return saved


def _save_occurrences(
    keyword: str,
    date_value: str,
    saved_issues: dict[str, Path],
    native_occurrences: dict[str, list[tuple[int, str]]],
    failed_page_issues: set[str],
) -> None:
    for issue_url in set(saved_issues) | set(native_occurrences):
        full_pdf = saved_issues.get(issue_url)
        pages = native_occurrences.get(issue_url, [])
        issue_id = urlparse(issue_url).path.rstrip("/").split("/")[-1] or "edicao"
        filename = (
            full_pdf.name
            if full_pdf is not None
            else f"IOMAT-{date_value}-edicao-{issue_id}.pdf"
        )
        if pages and issue_url not in failed_page_issues:
            save_occurrence_text(
                STATE,
                keyword,
                filename,
                pages,
                date_value=date_value,
            )
            continue
        if full_pdf is not None and save_occurrence_pages(full_pdf, keyword):
            continue
        if pages:
            save_occurrence_text(
                STATE,
                keyword,
                filename,
                pages,
                date_value=date_value,
            )


def _go_to_next_page(page) -> bool:
    next_link = page.get_by_role("link", name=re.compile(r"^(>|»|próxima)$", re.I))
    if not is_enabled(next_link):
        return False
    try:
        with page.expect_response(
            lambda response: "/busca/busca/buscar/" in response.url,
            timeout=60_000,
        ):
            if not click_next(next_link, wait_ms=0):
                return False
        page.wait_for_timeout(300)
        return True
    except Exception:
        return False


def search(page, keyword: str, date_value: str) -> None:
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

    saved_issues: dict[str, Path] = {}
    seen_pages: set[str] = set()
    native_occurrences: dict[str, list[tuple[int, str]]] = {}
    failed_page_issues: set[str] = set()
    paginate(
        lambda _first_result: _process_results(
            page,
            keyword,
            date_value,
            saved_issues,
            seen_pages,
            native_occurrences,
            failed_page_issues,
        ),
        lambda: _go_to_next_page(page),
        max_pages=10_000,
    )
    _save_occurrences(
        keyword,
        date_value,
        saved_issues,
        native_occurrences,
        failed_page_issues,
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
