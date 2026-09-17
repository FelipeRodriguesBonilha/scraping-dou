from __future__ import annotations

from urllib.parse import quote, urlencode

from scrapers.common import (
    DEFAULT_MAX_PAGES,
    filter_occurrence_pages,
    normalize_date,
    save_occurrence_text,
)


def _scalar(value):
    return value[0] if isinstance(value, list) and value else value


def _source_date(source: dict) -> str:
    value = _scalar(source.get("data"))
    if value:
        return normalize_date(str(value)[:10])
    parts = [_scalar(source.get(name)) for name in ("year", "month", "day")]
    return normalize_date("-".join(str(part or "") for part in parts))


def _edition_catalog(request, base_url: str, date_value: str) -> dict[str, dict]:
    response = request.get(
        f"{base_url}/apifront/portal/edicoes/edicoes_from_data/{date_value}.json",
        timeout=60_000,
    )
    if not response.ok:
        raise RuntimeError(f"catálogo de edições indisponível (HTTP {response.status})")
    payload = response.json()
    if payload.get("erro") or not isinstance(payload.get("itens"), list):
        raise RuntimeError("resposta inválida do catálogo de edições")

    editions: dict[str, dict] = {}
    for item in payload["itens"]:
        issue_id = str(item.get("id") or "")
        if not issue_id:
            raise RuntimeError("catálogo retornou edição sem identificador")
        if normalize_date(str(item.get("data") or "")) != date_value:
            raise RuntimeError("catálogo retornou edição fora da data solicitada")
        editions[issue_id] = {
            "pages": int(item.get("paginas") or 0),
            "number": str(item.get("numero") or "").strip(),
            "supplement": bool(int(item.get("suplemento") or 0)),
        }
    return editions


def _reader_url(
    base_url: str,
    viewer: str,
    issue_id: str,
    page_number: int,
    keyword: str,
) -> str:
    if viewer == "flip":
        term = quote(keyword, safe="")
        return (
            f"{base_url}/ver-flip/{issue_id}/#/e:{issue_id}/p:{page_number}"
            f"?find={term}"
        )
    return f"{base_url}/ver-html/{issue_id}/#/e:{issue_id}"


def search_public_reader(
    page,
    keyword: str,
    date_value: str,
    *,
    state: str,
    base_url: str,
    viewer: str,
    reader_base_url: str | None = None,
) -> None:
    date_value = normalize_date(date_value)
    base_url = base_url.rstrip("/")
    request = page.context.request
    catalog = _edition_catalog(request, base_url, date_value)

    editions: dict[str, dict] = {}
    seen_hits: set[str] = set()
    processed = 0
    exact_term = f'"{keyword.strip().strip(chr(34))}"'
    for result_page in range(DEFAULT_MAX_PAGES):
        query = urlencode({"1": "1", "q": exact_term})
        url = (
            f"{base_url}/busca/busca/buscar/query/{result_page}"
            f"/di:{date_value}/df:{date_value}/?{query}"
        )
        response = request.get(url, timeout=60_000)
        if not response.ok:
            raise RuntimeError(f"busca pública indisponível (HTTP {response.status})")
        payload = response.json()
        if payload.get("error") or payload.get("timed_out") or "hits" not in payload:
            raise RuntimeError("o portal não concluiu a busca pública")

        hit_block = payload["hits"]
        if (
            not isinstance(hit_block, dict)
            or "total" not in hit_block
            or not isinstance(hit_block.get("hits"), list)
        ):
            raise RuntimeError("a busca pública não informou a paginação")
        hits = hit_block["hits"]
        total_value = hit_block["total"]
        if isinstance(total_value, dict):
            if total_value.get("relation") not in (None, "eq"):
                raise RuntimeError(
                    "a busca pública não informou um total exato de resultados"
                )
            total_value = total_value.get("value")
        try:
            total = int(total_value)
        except (TypeError, ValueError) as error:
            raise RuntimeError("a busca pública não informou o total de resultados") from error
        if total < 0 or processed + len(hits) > total:
            raise RuntimeError("a busca pública informou um total inválido")
        if not hits and processed < total:
            raise RuntimeError("paginação da busca interrompida antes do fim")

        for hit in hits:
            hit_id = str(hit.get("_id") or "")
            if not hit_id or hit_id in seen_hits:
                raise RuntimeError("a busca repetiu ou omitiu o identificador de um resultado")
            seen_hits.add(hit_id)

            source = hit.get("_source") or hit.get("fields") or {}
            if _source_date(source) != date_value:
                raise RuntimeError("a busca retornou resultado fora da data solicitada")
            issue_id = str(
                _scalar(source.get("edicao_id") or source.get("diario_id")) or ""
            )
            page_number = int(_scalar(source.get("pagina")) or 0)
            text = str(_scalar(source.get("conteudo")) or "")
            if issue_id not in catalog:
                raise RuntimeError("a busca retornou edição ausente do catálogo da data")
            catalog_pages = catalog[issue_id]["pages"]
            if page_number < 1 or (catalog_pages and page_number > catalog_pages):
                raise RuntimeError("a busca retornou um número de página inválido")
            matches = filter_occurrence_pages([(page_number, text)], keyword)
            if not matches:
                continue

            edition = editions.setdefault(
                issue_id,
                {
                    "pages": {},
                    "number": catalog[issue_id]["number"],
                    "supplement": catalog[issue_id]["supplement"],
                },
            )
            edition["pages"][page_number] = text

        processed += len(hits)
        if processed >= total:
            break
    else:
        raise RuntimeError("a busca pública excedeu o limite de páginas")

    for issue_id, edition in editions.items():
        pages = sorted(edition["pages"].items())
        label = edition["number"] or f"edicao-{issue_id}"
        suffix = f"-suplemento-{issue_id}" if edition["supplement"] else ""
        source_name = f"DOE-{state}-{date_value}-{label}{suffix}.html"
        save_occurrence_text(
            state,
            keyword,
            source_name,
            pages,
            date_value=date_value,
            source_url=_reader_url(
                reader_base_url or base_url, viewer, issue_id, pages[0][0], keyword
            ),
        )
    print(
        f"[{state}] {len(editions)} edição(ões) com ocorrência exata "
        f"consultada(s) publicamente em {date_value}"
    )
