from __future__ import annotations

from io import BytesIO
from pathlib import Path
import re
from typing import Iterable
from urllib.parse import urljoin

from playwright.sync_api import Page, Playwright

from scrapers.common import (
    matches_date,
    run_for_keywords,
    save_download,
    save_occurrence_metadata,
    scrape_with_playwright,
)


STATE = "PI"
URL = "https://www.diario.pi.gov.br/doe/busca"
PDF_BASE_URL = "https://www.diario.pi.gov.br/doe/"
SEARCH_API_URL = "https://www.diario.pi.gov.br/doe/Api/buscaavancada.json"
SEARCH_TIMEOUT_MS = 60_000
DOWNLOAD_TIMEOUT_MS = 120_000


class _ResponseDownload:
    def __init__(self, content: bytes, filename: str) -> None:
        self._content = content
        self.suggested_filename = filename

    def save_as(self, target: str | Path) -> None:
        Path(target).write_bytes(self._content)


def _result_matches_date(result: dict, date_value: str) -> bool:
    return matches_date(result.get("dadosDiario"), date_value)


def _attachment_path(result: dict) -> str | None:
    attachment = str(result.get("anexodiario") or "").strip().strip("/")
    if not attachment or not attachment.lower().endswith(".pdf"):
        return None
    return attachment


def _plain_text(value: object) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", str(value or ""))).strip()


def _occurrence_metadata(result: dict) -> dict[str, str]:
    diary = _plain_text(result.get("dadosDiario"))
    date_match = re.search(r"(?<!\d)(\d{1,2}/\d{1,2}/\d{4})(?!\d)", diary)
    section_match = re.search(r"\bem\s+[\"“]?(.+?)[\"”]?$", diary, re.IGNORECASE)
    section = section_match.group(1).strip(" \"“”") if section_match else ""
    return {
        "date": date_match.group(1) if date_match else "",
        "section": section,
        "term": _plain_text(result.get("acertos")),
    }


def _search_results(page: Page, keyword: str) -> list[dict]:
    print(f"[{STATE}] consultando portal para '{keyword}'...")
    response = page.context.request.post(
        SEARCH_API_URL,
        form={"filter_texto": keyword},
        headers={
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Referer": URL,
            "X-Requested-With": "XMLHttpRequest",
        },
        timeout=SEARCH_TIMEOUT_MS,
    )
    if response.status != 200:
        raise RuntimeError(f"busca do PI indisponível (HTTP {response.status})")

    payload = response.json()
    if payload is None:
        return []
    if not isinstance(payload, dict):
        raise RuntimeError("resposta de busca do PI em formato inesperado")

    results = payload.get("resposta", [])
    if not isinstance(results, list):
        raise RuntimeError("lista de resultados do PI em formato inesperado")
    print(f"[{STATE}] portal retornou {len(results)} ocorrência(s) para '{keyword}'")
    return [result for result in results if isinstance(result, dict)]


def _pdf_content(response) -> bytes:
    content = response.body()
    if response.status != 200:
        raise RuntimeError(f"PDF do PI indisponível (HTTP {response.status})")
    if not content.startswith(b"%PDF"):
        raise RuntimeError("PDF do PI não começa com a assinatura esperada")
    if b"%%EOF" not in content:
        raise RuntimeError("PDF do PI não possui o marcador final %%EOF")

    try:
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(content), strict=True)
        len(reader.pages)
    except Exception as error:
        raise RuntimeError(f"PDF do PI inválido: {error}") from error
    return content


def _download_pdf(
    page: Page, href: str, keyword: str, date_value: str, index: int
) -> Path | None:
    try:
        response = page.context.request.get(
            href,
            headers={"Referer": URL},
            timeout=DOWNLOAD_TIMEOUT_MS,
        )
        return save_download(
            _ResponseDownload(_pdf_content(response), Path(href).name),
            STATE,
            keyword,
            date_value=date_value,
            extract_occurrences=False,
        )
    except Exception as error:
        print(f"[{STATE}] falha ao baixar resultado {index}: {error}")
        return None


def search(page: Page, keyword: str, date_value: str) -> None:
    try:
        page.goto(URL, wait_until="commit", timeout=15_000)
    except Exception as error:
        print(f"[{STATE}] não foi possível abrir a página de busca: {error}")
    try:
        results = _search_results(page, keyword)
    except Exception as error:
        print(f"[{STATE}] falha na busca para '{keyword}': {error}")
        return

    occurrences_by_issue: dict[str, list[dict[str, str]]] = {}
    for result in results:
        if not _result_matches_date(result, date_value):
            continue
        attachment = _attachment_path(result)
        if attachment is None:
            continue
        href = urljoin(PDF_BASE_URL, f"files/diarios/anexo/{attachment}")
        occurrences_by_issue.setdefault(href, []).append(_occurrence_metadata(result))

    print(
        f"[{STATE}] {len(occurrences_by_issue)} edição(ões) encontrada(s) "
        f"para {date_value}"
    )
    for index, (href, records) in enumerate(occurrences_by_issue.items(), start=1):
        pdf_path = _download_pdf(page, href, keyword, date_value, index)
        if pdf_path is None:
            continue
        try:
            save_occurrence_metadata(
                STATE,
                keyword,
                pdf_path.name,
                records,
                date_value=date_value,
            )
        except Exception as error:
            print(f"[{STATE}] falha ao salvar ocorrências do resultado {index}: {error}")


def scrape(
    playwright: Playwright | None = None,
    keywords: Iterable[str] | None = None,
    date_value: object | None = None,
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
