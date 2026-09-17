from __future__ import annotations

from collections.abc import Iterable
from html.parser import HTMLParser
from pathlib import PurePosixPath
from urllib.parse import unquote, urljoin, urlparse

from scrapers.common import normalize_date, run_for_keywords, scrape_with_playwright
from scrapers.public_pdf import save_matching_pdf


STATE = "CE"
DETAIL_URL = (
    "http://pesquisa.doe.seplag.ce.gov.br/doepesquisa/sead.do"
    "?page=ultimasDetalhe&cmd=10&action=Cadernos&data={date}"
)


class _PdfLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href") or ""
        if urlparse(href).path.lower().endswith(".pdf"):
            self.links.append(href)


def _compact_date(date_value: str) -> str:
    return normalize_date(date_value).replace("-", "")


def _edition_links(page, date_value: str) -> list[str]:
    response = page.context.request.get(
        DETAIL_URL.format(date=_compact_date(date_value)), timeout=60_000
    )
    if response.status != 200:
        raise RuntimeError(f"lista de cadernos do Ceará indisponível (HTTP {response.status})")

    parser = _PdfLinkParser()
    html = response.body().decode("latin-1")
    parser.feed(html)
    expected_date = _compact_date(date_value)
    links = list(
        dict.fromkeys(
            urljoin(response.url, link)
            for link in parser.links
            if expected_date in unquote(urlparse(link).path)
        )
    )
    if parser.links and not links:
        raise RuntimeError("catálogo do Ceará retornou cadernos de outra data")
    if not parser.links and (
        "Upload do Di" not in html or "Nome do arquivo" not in html
    ):
        raise RuntimeError("catálogo do Ceará retornou uma página inesperada")
    return links


def _filename(url: str) -> str:
    return unquote(PurePosixPath(urlparse(url).path).name) or "DOE-CE.pdf"


def search(page, keyword: str, date_value: str) -> None:
    for pdf_url in _edition_links(page, date_value):
        response = page.context.request.get(pdf_url, timeout=120_000)
        if response.status != 200:
            raise RuntimeError(f"caderno do Ceará indisponível (HTTP {response.status})")
        save_matching_pdf(
            response.body(),
            STATE,
            [keyword],
            _filename(pdf_url),
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
