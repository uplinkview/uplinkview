"""Szyfrowanie sekretów w bazie: community SNMP, klucze SNMPv3, klucz API kontrolera, adres webhooka.

Klucz: zmienna `NETPULSE_SECRET_KEY` (deploy/.env, opcjonalnie) albo plik `/var/lib/netpulse/secret.key`
w wolumenie Dockera `netpulse_keys`, tworzony przy pierwszym starcie (losowy, jeden na instalację).
Wartość w bazie: `enc:v1:` + token Fernet (AES-128-CBC + HMAC-SHA256) z kluczem wyprowadzonym przez SHA-256.

- Bez klucza (np. testy, uruchomienie poza Dockerem) wartości zostają jawnym tekstem, a w logu jest ostrzeżenie.
- Wartości bez prefiksu są czytane jak dotąd i szyfrowane przy starcie (`encrypt_existing`).
- Kopia bazy zawiera sekrety zaszyfrowane – przy przenoszeniu na nowy serwer potrzebny jest ten sam klucz.
  Bez niego sekret czyta się jako pusty (trzeba go wpisać ponownie), a reszta danych działa.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import secrets
from functools import lru_cache
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

from .config import settings

log = logging.getLogger(__name__)

PREFIX = "enc:v1:"
# Kolumny z sekretami: tabela → kolumny (do zaszyfrowania wartości zapisanych przed wersją 0.15)
SECRET_COLUMNS: dict[str, tuple[str, ...]] = {
    "devices": ("community", "v3_auth_key", "v3_priv_key"),
    "controllers": ("api_key",),
    "notification_channels": ("url", "secret"),
    "proxmox_servers": ("token_secret",),
    "opnsense_apis": ("api_key", "api_secret"),
    "dashboards": ("public_token",),
    "users": ("totp_secret",),
}

_key: str | None = None  # nadpisanie w testach; None = z ustawień
_file_key: str | None = None  # klucz odczytany z pliku (raz na proces)


def set_key(key: str | None) -> None:
    """Tylko dla testów: inny klucz niż w ustawieniach (pusty tekst = bez szyfrowania)."""
    global _key
    _key = key


def load_or_create_key(path: Path) -> str:
    """Klucz z pliku; gdy pliku nie ma, a katalog istnieje – nowy, losowy. Pusty tekst, gdy się nie da.

    Kolektor i API mogą wystartować naraz: plik powstaje atomowo (link do pliku tymczasowego nie nadpisuje
    istniejącego), więc obie usługi zawsze używają tego samego klucza."""
    try:
        return path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        pass
    except OSError as exc:
        log.error("Nie da się odczytać klucza szyfrowania %s: %s", path, exc)
        return ""
    if not path.parent.is_dir():
        return ""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}")
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(secrets.token_hex(32) + "\n")
            f.flush()
            os.fsync(f.fileno())
        try:
            os.link(tmp, path)
            log.info("Utworzono klucz szyfrowania sekretów: %s", path)
        except FileExistsError:
            pass  # druga usługa była szybsza – używamy jej klucza
    except OSError as exc:
        log.error("Nie da się utworzyć klucza szyfrowania %s: %s", path, exc)
        return ""
    finally:
        tmp.unlink(missing_ok=True)
    return path.read_text(encoding="utf-8").strip()


def _secret() -> str:
    global _file_key
    if _key is not None:
        return _key
    if settings.secret_key:
        return settings.secret_key
    if _file_key is None or not _file_key:
        _file_key = load_or_create_key(Path(settings.secret_key_file)) if settings.secret_key_file else ""
    return _file_key


@lru_cache(maxsize=4)
def _fernet_for(secret: str) -> Fernet:
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest()))


def enabled() -> bool:
    return bool(_secret())


def encrypt(value: str | None) -> str | None:
    if not value or value.startswith(PREFIX) or not enabled():
        return value
    return PREFIX + _fernet_for(_secret()).encrypt(value.encode()).decode()


@lru_cache(maxsize=64)
def _warn_once(message: str) -> None:
    log.error(message)


def decrypt(value: str | None) -> str | None:
    if value is None or not value.startswith(PREFIX):
        return value
    if not enabled():
        _warn_once("W bazie są zaszyfrowane sekrety, a klucza szyfrowania nie ma (wolumen netpulse_keys albo NETPULSE_SECRET_KEY)")
        return None
    try:
        return _fernet_for(_secret()).decrypt(value[len(PREFIX) :].encode()).decode()
    except InvalidToken:
        _warn_once("Nie udało się odszyfrować sekretu – inny NETPULSE_SECRET_KEY niż przy zapisie? Wpisz sekret ponownie w panelu")
        return None


class EncryptedText(TypeDecorator):
    """Kolumna tekstowa szyfrowana przy zapisie i odszyfrowywana przy odczycie (przezroczyście dla ORM)."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return encrypt(value)

    def process_result_value(self, value, dialect):
        return decrypt(value)
