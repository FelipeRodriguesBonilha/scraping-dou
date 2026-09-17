from __future__ import annotations

from datetime import date, datetime
import hashlib
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
import time
from typing import Callable, Iterable

import config


DOWNLOADS_ROOT = Path("downloads")


DEFAULT_MAX_PAGES = 10_000


def occurrence_dir(
    state: str,
    keyword: str,
    date_value: date | datetime | str | None = None,
) -> Path:
    return download_dir(state, keyword, date_value).parent / "ocorrencias"


def _exact_phrase_pattern(keyword: str) -> re.Pattern[str] | None:
    words = [word for word in re.split(r"\s+", keyword.strip()) if word]
    if not words:
        return None

    phrase = r"\s+".join(re.escape(word) for word in words)
    first, last = words[0][0], words[-1][-1]
    prefix = r"(?<!\w)" if first.isalnum() or first == "_" else ""
    suffix = r"(?!\w)" if last.isalnum() or last == "_" else ""
    return re.compile(prefix + phrase + suffix, re.IGNORECASE)


def _page_contains_exact_phrase(text: str, pattern: re.Pattern[str] | None) -> bool:
    if not text or pattern is None:
        return False

    normalized = re.sub(r"(?<=\w)-\s*\n\s*(?=\w)", "", text)
    normalized = re.sub(r"\s+", " ", normalized)
    return bool(pattern.search(normalized))


def filter_occurrence_pages(
    pages: Iterable[tuple[int, str]], keyword: str
) -> list[tuple[int, str]]:
    pattern = _exact_phrase_pattern(keyword)
    if pattern is None:
        return list(pages)

    filtered: list[tuple[int, str]] = []
    for page_number, text in pages:
        if not text or not text.strip() or _page_contains_exact_phrase(text, pattern):
            filtered.append((page_number, text))
    return filtered


def save_occurrence_pages(pdf_path: Path, keyword: str) -> list[Path]:
    pattern = _exact_phrase_pattern(keyword)
    if pattern is None:
        return []

    try:
        from pypdf import PdfReader

        reader = PdfReader(str(pdf_path), strict=True)
        matches: list[tuple[int, str]] = []
        for page_number, page in enumerate(reader.pages, start=1):
            try:
                text = page.extract_text() or ""
            except Exception:
                continue
            if _page_contains_exact_phrase(text, pattern):
                matches.append((page_number, text))
    except Exception as error:
        print(
            f"[PDF] não foi possível identificar páginas de ocorrência em "
            f"'{pdf_path.name}': {error}"
        )
        return []

    if not matches:
        return []

    keyword_dir = pdf_path.parent.parent
    date_dir = keyword_dir.parent
    state_dir = date_dir.parent
    return [
        save_occurrence_text(
            state_dir.name,
            keyword_dir.name,
            pdf_path.name,
            matches,
            date_value=date_dir.name,
            target_dir=keyword_dir / "ocorrencias",
        )
    ]


def normalize_date(value: date | datetime | str | None = None) -> str:
    if value is None:
        value = config.DATE
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()

    text = str(value).strip()
    for pattern in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, pattern).date().isoformat()
        except ValueError:
            continue
    raise ValueError(
        f"Data inválida: {value!r}. Use YYYY-MM-DD ou DD/MM/YYYY."
    )

_DATE_IN_TEXT = re.compile(
    r"(?<!\d)(?P<year>\d{4})[/-](?P<month>\d{1,2})[/-](?P<day>\d{1,2})(?!\d)"
    r"|(?<!\d)(?P<br_day>\d{1,2})[./-](?P<br_month>\d{1,2})[./-](?P<br_year>\d{4})(?!\d)"
    r"|(?<!\d)(?P<compact_year>20\d{2})(?P<compact_month>\d{2})(?P<compact_day>\d{2})(?!\d)"
)
_PORTUGUESE_MONTHS = {
    "janeiro": 1,
    "fevereiro": 2,
    "março": 3,
    "marco": 3,
    "abril": 4,
    "maio": 5,
    "junho": 6,
    "julho": 7,
    "agosto": 8,
    "setembro": 9,
    "outubro": 10,
    "novembro": 11,
    "dezembro": 12,
}
_PORTUGUESE_DATE_IN_TEXT = re.compile(
    r"(?<!\d)(?P<day>\d{1,2})\s+de\s+"
    r"(?P<month>janeiro|fevereiro|março|marco|abril|maio|junho|julho|agosto|"
    r"setembro|outubro|novembro|dezembro)\s+de\s+(?P<year>\d{4})(?!\d)",
    re.IGNORECASE,
)


def dates_in_text(value: object) -> set[str]:
    found: set[str] = set()
    for match in _DATE_IN_TEXT.finditer(str(value or "")):
        groups = match.groupdict()
        if groups["year"]:
            raw = f"{groups['year']}-{groups['month']}-{groups['day']}"
        elif groups["compact_year"]:
            raw = (
                f"{groups['compact_year']}-{groups['compact_month']}-"
                f"{groups['compact_day']}"
            )
        else:
            raw = f"{groups['br_year']}-{groups['br_month']}-{groups['br_day']}"
        try:
            found.add(normalize_date(raw))
        except ValueError:
            continue

    for match in _PORTUGUESE_DATE_IN_TEXT.finditer(str(value or "")):
        month = _PORTUGUESE_MONTHS[match.group("month").lower()]
        try:
            found.add(
                normalize_date(
                    f"{match.group('year')}-{month:02}-{match.group('day')}"
                )
            )
        except ValueError:
            continue
    return found


def matches_date(value: object, date_value: date | datetime | str | None = None) -> bool:
    return normalize_date(date_value) in dates_in_text(value)


def date_as_br(value: date | datetime | str | None = None) -> str:
    return datetime.strptime(normalize_date(value), "%Y-%m-%d").strftime("%d/%m/%Y")


def date_parts_br(value: date | datetime | str | None = None) -> tuple[str, str, str]:
    return tuple(date_as_br(value).split("/"))


def _safe_component(value: object, fallback: str) -> str:
    text = str(value or "").strip()

    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", text)
    text = text.rstrip(". ")
    return text or fallback


def download_dir(
    state: str,
    keyword: str,
    date_value: date | datetime | str | None = None,
) -> Path:
    state_part = _safe_component(state, "UF").upper()
    keyword_part = _safe_component(keyword, "sem-termo")
    return DOWNLOADS_ROOT / state_part / normalize_date(date_value) / keyword_part / "pdf"


def _pdf_filename(download, filename: str | int | None) -> str:
    if isinstance(filename, int):
        filename = None
    source = filename or getattr(download, "suggested_filename", None) or "diario.pdf"

    source = _safe_component(source, "diario.pdf")
    path = Path(source)
    suffix = path.suffix
    if suffix.lower() != ".pdf":
        suffix = ".pdf"
    stem = _safe_component(path.stem, "diario")
    return f"{stem}{suffix}"


def _next_available_path(target_dir: Path, original_name: str) -> Path:
    original = Path(original_name)
    target = target_dir / original_name
    sequence = 2
    while target.exists():
        target = target_dir / f"{original.stem}-{sequence}{original.suffix}"
        sequence += 1
    return target


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _same_filename_candidates(target_dir: Path, original_name: str) -> list[Path]:
    original = Path(original_name)
    numbered_name = re.compile(
        rf"^{re.escape(original.stem)}-(?:[2-9]|[1-9]\d+){re.escape(original.suffix)}$",
        re.IGNORECASE,
    )
    candidates = [
        path
        for path in target_dir.iterdir()
        if path.is_file()
        and (path.name.casefold() == original.name.casefold() or numbered_name.fullmatch(path.name))
    ]
    return sorted(
        candidates,
        key=lambda path: (
            path.name.casefold() != original.name.casefold(),
            path.name.casefold(),
        ),
    )


def _save_deduplicated_download(download, target_dir: Path, original_name: str) -> tuple[Path, bool]:
    with NamedTemporaryFile(
        dir=target_dir,
        prefix=".download-",
        suffix=".part",
        delete=False,
    ) as temporary:
        temporary_path = Path(temporary.name)

    try:
        download.save_as(temporary_path)
        content_hash = _file_sha256(temporary_path)
        for candidate in _same_filename_candidates(target_dir, original_name):
            if _file_sha256(candidate) == content_hash:
                return candidate, False

        target = _next_available_path(target_dir, original_name)
        temporary_path.replace(target)
        return target, True
    finally:
        temporary_path.unlink(missing_ok=True)


def _write_occurrence_text(
    target: Path,
    *,
    source_name: str,
    source_url: str | None,
    keyword: str,
    pages: list[tuple[int, str]],
) -> None:
    header = [
        f"Arquivo de origem: {source_name}",
        f"Busca: {keyword}",
        "Páginas de ocorrência: " + ", ".join(str(number) for number, _ in pages),
    ]
    if source_url:
        header.append(f"Consulta pública: {source_url}")

    sections = ["\n".join(header), ""]
    for page_number, text in pages:
        sections.extend(
            [
                f"===== PÁGINA {page_number} =====",
                text.strip() or "[O PDF não possui texto extraível nesta página.]",
                "",
            ]
        )
    target.write_text("\n".join(sections), encoding="utf-8")


def save_occurrence_text(
    state: str,
    keyword: str,
    filename: str,
    pages: list[tuple[int, str]],
    *,
    date_value: date | datetime | str | None = None,
    target_dir: Path | None = None,
    source_url: str | None = None,
) -> Path:
    page_map: dict[int, str] = {}
    for page_number, text in pages:
        try:
            number = int(page_number)
        except (TypeError, ValueError):
            continue
        if number > 0:
            page_map[number] = text
    normalized_pages = sorted(page_map.items())
    if not normalized_pages:
        raise RuntimeError("nenhuma página de ocorrência foi identificada")

    source_name = _safe_component(filename, "diario.pdf")
    target_dir = target_dir or occurrence_dir(state, keyword, date_value)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{_safe_component(Path(source_name).stem, 'diario')}__ocorrencias.txt"
    _write_occurrence_text(
        target,
        source_name=source_name,
        source_url=source_url,
        keyword=keyword,
        pages=normalized_pages,
    )
    page_list = ", ".join(str(number) for number, _ in normalized_pages)
    print(f"[{state.upper()}] ocorrências salvas: {target} (páginas: {page_list})")
    return target


def save_occurrence_metadata(
    state: str,
    keyword: str,
    filename: str,
    records: Iterable[dict[str, object]],
    *,
    date_value: date | datetime | str | None = None,
) -> Path:
    normalized: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for record in records:
        edition_date = str(record.get("date") or "").strip()
        section = str(record.get("section") or "").strip()
        term = str(record.get("term") or "").strip()
        page = str(record.get("page") or "").strip()
        key = (edition_date, section, term, page)
        if key in seen:
            continue
        seen.add(key)
        normalized.append(
            {"date": edition_date, "section": section, "term": term, "page": page}
        )

    if not normalized:
        raise RuntimeError("nenhuma ocorrência informada pelo portal")

    source_name = _safe_component(filename, "diario.pdf")
    target_dir = occurrence_dir(state, keyword, date_value)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{_safe_component(Path(source_name).stem, 'diario')}__ocorrencias.txt"
    pages = list(dict.fromkeys(record["page"] for record in normalized if record["page"]))
    lines = [
        f"Arquivo de origem: {source_name}",
        f"Busca: {keyword}",
        "Páginas de ocorrência: "
        + (", ".join(pages) if pages else "não informadas pelo portal"),
        "",
    ]
    for index, record in enumerate(normalized, start=1):
        lines.append(f"===== OCORRÊNCIA {index} =====")
        lines.append(f"Data da edição: {record['date'] or 'não informada'}")
        lines.append(f"Seção: {record['section'] or 'não informada'}")
        if record["page"]:
            lines.append(f"Página: {record['page']}")
        lines.append(f"Termo informado pelo portal: {record['term'] or keyword}")
        lines.append("")
    target.write_text("\n".join(lines), encoding="utf-8")
    page_detail = ", ".join(pages) if pages else "não informadas"
    print(f"[{state.upper()}] ocorrências salvas: {target} (páginas: {page_detail})")
    return target


def read_occurrence_download(
    download,
    *,
    page_number: int | None = None,
) -> list[tuple[int, str]]:
    with NamedTemporaryFile(suffix=".pdf", prefix=".ocorrencia-", delete=False) as temporary:
        temporary_path = Path(temporary.name)

    try:
        download.save_as(temporary_path)
        from pypdf import PdfReader

        reader = PdfReader(str(temporary_path), strict=True)
        pages: list[tuple[int, str]] = []
        for index, page in enumerate(reader.pages, start=1):
            try:
                text = page.extract_text() or ""
            except Exception:
                text = ""
            pages.append(((page_number or 1) + index - 1, text))
        if not pages:
            raise RuntimeError("PDF da página de ocorrência não possui páginas")
        return pages
    finally:
        temporary_path.unlink(missing_ok=True)


def save_download(
    download,
    state: str,
    keyword: str,
    filename: str | int | None = None,
    *,
    date_value: date | datetime | str | None = None,
    extract_occurrences: bool = True,
    deduplicate_identical: bool = True,
) -> Path:
    target_dir = download_dir(state, keyword, date_value)
    target_dir.mkdir(parents=True, exist_ok=True)

    original_name = _pdf_filename(download, filename)
    if deduplicate_identical:
        target, saved = _save_deduplicated_download(download, target_dir, original_name)
    else:
        target = _next_available_path(target_dir, original_name)
        download.save_as(target)
        saved = True

    if saved:
        print(f"[{state.upper()}] salvo: {target}")
    else:
        print(f"[{state.upper()}] arquivo idêntico já existe: {target}")
    if extract_occurrences:
        save_occurrence_pages(target, keyword)
    return target


def is_enabled(locator) -> bool:
    try:
        return locator.count() > 0 and locator.first.is_visible() and locator.first.is_enabled()
    except Exception:
        return False


def click_next(next_locator, *, wait_ms: int = 750) -> bool:
    if not is_enabled(next_locator):
        return False
    try:
        item = next_locator.first
        class_name = item.get_attribute("class") or ""
        aria_disabled = item.get_attribute("aria-disabled") or ""
        if "disabled" in class_name.lower() or aria_disabled.lower() == "true":
            return False
        item.click()
        time.sleep(wait_ms / 1000)
        return True
    except Exception:
        return False


def paginate(
    process_page: Callable[[int], int],
    go_next: Callable[[], bool],
    *,
    max_pages: int = DEFAULT_MAX_PAGES,
) -> int:
    total = 0
    for _ in range(max_pages):
        total += process_page(total + 1)
        if not go_next():
            break
    return total


def click_pdf_download(page) -> None:
    pattern = re.compile(r"baixar|download", re.I)
    candidates = [page, *getattr(page, "frames", [])]
    for frame in candidates:
        try:
            button = frame.get_by_role("button", name=pattern).first
            button.click()
            return
        except Exception:
            continue
    raise RuntimeError("botão de download do PDF não encontrado")


def run_for_keywords(
    playwright,
    state: str,
    search: Callable,
    *,
    keywords: Iterable[str] | None = None,
    date_value: date | datetime | str | None = None,
    headless: bool = True,
) -> None:
    selected_keywords = list(config.KEYWORDS if keywords is None else keywords)
    normalized_date = normalize_date(date_value)
    browser = playwright.chromium.launch(headless=headless)
    context = browser.new_context(accept_downloads=True)
    failed_keywords: list[str] = []
    try:
        for keyword in selected_keywords:
            if not keyword or not keyword.strip():
                continue
            print(f"[{state.upper()}] pesquisando: {keyword}")
            page = context.new_page()
            try:
                search(page, keyword, normalized_date)
            except Exception as error:
                failed_keywords.append(keyword)
                print(f"[{state.upper()}] falha na busca '{keyword}': {error}")
            finally:
                page.close()
    finally:
        context.close()
        browser.close()
    if failed_keywords:
        raise RuntimeError(
            f"{len(failed_keywords)} busca(s) falharam: {', '.join(failed_keywords)}"
        )


def scrape_with_playwright(
    state: str,
    search: Callable,
    *,
    keywords: Iterable[str] | None = None,
    date_value: date | datetime | str | None = None,
    headless: bool = True,
) -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        run_for_keywords(
            playwright,
            state,
            search,
            keywords=keywords,
            date_value=date_value,
            headless=headless,
        )
