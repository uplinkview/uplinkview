"""Kolektor OPNsense API (od 0.81.0): co cykl czyta API każdego urządzenia z kluczem (Ustawienia → OPNsense).

Zapisuje w ogólnej tabeli `metrics` na urządzeniu OPNsense:
- `wan_latency_ms`, `wan_jitter_ms`, `wan_loss_percent` – klucz = interfejs bramy (np. `em1`), jak pomiary bramy UniFi,
  więc działa to samo źródło wykresu „Opóźnienie WAN” i te same reguły alertów,
- `gateway_up` (1/0) – klucz = nazwa bramy (WAN_DHCP), tylko bramy z monitorowaniem,
- `opnsense_service_up` (1/0) – klucz = id usługi,
- `client_down_bps`, `client_up_bps` (od 0.82.0) – ruch urządzenia w sieci LAN z próbki OPNsense, klucz = MAC;
  wiersz dla każdego znanego urządzenia (DHCP/ARP) z mierzonej sieci, także 0 – średnia na wykresie jest wtedy uczciwa.
Stan bram trafia też do łączy WAN (`wan_links.apply_controller`): brama działa/nie działa i która ma trasę domyślną –
kolektor SNMP użyje tego w następnym cyklu (aktywne łącze, alert przełączenia WAN).
Pozostałe dane (wersja, interfejsy, usługi, urządzenia z DHCP i ARP) – w `opnsense_apis.snapshot` do panelu.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from . import wan_links
from .collector import _write_with_retry
from .config import settings
from .db import Session
from .db.models import Device, Metric, OpnsenseApi
from .modules import is_enabled
from .opnsense import OpnsenseApi as Client
from .opnsense import OpnsenseError, Snapshot

log = logging.getLogger("netpulse.opnsense")


@dataclass(frozen=True)
class Target:
    id: int
    device_id: int
    name: str
    host: str
    port: int
    key: str
    secret: str
    verify_tls: bool


@dataclass(frozen=True)
class WanState:
    """Co OPNsense wie o łączu WAN – w formacie, którego oczekuje `wan_links.apply_controller`."""

    ifname: str
    up: bool
    active: bool


def make_client(t: Target) -> Client:
    return Client(t.host, t.key, t.secret, port=t.port, verify_tls=t.verify_tls, timeout=max(5.0, settings.snmp_timeout * 3))


def metric_rows(dev_id: int, snap: Snapshot, now: datetime) -> list[dict]:
    rows: dict[tuple[str, str], float] = {}
    for g in snap.gateways:
        if g.up is None:
            continue  # brama bez monitorowania – OPNsense nic o niej nie mierzy
        rows[("gateway_up", g.name)] = 1.0 if g.up else 0.0
        if g.interface:
            for name, value in (("wan_latency_ms", g.delay_ms), ("wan_jitter_ms", g.jitter_ms), ("wan_loss_percent", g.loss_percent)):
                if value is not None:
                    rows.setdefault((name, g.interface), value)  # kilka bram na jednym interfejsie (v4/v6) – pierwsza
    for s in snap.services:
        rows[("opnsense_service_up", s.name)] = 1.0 if s.running else 0.0
    for h in snap.hosts:
        if h.down_bps is not None and h.up_bps is not None:
            rows[("client_down_bps", h.mac)] = h.down_bps
            rows[("client_up_bps", h.mac)] = h.up_bps
    return [{"time": now, "device_id": dev_id, "name": n, "key": k[:255], "value": v} for (n, k), v in rows.items()]


def wan_states(snap: Snapshot) -> list[WanState]:
    return [WanState(g.interface, bool(g.up), g.default) for g in snap.gateways if g.interface and g.up is not None]


class OpnsenseCollector:
    def __init__(self, client_factory=make_client) -> None:
        self.client_factory = client_factory

    async def run_forever(self) -> None:
        log.info("Kolektor OPNsense start: interwał %ss", settings.poll_interval)
        while True:
            started = time.monotonic()
            try:
                await self.poll_all()
            except Exception:
                log.exception("Błąd cyklu odpytywania OPNsense")
            await asyncio.sleep(max(1.0, settings.poll_interval - (time.monotonic() - started)))

    async def load_targets(self) -> list[Target]:
        async with Session() as session:
            rows = (
                await session.execute(
                    select(OpnsenseApi, Device.name, Device.host)
                    .join(Device, Device.id == OpnsenseApi.device_id)
                    .where(OpnsenseApi.enabled, Device.enabled)
                )
            ).all()
        return [Target(a.id, a.device_id, name, host, a.port, a.api_key or "", a.api_secret or "", a.verify_tls) for a, name, host in rows]

    async def poll_all(self) -> None:
        if not await is_enabled("opnsense"):
            return  # moduł wyłączony (Ustawienia → Moduły)
        targets = await self.load_targets()
        if targets:
            await asyncio.gather(*(self.poll_one(t) for t in targets))

    async def poll_one(self, target: Target) -> bool:
        now = datetime.now(UTC)
        client = self.client_factory(target)
        try:
            snap = await client.snapshot()
            await client.read_traffic(snap)
        except OpnsenseError as exc:
            log.warning("%s (%s): %s", target.name, target.host, exc)
            await self.save_failure(target, now, str(exc))
            return False
        except Exception as exc:
            log.exception("%s (%s): błąd odczytu OPNsense", target.name, target.host)
            await self.save_failure(target, now, f"{type(exc).__name__}: {exc}")
            return False
        finally:
            await client.close()
        await self.save_result(target, now, snap)
        return True

    async def save_failure(self, target: Target, now: datetime, error: str) -> None:
        async def write(session) -> None:
            await session.execute(
                update(OpnsenseApi).where(OpnsenseApi.id == target.id).values(status="down", last_polled_at=now, last_error=error[:2000])
            )

        await _write_with_retry(write)

    async def save_result(self, target: Target, now: datetime, snap: Snapshot) -> None:
        rows = metric_rows(target.device_id, snap, now)
        wans = wan_states(snap)

        async def write(session) -> None:
            await session.execute(
                update(OpnsenseApi)
                .where(OpnsenseApi.id == target.id)
                .values(
                    status="up",
                    version=(snap.version or "")[:32] or None,
                    latest_version=(snap.latest or "")[:32] or None,
                    snapshot=snap.as_dict(),
                    last_polled_at=now,
                    last_ok_at=now,
                    last_error=None,
                )
            )
            if rows:
                await session.execute(insert(Metric).values(rows).on_conflict_do_nothing())
            if wans:
                await wan_links.apply_controller(session, target.device_id, wans, now)

        await _write_with_retry(write)
