from __future__ import annotations

from collections.abc import Iterable
from html.parser import HTMLParser
from pathlib import PurePosixPath
from urllib.parse import unquote, urljoin, urlparse

from scrapers.common import (
    dates_in_text,
    normalize_date,
    run_for_keywords,
    scrape_with_playwright,
)
from scrapers.public_pdf import save_matching_pdf


STATE = "PB"
ARCHIVE_URL = "https://auniao.pb.gov.br/doe/edicoes-recentes"
ARCHIVE_PAGE_SIZE = 12
MAX_ARCHIVE_PAGES = 1_000


class _PdfLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href") or ""
        if ".pdf" in urlparse(href).path.lower():
            self._href = href
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._href is not None:
            self.links.append((self._href, " ".join(self._text).strip()))
            self._href = None
            self._text = []


def _archive_page_url(page_number: int) -> str:
    if page_number <= 1:
        return ARCHIVE_URL
    offset = (page_number - 1) * ARCHIVE_PAGE_SIZE
    return f"{ARCHIVE_URL}?b_start:int={offset}"


def _pdf_links(html: str) -> list[tuple[str, str]]:
    parser = _PdfLinkParser()
    parser.feed(html)
    return parser.links


def _link_dates(href: str, text: str) -> set[str]:
    return dates_in_text(f"{unquote(href)} {text}")


def _direct_pdf_url(href: str) -> str:
    absolute = urljoin(ARCHIVE_URL, href)
    parsed = urlparse(absolute)
    pdf_end = parsed.path.lower().find(".pdf")
    if pdf_end < 0:
        return absolute
    return parsed._replace(
        path=parsed.path[: pdf_end + 4], params="", query="", fragment=""
    ).geturl()


def _find_editions(page, date_value: str) -> list[str]:
    target_date = normalize_date(date_value)
    matches: list[str] = []
    for page_number in range(1, MAX_ARCHIVE_PAGES + 1):
        response = page.context.request.get(_archive_page_url(page_number), timeout=60_000)
        if response.status != 200:
            raise RuntimeError(
                f"arquivo de edições da Paraíba indisponível (HTTP {response.status})"
            )

        html = response.text()
        links = _pdf_links(html)
        if not links:
            if (
                "Edições Recentes" not in html
                or 'id="content-core"' not in html
            ):
                raise RuntimeError("o arquivo da Paraíba retornou uma página inesperada")
            return list(dict.fromkeys(matches))

        matches.extend(
            _direct_pdf_url(href)
            for href, text in links
            if target_date in _link_dates(href, text)
        )

        page_dates = sorted(
            {
                found_date
                for href, text in links
                for found_date in _link_dates(href, text)
            }
        )
        if page_dates and target_date > page_dates[0]:
            return list(dict.fromkeys(matches))
    raise RuntimeError("limite de páginas do arquivo da Paraíba excedido")


def _filename(url: str) -> str:
    return unquote(PurePosixPath(urlparse(url).path).name) or "DOE-PB.pdf"


def search(page, keyword: str, date_value: str) -> None:
    edition_urls = _find_editions(page, date_value)
    for edition_url in edition_urls:
        response = page.context.request.get(edition_url, timeout=120_000)
        content = response.body()
        if response.status != 200:
            raise RuntimeError(f"PDF da Paraíba indisponível (HTTP {response.status})")
        save_matching_pdf(
            content,
            STATE,
            [keyword],
            _filename(edition_url),
            date_value,
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
