from __future__ import annotations

import re

from scrapers.common import (
    matches_date,
    run_for_keywords,
    save_download,
    scrape_with_playwright,
)


STATE = "AC"
URL = "https://diario.ac.gov.br/"
MAX_PAGES = 10_000


def _publication_date(link) -> str:
    row = link.locator("xpath=ancestor::tr[1]")
    try:
        return " ".join(row.locator("td").first.inner_text().split())
    except Exception:
        return ""


def _result_filename(link, publication_date: str | None = None) -> str | None:
    label = " ".join(link.inner_text().split())
    if publication_date is None:
        publication_date = _publication_date(link)

    if not label:
        return None
    return f"{label} - {publication_date}.pdf" if publication_date else f"{label}.pdf"


def _download_results(
    page, keyword: str, date_value: str, seen_diaries: set[str]
) -> int:
    links = page.locator(".resultados_busca a[title='Fazer download']")
    downloaded = 0
    for index in range(links.count()):
        link = links.nth(index)
        label = " ".join(link.inner_text().split())
        publication_date = _publication_date(link)

        if not matches_date(publication_date, date_value):
            print(
                f"[{STATE}] edição fora da data solicitada ignorada: "
                f"{label} ({publication_date or 'data ausente'})"
            )
            continue
        href = link.get_attribute("href") or label
        if href in seen_diaries:
            print(f"[{STATE}] edição repetida ignorada: {label}")
            continue

        seen_diaries.add(href)
        filename = _result_filename(link, publication_date)
        try:
            with page.expect_download() as download_info:
                link.click()
            save_download(
                download_info.value,
                STATE,
                keyword,
                filename,
                date_value=date_value,
            )
            downloaded += 1
        except Exception as error:
            print(f"[{STATE}] falha ao baixar '{label}': {error}")
    return downloaded


def _current_page_index(page) -> int | None:
    try:
        return int(page.locator("#paginaIni").input_value())
    except (TypeError, ValueError):
        pass
    except Exception:
        return None

    try:
        return int(page.locator(".paginacao .linkAtual").first.inner_text().strip()) - 1
    except (TypeError, ValueError):
        return None
    except Exception:
        return None


def _next_page_index(page, current_index: int) -> int | None:
    links = page.locator(".paginacao [onclick*='vaiParaPaginaBusca']")
    candidates: set[int] = set()
    for index in range(links.count()):
        onclick = links.nth(index).get_attribute("onclick") or ""
        match = re.search(r"vaiParaPaginaBusca\((\d+)\)", onclick)
        if match:
            candidates.add(int(match.group(1)))

    future_pages = [candidate for candidate in candidates if candidate > current_index]
    return min(future_pages, default=None)


def _go_to_page(page, page_index: int) -> bool:
    form = page.locator("#buscaPorPalavra")
    try:
        with page.expect_navigation(wait_until="domcontentloaded", timeout=60_000):
            form.evaluate(
                """(form, pageIndex) => {
                    form.querySelector('#paginaIni').value = String(pageIndex);
                    form.submit();
                }""",
                page_index,
            )
        page.locator(".resultados_busca").wait_for(timeout=60_000)
    except Exception as error:
        print(f"[{STATE}] falha ao abrir página {page_index + 1}: {error}")
        return False

    return _current_page_index(page) == page_index


def _select_exact_text(page) -> None:
    mode_field = page.locator("#palavraTipo")
    if mode_field.count():
        mode_field.evaluate("field => field.value = '0'")

    exact_radio = page.locator("#tipoBusca0")
    if exact_radio.count():
        exact_radio.evaluate("radio => radio.checked = true")


def search(page, keyword: str, date_value: str) -> None:
    page.goto(URL, wait_until="domcontentloaded")
    form = page.locator("#buscaPorPalavra")

    form.evaluate("form => form.noValidate = true")
    page.locator("#palavra").fill(keyword)
    _select_exact_text(page)
    year = date_value.split("-", 1)[0]
    year_select = page.locator("#ano_palavra")
    if year_select.locator(f"option[value='{year}']").count():
        year_select.select_option(year)
    with page.expect_navigation(wait_until="domcontentloaded", timeout=60_000):
        form.locator("button[type='submit']").click()
    page.locator(".resultados_busca").wait_for()
    _select_exact_text(page)

    seen_diaries: set[str] = set()
    visited_pages: set[int] = set()
    for _ in range(MAX_PAGES):
        current_index = _current_page_index(page)
        if current_index is None or current_index in visited_pages:
            break
        visited_pages.add(current_index)
        _download_results(page, keyword, date_value, seen_diaries)

        next_index = _next_page_index(page, current_index)
        if next_index is None or next_index in visited_pages:
            break
        if not _go_to_page(page, next_index):
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
