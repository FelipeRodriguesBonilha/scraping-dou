from __future__ import annotations

from urllib.parse import urljoin

from scrapers.common import (
    filter_occurrence_pages,
    matches_date,
    read_occurrence_download,
    run_for_keywords,
    save_download,
    scrape_with_playwright,
)


STATE = "RR"
BASE_URL = "https://www.imprensaoficial.rr.gov.br/app/"
URL = f"{BASE_URL}_visualizar-mes/"


def _archive_url(date_value: str) -> str:
    year, month, _ = date_value.split("-", 2)
    return f"{URL}?ano={year}&mes={month}"


def _edition_url(value: str) -> str:
    return urljoin(BASE_URL, f"_edicoes/{value.lstrip('/')}")


def _trigger_download(page, href: str):
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
    return download_info.value


def _download_results(page, keyword: str, date_value: str) -> int:
    forms = page.locator("form:has(input[name='doe'])")
    downloaded = 0
    for index in range(forms.count()):
        form = forms.nth(index)
        source = form.locator("input[name='doe']").input_value()
        if not source or not matches_date(source, date_value):
            continue
        try:
            download = _trigger_download(page, _edition_url(source))
            pages = filter_occurrence_pages(read_occurrence_download(download), keyword)
            if not pages:
                print(f"[{STATE}] nenhuma ocorr\u00eancia exata na edi\u00e7\u00e3o de {date_value}")
                continue
            save_download(download, STATE, keyword, date_value=date_value)
            downloaded += 1
        except Exception as error:
            print(f"[{STATE}] falha no resultado {index + 1}: {error}")
    return downloaded


def search(page, keyword: str, date_value: str) -> None:
    page.goto(_archive_url(date_value), wait_until="domcontentloaded")
    page.locator("form:has(input[name='doe'])").first.wait_for(timeout=60_000)
    _download_results(page, keyword, date_value)


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
