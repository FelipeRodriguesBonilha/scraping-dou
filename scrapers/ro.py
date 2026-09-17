from __future__ import annotations

from html.parser import HTMLParser
from pathlib import PurePosixPath
from urllib.parse import urlencode, urljoin, urlparse

from .common import (
    date_as_br,
    matches_date,
    normalize_date,
    run_for_keywords,
    scrape_with_playwright,
)
from .public_pdf import save_matching_pdf

STATE = "RO"
BASE_URL = "https://diof.ro.gov.br"


class _EditionRows(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows: list[tuple[str, list[str]]] = []
        self._text: list[str] | None = None
        self._links: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._text, self._links = [], []
        elif self._text is not None and tag == "a":
            href = dict(attrs).get("href", "")
            if urlparse(href).path.lower().endswith(".pdf"):
                self._links.append(href)

    def handle_data(self, data):
        if self._text is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag == "tr" and self._text is not None:
            self.rows.append((" ".join(self._text), self._links))
            self._text = None


def edition_urls(html: str, date_value: str) -> list[str]:
    parser = _EditionRows()
    parser.feed(html)
    urls = []
    for text, links in parser.rows:
        if links and not matches_date(text, date_value):
            raise RuntimeError("o portal retornou uma edição fora da data solicitada")
        urls.extend(urljoin(BASE_URL, link) for link in links)
    if not urls and not any(
        "nenhuma publicação encontrada" in " ".join(text.casefold().split())
        for text, _links in parser.rows
    ):
        raise RuntimeError("resposta da consulta de diários não reconhecida")
    return list(dict.fromkeys(urls))


def search(page, keyword: str, date_value: str) -> None:
    date_value = normalize_date(date_value)
    query = urlencode({"cf_time": date_as_br(date_value).replace("/", "-")})
    request = page.context.request
    response = request.get(f"{BASE_URL}/diarios?{query}", timeout=60_000)
    if not response.ok:
        raise RuntimeError(f"consulta indisponível (HTTP {response.status})")
    saved = 0
    for url in edition_urls(response.text(), date_value):
        response = request.get(url, timeout=120_000)
        if not response.ok:
            raise RuntimeError(f"diário indisponível (HTTP {response.status})")
        saved += len(save_matching_pdf(
            response.body(),
            STATE,
            [keyword],
            PurePosixPath(urlparse(url).path).name,
            date_value,
        ))
    print(f"[{STATE}] {saved} edição(ões) completa(s) com ocorrência exata em {date_value}")


def scrape(playwright=None, *, keywords=None, date_value=None, headless=True) -> None:
    if playwright is None:
        scrape_with_playwright(
            STATE,
            search,
            keywords=keywords,
            date_value=date_value,
            headless=headless,
        )
    else:
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
