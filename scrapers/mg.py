"""Jornal Minas Gerais: public anonymous API and complete cadernos."""
from __future__ import annotations

import base64
from urllib.parse import urlencode

import config
from scrapers.common import normalize_date
from scrapers.public_api import get_json
from scrapers.public_pdf import save_matching_pdf

STATE = "MG"
PLAYWRIGHT_REQUIRED = False
API = "https://www.jornalminasgerais.mg.gov.br/api/v1/"


def _decode_pdf(value: str) -> bytes:
    """Extract MG's PDF from its CMS envelope without altering PDF bytes.

    This extracts the content; it does not verify the CMS signature.
    """
    data = base64.b64decode(value, validate=True)
    if data.startswith(b"%PDF"):
        return data

    def parse(pos: int, limit: int, depth: int = 0):
        if depth > 32 or pos + 2 > limit:
            raise ValueError("envelope CMS inválido")
        tag, length = data[pos], data[pos + 1]
        pos += 2
        indefinite = length == 128
        if length > 128:
            count = length & 127
            if count > 8 or pos + count > limit:
                raise ValueError("comprimento CMS inválido")
            length = int.from_bytes(data[pos:pos + count], "big")
            pos += count
        end = limit if indefinite else pos + length
        if end > limit or (indefinite and not tag & 32):
            raise ValueError("envelope CMS truncado")
        if tag & 32:
            children = []
            terminated = False
            while pos < end:
                if indefinite and data[pos:pos + 2] == b"\0\0":
                    pos += 2
                    terminated = True
                    break
                pos, value = parse(pos, end, depth + 1)
                children.extend(value)
            if indefinite and not terminated:
                raise ValueError("envelope CMS sem terminador")
            if tag == 36:
                children = [b"".join(children)]
            return pos, children
        return end, [data[pos:end]] if tag == 4 else []

    _, values = parse(0, len(data))
    matches = [value for value in values if value.startswith(b"%PDF")]
    if len(matches) != 1:
        raise ValueError("PDF não encontrado no envelope CMS de MG")
    return matches[0]


def _payload(response: dict):
    if response.get("erros"):
        raise RuntimeError(f"API de MG: {response['erros']}")
    if "dados" not in response:
        raise RuntimeError("resposta inesperada da API de MG")
    return response["dados"]


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
    # Same anonymous session opened by the public portal, without a user account.
    token = _payload(get_json(API + "Autenticacao/Autenticar", data=b"{}",
                              headers={"Content-Type": "application/json"}))
    if not isinstance(token, str) or not token:
        raise RuntimeError("sessão pública de MG indisponível")
    headers = {"Authorization": f"Bearer {token}"}
    issue = _payload(get_json(API + "Jornal/ObterEdicaoPorDataPublicacao?" +
                              urlencode({"dataPublicacao": day}), headers=headers))
    if issue is None:
        print(f"[MG] nenhuma edição em {day}")
        return
    if normalize_date(str(issue.get("dataPublicacao", ""))[:10]) != day:
        raise RuntimeError("MG retornou edição fora da data solicitada")
    cadernos = issue.get("cadernos")
    if not isinstance(cadernos, list):
        raise RuntimeError("catálogo de cadernos de MG ausente")
    saved = 0
    seen = set()
    for caderno in cadernos:
        identifier = caderno["id"]
        if identifier in seen:
            continue
        seen.add(identifier)
        # No pagina parameter: obtain the entire caderno, not the displayed page.
        document = _payload(get_json(API + "Caderno/ObterArquivoCadernoPorId?" +
                                     urlencode({"id": identifier}), headers=headers))
        if not document or not document.get("arquivoUnico"):
            raise RuntimeError(f"MG: caderno {identifier} não disponibilizou arquivo completo")
        data = _decode_pdf(document["arquivo"])
        saved += len(save_matching_pdf(data, STATE, selected,
                     f"MG-{day}-{identifier}.pdf", day,
                     expected_pages=int(document["totalPaginas"])))
    print(f"[MG] {len(seen)} caderno(s) consultado(s); {saved} arquivo(s) com ocorrências")


if __name__ == "__main__":
    scrape()
