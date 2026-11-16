"""Komunikaty backendu po angielsku (0.75.0, etap 4b): katalog `messages.py`, `i18n.translate` i middleware."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel, field_validator

from netpulse import i18n
from netpulse.i18n import LanguageMiddleware, parse_accept_language, translate
from netpulse.messages import MESSAGES

REPO = Path(__file__).resolve().parents[2]
# Kod, którego komunikaty mogą trafić do API: backend i usługa aktualizacji (jej komunikaty przekazuje API)
ROOTS = (REPO / "backend" / "netpulse", REPO / "updater" / "netpulse_updater")
# Poza zakresem: CLI i agent (terminal na serwerze), migracje
SKIP_FILES = {"cli.py", "agent/netpulse_agent.py", "__main__.py", "messages.py", "i18n.py"}
SKIP_CALLS = {"info", "warning", "debug", "error", "exception", "critical", "print", "echo", "APIRouter", "Query", "Field", "Path", "Body"}
POLISH = re.compile(
    r"[ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]|(?i:\b(?:nie|brak|podaj|wybierz|najpierw|wymagane|tych|ten|ta|to|niedozwolony|oczekiwany"
    r"|albo|lub|godzina|niepoprawny|jest|dla|portu|nieznany|nieznana|zbyt|wymaga|kopii|kopia"
    r"|w|i|z|na|do|od|po|przez|oraz|ze|za|bez|kontener|zatrzymany|zatrzymana|maszyna|wysoka|temperatura|fabryczne"
    r"|pobieranie|serwer|porty|pomiar|zanonimizowane|odpowiedzi|kontroler|kontrolera|bramy|dysk|certyfikat|wygasa)\b)"
)
HOLE = re.compile(r"\{[^{}]*\}")
# Polskie teksty, które celowo nie są komunikatami API (porównania w kodzie, kawałki składane gdzie indziej)
NOT_MESSAGES = {
    "Nie ma takiej",  # updater/server.py: rozpoznanie błędu po treści
    "nie zna adresu",  # unifi.py: rozpoznanie błędu po treści
    "włączona",  # updater/server.py: wydruk przy starcie usługi
    "WYŁĄCZONA (NETPULSE_UPDATER=off)",
    "ąćęłńóśźżĄĆĘŁŃÓŚŹŻ–—„”’",  # report.py: zamiana liter, gdy PDF nie ma czcionki z ogonkami
}


def _template(node) -> str:
    if isinstance(node, ast.Constant):
        return node.value
    return "".join(v.value if isinstance(v, ast.Constant) else "{" + ast.unparse(v.value) + "}" for v in node.values)


def polish_literals() -> dict[str, str]:
    """Polskie teksty w kodzie (stałe i f-stringi jako wzorce), bez logów, docstringów i opisów w OpenAPI."""
    found: dict[str, str] = {}
    for root in ROOTS:
        for path in sorted(root.rglob("*.py")):
            rel = path.relative_to(root).as_posix()
            if rel in SKIP_FILES or "migrations" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            skip: set[int] = set()
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)) and node.body:
                    first = node.body[0]
                    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                        skip.add(id(first.value))
                if isinstance(node, ast.Call):
                    fn = node.func
                    name = fn.attr if isinstance(fn, ast.Attribute) else fn.id if isinstance(fn, ast.Name) else ""
                    if name in SKIP_CALLS:
                        skip.update(id(s) for s in ast.walk(node))
                if isinstance(node, ast.keyword) and node.arg in ("description", "summary", "tags", "help"):
                    skip.update(id(s) for s in ast.walk(node))
            for node in ast.walk(tree):
                if id(node) in skip:
                    continue
                if isinstance(node, ast.JoinedStr):
                    skip.update(id(s) for s in ast.walk(node))
                elif not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
                    continue
                text = _template(node)
                if _is_message(text):
                    found.setdefault(text, f"{root.name}/{rel}:{node.lineno}")
    return found


def _is_message(text: str) -> bool:
    if not text or text.startswith(("^", "(?")) or "SELECT " in text or "\\" in text:
        return False
    fixed = HOLE.sub("", text)
    letters = re.sub(r"[^A-Za-ząćęłńóśźżĄĆĘŁŃÓŚŹŻ ]", "", fixed).strip()
    if not letters or " " not in fixed and len(fixed) <= 4:  # same zmienne i znaki („{a}: {b}”), klucze („i{id}”), tryby („w”)
        return False
    return bool(POLISH.search(text))


def _translated(text: str) -> bool:
    """Czy katalog tłumaczy tekst – zmienne f-stringa zastąpione przykładową liczbą."""
    sample = HOLE.sub("9", text)
    return i18n._to_english(sample) != sample


def test_every_polish_message_is_in_catalog():
    missing = [
        f"{where}: {text!r}"
        for text, where in sorted(polish_literals().items(), key=lambda x: x[1])
        if text not in NOT_MESSAGES and not _translated(text)
    ]
    assert not missing, "Brak tłumaczenia w netpulse/messages.py:\n" + "\n".join(missing)


def test_catalog_is_consistent():
    seen = set()
    for pl, en in MESSAGES:
        assert pl not in seen, f"powtórzony wpis: {pl!r}"
        seen.add(pl)
        names = re.findall(r"\{(\w+)\}", pl)
        assert len(names) == len(set(names)), pl
        assert sorted(re.findall(r"\{(\w+)\}", en)) == sorted(names), pl
        assert not re.search("[ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]", en), en
        assert pl != en or "{" in pl, pl


def test_translate_titles_errors_and_details():
    cases = {
        "Garaż nie odpowiada": "Garaż is not responding",
        "Port eth4 (UCG Ultra) jest wyłączony": "Port eth4 (UCG Ultra) is down",
        "Serwer: dysk /mnt/data zajęty w 91,5%": "Serwer: disk /mnt/data 91.5% used",
        "Google: certyfikat wygasa za 13,0 dni": "Google: certificate expires in 13.0 days",
        "NAS: kontener nginx zatrzymany": "NAS: container nginx stopped",
        "Warunek: Obciążenie (1 min) > 2,0 przez 5 min": "Condition: Load (1 min) > 2.0 for 5 min",
        "Warunek: Pobieranie WAN > 100,0 Mb/s": "Condition: WAN download > 100.0 Mb/s",
        "Stan z agenta UplinkView od 2 min (filtr: web*)": "State from the UplinkView agent for 2 min (filter: web*)",
        "Ta operacja wymaga uprawnień podglądu": "This operation requires viewer permissions",
        "Kontroler UniFi: urządzenie niedostępne": "UniFi controller: device unavailable",
        "NXDOMAIN: nazwa nie istnieje": "NXDOMAIN: name does not exist",
        "Value error, Podaj nazwę sekcji": "Value error, Enter a section name",
        "UCG nie odpowiada\nZa nim nie odpowiada też: AP, Switch": "UCG is not responding\nAlso not responding behind it: AP, Switch",
        "Brak połączenia z OPNsense: ConnectError: refused": "No connection to OPNsense: ConnectError: refused",
        "Mój pulpit": "My dashboard",
        # przedrostek źródła przed błędem (0.75.1: tak zapisuje błąd kolektor UniFi)
        "Kontroler UniFi: Kontroler odpowiedział kodem 401": "UniFi controller: The controller responded with code 401",
        # spoza katalogu – bez zmian
        "Garaż": "Garaż",
        "2026-11-13T10:00:00Z": "2026-11-13T10:00:00Z",
    }
    for pl, en in cases.items():
        assert translate(pl, "en") == en, pl
        assert translate(pl, "pl") == pl


def test_accept_language():
    assert parse_accept_language("en-GB,en;q=0.9,pl;q=0.8") == "en"
    assert parse_accept_language("pl-PL,pl;q=0.9,en;q=0.8") == "pl"
    assert parse_accept_language("de-DE, en;q=0.5") == "en"
    assert parse_accept_language("de") == "pl"
    assert parse_accept_language(None) == "pl"
    assert parse_accept_language("en;q=abc, pl;q=0.1") == "pl"


class _Body(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Podaj nazwę sekcji")
        return v


def _app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(LanguageMiddleware)

    @app.get("/api/devices/{device_id}")
    async def device(device_id: int):
        raise HTTPException(404, "Nie ma takiego urządzenia")

    @app.get("/api/alerts")
    async def alerts():
        return [{"title": "Garaż nie odpowiada", "message": None, "name": "Garaż", "value": 1.5, "lang": i18n.current_language()}]

    @app.post("/api/sections")
    async def sections(body: _Body):
        return body

    @app.get("/api/devices/{device_id}/metrics")
    async def metrics(device_id: int):
        return [{"name": "Mój pulpit"}]

    return app


def test_middleware_translates_json_for_english_only():
    client = TestClient(_app())
    en = {"Accept-Language": "en"}
    r = client.get("/api/devices/1", headers=en)
    assert r.status_code == 404 and r.json() == {"detail": "No such device"}
    assert int(r.headers["content-length"]) == len(r.content)
    assert client.get("/api/devices/1").json() == {"detail": "Nie ma takiego urządzenia"}
    assert client.get("/api/alerts", headers=en).json() == [
        {"title": "Garaż is not responding", "message": None, "name": "Garaż", "value": 1.5, "lang": "en"}
    ]
    assert client.get("/api/alerts", headers={"Accept-Language": "pl-PL"}).json()[0]["title"] == "Garaż nie odpowiada"
    r = client.post("/api/sections", json={"name": " "}, headers=en)
    assert r.status_code == 422 and r.json()["detail"][0]["msg"] == "Value error, Enter a section name"
    # serie liczb nie przechodzą przez tłumaczenie
    assert client.get("/api/devices/1/metrics", headers=en).json() == [{"name": "Mój pulpit"}]
