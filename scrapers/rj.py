from __future__ import annotations

import binascii
import re
import zlib
from base64 import b64decode
from io import BytesIO
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qs, urlparse

from .common import (
    date_parts_br,
    run_for_keywords,
    save_download,
    scrape_with_playwright,
)


STATE = "RJ"
SEARCH_URL = "https://www.ioerj.com.br/portal/modules/conteudoonline/busca_do.php"


class _ResponseDownload:
    def __init__(self, content: bytes, filename: str) -> None:
        self._content = content
        self.suggested_filename = filename

    def save_as(self, target: str | Path) -> None:
        Path(target).write_bytes(self._content)


def _complete_pdf_content(content: bytes, expected_pages: int | None = None) -> bytes:
    if not content.startswith(b"%PDF"):
        raise RuntimeError("PDF do IOERJ não começa com a assinatura esperada")

    eof_at = content.rfind(b"%%EOF")
    if eof_at < 0:
        raise RuntimeError("PDF do IOERJ não termina no marcador %%EOF")
    suffix = content[eof_at + len(b"%%EOF"):]
    if suffix.strip(b"\x00 \t\r\n\f"):
        # O IOERJ anexa um comentário de assinatura compactado após %%EOF.
        signature = re.fullmatch(
            rb"\r?\n%([A-Za-z0-9+/]+={0,2})%\r?\n?", suffix
        )
        if signature is None:
            raise RuntimeError("PDF do IOERJ não termina no marcador %%EOF")
        try:
            zlib.decompress(b64decode(signature.group(1), validate=True))
        except (binascii.Error, ValueError, zlib.error) as error:
            raise RuntimeError("assinatura final do PDF do IOERJ inválida") from error
    complete = content[: eof_at + len(b"%%EOF")]

    try:
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(complete), strict=True)
        page_count = len(reader.pages)
    except Exception as error:
        raise RuntimeError(f"PDF do IOERJ inválido: {error}") from error
    if expected_pages is not None and page_count != expected_pages:
        raise RuntimeError(
            f"PDF do IOERJ incompleto: visualizador informou {expected_pages} "
            f"página(s), arquivo contém {page_count}"
        )
    return complete


def _result_journal_id(result_link) -> str:
    encoded_journal = parse_qs(
        urlparse(result_link.get_attribute("href") or "").query
    ).get("j", [""])[0]
    try:
        return b64decode(encoded_journal).decode("ascii")
    except Exception:
        return ""


def _result_filename(result_link, date_value: str) -> str:
    journal_id = _result_journal_id(result_link) or "desconhecido"
    return f"IOERJ-{date_value}-caderno-{journal_id}.pdf"


def _reported_result_count(result_text: str) -> int:
    count_match = re.search(
        r"(\d+)\s+mat[eé]rias?\s+encontradas?", result_text, re.IGNORECASE
    )
    if count_match is not None:
        return int(count_match.group(1))
    if re.search(
        r"Nenhuma\s+publica[cç][aã]o\s+foi\s+encontrada\.",
        result_text,
        re.IGNORECASE,
    ):
        return 0
    raise RuntimeError("o IOERJ não informou o total de resultados")


def _download_result(
    page,
    result_link,
    keyword: str,
    date_value: str,
) -> bool:
    detail_page = None
    try:
        with page.expect_popup(timeout=30_000) as detail_info:
            result_link.click()
        detail_page = detail_info.value
        detail_page.once("dialog", lambda dialog: dialog.dismiss())
        detail_page.wait_for_function(
            """() => window.PDFViewerApplication
                && PDFViewerApplication.pdfDocument
                && PDFViewerApplication.url""",
            timeout=60_000,
        )
        document = detail_page.evaluate(
            """() => ({
                url: PDFViewerApplication.url,
                pages: PDFViewerApplication.pdfDocument.numPages
            })"""
        )
        pdf_url = str(document.get("url") or "")
        page_count = int(document.get("pages") or 0)
        if not pdf_url or page_count < 1:
            raise RuntimeError("visualizador do IOERJ não informou o PDF completo")
        response = page.context.request.get(pdf_url, timeout=120_000)
        if response.status != 200:
            raise RuntimeError(f"PDF do IOERJ indisponível (HTTP {response.status})")
        content = _complete_pdf_content(response.body(), expected_pages=page_count)
        save_download(
            _ResponseDownload(content, _result_filename(result_link, date_value)),
            STATE,
            keyword,
            date_value=date_value,
            deduplicate_identical=False,
        )
        return True
    finally:
        if detail_page is not None:
            try:
                detail_page.close()
            except Exception:
                pass


def _process_results(
    page,
    keyword: str,
    date_value: str,
    journal_id: str,
) -> int:
    result_links = page.locator('a[href*="view_publicacao.php"]')
    total = result_links.count()
    result_text = page.locator("body").inner_text()
    reported = _reported_result_count(result_text)
    if (reported == 0) != (total == 0):
        raise RuntimeError("o IOERJ retornou uma lista de resultados inconsistente")
    if not total:
        return 0

    first_result = result_links.first
    if _result_journal_id(first_result) != journal_id:
        raise RuntimeError("o IOERJ retornou resultado de outro caderno")
    return int(
        _download_result(page, first_result, keyword, date_value)
    )


def _journal_ids(page) -> list[str]:
    options = page.locator('select[name="busca[jornal]"] option')
    identifiers = [
        str(options.nth(index).get_attribute("value") or "").strip()
        for index in range(options.count())
    ]
    identifiers = [identifier for identifier in identifiers if identifier]
    if not identifiers or len(identifiers) != len(set(identifiers)):
        raise RuntimeError("o IOERJ não informou uma lista válida de cadernos")
    return identifiers


def search(page, keyword: str, date_value: str) -> None:
    day, month, year = date_parts_br(date_value)
    page.goto(SEARCH_URL, wait_until="domcontentloaded")
    journal_ids = _journal_ids(page)
    phrase = keyword.strip().strip('"')
    saved = 0
    # O portal limita uma busca geral aos primeiros 100 resultados. Consultar
    # cada caderno separadamente permite obter seu PDF integral por um único hit.
    for journal_id in journal_ids:
        page.goto(SEARCH_URL, wait_until="domcontentloaded")
        page.locator('input[name="textobusca"]').fill(
            f'"{phrase}"' if phrase else keyword
        )
        page.locator('select[name="busca[jornal]"]').select_option(journal_id)
        page.locator('select[name="tipobusca"]').select_option("texto")
        page.locator('input[name="datapublicacao[dia]"]').fill(day)
        page.locator('input[name="datapublicacao[mes]"]').fill(month)
        page.locator('input[name="datapublicacao[ano]"]').fill(year)

        with page.expect_navigation(wait_until="domcontentloaded"):
            page.locator('input[name="buscar"]').click()
        saved += _process_results(page, keyword, date_value, journal_id)
    print(f"[{STATE}] {saved} caderno(s) completo(s) com ocorrência em {date_value}")


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
