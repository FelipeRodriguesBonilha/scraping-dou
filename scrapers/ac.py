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
    page,
    keyword: str,
    date_value: str,
    seen_diaries: set[str],
    failed_downloads: list[str],
) -> int:
    links = page.locator(".resultados_busca a[title='Fazer download']")
    skipped_dates = 0
    for index in range(links.count()):
        link = links.nth(index)
        label = " ".join(link.inner_text().split())
        publication_date = _publication_date(link)

        if not matches_date(publication_date, date_value):
            skipped_dates += 1
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
        except Exception as error:
            print(f"[{STATE}] falha ao baixar '{label}': {error}")
            failed_downloads.append(label)
    return skipped_dates


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


def _go_to_page(page, page_index: int) -> None:
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
        raise RuntimeError(f"falha ao abrir página {page_index + 1}: {error}") from error

    if _current_page_index(page) != page_index:
        raise RuntimeError(f"o portal não avançou para a página {page_index + 1}")


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
    failed_downloads: list[str] = []
    skipped_dates = 0
    pagination_error: Exception | None = None
    for _ in range(MAX_PAGES):
        current_index = _current_page_index(page)
        if current_index is None:
            pagination_error = RuntimeError("o portal não informou a página atual")
            break
        if current_index in visited_pages:
            pagination_error = RuntimeError(f"o portal repetiu a página {current_index + 1}")
            break
        visited_pages.add(current_index)
        skipped_dates += _download_results(
            page, keyword, date_value, seen_diaries, failed_downloads
        )

        next_index = _next_page_index(page, current_index)
        if next_index is None:
            break
        if next_index in visited_pages:
            pagination_error = RuntimeError(f"o portal repetiu a página {next_index + 1}")
            break
        try:
            _go_to_page(page, next_index)
        except Exception as error:
            pagination_error = error
            break
    else:
        pagination_error = RuntimeError(f"a busca excedeu o limite de {MAX_PAGES} páginas")

    if skipped_dates:
        print(
            f"[{STATE}] {skipped_dates} edição(ões) fora da data {date_value} "
            f"ignorada(s) para '{keyword}'"
        )
    if failed_downloads or pagination_error:
        details = []
        if failed_downloads:
            details.append(f"{len(failed_downloads)} download(s) falharam")
        if pagination_error:
            details.append(str(pagination_error))
        raise RuntimeError("coleta incompleta: " + "; ".join(details))


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
