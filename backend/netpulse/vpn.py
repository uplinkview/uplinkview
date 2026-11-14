"""VPN użytkowników zdalnych z kontrolera UniFi (od 0.57.0; opis: docs/30-vpn.md).

Kontroler podaje serwery VPN (`rest/networkconf`), skonfigurowanych klientów WireGuard (`v2/.../wireguard/users`)
i trwające połączenia (`stat/remoteuservpn`). Co cykl kolektora UniFi:

- **stan** (kto jest połączony, od kiedy, skąd, ile przesłał) – zdjęcie w `app_settings` pod `vpn:<id kontrolera>`,
  czytane przez `GET /api/vpn` i widget „VPN”; klient, który się rozłączył, zostaje z czasem ostatniego połączenia;
- **metryki** w ogólnej tabeli `metrics` (urządzenie = brama, klucz = nazwa klienta): `vpn_connected` (1/0 dla każdego
  znanego klienta – oś połączeń, wykrywanie nowych połączeń), `vpn_down_bps` / `vpn_up_bps` (pobieranie / wysyłanie
  klienta, tylko w trakcie połączenia) – źródło wykresu `vpn`;
- **nowe połączenie** = próbka `vpn_connected` 1 po próbce 0 (`connections`) – alert `vpn_connect` i kafelek „Zdarzenia”.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from .db.models import AppSetting, Metric
from .unifi import VpnServer, VpnSession, VpnUser

KEY_PREFIX = "vpn:"
# Dwie próbki dalej od siebie niż to = przerwa w odczytach, a nie „rozłączył się i połączył”
SAMPLE_GAP = timedelta(seconds=150)

VPN_TYPES = {
    "wireguard-server": "WireGuard",
    "openvpn-server": "OpenVPN",
    "l2tp-server": "L2TP",
    "pptp-server": "PPTP",
}


def _iso(ts: int | None) -> str | None:
    return datetime.fromtimestamp(ts, UTC).isoformat() if ts else None


# Prędkość z przyrostu bajtów od poprzedniego zdjęcia (od 0.85.5): `rx_rate`/`tx_rate` kontrolera to wartość z ok. 1 s,
# więc jeden odczyt co 30 s przy ruchu w porywach trafiał raz w szczyt, raz w ciszę (tunel WG-VPS 14.11.2026: −53 % / −27 %
# względem liczników jądra bramy w 10 min; bajty kontrolera zgodne co do bajta). Chwilowa wartość zostaje dla pierwszego
# odczytu sesji, po przerwie dłuższej niż `RATE_MAX_GAP` i po wyzerowaniu licznika.
RATE_MAX_GAP = timedelta(seconds=150)


def _rate(now: datetime, prev_at: str | None, old: dict, since: str | None, field: str, value: float | None, fallback: float | None) -> float | None:
    if value is None or not prev_at or not old.get("connected") or old.get("since") != since or old.get(field) is None:
        return fallback
    dt = (now - datetime.fromisoformat(prev_at)).total_seconds()
    if dt <= 0 or dt > RATE_MAX_GAP.total_seconds() or value < old[field]:
        return fallback
    return (value - old[field]) * 8 / dt


def snapshot(
    servers: list[VpnServer], users: list[VpnUser], sessions: list[VpnSession], prev: dict | None, now: datetime, device_id: int | None
) -> dict:
    """Stan VPN do zapisu: serwery i klienci (skonfigurowani i połączeni). Rozłączony klient ma `last_seen` z poprzedniego
    stanu – widget pokazuje „ostatnio połączony”. Klient spoza listy (np. OpenVPN, L2TP) pojawia się, gdy się połączy."""
    previous = {u["name"]: u for u in (prev or {}).get("users", [])}
    prev_at = (prev or {}).get("at")
    by_name = {s.user: s for s in sessions}
    names = [u.name for u in users] + [s.user for s in sessions if s.user not in {u.name for u in users}]
    names += [n for n in previous if n not in names]  # klient, którego usunięto z listy, a łączył się – zostaje do końca zdjęcia
    configured = {u.name: u for u in users}
    out_users = []
    for name in dict.fromkeys(names):
        s = by_name.get(name)
        u = configured.get(name)
        old = previous.get(name, {})
        if s is None and u is None and not old.get("connected"):
            continue  # nie ma go w konfiguracji ani w połączeniach – stary wpis znika
        connected = s is not None
        since = _iso(s.connected_at) if s else None
        out_users.append(
            {
                "name": name,
                "server_id": (s.server_id if s else None) or (u.server_id if u else None) or old.get("server_id"),
                "tunnel_ip": (s.tunnel_ip if s else None) or (u.tunnel_ip if u else None) or old.get("tunnel_ip"),
                "connected": connected,
                "since": since,
                "remote_ip": s.remote_ip if s else old.get("remote_ip"),
                "down_bytes": s.tx_bytes if s else old.get("down_bytes"),
                "up_bytes": s.rx_bytes if s else old.get("up_bytes"),
                "down_bps": _rate(now, prev_at, old, since, "down_bytes", s.tx_bytes, s.tx_bps) if s else None,
                "up_bps": _rate(now, prev_at, old, since, "up_bytes", s.rx_bytes, s.rx_bps) if s else None,
                "last_seen": now.isoformat() if connected else old.get("last_seen"),
            }
        )
    return {
        "at": now.isoformat(),
        "device_id": device_id,
        "servers": [
            {"id": v.id, "name": v.name, "type": VPN_TYPES.get(v.vpn_type, v.vpn_type), "enabled": v.enabled, "port": v.port, "subnet": v.subnet}
            for v in servers
        ],
        "users": out_users,
    }


def metrics(device_id: int, snap: dict, now: datetime) -> list[Metric]:
    rows: list[Metric] = []
    for u in snap["users"]:
        key = u["name"][:255]
        rows.append(Metric(time=now, device_id=device_id, name="vpn_connected", key=key, value=1.0 if u["connected"] else 0.0))
        if u["connected"]:
            for name, field in (("vpn_down_bps", "down_bps"), ("vpn_up_bps", "up_bps")):
                if u[field] is not None:
                    rows.append(Metric(time=now, device_id=device_id, name=name, key=key, value=u[field]))
    return rows


async def previous(session, controller_id: int) -> dict | None:
    row = await session.get(AppSetting, f"{KEY_PREFIX}{controller_id}")
    return row.value if row is not None else None


async def save(session, controller_id: int, snap: dict) -> None:
    stmt = insert(AppSetting).values(key=f"{KEY_PREFIX}{controller_id}", value=snap)
    await session.execute(
        stmt.on_conflict_do_update(index_elements=[AppSetting.key], set_={"value": stmt.excluded.value, "updated_at": func.now()})
    )


async def read_all(session) -> list[dict]:
    """Zdjęcia VPN wszystkich kontrolerów."""
    rows = await session.scalars(select(AppSetting).where(AppSetting.key.startswith(KEY_PREFIX)).order_by(AppSetting.key))
    return [r.value for r in rows if r.value]


@dataclass(frozen=True)
class VpnConnection:
    time: datetime
    device_id: int
    user: str


def detect(samples: Iterable[tuple[int, str, datetime, float]]) -> list[VpnConnection]:
    """Nowe połączenia z próbek `vpn_connected` (urządzenie, klient, czas, wartość) posortowanych po kliencie i czasie:
    1 tuż po 0. Pierwsza próbka w ogóle albo po przerwie w odczytach nie jest połączeniem (nie wiadomo, co było wcześniej)."""
    out = []
    last: dict[tuple[int, str], tuple[datetime, float]] = {}
    for dev, user, at, value in samples:
        prev = last.get((dev, user))
        if value >= 0.5 and prev is not None and prev[1] < 0.5 and at - prev[0] <= SAMPLE_GAP:
            out.append(VpnConnection(at, dev, user))
        last[(dev, user)] = (at, value)
    return out


async def connections(session, device_ids: Iterable[int], since: datetime, until: datetime) -> list[VpnConnection]:
    ids = list(device_ids)
    if not ids:
        return []
    rows = (
        await session.execute(
            select(Metric.device_id, Metric.key, Metric.time, Metric.value)
            .where(Metric.name == "vpn_connected", Metric.device_id.in_(ids), Metric.time >= since - SAMPLE_GAP, Metric.time < until)
            .order_by(Metric.device_id, Metric.key, Metric.time)
        )
    ).all()
    return [c for c in detect(rows) if c.time >= since]
