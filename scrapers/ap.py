from __future__ import annotations

from pathlib import Path
from urllib.parse import quote, urlparse

from scrapers.common import (
    filter_occurrence_pages,
    read_occurrence_download,
    run_for_keywords,
    save_download,
    save_occurrence_pages,
    save_occurrence_text,
    scrape_with_playwright,
)


STATE = "AP"
URL = "https://diofe.portal.ap.gov.br/"


def _edition_key(href: str) -> str:
    path = urlparse(href).path.rstrip("/")
    marker = "/portal/edicoes/download/"
    if marker in path:
        return path.split(marker, 1)[1].split("/", 1)[0]
    return href


def _occurrence_page_number(href: str) -> int | None:
    parts = urlparse(href).path.rstrip("/").split("/")
    try:
        return int(parts[-1])
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
    year, month, day = date_value.split("-")
    exact_phrase = quote(f'"{keyword.strip().strip(chr(34))}"')
    return (
        f"{URL}buscanova/#/p=1&q={exact_phrase}"
        f"&di={year}{month}{day}&df={year}{month}{day}"
    )


def _result_page_count(response) -> int:
    try:
        total = response.json().get("hits", {}).get("total", 0)
        if isinstance(total, dict):
            total = total.get("value", 0)
        return max(0, (int(total) + 9) // 10)
    except Exception:
        return 1


def _wait_for_rendered_page(page, page_number: int) -> None:
    page.wait_for_function(
        """pageNumber => Array.from(document.querySelectorAll('ul.paginate li.active'))
            .some(item => item.textContent.trim().startsWith(String(pageNumber)))""",
        arg=page_number,
        timeout=30_000,
    )
    page.locator("a.pdf-full").first.wait_for(state="attached", timeout=30_000)


def _page_link(page, page_number: int):
    page.wait_for_function(
        """pageNumber => Array.from(document.querySelectorAll('ul.paginate a.page-link'))
            .some(item => item.textContent.trim() === String(pageNumber))""",
        arg=page_number,
        timeout=30_000,
    )
    links = page.locator("ul.paginate a.page-link")
    for index in range(links.count()):
        candidate = links.nth(index)
        if candidate.inner_text().strip() == str(page_number):
            return candidate
    raise RuntimeError(f"controle da página {page_number} não encontrado")


def _download_results(
    page,
    keyword: str,
    date_value: str,
    saved_editions: dict[str, Path],
    saved_pages: set[str],
    native_occurrences: dict[str, list[tuple[int, str]]],
    failed_page_editions: set[str],
) -> int:
    page_links = page.locator("a.pdf-page")
    for index in range(page_links.count()):
        href = page_links.nth(index).get_attribute("href")
        if not href or href in saved_pages:
            continue

        saved_pages.add(href)
        edition_key = _edition_key(href)
        try:
            occurrence_download = _trigger_download(page, href)
            native_occurrences.setdefault(edition_key, []).extend(
                filter_occurrence_pages(
                    read_occurrence_download(
                        occurrence_download,
                        page_number=_occurrence_page_number(href),
                    ),
                    keyword,
                )
            )
        except Exception as error:
            failed_page_editions.add(edition_key)
            print(f"[{STATE}] falha na página da ocorrência {index + 1}: {error}")

    links = page.locator("a.pdf-full")
    downloaded = 0
    for index in range(links.count()):
        link = links.nth(index)
        href = link.get_attribute("href")
        if not href:
            continue
        edition_key = _edition_key(href)
        if edition_key in saved_editions:
            continue
        try:
            full_download = _trigger_download(page, href)
            saved_editions[edition_key] = save_download(
                full_download,
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
    edition_keys = set(saved_editions) | set(native_occurrences)
    for edition_key in edition_keys:
        full_pdf = saved_editions.get(edition_key)
        pages = native_occurrences.get(edition_key, [])
        if full_pdf is not None and (
            edition_key in failed_page_editions or not pages
        ):
            if save_occurrence_pages(full_pdf, keyword) or not pages:
                continue
        if pages:
            filename = full_pdf.name if full_pdf is not None else f"diario_ap_edicao-{edition_key}.pdf"
            save_occurrence_text(
                STATE,
                keyword,
                filename,
                pages,
                date_value=date_value,
            )


def search(page, keyword: str, date_value: str) -> None:
    saved_editions: dict[str, Path] = {}
    saved_pages: set[str] = set()
    native_occurrences: dict[str, list[tuple[int, str]]] = {}
    failed_page_editions: set[str] = set()

    with page.expect_response(
        lambda response: "/busca/busca/buscar/" in response.url,
        timeout=60_000,
    ) as response_info:
        page.goto(_search_url(keyword, date_value), wait_until="domcontentloaded")
    total_pages = _result_page_count(response_info.value)
    if total_pages == 0:
        return

    try:
        _wait_for_rendered_page(page, 1)
    except Exception:
        print(f"[{STATE}] a API retornou resultados, mas a tela não os renderizou.")
        return
    _download_results(
        page,
        keyword,
        date_value,
        saved_editions,
        saved_pages,
        native_occurrences,
        failed_page_editions,
    )

    for page_number in range(2, total_pages + 1):
        try:
            next_page = _page_link(page, page_number)
            with page.expect_response(
                lambda response: "/busca/busca/buscar/" in response.url,
                timeout=60_000,
            ):
                next_page.click()
            _wait_for_rendered_page(page, page_number)
            _download_results(
                page,
                keyword,
                date_value,
                saved_editions,
                saved_pages,
                native_occurrences,
                failed_page_editions,
            )
        except Exception as error:
            print(f"[{STATE}] falha ao abrir página {page_number}: {error}")
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
