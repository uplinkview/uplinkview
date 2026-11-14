"""REST API UplinkView (FastAPI).

Wszystko poza /api/health i /api/auth/{status,setup,login} wymaga zalogowania
(ciasteczko sesji). Wyjątki: agenci serwerów (/api/agent/v1/report) logują się tokenem, a pulpity publiczne
(/api/public/dashboards/<token>) mają własne API tylko do odczytu z białą listą danych (public.py). Pierwsze konto administratora zakłada kreator: POST /api/auth/setup.
Dokumentacja interaktywna (od 0.65.6 tylko po zalogowaniu): http://<serwer>:8000/docs
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse
from sqlalchemy import text

from .. import __version__, audit
from ..config import settings
from ..db import engine, has_timescale
from ..i18n import LanguageMiddleware
from . import (
    agents,
    alerts,
    auth_routes,
    availability,
    backups,
    checks,
    clients,
    controllers,
    dashboard,
    dashboards,
    devices,
    discovery,
    events,
    live,
    maintenance,
    metrics,
    modules_api,
    notifications,
    opnsense,
    panels,
    preferences,
    proxmox,
    public,
    reports,
    servers,
    system,
    topology,
    updates,
    users,
    vpn,
    wan,
)
from . import (
    tls as tls_api,
)
from .security import CurrentUser, check_origin, client_ip, route_template
from .web import content_security_policy, mount_web, panel_script_hashes


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Cykliczne sprawdzanie aktualizacji (jeśli włączone w ustawieniach), żeby panel mógł o nich przypomnieć
    task = asyncio.create_task(updates.auto_check_loop())
    try:
        yield
    finally:
        task.cancel()


# Dokumentacja i schemat API tylko dla zalogowanych (od 0.65.6) – trasy niżej, standardowe są wyłączone
app = FastAPI(
    title="UplinkView API",
    version=__version__,
    dependencies=[Depends(check_origin)],
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

# Nagłówki bezpieczeństwa każdej odpowiedzi HTTP (od 0.65.6). Bez osadzania panelu w obcych stronach (clickjacking),
# bez zgadywania typu treści; odpowiedź może ustawić własną wartość (np. pulpit publiczny: Referrer-Policy no-referrer).
# Od 0.68.0 pełna polityka treści (web.content_security_policy) ze skrótem skryptu motywu z index.html.
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "SAMEORIGIN",
    "Referrer-Policy": "same-origin",
    "Content-Security-Policy": content_security_policy(panel_script_hashes(settings.web_dir) if settings.web_dir else ()),
}


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    return response


@app.middleware("http")
async def audit_changes(request: Request, call_next):
    """Dziennik audytu: każda zmiana zalogowanego użytkownika (też odrzucona) – bez treści żądania (audit.py)."""
    response = await call_next(request)
    if audit.should_record(request.method, request.url.path):
        user = getattr(request.state, "user", None)
        if user is not None:
            await audit.record(
                f"{request.method} {route_template(request)}",
                user=user,
                ip=client_ip(request),
                target=request.url.path,
                status=response.status_code,
            )
    return response
# Komunikaty po angielsku dla `Accept-Language: en` (od 0.75.0, netpulse/i18n.py) – najbardziej zewnętrzna warstwa
app.add_middleware(LanguageMiddleware)

app.include_router(agents.admin_router)
app.include_router(agents.push_router)
app.include_router(alerts.router)
app.include_router(auth_routes.router)
app.include_router(availability.router)
app.include_router(backups.router)
app.include_router(checks.router)
app.include_router(clients.router)
app.include_router(controllers.router)
app.include_router(dashboard.router)
app.include_router(dashboards.router)
app.include_router(events.router)
app.include_router(devices.router)
app.include_router(discovery.router)
app.include_router(live.router)
app.include_router(maintenance.router)
app.include_router(metrics.router)
app.include_router(modules_api.router)
app.include_router(notifications.router)
app.include_router(opnsense.router)
app.include_router(panels.router)
app.include_router(preferences.router)
app.include_router(proxmox.router)
app.include_router(public.router)
app.include_router(reports.router)
app.include_router(servers.router)
app.include_router(system.router)
app.include_router(tls_api.router)
app.include_router(topology.router)
app.include_router(updates.router)
app.include_router(users.router)
app.include_router(vpn.router)
app.include_router(wan.router)


@app.get("/api/health", tags=["system"])
async def health() -> dict:
    """Publiczne (healthcheck Dockera, instalator) – bez numeru wersji (od 0.65.6; wersję podaje /api/auth/status po zalogowaniu)."""
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
        timescale = await has_timescale(conn)
    return {"status": "ok", "timescaledb": timescale}


@app.get("/openapi.json", include_in_schema=False)
async def openapi_schema(_: CurrentUser) -> dict:
    return app.openapi()


# Dokumentacja Swagger UI ładuje skrypt i style z cdn.jsdelivr.net i ma skrypt w stronie – własna, luźniejsza polityka
# tylko dla tej jednej strony (dostępnej po zalogowaniu)
DOCS_CSP = (
    "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data: https://fastapi.tiangolo.com; "
    "connect-src 'self'; frame-ancestors 'self'; base-uri 'self'; object-src 'none'"
)


@app.get("/docs", include_in_schema=False)
async def api_docs(_: CurrentUser) -> HTMLResponse:
    page = get_swagger_ui_html(openapi_url="/openapi.json", title="UplinkView API")
    page.headers["Content-Security-Policy"] = DOCS_CSP
    return page


# Panel (frontend/dist) – na końcu, żeby nie przesłaniał tras API. W obrazie Dockera NETPULSE_WEB_DIR=/app/web
if settings.web_dir:
    mount_web(app, settings.web_dir)


__all__ = ["app"]
