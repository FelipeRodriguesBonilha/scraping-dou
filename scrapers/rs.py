from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qs, urljoin, urlparse

from playwright.sync_api import Page, Playwright

from scrapers.common import (
    click_next,
    date_as_br,
    filter_occurrence_pages,
    read_occurrence_download,
    run_for_keywords,
    save_download,
    save_occurrence_pages,
    save_occurrence_text,
    scrape_with_playwright,
)


STATE = "RS"
URL = "https://www.diariooficial.rs.gov.br/resultado"
API_BASE = "https://doe-backend.pro.rs.gov.br/public"


class _ResponseDownload:
    def __init__(self, content: bytes, filename: str) -> None:
        self._content = content
        self.suggested_filename = filename

    def save_as(self, target: str | Path) -> None:
        Path(target).write_bytes(self._content)


def _get_json(page: Page, url: str) -> dict:
    response = page.context.request.get(url, timeout=60_000)
    if response.status != 200:
        raise RuntimeError(f"API do RS indisponível (HTTP {response.status})")
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("API do RS retornou um JSON inesperado")
    return payload


def _get_pdf(page: Page, url: str, filename: str) -> _ResponseDownload:
    response = page.context.request.get(url, timeout=60_000)
    content = response.body()
    if response.status != 200 or not content.startswith(b"%PDF"):
        raise RuntimeError(f"PDF do RS indisponível (HTTP {response.status})")
    return _ResponseDownload(content, filename)


def _material_id(href: str, base_url: str) -> str | None:
    parsed = urlparse(urljoin(base_url, href))
    material_id = parse_qs(parsed.query).get("id", [""])[0]
    return material_id if material_id.isdigit() else None


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


def _download_current_page(
    page: Page,
    keyword: str,
    date_value: str,
    saved_editions: dict[str, Path],
    seen_pages: set[str],
    seen_materials: set[str],
    native_occurrences: dict[str, list[tuple[int, str]]],
    failed_page_editions: set[str],
) -> int:
    result_links = page.locator("a[href*='/materia']")
    saved = 0
    for index in range(result_links.count()):
        href = result_links.nth(index).get_attribute("href") or ""
        material_id = _material_id(href, page.url)
        if material_id is None or material_id in seen_materials:
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
            print(f"[{STATE}] falha ao baixar resultado {index + 1}: {error}")
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
    page.goto(URL, wait_until="domcontentloaded")
    page.get_by_role("textbox", name="Digite").fill(keyword)
    formatted_date = date_as_br(date_value)
    page.get_by_role("textbox", name="Data inicial").fill(formatted_date)
    page.get_by_role("textbox", name="Data final").fill(formatted_date)
    page.get_by_role("button", name="Buscar").click()
    page.wait_for_timeout(750)

    next_page = page.get_by_text("»", exact=True)
    saved_editions: dict[str, Path] = {}
    seen_pages: set[str] = set()
    seen_materials: set[str] = set()
    native_occurrences: dict[str, list[tuple[int, str]]] = {}
    failed_page_editions: set[str] = set()
    for _ in range(10_000):
        _download_current_page(
            page,
            keyword,
            date_value,
            saved_editions,
            seen_pages,
            seen_materials,
            native_occurrences,
            failed_page_editions,
        )
        if not click_next(next_page):
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
