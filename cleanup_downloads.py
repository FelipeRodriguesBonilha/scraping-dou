from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import re
import shutil
from typing import Iterable


ROOT = Path(__file__).resolve().parent
DOWNLOADS_DIR = ROOT / "downloads"
DEFAULT_KEEP_DAYS = 15
BRAZIL_TIMEZONE = timezone(timedelta(hours=-3), name="BRT")
DATE_DIRECTORY_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class CleanupResult:
    cutoff: date
    candidates: tuple[Path, ...]
    removed: tuple[Path, ...]
    protected: tuple[Path, ...]
    errors: tuple[tuple[Path, str], ...]


def today_in_brazil() -> date:
    return datetime.now(BRAZIL_TIMEZONE).date()


def _date_from_directory_name(name: str) -> date | None:
    if not DATE_DIRECTORY_PATTERN.fullmatch(name):
        return None
    try:
        return date.fromisoformat(name)
    except ValueError:
        return None


def _is_direct_date_directory(path: Path, root: Path) -> bool:
    try:
        relative = path.resolve().relative_to(root)
    except (OSError, ValueError):
        return False
    return len(relative.parts) == 2


def cleanup_downloads(
    downloads_dir: Path | str = DOWNLOADS_DIR,
    *,
    keep_days: int = DEFAULT_KEEP_DAYS,
    today: date | None = None,
    protected_dates: Iterable[str] = (),
    dry_run: bool = False,
) -> CleanupResult:
    if not 1 <= keep_days <= 365:
        raise ValueError("A retenção deve ficar entre 1 e 365 dias.")

    reference_date = today or today_in_brazil()
    cutoff = reference_date - timedelta(days=keep_days - 1)
    root = Path(downloads_dir).resolve()
    protected = {
        normalized
        for value in protected_dates
        if (normalized := str(value).strip()) and _date_from_directory_name(normalized)
    }
    candidates: list[Path] = []
    removed: list[Path] = []
    preserved: list[Path] = []
    errors: list[tuple[Path, str]] = []

    if not root.is_dir():
        return CleanupResult(cutoff, (), (), (), ())

    for state_dir in sorted(root.iterdir(), key=lambda item: item.name.upper()):
        if state_dir.is_symlink() or not state_dir.is_dir():
            continue
        for date_dir in sorted(state_dir.iterdir(), key=lambda item: item.name):
            if date_dir.is_symlink() or not date_dir.is_dir():
                continue
            folder_date = _date_from_directory_name(date_dir.name)
            if folder_date is None or folder_date >= cutoff:
                continue
            if not _is_direct_date_directory(date_dir, root):
                continue

            candidates.append(date_dir)
            if date_dir.name in protected:
                preserved.append(date_dir)
                continue
            if dry_run:
                continue
            try:
                shutil.rmtree(date_dir)
            except OSError as error:
                errors.append((date_dir, str(error)))
            else:
                removed.append(date_dir)

    return CleanupResult(
        cutoff,
        tuple(candidates),
        tuple(removed),
        tuple(preserved),
        tuple(errors),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Remove resultados de coleta mais antigos que a janela de retenção."
    )
    parser.add_argument(
        "--keep-days",
        type=int,
        default=DEFAULT_KEEP_DAYS,
        help=f"Quantidade de datas-calendário a manter (padrão: {DEFAULT_KEEP_DAYS}).",
    )
    parser.add_argument(
        "--downloads-dir",
        type=Path,
        default=DOWNLOADS_DIR,
        help="Diretório raiz dos resultados (padrão: downloads).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Aplica a exclusão. Sem esta opção, apenas mostra o que seria removido.",
    )
    return parser.parse_args()


def print_result(result: CleanupResult, *, applied: bool) -> None:
    action = "removida" if applied else "seria removida"
    for path in result.removed if applied else result.candidates:
        if path in result.protected:
            continue
        print(f"[limpeza] {action}: {path}")
    for path in result.protected:
        print(f"[limpeza] preservada por coleta em andamento: {path}")
    for path, error in result.errors:
        print(f"[limpeza] falha ao remover {path}: {error}")
    if not result.candidates:
        print(f"[limpeza] nada a remover antes de {result.cutoff.isoformat()}.")


def main() -> int:
    arguments = parse_args()
    try:
        result = cleanup_downloads(
            arguments.downloads_dir,
            keep_days=arguments.keep_days,
            dry_run=not arguments.apply,
        )
    except ValueError as error:
        raise SystemExit(f"Erro de configuração: {error}") from error

    print_result(result, applied=arguments.apply)
    return 1 if result.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
