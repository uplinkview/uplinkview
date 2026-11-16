"""Sesje logowania, role kont, ochrona CSRF i limit prób logowania.

Role (od 0.61.0): zmiany (POST/PUT/PATCH/DELETE) robi tylko administrator, z wyjątkiem tras z `ROLE_RULES`
– tam wystarczy rola operatora albo podglądu. Nowa trasa zmieniająca dane jest więc domyślnie tylko dla
administratora; trasę dla innych ról trzeba dopisać tutaj świadomie."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import delete
from starlette.requests import HTTPConnection

from ..auth import hash_token, new_token
from ..config import settings
from ..db import Session
from ..db.models import AuthSession, User

# Ciasteczko sesji: przez HTTPS (z flagą Secure) i osobne przez HTTP (od 0.65.5). Przy jednej nazwie przeglądarka po
# logowaniu przez HTTPS (:8443) nie pozwala stronie HTTP (:8080) nadpisać tego ciasteczka (porty go nie rozdzielają),
# a przez HTTP go nie wysyła – logowanie się udawało, a panel od razu wracał do ekranu logowania.
COOKIE = "netpulse_session"
COOKIE_HTTP = "netpulse_session_http"
# Co ile przedłużać sesję przy aktywności (żeby nie pisać do bazy przy każdym żądaniu)
REFRESH_EVERY = timedelta(hours=1)
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _session_ttl() -> timedelta:
    return timedelta(days=settings.session_days)


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "?"


def _secure(conn: HTTPConnection) -> bool:
    return conn.url.scheme in ("https", "wss")


def cookie_name(conn: HTTPConnection) -> str:
    return COOKIE if _secure(conn) else COOKIE_HTTP


def session_token(conn: HTTPConnection) -> str | None:
    """Token sesji z ciasteczka – najpierw z nazwy dla tego protokołu, potem z drugiej (sesje sprzed 0.65.5,
    aplikacja Android 0.2.0 i HTTPS, do którego przeglądarka dosyła też ciasteczko z HTTP)."""
    first = cookie_name(conn)
    for name in (first, COOKIE_HTTP if first == COOKIE else COOKIE):
        if token := conn.cookies.get(name):
            return token
    return None


def set_session_cookie(response: Response, request: HTTPConnection, token: str) -> None:
    response.set_cookie(
        cookie_name(request),
        token,
        max_age=int(_session_ttl().total_seconds()),
        httponly=True,
        samesite="lax",
        secure=_secure(request),
        path="/",
    )


def clear_session_cookie(response: Response, request: HTTPConnection) -> None:
    response.delete_cookie(COOKIE_HTTP, path="/")
    # Ciasteczko Secure usuwa tylko odpowiedź przez HTTPS; przez HTTP usuwamy stare `netpulse_session` sprzed 0.65.5
    response.delete_cookie(COOKIE, path="/", secure=_secure(request), httponly=True, samesite="lax")


async def start_session(session, user: User, request: Request) -> str:
    """Tworzy sesję w bazie (w transakcji wywołującego) i zwraca token do ciasteczka."""
    now = datetime.now(UTC)
    token = new_token()
    session.add(
        AuthSession(
            token_hash=hash_token(token),
            user_id=user.id,
            created_at=now,
            last_seen_at=now,
            expires_at=now + _session_ttl(),
            ip=client_ip(request)[:64],
            user_agent=(request.headers.get("user-agent") or "")[:255] or None,
        )
    )
    user.last_login_at = now
    # Sprzątanie wygasłych sesji przy okazji logowania
    await session.execute(delete(AuthSession).where(AuthSession.expires_at < now))
    return token


@dataclass
class _CachedSession:
    user: User
    expires_at: datetime
    last_seen_at: datetime
    checked: float  # time.monotonic() ostatniego sprawdzenia w bazie


# Pamięć sprawdzonych sesji (od 0.67.0): skrót tokenu → użytkownik. Pulpit z kilkunastoma widgetami pyta API
# kilkadziesiąt razy na odświeżenie, a każde żądanie czytało z bazy sesję i użytkownika. Wpis żyje
# `settings.session_cache_s` sekund; zmiany sesji i kont w API czyszczą pamięć od razu (`forget_sessions`).
# Zmiana z innego procesu (`uplinkview user passwd`, `2fa-off`) działa najpóźniej po tym czasie.
SESSION_CACHE_S = settings.session_cache_s  # osobna zmienna: testy włączają pamięć u siebie
_sessions: dict[str, _CachedSession] = {}
_SESSIONS_MAX = 1000


def forget_sessions() -> None:
    """Czyści pamięć sesji – wołać po każdej zmianie sesji albo konta (wylogowanie, hasło, rola, usunięcie, 2FA)."""
    _sessions.clear()


async def user_from_request(request: Request, response: Response | None = None) -> User | None:
    token = session_token(request)
    if not token:
        return None
    now = datetime.now(UTC)
    key = hash_token(token)
    ttl = SESSION_CACHE_S
    cached = _sessions.get(key) if ttl > 0 else None
    if cached is not None:
        fresh = time.monotonic() - cached.checked < ttl and cached.expires_at > now
        # Sesja do przedłużenia (raz na godzinę) idzie zwykłą drogą – z zapisem do bazy i nowym ciasteczkiem
        if fresh and now - cached.last_seen_at <= REFRESH_EVERY:
            return cached.user
        _sessions.pop(key, None)
    async with Session() as session, session.begin():
        auth = await session.get(AuthSession, key)
        if auth is None or auth.expires_at <= now:
            return None
        user = await session.get(User, auth.user_id)
        if user is None:
            return None
        if now - auth.last_seen_at > REFRESH_EVERY:
            auth.last_seen_at = now
            auth.expires_at = now + _session_ttl()
            if response is not None:
                set_session_cookie(response, request, token)
        if ttl > 0:
            if len(_sessions) >= _SESSIONS_MAX:
                _sessions.clear()
            _sessions[key] = _CachedSession(user, auth.expires_at, auth.last_seen_at, time.monotonic())
        return user


RANK = {"viewer": 0, "operator": 1, "admin": 2}
# (metoda, szablon trasy) → najniższa rola, która może to zrobić; reszta zmian = administrator
ROLE_RULES: dict[tuple[str, str], str] = {
    # każdy: własne hasło, odświeżanie i własne pulpity (pulpity mają właściciela)
    ("POST", "/api/auth/password"): "viewer",
    ("POST", "/api/auth/totp/setup"): "viewer",
    ("POST", "/api/auth/totp/enable"): "viewer",
    ("POST", "/api/auth/totp/disable"): "viewer",
    ("POST", "/api/auth/totp/recovery"): "viewer",
    ("PUT", "/api/preferences/refresh"): "viewer",
    ("PUT", "/api/dashboards/default"): "viewer",
    ("DELETE", "/api/dashboards/default"): "viewer",
    ("POST", "/api/dashboards"): "viewer",
    ("PATCH", "/api/dashboards/{dashboard_id}"): "viewer",
    ("DELETE", "/api/dashboards/{dashboard_id}"): "viewer",
    ("POST", "/api/dashboards/{dashboard_id}/default"): "viewer",
    # operator: obsługa bieżąca
    ("POST", "/api/alerts/{alert_id}/ack"): "operator",
}
ROLE_NAMES = {"admin": "administratora", "operator": "operatora", "viewer": "podglądu"}


def route_template(request: HTTPConnection) -> str:
    route = request.scope.get("route")
    return getattr(route, "path", None) or request.url.path


def required_role(method: str, template: str) -> str:
    if method not in UNSAFE_METHODS:
        return "viewer"
    return ROLE_RULES.get((method, template), "admin")


def has_role(user: User, role: str) -> bool:
    return RANK.get(user.role, 0) >= RANK[role]


async def require_user(request: Request, response: Response) -> User:
    """Zależność FastAPI: zalogowany użytkownik albo 401; zmiany zgodnie z rolą (ROLE_RULES) albo 403."""
    user = await user_from_request(request, response)
    if user is None:
        raise HTTPException(401, "Wymagane logowanie", headers={"WWW-Authenticate": "Cookie"})
    request.state.user = user
    need = required_role(request.method, route_template(request))
    if not has_role(user, need):
        raise HTTPException(403, f"Ta operacja wymaga uprawnień {ROLE_NAMES[need]}")
    return user


CurrentUser = Annotated[User, Depends(require_user)]


async def require_admin(user: CurrentUser) -> User:
    """Zależność FastAPI: tylko administrator – także odczyt (kopie zapasowe, konta, dziennik audytu)."""
    if user.role != "admin":
        raise HTTPException(403, "Ta operacja wymaga uprawnień administratora")
    return user


AdminUser = Annotated[User, Depends(require_admin)]


async def require_operator(user: CurrentUser) -> User:
    if not has_role(user, "operator"):
        raise HTTPException(403, "Ta operacja wymaga uprawnień operatora")
    return user


OperatorUser = Annotated[User, Depends(require_operator)]


def allowed_hosts(request: HTTPConnection) -> set[str]:
    hosts = {request.headers.get("host", "").lower()}
    if fwd := request.headers.get("x-forwarded-host"):
        hosts.add(fwd.split(",")[0].strip().lower())
    for origin in settings.trusted_origins.split(","):
        if origin.strip():
            hosts.add(urlsplit(origin.strip()).netloc.lower())
    hosts.discard("")
    return hosts


async def check_origin(request: HTTPConnection) -> None:
    """CSRF: zmiany (POST/PATCH/DELETE) tylko z tej samej strony.

    Przeglądarka zawsze dodaje Origin do żądań między stronami, więc obca strona
    (np. inna aplikacja w homelabie na innym porcie) nie wyśle nic w naszym imieniu.
    Klienci spoza przeglądarki (curl, skrypty) Origin nie wysyłają.
    """
    # WebSocket (brak metody) sprawdza Origin sam przy łączeniu – patrz api/live.py
    if getattr(request, "method", None) not in UNSAFE_METHODS:
        return
    origin = request.headers.get("origin") or request.headers.get("referer")
    if origin is None:
        return
    if origin == "null" or urlsplit(origin).netloc.lower() not in allowed_hosts(request):
        raise HTTPException(403, "Żądanie z innej strony odrzucone (CSRF)")


# Limit nieudanych logowań na jedno konto, niezależnie od adresu (od 0.68.0): zgadywanie hasła z wielu adresów naraz
# (albo zza wspólnego reverse proxy) omijało limit na adres. Wyższy niż limit adresu – pomyłki kilku osób to nie atak.
USER_MAX_FAILURES = 20
TRUSTED_FOR_S = 30 * 86400.0


def username_key(username: str) -> str:
    return "user:" + username.strip().lower()[:64]


class LoginLimiter:
    """Prosty limit nieudanych logowań na adres IP i na konto (w pamięci procesu API).

    Blokada konta nie dotyczy adresu, z którego to konto niedawno się zalogowało (`trust`) – ktoś, kto zgaduje
    hasło administratora, nie odcina go od panelu na jego własnym komputerze."""

    def __init__(self, max_failures: int = 10, window_s: float = 900) -> None:
        self.max_failures = max_failures
        self.window_s = window_s
        self._failures: dict[str, deque[float]] = defaultdict(deque)
        self._trusted: dict[tuple[str, str], float] = {}

    def _recent(self, key: str, now: float) -> deque[float]:
        q = self._failures[key]
        while q and now - q[0] > self.window_s:
            q.popleft()
        return q

    def retry_after(self, key: str, now: float | None = None, max_failures: int | None = None) -> int | None:
        """Sekundy do odblokowania albo None, gdy można próbować."""
        now = time.monotonic() if now is None else now
        q = self._recent(key, now)
        limit = self.max_failures if max_failures is None else max_failures
        if len(q) < limit:
            return None
        return max(1, int(self.window_s - (now - q[-limit])))

    def trust(self, ip: str, user_key: str, now: float | None = None) -> None:
        """Zapamiętuje udane logowanie konta z tego adresu (na 30 dni albo do restartu API)."""
        now = time.monotonic() if now is None else now
        if len(self._trusted) > 5000:
            self._trusted = {k: t for k, t in self._trusted.items() if now - t < TRUSTED_FOR_S}
        self._trusted[(ip, user_key)] = now

    def trusted(self, ip: str, user_key: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        seen = self._trusted.get((ip, user_key))
        return seen is not None and now - seen < TRUSTED_FOR_S

    def failure(self, key: str, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        if len(self._failures) > 5000:
            self.prune(now)
        self._recent(key, now).append(now)

    def success(self, key: str) -> None:
        self._failures.pop(key, None)

    def prune(self, now: float | None = None) -> None:
        """Usuwa adresy bez prób w oknie – bez tego słownik rósłby z każdym adresem, który kiedyś się pomylił."""
        now = time.monotonic() if now is None else now
        for key in [k for k in self._failures if not self._recent(k, now)]:
            del self._failures[key]


login_limiter = LoginLimiter()
