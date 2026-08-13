from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlsplit

from scrapers.common import (
    matches_date,
    run_for_keywords,
    save_download,
    scrape_with_playwright,
)


STATE = "TO"
URL = "https://diariooficial.to.gov.br/"
DOWNLOAD_TIMEOUT_MS = 120_000
RESULT_LINK_SELECTOR = (
    "section.search-results a[href*='doe.to.gov.br/diario/'][href$='/download']"
)


class _ResponseDownload:
    def __init__(self, content: bytes, filename: str) -> None:
        self._content = content
        self.suggested_filename = filename

    def save_as(self, target: str | Path) -> None:
        Path(target).write_bytes(self._content)


def _download_filename(href: str) -> str:
    path_parts = [part for part in urlsplit(href).path.split("/") if part]
    edition_id = path_parts[-2] if len(path_parts) >= 2 else ""
    if edition_id.isdigit():
        return f"DOETO-edicao-{edition_id}.pdf"
    return "DOETO.pdf"


def _get_pdf(page, href: str) -> _ResponseDownload:
    response = page.context.request.get(
        href,
        headers={"Referer": URL},
        timeout=DOWNLOAD_TIMEOUT_MS,
    )
    content = response.body()
    if response.status != 200:
        raise RuntimeError(f"PDF do TO indisponível (HTTP {response.status})")
    if not content.startswith(b"%PDF"):
        raise RuntimeError("resposta da edição não é um PDF")
    return _ResponseDownload(content, _download_filename(href))


def _search_url(keyword: str, date_value: str) -> str:
    parameters = {
        "por": "texto",
        "texto": keyword,
        "data-inicial": date_value,
        "data-final": date_value,
    }
    return f"{urljoin(URL, 'busca')}?{urlencode(parameters)}"


def _publication_date(link) -> str:
    row = link.locator("xpath=ancestor::tr[1]")
    try:
        return " ".join(row.locator("td").nth(1).inner_text().split())
    except Exception:
        return ""


def _download_results(
    page,
    keyword: str,
    date_value: str,
    saved_editions: set[str],
) -> int:
    links = page.locator(RESULT_LINK_SELECTOR)
    downloaded = 0
    failed_editions: list[str] = []
    for index in range(links.count()):
        link = links.nth(index)
        raw_href = link.get_attribute("href")
        href = urljoin(page.url, raw_href) if raw_href else ""
        if not href or href in saved_editions:
            continue
        publication_date = _publication_date(link)
        if not matches_date(publication_date, date_value):
            print(
                f"[{STATE}] edição fora da data solicitada ignorada: "
                f"{href} ({publication_date or 'data ausente'})"
            )
            continue
        try:
            save_download(
                _get_pdf(page, href),
                STATE,
                keyword,
                date_value=date_value,
                deduplicate_identical=True,
            )
            saved_editions.add(href)
            downloaded += 1
        except Exception as error:
            failed_editions.append(href)
            print(f"[{STATE}] falha ao baixar resultado {index + 1}: {error}")
    if failed_editions:
        raise RuntimeError(
            f"{len(failed_editions)} edição(ões) não puderam ser baixadas para '{keyword}'"
        )
    return downloaded


def search(page, keyword: str, date_value: str) -> None:
    page.goto(_search_url(keyword, date_value), wait_until="domcontentloaded")
    page.locator("section.search-results").wait_for(timeout=30_000)

    saved_editions: set[str] = set()
    while True:
        results = page.locator(RESULT_LINK_SELECTOR)
        if not results.count():
            break
        before_url = page.url
        _download_results(page, keyword, date_value, saved_editions)
        next_page = page.locator("a[rel='next'], a[title*='Próxima']").first
        if not next_page.count():
            next_page = page.locator(".pagination a").filter(
                has_text=re.compile(r"^(›|»|Próxima)$", re.I)
            ).first
        if not next_page.count() or not next_page.is_visible():
            break
        try:
            next_page.click()
            page.wait_for_function(
                "url => location.href !== url",
                arg=before_url,
            )
            page.wait_for_load_state("domcontentloaded")
        except Exception:
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
