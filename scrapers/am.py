from __future__ import annotations

from pathlib import Path
from urllib.parse import quote, urlparse

from scrapers.common import (
    date_as_br,
    filter_occurrence_pages,
    read_occurrence_download,
    run_for_keywords,
    save_download,
    save_occurrence_pages,
    save_occurrence_text,
    scrape_with_playwright,
)


STATE = "AM"
URL = "https://diario.imprensaoficial.am.gov.br/"


def _edition_key(href: str) -> str:
    path = urlparse(href).path.rstrip("/")
    marker = "/portal/edicoes/download/"
    if marker in path:
        return path.split(marker, 1)[1].split("/", 1)[0]
    return href


def _is_occurrence_page(href: str) -> bool:
    path = urlparse(href).path.rstrip("/")
    marker = "/portal/edicoes/download/"
    if marker not in path:
        return False
    return "/" in path.split(marker, 1)[1]


def _occurrence_page_number(href: str) -> int | None:
    try:
        return int(urlparse(href).path.rstrip("/").split("/")[-1])
    except (IndexError, ValueError):
        return None


def _trigger_download(page, href: str):
    with page.expect_download() as download_info:
        page.evaluate(
            """url => {
                const link = document.createElement('a');
                link.href = url;
                link.download = '';
                document.body.appendChild(link);
                link.click();
                link.remove();
            }""",
            href,
        )
    return download_info.value


def _search_url(keyword: str, date_value: str) -> str:
    day, month, year = date_as_br(date_value).split("/")
    query = quote(keyword.strip())
    return (
        f"{URL}busca/#/?page=1&q={query}&exata=1"
        f"&data_init={day}-{month}-{year}&data_end={day}-{month}-{year}"
    )


def _download_results(
    page,
    keyword: str,
    date_value: str,
    saved_editions: dict[str, Path],
    saved_pages: set[str],
    native_occurrences: dict[str, list[tuple[int, str]]],
    failed_page_editions: set[str],
) -> int:
    download_links = page.locator("a[href*='/portal/edicoes/download/']")
    for index in range(download_links.count()):
        href = download_links.nth(index).get_attribute("href")
        if not href or not _is_occurrence_page(href) or href in saved_pages:
            continue

        saved_pages.add(href)
        edition_key = _edition_key(href)
        try:
            native_occurrences.setdefault(edition_key, []).extend(
                filter_occurrence_pages(
                    read_occurrence_download(
                        _trigger_download(page, href),
                        page_number=_occurrence_page_number(href),
                    ),
                    keyword,
                )
            )
        except Exception as error:
            failed_page_editions.add(edition_key)
            print(f"[{STATE}] falha na página da ocorrência {index + 1}: {error}")

    downloaded = 0
    for index in range(download_links.count()):
        href = download_links.nth(index).get_attribute("href")
        if not href or _is_occurrence_page(href):
            continue
        edition_key = _edition_key(href)
        if edition_key in saved_editions:
            continue
        try:
            saved_editions[edition_key] = save_download(
                _trigger_download(page, href),
                STATE,
                keyword,
                date_value=date_value,
                extract_occurrences=False,
            )
            downloaded += 1
        except Exception as error:
            print(f"[{STATE}] falha no resultado {index + 1}: {error}")
    return downloaded


def _save_occurrences(
    keyword: str,
    date_value: str,
    saved_editions: dict[str, Path],
    native_occurrences: dict[str, list[tuple[int, str]]],
    failed_page_editions: set[str],
) -> None:
    for edition_key in set(saved_editions) | set(native_occurrences):
        full_pdf = saved_editions.get(edition_key)
        pages = native_occurrences.get(edition_key, [])
        filename = (
            full_pdf.name
            if full_pdf is not None
            else f"diario_am_edicao-{edition_key}.pdf"
        )
        if pages and edition_key not in failed_page_editions:
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


def search(page, keyword: str, date_value: str) -> None:
    with page.expect_response(
        lambda response: "/apibusca/multidiarios/busca" in response.url,
        timeout=60_000,
    ):
        page.goto(_search_url(keyword, date_value), wait_until="domcontentloaded")
    page.wait_for_function(
        """() =>
            document.querySelector("a[href*='/portal/edicoes/download/']") ||
            document.body.innerText.includes('Nenhum resultado encontrado')
        """,
        timeout=60_000,
    )

    saved_editions: dict[str, Path] = {}
    saved_pages: set[str] = set()
    native_occurrences: dict[str, list[tuple[int, str]]] = {}
    failed_page_editions: set[str] = set()
    while True:
        first_result = page.locator("a[href*='/portal/edicoes/download/']")
        if not first_result.count():
            break
        before_url = page.url
        _download_results(
            page,
            keyword,
            date_value,
            saved_editions,
            saved_pages,
            native_occurrences,
            failed_page_editions,
        )
        next_page = page.locator("a[aria-label='Próxima página']")
        if not next_page.count() or not next_page.first.is_visible():
            break
        try:
            with page.expect_response(
                lambda response: "/apibusca/multidiarios/busca" in response.url,
                timeout=60_000,
            ):
                next_page.first.click()
            page.wait_for_function(
                "url => location.href !== url",
                arg=before_url,
            )
            page.wait_for_timeout(100)
        except Exception:
            break

    _save_occurrences(
        keyword,
        date_value,
        saved_editions,
        native_occurrences,
        failed_page_editions,
    )


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
