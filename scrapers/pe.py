from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlencode

from scrapers.common import date_as_br, run_for_keywords, save_download, scrape_with_playwright


STATE = "PE"
SEARCH_URL = "https://diariooficial.cepe.com.br/diariooficialweb/#/busca-avancada"
S3_URL = "https://cepebr-prod.s3.sa-east-1.amazonaws.com"
DIARY = "MQ=="
DIARY_ID = 1
MAX_RESULTS = 1_000


class CepeSearchUnavailable(RuntimeError):
    def __init__(self, status: int | None) -> None:
        self.status = status
        super().__init__(f"busca CEPE indisponível (HTTP {status})")


class _ResponseDownload:
    def __init__(self, content: bytes, filename: str) -> None:
        self._content = content
        self.suggested_filename = filename

    def save_as(self, target: str | Path) -> None:
        Path(target).write_bytes(self._content)


def _cepe_date(date_value: str) -> str:
    year, month, day = date_value.split("-")
    return f"{day}~2F{month}~2F{year}"


def _keyword(keyword: str) -> str:
    return keyword.strip().strip('"').strip()


def search_url(keyword: str, date_value: str) -> str:
    query = urlencode(
        {
            "diario": DIARY,
            "inicio": _cepe_date(date_value),
            "fim": _cepe_date(date_value),
            "palavra": _keyword(keyword),
            "consultar": "true",
        }
    )
    return f"{SEARCH_URL}?{query}"


def _search_payload(keyword: str, date_value: str) -> dict[str, Any]:
    br_date = date_as_br(date_value)
    return {
        "first": 0,
        "maxResults": MAX_RESULTS,
        "restricoes": {},
        "order": {},
        "data": f"{date_value}T00:00:00.000Z",
        "minDate": "2020-01-01T03:00:00.000Z",
        "maxDate": "2029-01-01T03:00:00.000Z",
        "palavras": _keyword(keyword),
        "dataInicial": br_date,
        "dataFinal": br_date,
        "intervaloAno": f"{br_date}-{br_date}",
        "codigoDiario": str(DIARY_ID),
    }


def _result_text(result: dict[str, Any]) -> str:
    text = " ".join(str(result.get(field, "")) for field in ("titulo", "texto", "resumo"))
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    return re.sub(r"\s+", " ", text).strip()


def _exact_pattern(keyword: str) -> re.Pattern[str] | None:
    words = [word for word in re.split(r"\s+", _keyword(keyword)) if word]
    if not words:
        return None
    phrase = r"\s+".join(re.escape(word) for word in words)
    prefix = r"(?<!\w)" if words[0][0].isalnum() or words[0][0] == "_" else ""
    suffix = r"(?!\w)" if words[-1][-1].isalnum() or words[-1][-1] == "_" else ""
    return re.compile(prefix + phrase + suffix, re.IGNORECASE)


def _matches_result(result: dict[str, Any], keyword: str, date_value: str) -> bool:
    published = str(result.get("dataPublicacao", "")).split("T", 1)[0]
    pattern = _exact_pattern(keyword)
    return published == date_value and pattern is not None and bool(pattern.search(_result_text(result)))


def _daily_pdf_url(date_value: str) -> str:
    return (
        f"{S3_URL}/{DIARY_ID}/arquivos/resumoDiario/{date_value}/"
        f"{date_value}.pdf"
    )


def _search_results(page, keyword: str, date_value: str) -> list[dict[str, Any]]:
    payload = _search_payload(keyword, date_value)
    result = page.evaluate(
        """async payload => {
            const response = await fetch('/diariooficial/public/search', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(payload),
            });
            const body = await response.json();
            return {status: response.status, body};
        }""",
        payload,
    )
    if result.get("status") != 200:
        raise CepeSearchUnavailable(result.get("status"))
    records = result.get("body", {}).get("list", [])
    return [record for record in records if isinstance(record, dict)]


def _download_daily_pdf(page, keyword: str, date_value: str) -> None:
    response = page.context.request.get(_daily_pdf_url(date_value), timeout=60_000)
    content = response.body()
    if response.status != 200 or not content.startswith(b"%PDF"):
        raise RuntimeError(f"edição CEPE indisponível (HTTP {response.status})")
    save_download(
        _ResponseDownload(content, f"Diário Oficial de Pernambuco {date_value}.pdf"),
        STATE,
        keyword,
        date_value=date_value,
    )


def search(page, keyword: str, date_value: str) -> None:
    page.goto(search_url(keyword, date_value), wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_timeout(500)
    try:
        results = _search_results(page, keyword, date_value)
    except CepeSearchUnavailable as error:
        if error.status != 429:
            raise
        print(f"[{STATE}] busca temporariamente limitada; baixando a edição oficial disponível.")
        _download_daily_pdf(page, keyword, date_value)
        return
    if not any(_matches_result(result, keyword, date_value) for result in results):
        return
    try:
        _download_daily_pdf(page, keyword, date_value)
    except Exception as error:
        print(f"[{STATE}] falha ao baixar edição para '{keyword}': {error}")


def scrape(
    playwright=None,
    keywords: Iterable[str] | None = None,
    date_value=None,
    headless: bool = True,
) -> None:
    if playwright is None:
        return scrape_with_playwright(
            STATE,
            search,
            keywords=keywords,
            date_value=date_value,
            headless=headless,
        )
    return run_for_keywords(
        playwright,
        STATE,
        search,
        keywords=keywords,
        date_value=date_value,
        headless=headless,
    )


if __name__ == "__main__":
    scrape()
