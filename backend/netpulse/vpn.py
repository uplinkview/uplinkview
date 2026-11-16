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

from .db.models import AppSetting, Interface, InterfaceMetric, Metric
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
                "interface": (s.interface if s else None) or old.get("interface"),
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
        if u["connected"] and u.get("rate_source") != "interface":  # z interfejsu: `use_interface_rates`
            for name, field in (("vpn_down_bps", "down_bps"), ("vpn_up_bps", "up_bps")):
                if u[field] is not None:
                    rows.append(Metric(time=now, device_id=device_id, name=name, key=key, value=u[field]))
    return rows


# Prędkość z licznika interfejsu bramy (od 0.86.1). Kontroler przelicza bajty klienta z opóźnieniem ok. minuty i nierówno
# (test 60 s UCG ↔ VPS 16.11.2026: sumy zgodne, ale szczyt wykresu klienta minutę po końcu transferu, 386 Mb/s zamiast
# 343). Gdy klient jest jedynym połączonym na swoim interfejsie (`wgsrv2` = tylko tunel do VPS), ruch interfejsu to jego
# ruch: próbki SNMP tego interfejsu (co 30 s, czas = środek przedziału) idą do `vpn_down_bps`/`vpn_up_bps` ze swoim czasem.
# Interfejs: in = od klienta (jego wysyłanie), out = do klienta. Kilku klientów na jednym serwerze – dalej bajty kontrolera.
IFACE_MAX_AGE = timedelta(seconds=90)  # najnowsza próbka interfejsu starsza = kolektor SNMP nie działa, zostaje kontroler
IFACE_FIRST = timedelta(seconds=60)  # pierwszy odczyt z interfejsu (bez `rate_until`) – tyle próbek wstecz


def single_client_interfaces(snap: dict) -> dict[str, str]:
    """Interfejs → klient dla interfejsów, na których jest połączony dokładnie jeden klient."""
    users: dict[str, list[str]] = {}
    for u in snap["users"]:
        if u["connected"] and u.get("interface"):
            users.setdefault(u["interface"], []).append(u["name"])
    return {iface: names[0] for iface, names in users.items() if len(names) == 1}


def use_interface_rates(
    device_id: int, snap: dict, prev: dict | None, samples: dict[str, list[tuple[datetime, float | None, float | None]]], now: datetime
) -> list[Metric]:
    """Przełącza klientów jedynych na swoim interfejsie na prędkość z próbek interfejsu (`samples`: nazwa → (czas, in, out)
    rosnąco). Zwraca wiersze `vpn_down_bps`/`vpn_up_bps` z próbek nowszych niż zapisane `rate_until` (pierwszy raz: z ostatniej
    minuty, nie sprzed połączenia) i ustawia w zdjęciu `rate_source`, `rate_until` oraz bieżące `down_bps`/`up_bps`."""
    previous = {u["name"]: u for u in (prev or {}).get("users", [])}
    by_name = {u["name"]: u for u in snap["users"]}
    rows: list[Metric] = []
    for iface, name in single_client_interfaces(snap).items():
        series = samples.get(iface) or []
        if not series or now - series[-1][0] > IFACE_MAX_AGE:
            continue
        u, old = by_name[name], previous.get(name, {})
        after = now - IFACE_FIRST
        if old.get("rate_until") and old.get("since") == u["since"]:
            after = datetime.fromisoformat(old["rate_until"])
        else:
            # Pierwszy raz: bez próbek sprzed połączenia i bez chwil, które opisał już poprzedni odczyt z kontrolera
            if u["since"]:
                after = max(after, datetime.fromisoformat(u["since"]) - timedelta(seconds=30))
            if old.get("connected") and old.get("since") == u["since"] and (prev or {}).get("at"):
                after = max(after, datetime.fromisoformat(prev["at"]))
        new = [s for s in series if s[0] > after]
        key = name[:255]
        for t, in_bps, out_bps in new:
            for metric, v in (("vpn_down_bps", out_bps), ("vpn_up_bps", in_bps)):
                if v is not None:
                    rows.append(Metric(time=t, device_id=device_id, name=metric, key=key, value=v))
        last = series[-1]
        u.update(rate_source="interface", rate_until=(new[-1][0] if new else after).isoformat(), down_bps=last[2], up_bps=last[1])
    return rows


async def interface_samples(session, device_id: int, names: Iterable[str], now: datetime) -> dict[str, list[tuple[datetime, float | None, float | None]]]:
    """Próbki interfejsów bramy o podanych nazwach z ostatnich 5 minut (nazwa → (czas, in_bps, out_bps) rosnąco)."""
    names = list(names)
    if not names:
        return {}
    rows = (
        await session.execute(
            select(Interface.name, InterfaceMetric.time, InterfaceMetric.in_bps, InterfaceMetric.out_bps)
            .join(InterfaceMetric, InterfaceMetric.interface_id == Interface.id)
            .where(Interface.device_id == device_id, Interface.name.in_(names), InterfaceMetric.time > now - timedelta(minutes=5))
            .order_by(Interface.name, InterfaceMetric.time)
        )
    ).all()
    out: dict[str, list[tuple[datetime, float | None, float | None]]] = {}
    for name, t, in_bps, out_bps in rows:
        series = out.setdefault(name, [])
        if not series or series[-1][0] != t:  # dwa wiersze o tej nazwie (przesunięty ifIndex) – jedna próbka na chwilę
            series.append((t, in_bps, out_bps))
    return out


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
