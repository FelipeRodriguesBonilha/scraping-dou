"""Public IONews search and complete-edition downloads (GO and ES)."""
from __future__ import annotations

from urllib.parse import urlencode

from .common import DEFAULT_MAX_PAGES, normalize_date
from .public_pdf import save_matching_pdf


def _scalar(value):
    return value[0] if isinstance(value, list) and value else value


def search_ionews(page, keyword: str, date_value: str, *, state: str, base_url: str) -> None:
    date_value = normalize_date(date_value)
    base_url = base_url.rstrip("/")
    request = page.context.request
    editions: dict[str, int | None] = {}
    seen: set[str] = set()
    processed = 0
    for index in range(DEFAULT_MAX_PAGES):
        params = urlencode({"q": '"' + keyword.strip().strip('"') + '"'})
        url = (
            f"{base_url}/busca/busca/buscar/query/{index}"
            f"/di:{date_value}/df:{date_value}/?{params}"
        )
        response = request.get(url, timeout=60_000)
        if not response.ok:
            raise RuntimeError(f"busca indisponível (HTTP {response.status})")
        result = response.json()
        hit_block = result.get("hits")
        if (
            result.get("error")
            or result.get("timed_out")
            or not isinstance(hit_block, dict)
            or "total" not in hit_block
            or not isinstance(hit_block.get("hits"), list)
        ):
            raise RuntimeError("o portal não concluiu a busca de edições")
        hits = hit_block["hits"]
        total = hit_block["total"]
        if isinstance(total, dict):
            if total.get("relation") not in (None, "eq"):
                raise RuntimeError("a busca não informou um total exato de resultados")
            total = total.get("value")
        try:
            total = int(total)
        except (TypeError, ValueError) as error:
            raise RuntimeError("a busca não informou o total de resultados") from error
        if total < 0 or processed + len(hits) > total:
            raise RuntimeError("a busca informou um total de resultados inválido")
        if not hits and processed < int(total):
            raise RuntimeError("paginação interrompida antes de todos os resultados")
        for hit in hits:
            source = hit.get("_source") or hit.get("fields") or {}
            issue_id = str(_scalar(source.get("edicao_id") or source.get("diario_id")) or "")
            if not issue_id.isdigit():
                raise RuntimeError("resultado sem identificador de edição")
            published = _scalar(source.get("data"))
            if not published:
                published = "-".join(
                    str(_scalar(source.get(key, "")))
                    for key in ("year", "month", "day")
                )
            if normalize_date(str(published)[:10]) != date_value:
                raise RuntimeError("o portal retornou uma edição fora da data solicitada")
            key = str(hit.get("_id") or f"{issue_id}:{_scalar(source.get('pagina'))}")
            if key in seen:
                raise RuntimeError("o portal repetiu resultados durante a paginação")
            seen.add(key)
            count = _scalar(source.get("paginas"))
            page_count = None if count in (None, "") else int(count)
            if page_count is not None and page_count < 1:
                raise RuntimeError("resultado informou quantidade de páginas inválida")
            known_count = editions.get(issue_id)
            if known_count and page_count and known_count != page_count:
                raise RuntimeError("resultados divergem sobre o tamanho da edição")
            if issue_id not in editions or known_count is None:
                editions[issue_id] = page_count
        processed += len(hits)
        if processed >= total:
            break
    else:
        raise RuntimeError("a busca excedeu o limite de páginas de resultados")

    saved = 0
    for issue_id, page_count in editions.items():
        # /<edition>/<page> is only one page. This route downloads the entire issue.
        response = request.get(
            f"{base_url}/portal/edicoes/download/{issue_id}", timeout=120_000
        )
        if not response.ok:
            raise RuntimeError(f"edição {issue_id} indisponível (HTTP {response.status})")
        saved += len(save_matching_pdf(
            response.body(),
            state,
            [keyword],
            f"DOE-{state}-{date_value}-edicao-{issue_id}.pdf",
            date_value,
            expected_pages=page_count,
        ))
    print(f"[{state}] {saved} edição(ões) completa(s) com ocorrência exata em {date_value}")
