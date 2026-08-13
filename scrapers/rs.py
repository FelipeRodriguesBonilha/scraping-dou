from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Iterable
from urllib.parse import urlencode

from playwright.sync_api import Page, Playwright

from scrapers.common import (
    filter_occurrence_pages,
    read_occurrence_download,
    run_for_keywords,
    save_download,
    save_occurrence_pages,
    save_occurrence_text,
    scrape_with_playwright,
)


STATE = "RS"
API_BASE = "https://doe-backend.pro.rs.gov.br/public"
API_REQUEST_ATTEMPTS = 3
API_REQUEST_TIMEOUT_MS = 60_000
MAX_SEARCH_PAGES = 10_000


class _ResponseDownload:
    def __init__(self, content: bytes, filename: str) -> None:
        self._content = content
        self.suggested_filename = filename

    def save_as(self, target: str | Path) -> None:
        Path(target).write_bytes(self._content)


def _get_json(page: Page, url: str) -> dict:
    last_error: Exception | None = None
    for attempt in range(1, API_REQUEST_ATTEMPTS + 1):
        try:
            response = page.context.request.get(url, timeout=API_REQUEST_TIMEOUT_MS)
        except Exception as error:
            last_error = error
        else:
            if response.status == 200:
                payload = response.json()
                if not isinstance(payload, dict):
                    raise RuntimeError("API do RS retornou um JSON inesperado")
                return payload
            if response.status < 500 and response.status != 429:
                raise RuntimeError(f"API do RS indisponível (HTTP {response.status})")
            last_error = RuntimeError(f"API do RS indisponível (HTTP {response.status})")

        if attempt < API_REQUEST_ATTEMPTS:
            print(
                f"[{STATE}] API indisponível "
                f"(tentativa {attempt}/{API_REQUEST_ATTEMPTS}); tentando novamente..."
            )
            time.sleep(attempt)

    raise RuntimeError(
        "API do RS não respondeu após "
        f"{API_REQUEST_ATTEMPTS} tentativas: {last_error}"
    ) from last_error


def _search_url(keyword: str, date_value: str, page_number: int) -> str:
    parameters = {
        "page": page_number,
        "tipoDiario": 1,
        "queryString": keyword,
        "dataIni": date_value,
        "dataFim": date_value,
    }
    return f"{API_BASE}/materias/?{urlencode(parameters)}"


def _search_page(payload: dict) -> tuple[list[str], int, int, int]:
    collection = payload.get("collection")
    if not isinstance(collection, list):
        raise RuntimeError("API do RS retornou resultados em formato inesperado")
    try:
        total = int(payload.get("collectionSize", 0))
        page_size = int(payload.get("pageSize", 0))
    except (TypeError, ValueError) as error:
        raise RuntimeError("API do RS não informou a paginação da busca") from error
    if total < 0 or page_size <= 0:
        raise RuntimeError("API do RS informou uma paginação inválida")

    material_ids: list[str] = []
    for result in collection:
        if not isinstance(result, dict):
            continue
        origin = str(result.get("origem") or "MATERIA").strip().upper()
        if origin != "MATERIA":
            continue
        material_id = str(result.get("id") or "").strip()
        if material_id.isdigit():
            material_ids.append(material_id)
    return material_ids, total, page_size, len(collection)


def _get_pdf(page: Page, url: str, filename: str) -> _ResponseDownload:
    response = page.context.request.get(url, timeout=API_REQUEST_TIMEOUT_MS)
    content = response.body()
    if response.status != 200 or not content.startswith(b"%PDF"):
        raise RuntimeError(f"PDF do RS indisponível (HTTP {response.status})")
    return _ResponseDownload(content, filename)


def _publication_date(value: object) -> str | None:
    try:
        return datetime.strptime(str(value), "%d-%m-%Y").date().isoformat()
    except (TypeError, ValueError):
        return None


def _edition_id(diary: dict, occurrence: dict) -> int | None:
    edition_number = occurrence.get("edicaoDoDia") or 1
    try:
        edition_number = int(edition_number)
    except (TypeError, ValueError):
        edition_number = 1
    if edition_number <= 1:
        edition_id = diary.get("id")
        return int(edition_id) if str(edition_id).isdigit() else None

    for edition in diary.get("edicoes", []):
        if not isinstance(edition, dict):
            continue
        if str(edition.get("nroEdicao")) == str(edition_number):
            edition_id = edition.get("id")
            return int(edition_id) if str(edition_id).isdigit() else None
    return None


def _page_id(diary: dict, page_number: object) -> int | None:
    for page_info in diary.get("paginas", []):
        if not isinstance(page_info, dict):
            continue
        if str(page_info.get("nroPagina")) == str(page_number):
            page_id = page_info.get("id")
            return int(page_id) if str(page_id).isdigit() else None
    return None


def _download_material(
    page: Page,
    material_id: str,
    keyword: str,
    date_value: str,
    saved_editions: dict[str, Path],
    seen_pages: set[str],
    native_occurrences: dict[str, list[tuple[int, str]]],
    failed_page_editions: set[str],
) -> bool:
    edition_key: str | None = None
    try:
        occurrence = _get_json(page, f"{API_BASE}/materias/{material_id}")
        publication_date = _publication_date(occurrence.get("dataPublicacao"))
        if publication_date != date_value:
            print(
                f"[{STATE}] matéria fora da data solicitada ignorada: "
                f"{material_id} ({publication_date or 'data ausente'})"
            )
            return False
        diary = _get_json(
            page,
            f"{API_BASE}/diarios/consultar/?tipoDiario=1&data={publication_date}&tipoRetorno=2",
        )
        edition_id = _edition_id(diary, occurrence)
        page_number = occurrence.get("pagina")
        page_id = _page_id(diary, page_number)
        if edition_id is None or page_id is None or not str(page_number).isdigit():
            raise RuntimeError("matéria sem edição ou página identificável")

        edition_key = str(edition_id)
        if edition_key not in saved_editions:
            saved_editions[edition_key] = save_download(
                _get_pdf(
                    page,
                    f"{API_BASE}/diarios/download/{edition_id}/pdf",
                    f"DORS-{publication_date}-edicao-{edition_id}.pdf",
                ),
                STATE,
                keyword,
                date_value=date_value,
                extract_occurrences=False,
                deduplicate_identical=True,
            )

        page_key = str(page_id)
        if page_key in seen_pages or edition_key in failed_page_editions:
            return False
        native_occurrences.setdefault(edition_key, []).extend(
            filter_occurrence_pages(
                read_occurrence_download(
                    _get_pdf(
                        page,
                        f"{API_BASE}/paginas/download/pdf-inline/{page_id}",
                        f"DORS-{publication_date}-edicao-{edition_id}-pagina-{int(page_number):03}.pdf",
                    ),
                    page_number=int(page_number),
                ),
                keyword,
            )
        )
        seen_pages.add(page_key)
        return True
    except Exception as error:
        if edition_key is not None:
            failed_page_editions.add(edition_key)
        if edition_key is None or edition_key not in saved_editions:
            print(f"[{STATE}] falha ao baixar matéria {material_id}: {error}")
        return False


def _download_search_page(
    page: Page,
    material_ids: Iterable[str],
    keyword: str,
    date_value: str,
    saved_editions: dict[str, Path],
    seen_pages: set[str],
    seen_materials: set[str],
    native_occurrences: dict[str, list[tuple[int, str]]],
    failed_page_editions: set[str],
) -> int:
    saved = 0
    for index, material_id in enumerate(material_ids, start=1):
        if material_id in seen_materials:
            continue
        seen_materials.add(material_id)
        try:
            if _download_material(
                page,
                material_id,
                keyword,
                date_value,
                saved_editions,
                seen_pages,
                native_occurrences,
                failed_page_editions,
            ):
                saved += 1
        except Exception as error:
            print(f"[{STATE}] falha ao baixar resultado {index}: {error}")
    return saved


def _save_occurrences(
    keyword: str,
    date_value: str,
    saved_editions: dict[str, Path],
    native_occurrences: dict[str, list[tuple[int, str]]],
    failed_page_editions: set[str],
) -> None:
    for edition_key in set(saved_editions) | set(native_occurrences):
        full_pdf = saved_editions.get(edition_key)
        pages = native_occurrences.get(edition_key, [])
        filename = (
            full_pdf.name
            if full_pdf is not None
            else f"DORS-{date_value}-edicao-{edition_key}.pdf"
        )
        if pages and edition_key not in failed_page_editions:
            save_occurrence_text(
                STATE,
                keyword,
                filename,
                pages,
                date_value=date_value,
            )
            continue
        if full_pdf is not None and save_occurrence_pages(full_pdf, keyword):
            continue
        if pages:
            save_occurrence_text(
                STATE,
                keyword,
                filename,
                pages,
                date_value=date_value,
            )


def search(page: Page, keyword: str, date_value: str) -> None:
    saved_editions: dict[str, Path] = {}
    seen_pages: set[str] = set()
    seen_materials: set[str] = set()
    native_occurrences: dict[str, list[tuple[int, str]]] = {}
    failed_page_editions: set[str] = set()

    for page_number in range(1, MAX_SEARCH_PAGES + 1):
        material_ids, total, page_size, result_count = _search_page(
            _get_json(page, _search_url(keyword, date_value, page_number))
        )
        if result_count == 0:
            break
        _download_search_page(
            page,
            material_ids,
            keyword,
            date_value,
            saved_editions,
            seen_pages,
            seen_materials,
            native_occurrences,
            failed_page_editions,
        )
        if page_number * page_size >= total:
            break

    _save_occurrences(
        keyword,
        date_value,
        saved_editions,
        native_occurrences,
        failed_page_editions,
    )


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
