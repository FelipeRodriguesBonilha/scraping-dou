from __future__ import annotations

import argparse
import base64
import binascii
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hmac
import ipaddress
import json
import mimetypes
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlsplit
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = Path(__file__).resolve().parent / "static"
DOWNLOADS_DIR = ROOT / "downloads"
MAX_REQUEST_BYTES = 64 * 1024
MAX_KEYWORDS = 50
MAX_KEYWORD_LENGTH = 300
ALLOWED_RESULT_SUFFIXES = {".pdf", ".txt"}
AUTH_USERNAME_ENV = "DOU_WEB_USERNAME"
AUTH_PASSWORD_ENV = "DOU_WEB_PASSWORD"
AUTH_REALM = "Scraping DOU"
BRAZIL_TIMEZONE = timezone(timedelta(hours=-3), name="BRT")
RETENTION_DAYS_ENV = "DOU_RETENTION_DAYS"
DEFAULT_RETENTION_DAYS = 15
CLEANUP_HOUR = 3
CLEANUP_MINUTE = 15
MAINTENANCE_LOCK = threading.RLock()


if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config
from cleanup_downloads import CleanupResult, cleanup_downloads


@dataclass(frozen=True)
class BasicAuth:
    username: str
    password: str

    def matches(self, authorization: str | None) -> bool:
        if not authorization:
            return False

        scheme, separator, token = authorization.partition(" ")
        if scheme.lower() != "basic" or not separator or not token:
            return False

        try:
            decoded = base64.b64decode(token.encode("ascii"), validate=True).decode("utf-8")
        except (UnicodeDecodeError, UnicodeEncodeError, binascii.Error):
            return False

        username, separator, password = decoded.partition(":")
        if not separator:
            return False

        username_matches = hmac.compare_digest(
            username.encode("utf-8"), self.username.encode("utf-8")
        )
        password_matches = hmac.compare_digest(
            password.encode("utf-8"), self.password.encode("utf-8")
        )
        return username_matches & password_matches


def is_loopback_host(host: str) -> bool:
    normalized = host.strip().strip("[]").lower()
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def auth_from_environment(host: str, no_auth: bool = False) -> BasicAuth | None:
    if no_auth:
        if not is_loopback_host(host):
            raise ValueError("--no-auth só pode ser usado com um endereço local (loopback).")
        return None

    username = os.environ.get(AUTH_USERNAME_ENV)
    password = os.environ.get(AUTH_PASSWORD_ENV)
    if not username or not password:
        raise ValueError(
            f"Defina {AUTH_USERNAME_ENV} e {AUTH_PASSWORD_ENV} antes de iniciar o servidor."
        )
    return BasicAuth(username=username, password=password)


def current_date() -> str:
    return datetime.now(BRAZIL_TIMEZONE).date().isoformat()


def retention_days_from_environment() -> int:
    raw_value = os.environ.get(RETENTION_DAYS_ENV, str(DEFAULT_RETENTION_DAYS)).strip()
    try:
        retention_days = int(raw_value)
    except ValueError as error:
        raise ValueError(f"{RETENTION_DAYS_ENV} deve ser um número inteiro.") from error
    if not 1 <= retention_days <= 365:
        raise ValueError(f"{RETENTION_DAYS_ENV} deve ficar entre 1 e 365.")
    return retention_days


def seconds_until_next_cleanup(now: datetime | None = None) -> float:
    local_now = now or datetime.now(BRAZIL_TIMEZONE)
    next_cleanup = local_now.replace(
        hour=CLEANUP_HOUR,
        minute=CLEANUP_MINUTE,
        second=0,
        microsecond=0,
    )
    if next_cleanup <= local_now:
        next_cleanup += timedelta(days=1)
    return (next_cleanup - local_now).total_seconds()


def normalize_date(value: object | None) -> str:
    text = str(value or current_date()).strip()
    if not text:
        text = current_date()
    for pattern in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, pattern).date().isoformat()
        except ValueError:
            continue
    raise ValueError("Use a data no formato YYYY-MM-DD ou DD/MM/YYYY.")


def parse_keywords(value: object | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw_terms = value.splitlines()
    elif isinstance(value, list) and all(isinstance(item, str) for item in value):
        raw_terms = value
    else:
        raise ValueError("As palavras-chave devem ser texto, uma por linha.")

    terms: list[str] = []
    for raw_term in raw_terms:
        term = raw_term.strip()
        if not term:
            continue
        if len(term) > MAX_KEYWORD_LENGTH:
            raise ValueError("Cada palavra-chave pode ter no máximo 300 caracteres.")
        if term not in terms:
            terms.append(term)

    if len(terms) > MAX_KEYWORDS:
        raise ValueError("Informe no máximo 50 palavras-chave.")
    return terms


def _safe_relative_path(value: str) -> Path | None:
    try:
        candidate = (DOWNLOADS_DIR / Path(value)).resolve()
        root = DOWNLOADS_DIR.resolve()
        candidate.relative_to(root)
    except (OSError, ValueError):
        return None
    if candidate.suffix.lower() not in ALLOWED_RESULT_SUFFIXES or not candidate.is_file():
        return None
    return candidate


def list_results(date_value: object | None) -> list[dict[str, Any]]:
    normalized_date = normalize_date(date_value)
    if not DOWNLOADS_DIR.is_dir():
        return []

    results: list[dict[str, Any]] = []
    for state_dir in sorted(DOWNLOADS_DIR.iterdir(), key=lambda item: item.name.upper()):
        date_dir = state_dir / normalized_date
        if not state_dir.is_dir() or not date_dir.is_dir():
            continue
        for path in sorted(date_dir.rglob("*"), key=lambda item: str(item).casefold()):
            if not path.is_file() or path.suffix.lower() not in ALLOWED_RESULT_SUFFIXES:
                continue
            try:
                relative = path.resolve().relative_to(DOWNLOADS_DIR.resolve())
            except (OSError, ValueError):
                continue

            parts = relative.parts

            if len(parts) < 5:
                continue
            kind = "ocorrência" if "ocorrencias" in parts else "PDF"
            results.append(
                {
                    "state": parts[0],
                    "date": parts[1],
                    "keyword": parts[2],
                    "kind": kind,
                    "name": path.name,
                    "size": path.stat().st_size,
                    "url": "/files/" + quote(relative.as_posix()),
                }
            )

    return results


class ScrapeJob:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._process: subprocess.Popen[str] | None = None
        self._state: dict[str, Any] = {
            "status": "idle",
            "date": None,
            "keywords": [],
            "headless": True,
            "startedAt": None,
            "lastActivityAt": None,
            "endedAt": None,
            "returncode": None,
            "error": None,
        }
        self._logs: deque[str] = deque(maxlen=500)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {**self._state, "logs": list(self._logs)}

    def start(self, date_value: str, keywords: list[str]) -> dict[str, Any]:
        with MAINTENANCE_LOCK:
            with self._lock:
                if self._state["status"] == "running":
                    raise RuntimeError("Já existe uma coleta em andamento.")

                self._state = {
                    "status": "running",
                    "date": date_value,
                    "keywords": keywords,
                    "headless": True,
                    "startedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
                    "lastActivityAt": None,
                    "endedAt": None,
                    "returncode": None,
                    "error": None,
                }
                self._logs.clear()
                self._thread = threading.Thread(
                    target=self._run,
                    args=(date_value, keywords),
                    name="scraping-dou-job",
                    daemon=True,
                )
                self._thread.start()
                return {**self._state, "logs": []}

    def _run(self, date_value: str, keywords: list[str]) -> None:
        arguments = [
            sys.executable,
            "-u",
            str(ROOT / "main.py"),
            f"--date={date_value}",
        ]
        for keyword in keywords:
            arguments.append(f"--keyword={keyword}")
        try:
            environment = os.environ.copy()
            environment["PYTHONIOENCODING"] = "utf-8"
            environment["PYTHONUTF8"] = "1"
            process = subprocess.Popen(
                arguments,
                cwd=ROOT,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=environment,
            )
            with self._lock:
                self._process = process

            if process.stdout is not None:
                for line in process.stdout:
                    with self._lock:
                        self._logs.append(line.rstrip())
                        self._state["lastActivityAt"] = datetime.now().astimezone().isoformat(
                            timespec="seconds"
                        )

            returncode = process.wait()
            with self._lock:
                self._state["status"] = "finished"
                self._state["returncode"] = returncode
                self._state["endedAt"] = datetime.now().astimezone().isoformat(
                    timespec="seconds"
                )
                self._process = None
        except Exception as error:
            with self._lock:
                self._state["status"] = "failed"
                self._state["error"] = str(error)
                self._state["endedAt"] = datetime.now().astimezone().isoformat(
                    timespec="seconds"
                )
                self._process = None

JOB = ScrapeJob()


def _log_cleanup_result(result: CleanupResult) -> None:
    for path in result.removed:
        print(f"[sistema] limpeza automática: removido {path}")
    for path in result.protected:
        print(f"[sistema] limpeza automática: preservado por coleta em andamento: {path}")
    for path, error in result.errors:
        print(f"[sistema] limpeza automática: falha ao remover {path}: {error}")
    if not result.candidates:
        print(
            "[sistema] limpeza automática: nenhum resultado anterior a "
            f"{result.cutoff.isoformat()} para remover."
        )


def run_retention_cleanup(retention_days: int) -> CleanupResult:
    with MAINTENANCE_LOCK:
        snapshot = JOB.snapshot()
        protected_dates = (
            (str(snapshot["date"]),)
            if snapshot["status"] == "running" and snapshot["date"]
            else ()
        )
        result = cleanup_downloads(
            DOWNLOADS_DIR,
            keep_days=retention_days,
            protected_dates=protected_dates,
        )
    _log_cleanup_result(result)
    return result


class RetentionScheduler:
    def __init__(self, retention_days: int) -> None:
        self._retention_days = retention_days
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run,
            name="scraping-dou-retention",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                run_retention_cleanup(self._retention_days)
            except Exception as error:
                print(f"[sistema] limpeza automática falhou: {error}")
            if self._stop_event.wait(seconds_until_next_cleanup()):
                break


class AppServer(ThreadingHTTPServer):
    def __init__(
        self,
        server_address: tuple[str, int],
        request_handler_class: type[BaseHTTPRequestHandler],
        auth: BasicAuth | None,
    ) -> None:
        super().__init__(server_address, request_handler_class)
        self.auth = auth


class AppHandler(BaseHTTPRequestHandler):
    server_version = "ScrapingDOU/1.0"

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def do_GET(self) -> None:
        if not self._require_authentication():
            return

        parsed = urlsplit(self.path)
        try:
            if parsed.path == "/":
                self._serve_static("index.html")
            elif parsed.path.startswith("/static/"):
                self._serve_static(parsed.path.removeprefix("/static/"))
            elif parsed.path == "/api/config":
                self._send_json(
                    200,
                    {"date": current_date(), "keywords": config.KEYWORDS},
                )
            elif parsed.path == "/api/status":
                self._send_json(200, JOB.snapshot())
            elif parsed.path == "/api/files":
                requested_date = parse_qs(parsed.query).get("date", [current_date()])[0]
                self._send_json(
                    200,
                    {"date": normalize_date(requested_date), "files": list_results(requested_date)},
                )
            elif parsed.path.startswith("/files/"):
                self._serve_result(unquote(parsed.path.removeprefix("/files/")))
            else:
                self._send_json(404, {"error": "Rota não encontrada."})
        except ValueError as error:
            self._send_json(400, {"error": str(error)})
        except Exception:
            self._send_json(500, {"error": "Não foi possível concluir a solicitação."})

    def do_POST(self) -> None:
        if not self._require_authentication():
            return

        if urlsplit(self.path).path != "/api/scrape":
            self._send_json(404, {"error": "Rota não encontrada."})
            return

        try:
            payload = self._read_json_body()
            date_value = normalize_date(payload.get("date"))
            keywords = parse_keywords(payload.get("keywords"))
            headless = payload.get("headless", True)
            if headless is not True:
                raise ValueError("A interface executa a coleta sem abrir o navegador.")
            self._send_json(202, JOB.start(date_value, keywords))
        except RuntimeError as error:
            self._send_json(409, {"error": str(error)})
        except ValueError as error:
            self._send_json(400, {"error": str(error)})
        except Exception:
            self._send_json(500, {"error": "Não foi possível iniciar a coleta."})

    def _require_authentication(self) -> bool:
        auth = getattr(self.server, "auth", None)
        if auth is None or auth.matches(self.headers.get("Authorization")):
            return True

        self.send_response(401)
        self.send_header("WWW-Authenticate", f'Basic realm="{AUTH_REALM}", charset="UTF-8"')
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        return False

    def _read_json_body(self) -> dict[str, Any]:
        raw_length = self.headers.get("Content-Length")
        try:
            content_length = int(raw_length or "0")
        except ValueError as error:
            raise ValueError("Content-Length inválido.") from error
        if content_length <= 0 or content_length > MAX_REQUEST_BYTES:
            raise ValueError("Envie um JSON de até 64 KB.")
        try:
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("Corpo JSON inválido.") from error
        if not isinstance(payload, dict):
            raise ValueError("O corpo deve ser um objeto JSON.")
        return payload

    def _serve_static(self, relative_name: str) -> None:
        try:
            path = (STATIC_DIR / relative_name).resolve()
            path.relative_to(STATIC_DIR.resolve())
        except (OSError, ValueError):
            self._send_json(404, {"error": "Arquivo não encontrado."})
            return
        if not path.is_file():
            self._send_json(404, {"error": "Arquivo não encontrado."})
            return
        mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if mime_type.startswith("text/") or mime_type in {
            "application/javascript",
            "application/json",
        }:
            mime_type += "; charset=utf-8"
        self._send_file(path, mime_type)

    def _serve_result(self, relative_name: str) -> None:
        path = _safe_relative_path(relative_name)
        if path is None:
            self._send_json(404, {"error": "Arquivo de resultado não encontrado."})
            return
        mime_type = "application/pdf" if path.suffix.lower() == ".pdf" else "text/plain; charset=utf-8"
        self._send_file(path, mime_type)

    def _send_file(self, path: Path, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(path.stat().st_size))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        with path.open("rb") as source:
            shutil.copyfileobj(source, self.wfile)

    def _send_json(self, status: int, body: dict[str, Any]) -> None:
        encoded = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inicia a interface local dos diários oficiais.")
    parser.add_argument("--host", default="127.0.0.1", help="Endereço local (padrão: 127.0.0.1).")
    parser.add_argument("--port", default=8000, type=int, help="Porta HTTP local (padrão: 8000).")
    parser.add_argument(
        "--no-auth",
        action="store_true",
        help="Desativa a senha somente para testes em endereço local.",
    )
    return parser.parse_args()


def serve(host: str = "127.0.0.1", port: int = 8000, no_auth: bool = False) -> None:
    auth = auth_from_environment(host, no_auth)
    retention_days = retention_days_from_environment()
    server = AppServer((host, port), AppHandler, auth)
    retention_scheduler = RetentionScheduler(retention_days)
    print(f"Interface disponível em http://{host}:{port}")
    if auth is None:
        print("Autenticação desativada somente para uso local.")
    else:
        print("Autenticação por usuário e senha ativada.")
    print(
        "Limpeza automática ativada: mantém os últimos "
        f"{retention_days} dias de resultados."
    )
    print("Use Ctrl+C para encerrar o servidor.")
    retention_scheduler.start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor encerrado.")
    finally:
        retention_scheduler.stop()
        server.server_close()

if __name__ == "__main__":
    arguments = parse_args()
    try:
        serve(arguments.host, arguments.port, arguments.no_auth)
    except ValueError as error:
        raise SystemExit(f"Erro de configuração: {error}") from error
