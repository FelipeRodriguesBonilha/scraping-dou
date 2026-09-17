"""DOE/SP: full sections, extra editions and supplements from the public APIs."""
from __future__ import annotations

import json
import re
from urllib.error import HTTPError
from urllib.parse import quote, urlencode, urlparse

import config

from scrapers.common import DEFAULT_MAX_PAGES, normalize_date
from scrapers.public_api import get_bytes, get_json
from scrapers.public_pdf import save_matching_pdf

STATE = "SP"
PLAYWRIGHT_REQUIRED = False
SEARCH_API = "https://do-api-web-search.doe.sp.gov.br/"
PDF_API = "https://do-api-publication-pdf.doe.sp.gov.br/"
LEGACY_PDF = "https://www.imprensaoficial.com.br/downloads/pdf/edicao/"
LEGACY_NOT_FOUND = re.compile(
    br"<title>\s*404\s*-\s*File or directory not found\.?\s*</title>",
    re.IGNORECASE,
)
# The public Sumário links these complementary files as well as the newer API.
LEGACY_SECTIONS = {
    ("Executivo", "Atos Normativos"): ("EXEC1", "EXEC1S", "EXEC1SUP", "EXEC1SUP - LDO"),
    ("Executivo", "Atos de Pessoal"): ("EXEC2", "EXEC2S", "EXEC2SUP"),
    ("Executivo", "Atos de Gestão e Despesas"): ("EXEC3", "EXEC3S", "EXEC3SUP"),
    ("Legislativo", "Atos Legislativos e Parlamentares da Assembleia"): ("LG", "LGS", "LGSUP"),
    ("Municípios", "Atos Municipais"): ("MNCP",),
    ("Empresarial", "Atos Empresariais"): ("EM", "EMS"),
    ("Jucesp", "Junta Comercial"): ("JUCESP",),
    ("BRASIL", "SUDESTE"): ("SUDESTE",),
}


def _matching_sections(keywords: list[str], day: str) -> set[tuple[str, str]]:
    matches: set[tuple[str, str]] = set()
    for keyword in keywords:
        seen: set[str] = set()
        processed = 0
        for page_number in range(1, DEFAULT_MAX_PAGES + 1):
            payload = get_json(
                SEARCH_API
                + "v2/advanced-search/publications?"
                + urlencode(
                    {
                        "PageNumber": page_number,
                        "Terms[0]": keyword,
                        "FromDate": day,
                        "ToDate": day,
                        "PageSize": 100,
                        "SortField": "Date",
                    }
                )
            )
            required = {
                "items",
                "currentPage",
                "totalPages",
                "totalItems",
                "pageSize",
                "hasNextPage",
            }
            if not isinstance(payload, dict) or not required.issubset(payload):
                raise RuntimeError("paginação da busca avançada de SP inválida")
            items = payload["items"]
            if not isinstance(items, list):
                raise RuntimeError("resultados da busca avançada de SP inválidos")
            current_page = int(payload["currentPage"])
            total_pages = int(payload["totalPages"])
            total_items = int(payload["totalItems"])
            page_size = int(payload["pageSize"])
            has_next = bool(payload["hasNextPage"])
            expected_pages = (
                (total_items + page_size - 1) // page_size if page_size > 0 else -1
            )
            if (
                current_page != page_number
                or total_items < 0
                or total_pages < 0
                or page_size < 1
                or total_pages != expected_pages
                or processed + len(items) > total_items
            ):
                raise RuntimeError("totais da busca avançada de SP inconsistentes")

            for item in items:
                identifier = str(item.get("id") or "")
                if not identifier or identifier in seen:
                    raise RuntimeError("a busca avançada de SP repetiu um resultado")
                seen.add(identifier)
                if normalize_date(str(item.get("date") or "")[:10]) != day:
                    raise RuntimeError("a busca avançada de SP retornou outra data")
                hierarchy = [
                    part.strip()
                    for part in str(item.get("hierarchy") or "").split(">")
                    if part.strip()
                ]
                if len(hierarchy) < 2:
                    raise RuntimeError("resultado de SP não informou caderno e seção")
                matches.add((hierarchy[0], hierarchy[1]))

            processed += len(items)
            if page_number >= total_pages:
                if processed != total_items or has_next:
                    raise RuntimeError("a busca avançada de SP terminou incompleta")
                break
            if not items or not has_next:
                raise RuntimeError("a busca avançada de SP interrompeu a paginação")
        else:
            raise RuntimeError("a busca avançada de SP excedeu o limite de páginas")
    return matches


def _optional_json(url: str):
    try:
        data = get_bytes(url)
    except HTTPError as error:
        if error.code == 404:
            return None
        raise
    if not data.strip():
        return None
    try:
        return json.loads(data)
    except json.JSONDecodeError as error:
        raise RuntimeError("SP retornou metadados de edição inválidos") from error


def _items(payload: dict, label: str) -> list:
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise RuntimeError(f"catálogo de {label} de SP inválido")
    return payload["items"]


def _edition_links(journal: dict, section: dict, day: str):
    params = urlencode({"JournalId": journal["id"], "RootSectionId": section["id"],
                        "EditionDate": day})
    main = _optional_json(PDF_API + "v1/editions/url?" + params)
    if main is not None:
        if not main.get("url"):
            raise RuntimeError("SP não informou a URL da edição completa")
        yield main["url"], f"{main['fileName']}.pdf", False
    supplements = _optional_json(PDF_API + "v1/supplementary-editions/url?" + params)
    if supplements is not None:
        if not isinstance(supplements.get("supplementaryEditionsUrls"), list):
            raise RuntimeError("catálogo de suplementos de SP inválido")
        for document in supplements["supplementaryEditionsUrls"]:
            if not document.get("url"):
                raise RuntimeError("SP informou suplemento sem arquivo disponível")
            yield document["url"], f"{document['fileName']}.pdf", False
    legacy = LEGACY_SECTIONS.get((journal["name"], section["name"]), ())
    # The modern main edition takes precedence; public legacy extras may coexist.
    for suffix in (legacy[1:] if main is not None else legacy):
        filename = day.replace("-", "") + suffix + ".pdf"
        yield LEGACY_PDF + quote(filename), filename, True


def scrape(playwright=None, *, keywords=None, date_value=None, headless=True) -> None:
    selected = [
        keyword
        for keyword in (config.KEYWORDS if keywords is None else keywords)
        if keyword and keyword.strip()
    ]
    if not selected:
        print(f"[{STATE}] nenhuma palavra-chave informada")
        return
    day = normalize_date(date_value)
    matching_sections = _matching_sections(selected, day)
    if not matching_sections:
        print(f"[SP] nenhuma ocorrência exata encontrada em {day}")
        return
    journals = _items(get_json(SEARCH_API + "v2/journals?" + urlencode({"date": day})), "cadernos")
    seen_urls = set()
    located_sections: set[tuple[str, str]] = set()
    editions = saved = 0
    for journal in journals:
        sections = _items(get_json(SEARCH_API + "v2/sections?" + urlencode({
                        "journalId": journal["id"], "date": day})), "seções")
        for section in sections:
            section_key = (str(journal["name"]).strip(), str(section["name"]).strip())
            if section_key not in matching_sections:
                continue
            located_sections.add(section_key)
            print(f"[SP] consultando {journal['name']} / {section['name']}")
            section_files = 0
            for url, filename, optional in _edition_links(journal, section, day):
                # API historically returns http URLs although HTTPS is supported.
                if urlparse(url).hostname == urlparse(PDF_API).hostname:
                    url = "https://" + url.split("://", 1)[-1]
                if url in seen_urls:
                    section_files += 1
                    continue
                try:
                    data = get_bytes(url)
                except HTTPError as error:
                    if optional and error.code == 404:
                        continue
                    raise
                if not data.startswith(b"%PDF"):
                    if optional and LEGACY_NOT_FOUND.search(data[:8_192]):
                        continue
                    raise RuntimeError(
                        f"SP: {filename} não retornou um PDF válido"
                    )
                seen_urls.add(url)
                section_files += 1
                editions += 1
                saved += len(save_matching_pdf(data, STATE, selected,
                             f"SP-{day}-{filename}", day))
            if not section_files:
                raise RuntimeError(
                    f"SP: nenhum PDF completo obtido para {section['name']}"
                )
    missing_sections = matching_sections - located_sections
    if missing_sections:
        missing = ", ".join(" / ".join(section) for section in sorted(missing_sections))
        raise RuntimeError(f"SP não localizou no catálogo: {missing}")
    print(f"[SP] {editions} edição(ões) consultada(s); {saved} arquivo(s) com ocorrências")


if __name__ == "__main__":
    scrape()
