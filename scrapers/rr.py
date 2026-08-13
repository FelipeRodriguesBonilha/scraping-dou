from __future__ import annotations

from pathlib import Path
from urllib.parse import urljoin, urlsplit

from scrapers.common import (
    filter_occurrence_pages,
    matches_date,
    read_occurrence_download,
    run_for_keywords,
    save_download,
    save_occurrence_text,
    scrape_with_playwright,
)


STATE = "RR"
BASE_URL = "https://www.imprensaoficial.rr.gov.br/app/"
URL = f"{BASE_URL}_visualizar-mes/"
DOWNLOAD_TIMEOUT_MS = 120_000


class _ResponseDownload:
    def __init__(self, content: bytes, filename: str) -> None:
        self._content = content
        self.suggested_filename = filename

    def save_as(self, target: str | Path) -> None:
        Path(target).write_bytes(self._content)


def _archive_url(date_value: str) -> str:
    year, month, _ = date_value.split("-", 2)
    return f"{URL}?ano={year}&mes={month}"


def _edition_url(value: str) -> str:
    return urljoin(BASE_URL, f"_edicoes/{value.lstrip('/')}")


def _filename(href: str) -> str:
    return Path(urlsplit(href).path).name or "diario_rr.pdf"


def _get_pdf(page, href: str) -> _ResponseDownload:
    response = page.context.request.get(
        href,
        headers={"Referer": URL},
        timeout=DOWNLOAD_TIMEOUT_MS,
    )
    content = response.body()
    if response.status != 200:
        raise RuntimeError(f"PDF da edição indisponível (HTTP {response.status})")
    if not content.startswith(b"%PDF"):
        raise RuntimeError("resposta da edição não é um PDF")
    return _ResponseDownload(content, _filename(href))


def _download_results(page, keyword: str, date_value: str) -> int:
    forms = page.locator("form:has(input[name='doe'])")
    downloaded = 0
    failed_editions: list[str] = []
    seen_sources: set[str] = set()
    for index in range(forms.count()):
        form = forms.nth(index)
        source = form.locator("input[name='doe']").input_value()
        if not source or source in seen_sources or not matches_date(source, date_value):
            continue
        seen_sources.add(source)
        try:
            download = _get_pdf(page, _edition_url(source))
            pages = filter_occurrence_pages(read_occurrence_download(download), keyword)
            if not pages:
                print(f"[{STATE}] nenhuma ocorr\u00eancia exata na edi\u00e7\u00e3o de {date_value}")
                continue
            pdf_path = save_download(
                download,
                STATE,
                keyword,
                date_value=date_value,
                extract_occurrences=False,
                deduplicate_identical=True,
            )
            save_occurrence_text(
                STATE,
                keyword,
                pdf_path.name,
                pages,
                date_value=date_value,
            )
            downloaded += 1
        except Exception as error:
            failed_editions.append(source)
            print(f"[{STATE}] falha ao baixar {source}: {error}")
    if failed_editions:
        raise RuntimeError(
            f"{len(failed_editions)} edição(ões) não puderam ser baixadas para '{keyword}'"
        )
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
