from __future__ import annotations

from collections.abc import Iterable
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader

from scrapers.common import filter_occurrence_pages, save_download, save_occurrence_text


class _BytesDownload:
    def __init__(self, content: bytes, filename: str) -> None:
        self._content = content
        self.suggested_filename = filename

    def save_as(self, target: str | Path) -> None:
        Path(target).write_bytes(self._content)


def _read_pages(content: bytes, *, strict: bool) -> list[tuple[int, str]]:
    reader = PdfReader(BytesIO(content), strict=strict)
    pages: list[tuple[int, str]] = []
    for page_number, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception as error:
            raise RuntimeError(
                f"não foi possível extrair o texto da página {page_number}"
            ) from error
        pages.append((page_number, text))
    return pages


def _extract_pages(content: bytes) -> list[tuple[int, str]]:
    if not content.startswith(b"%PDF"):
        raise RuntimeError("o arquivo retornado pelo portal não é um PDF")
    eof_at = content.rfind(b"%%EOF")
    if eof_at < 0 or content[eof_at + 5:].strip(b"\x00 \t\r\n\f"):
        raise RuntimeError("o PDF retornado pelo portal está truncado")

    try:
        pages = _read_pages(content, strict=True)
    except Exception as strict_error:
        try:
            pages = _read_pages(content, strict=False)
        except Exception as error:
            raise RuntimeError(f"PDF inválido: {error}") from strict_error

    if not pages:
        raise RuntimeError("o PDF não possui páginas")
    return pages


def save_matching_pdf(
    data: bytes,
    state: str,
    keywords: Iterable[str],
    filename: str,
    date_value: str,
    *,
    expected_pages: int | None = None,
) -> list[Path]:
    pages = _extract_pages(data)
    if expected_pages is not None and len(pages) != expected_pages:
        raise RuntimeError(
            f"PDF incompleto: o portal informou {expected_pages} página(s), "
            f"mas o arquivo contém {len(pages)}"
        )

    searchable_pages = [(number, text) for number, text in pages if text.strip()]
    if not searchable_pages:
        raise RuntimeError("o PDF não possui texto extraível; OCR é necessário")
    if len(searchable_pages) != len(pages):
        print(
            f"[{state.upper()}] aviso: {len(pages) - len(searchable_pages)} de "
            f"{len(pages)} página(s) sem texto extraível; OCR pode ser necessário"
        )

    saved: list[Path] = []
    for keyword in keywords:
        occurrence_pages = filter_occurrence_pages(searchable_pages, keyword)
        if not occurrence_pages:
            continue

        pdf_path = save_download(
            _BytesDownload(data, filename),
            state,
            keyword,
            filename,
            date_value=date_value,
            extract_occurrences=False,
            deduplicate_identical=False,
        )
        save_occurrence_text(
            state,
            keyword,
            pdf_path.name,
            occurrence_pages,
            date_value=date_value,
        )
        saved.append(pdf_path)
    return saved
