from __future__ import annotations

import html
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
import re
from typing import Iterable
from urllib.parse import urlencode

from pypdf import PdfReader

import config
from scrapers.common import (
    date_as_br,
    normalize_date,
    save_download,
    save_occurrence_metadata,
)
from scrapers.public_api import get_bytes, get_json


STATE = "MA"
PLAYWRIGHT_REQUIRED = False
URL = "https://diariooficial.ma.gov.br/busca/"
SEARCH_URL = "https://diariooficial.ma.gov.br/ajax.busca.php"
PDF_DOWNLOAD_URL = "https://diariooficial.ma.gov.br/download.php"
MAX_BATCHES = 10_000
ISSUE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
ONCLICK_VALUES = re.compile(r"'([^']*)'")


class _ResponseDownload:
    def __init__(self, content: bytes, filename: str) -> None:
        self._content = content
        self.suggested_filename = filename

    def save_as(self, target: str | Path) -> None:
        Path(target).write_bytes(self._content)


class _ResultParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[dict[str, str]] = []
        self._card: dict[str, str] | None = None
        self._capture: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = (attributes.get("class") or "").split()
        if tag == "div" and "card" in classes and "flex-md-row" in classes:
            self._card = {"section": "", "date": ""}
            self._capture = None
            return
        if self._card is None:
            return
        if tag == "strong" and "d-inline-block" in classes:
            self._capture = "section"
        elif tag == "div" and attributes.get("id") == "dataPub":
            self._capture = "date"
        elif tag == "a" and "btnVermais" in classes:
            self.results.append({**self._card, "onclick": attributes.get("onclick") or ""})

    def handle_data(self, data: str) -> None:
        if self._card is not None and self._capture is not None:
            self._card[self._capture] += data

    def handle_endtag(self, tag: str) -> None:
        if (tag == "strong" and self._capture == "section") or (
            tag == "div" and self._capture == "date"
        ):
            self._capture = None


def _parse_occurrences(fragment: str, keyword: str, date_value: str) -> list[tuple[str, dict[str, str]]]:
    parser = _ResultParser()
    parser.feed(fragment)
    occurrences: list[tuple[str, dict[str, str]]] = []
    expected_date = date_as_br(date_value)
    for result in parser.results:
        values = ONCLICK_VALUES.findall(result["onclick"])
        if len(values) < 5:
            raise RuntimeError("resultado sem identificador ou página da edição")
        issue_id = values[2].strip()
        if not ISSUE_ID_PATTERN.fullmatch(issue_id):
            raise RuntimeError(f"identificador inválido na busca do MA: {issue_id!r}")
        published_date = result["date"].strip()
        if expected_date not in published_date:
            raise RuntimeError(
                f"edição {issue_id} retornada com data inesperada: {published_date!r}"
            )
        section = html.unescape(result["section"].strip())
        if not section or section != html.unescape(values[0].strip()):
            raise RuntimeError(f"caderno inconsistente na edição {issue_id}")
        page = values[4].strip()
        if not page.isdigit() or int(page) <= 0:
            raise RuntimeError(f"página inválida na edição {issue_id}: {page!r}")
        occurrences.append(
            (
                issue_id,
                {
                    "date": expected_date,
                    "section": section,
                    "page": str(int(page)),
                    "term": keyword,
                },
            )
        )
    return occurrences


def _batch(keyword: str, date_value: str, scroll_id: str) -> dict:
    url = f"{SEARCH_URL}?{urlencode({'termo': keyword, 'sigla': '', 'datai': date_value, 'dataf': date_value, 'scrollId': scroll_id})}"
    payload = get_json(url, headers={"Referer": URL, "Accept": "application/json"})
    if not isinstance(payload, dict) or not isinstance(payload.get("busca"), dict):
        raise RuntimeError("resposta inválida da busca pública do MA")
    batch = payload["busca"]
    if batch.get("erro") is not False:
        raise RuntimeError(f"busca pública do MA recusada: {batch.get('msn') or batch}")
    return batch


def _search_occurrences(keyword: str, date_value: str) -> dict[str, list[dict[str, str]]]:
    occurrences_by_issue: dict[str, list[dict[str, str]]] = {}
    scroll_id = ""
    expected_editions: int | None = None

    for batch_number in range(MAX_BATCHES):
        batch = _batch(keyword, date_value, scroll_id)
        total = batch.get("total")
        if isinstance(total, bool) or not isinstance(total, int) or total < 0:
            raise RuntimeError("total de edições inválido na busca do MA")
        if expected_editions is None:
            expected_editions = total
        elif total != expected_editions:
            raise RuntimeError("total de edições mudou durante a paginação do MA")

        fragment = batch.get("es_html", "")
        fragment_count = batch.get("totalFragmentos", 0)
        has_more = batch.get("btnLoad", False)
        if not isinstance(fragment, str) or not isinstance(fragment_count, int) or fragment_count < 0:
            raise RuntimeError("fragmentos inválidos na busca do MA")
        if not isinstance(has_more, bool):
            raise RuntimeError("indicador de paginação inválido na busca do MA")
        found = _parse_occurrences(fragment, keyword, date_value)
        if len(found) != fragment_count:
            raise RuntimeError(
                f"busca do MA informou {fragment_count} ocorrência(s), mas retornou {len(found)}"
            )
        for issue_id, record in found:
            occurrences_by_issue.setdefault(issue_id, []).append(record)

        if not has_more:
            break
        next_scroll_id = batch.get("scrollId")
        if not isinstance(next_scroll_id, str) or not next_scroll_id:
            raise RuntimeError("busca do MA não retornou cursor para carregar mais")
        if batch_number > 0 and not found:
            raise RuntimeError("busca do MA não avançou na paginação")
        scroll_id = next_scroll_id
    else:
        raise RuntimeError(f"busca do MA excedeu {MAX_BATCHES} páginas")

    if len(occurrences_by_issue) != expected_editions:
        raise RuntimeError(
            f"busca do MA informou {expected_editions} edição(ões), "
            f"mas foram identificadas {len(occurrences_by_issue)}"
        )
    return occurrences_by_issue


def _download_result(issue_id: str, keyword: str, date_value: str, records: list[dict[str, str]]) -> Path:
    url = f"{PDF_DOWNLOAD_URL}?{urlencode({'arq': issue_id})}"
    content = get_bytes(url, headers={"Referer": URL})
    if not content.startswith(b"%PDF") or b"%%EOF" not in content[-1024:]:
        raise RuntimeError(f"a edição {issue_id} não retornou um PDF completo")
    reader = PdfReader(BytesIO(content), strict=False)
    page_count = len(reader.pages)
    required_page = max(int(record["page"]) for record in records)
    if page_count < required_page:
        raise RuntimeError(
            f"PDF da edição {issue_id} contém {page_count} página(s), "
            f"mas a busca cita a página {required_page}"
        )
    return save_download(
        _ResponseDownload(content, f"DOEMA-{issue_id}.pdf"),
        STATE,
        keyword,
        date_value=date_value,
        extract_occurrences=False,
        deduplicate_identical=False,
    )


def search(keyword: str, date_value: str) -> None:
    occurrences_by_issue = _search_occurrences(keyword, date_value)
    print(f"[{STATE}] {len(occurrences_by_issue)} edição(ões) com ocorrência em {date_value}")
    failed_issues: list[str] = []
    for issue_id, records in occurrences_by_issue.items():
        try:
            pdf_path = _download_result(issue_id, keyword, date_value, records)
            save_occurrence_metadata(
                STATE, keyword, pdf_path.name, records, date_value=date_value
            )
        except Exception as error:
            failed_issues.append(issue_id)
            print(f"[{STATE}] falha ao baixar edição {issue_id}: {error}")
    if failed_issues:
        raise RuntimeError(
            f"{len(failed_issues)} edição(ões) não puderam ser baixadas para '{keyword}': "
            + ", ".join(failed_issues)
        )


def scrape(
    playwright=None,
    keywords: Iterable[str] | None = None,
    date_value: object | None = None,
    headless: bool = True,
) -> None:
    selected_keywords = list(config.KEYWORDS if keywords is None else keywords)
    normalized_date = normalize_date(date_value)
    failed_keywords: list[str] = []
    for keyword in selected_keywords:
        if not keyword or not keyword.strip():
            continue
        print(f"[{STATE}] pesquisando: {keyword}")
        try:
            search(keyword, normalized_date)
        except Exception as error:
            failed_keywords.append(keyword)
            print(f"[{STATE}] falha na busca '{keyword}': {error}")
    if failed_keywords:
        raise RuntimeError(
            f"{len(failed_keywords)} busca(s) falharam: {', '.join(failed_keywords)}"
        )


if __name__ == "__main__":
    scrape()
