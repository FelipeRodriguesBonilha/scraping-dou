from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

from scrapers.common import date_as_br, run_for_keywords, save_download, scrape_with_playwright


STATE = "PA"
URL = "https://www.ioepa.com.br/pesquisa/"


class _ResponseDownload:
    def __init__(self, content: bytes, filename: str) -> None:
        self._content = content
        self.suggested_filename = filename

    def save_as(self, target: str | Path) -> None:
        Path(target).write_bytes(self._content)


def _exact_phrase(keyword: str) -> str:
    return f'"{keyword.strip().strip(chr(34))}"'


def _edition_key(href: str) -> str:
    return re.sub(r"DOE_\d+\.pdf$", "DOE_0.pdf", href, flags=re.IGNORECASE)


def _filename(href: str) -> str:
    return Path(urlparse(href).path).name or "diario_pa.pdf"


def _get_pdf(page, href: str) -> _ResponseDownload:
    response = page.context.request.get(href, timeout=60_000)
    content = response.body()
    if response.status != 200 or not content.startswith(b"%PDF"):
        raise RuntimeError(f"PDF indispon\u00edvel (HTTP {response.status})")
    return _ResponseDownload(content, _filename(href))


def _occurrence_page_url(full_link) -> str | None:
    card = full_link.locator(
        "xpath=ancestor::div[contains(concat(' ', normalize-space(@class), ' '), ' box-widget ')][1]"
    )
    if not card.count():
        return None
    links = card.locator("a[href*='/diarios/'][href$='.pdf']")
    for index in range(links.count()):
        href = links.nth(index).get_attribute("href")
        if href and _edition_key(href) != href:
            return href
    return None


def _download_issue(
    page,
    full_href: str,
    page_href: str | None,
    keyword: str,
    date_value: str,
) -> bool:
    try:
        download = _get_pdf(page, full_href)
    except Exception as full_error:
        if not page_href:
            print(f"[{STATE}] falha ao baixar edi\u00e7\u00e3o para '{keyword}': {full_error}")
            return False
        try:
            download = _get_pdf(page, page_href)
        except Exception as page_error:
            print(
                f"[{STATE}] falha ao baixar edi\u00e7\u00e3o para '{keyword}': "
                f"completo: {full_error}; p\u00e1gina da ocorr\u00eancia: {page_error}"
            )
            return False
    try:
        save_download(download, STATE, keyword, date_value=date_value)
        return True
    except Exception as error:
        print(f"[{STATE}] falha ao salvar edi\u00e7\u00e3o para '{keyword}': {error}")
        return False


def _download_results(
    page,
    keyword: str,
    date_value: str,
    processed_editions: set[str],
) -> tuple[int, int]:
    links = page.locator("a[href*='/diarios/'][href$='DOE_0.pdf']")
    attempted = 0
    downloaded = 0
    for index in range(links.count()):
        link = links.nth(index)
        href = link.get_attribute("href")
        if not href:
            continue
        edition_key = _edition_key(href)
        if edition_key in processed_editions:
            continue
        processed_editions.add(edition_key)
        attempted += 1
        if _download_issue(
            page,
            href,
            _occurrence_page_url(link),
            keyword,
            date_value,
        ):
            downloaded += 1
    return attempted, downloaded


def search(page, keyword: str, date_value: str) -> None:
    page.goto(URL, wait_until="domcontentloaded")

    page.locator("#InputTexto").fill(_exact_phrase(keyword))
    formatted_date = date_as_br(date_value)
    page.locator("#InputDataInicial").fill(formatted_date)
    page.locator("#InputDataFinal").fill(formatted_date)
    page.locator("button[type='submit']").click()
    page.wait_for_load_state("domcontentloaded")

    processed_editions: set[str] = set()
    matched_editions = 0
    downloaded = 0
    while True:
        full_editions = page.locator("a[href*='/diarios/'][href$='DOE_0.pdf']")
        if not full_editions.count():
            break
        before_url = page.url
        attempted, saved = _download_results(
            page,
            keyword,
            date_value,
            processed_editions,
        )
        matched_editions += attempted
        downloaded += saved
        next_page = page.locator("a[rel='next']")
        if not next_page.count() or not next_page.first.is_visible():
            break
        try:
            next_page.first.click()
            page.wait_for_function(
                "url => location.href !== url",
                arg=before_url,
            )
            page.wait_for_load_state("domcontentloaded")
        except Exception:
            break
    if matched_editions and not downloaded:
        raise RuntimeError(
            f"{matched_editions} edi\u00e7\u00e3o(\u00f5es) encontrada(s), mas nenhum PDF foi salvo"
        )


def scrape(
    playwright=None,
    keywords: Iterable[str] | None = None,
    date_value=None,
    headless: bool = True,
) -> None:
    if playwright is None:
        return scrape_with_playwright(
            STATE, search, keywords=keywords, date_value=date_value, headless=headless
        )
    return run_for_keywords(
        playwright, STATE, search, keywords=keywords, date_value=date_value, headless=headless
    )


if __name__ == "__main__":
    scrape()
