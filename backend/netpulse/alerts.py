"""Alerty: ocena reguł po każdym cyklu kolektora.

Stan trzymamy w bazie (tabela `alerts`), nie w pamięci, więc restart kolektora niczego nie gubi.
Wyzwolony alert żyje, dopóki warunek jest spełniony; potem przechodzi w „zakończony”. Alerty dla
usuniętych albo wyłączonych reguł są kończone przy najbliższej ocenie."""

from __future__ import annotations

import hashlib
import logging
from collections import defaultdict, deque
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from fnmatch import fnmatchcase

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import distinct_on

from . import maintenance, vpn, wan_links
from .config import settings
from .db import Session
from .db.models import (
    Alert,
    AlertRule,
    AppSetting,
    Check,
    CheckMetric,
    Device,
    DeviceMetric,
    DiskMetric,
    Interface,
    InterfaceMetric,
    Metric,
    SystemMetric,
    TopologyLink,
)
from .freshness import is_stale
from .modules import hidden_drivers, read_modules
from .notifications import AlertEvent, Notifier
from .timeline import restarts, wan_switches

log = logging.getLogger("netpulse.alerts")

SEVERITIES = ("info", "warning", "critical")
# Rodzaje na ogólnej tabeli `metrics`: z agenta (kontener, usługa systemd, SMART) i z Proxmoxa (maszyna, kopia)
# … i z OPNsense API (od 0.81.0): brama nie działa, usługa OPNsense zatrzymana
AGENT_KINDS = ("container_stopped", "service_failed", "smart_failed", "guest_stopped", "backup_failed", "gateway_down", "opnsense_service_failed")
# Zdarzenia chwilowe (od 0.49.0): alert trwa EVENT_HOLD od zdarzenia i kończy się bez powiadomienia o końcu
EVENT_KINDS = ("wan_switch", "device_restart", "vpn_connect")
EVENT_HOLD = timedelta(minutes=10)
KINDS = ("device_offline", "port_down", "metric", *AGENT_KINDS, "check_down", "default_community", *EVENT_KINDS)
OPS = (">", "<")

# Metryki reguł typu „metric”: nazwa → (opis, jednostka). Pierwsze trzy są per urządzenie, WAN to suma po routerach.
METRICS: dict[str, tuple[str, str]] = {
    "cpu_percent": ("CPU", "%"),
    "mem_used_percent": ("RAM", "%"),
    "load1": ("Obciążenie (1 min)", ""),
    "wan_in_bps": ("Pobieranie WAN", "b/s"),
    "wan_out_bps": ("Wysyłanie WAN", "b/s"),
    "disk_used_percent": ("Zajętość dysku (każda partycja serwera)", "%"),
    "port_errors": ("Błędy na porcie (w jednym cyklu odczytu)", ""),
    "system_cpu_percent": ("Serwer UplinkView: CPU", "%"),
    "system_mem_used_percent": ("Serwer UplinkView: RAM", "%"),
    "system_disk_used_percent": ("Serwer UplinkView: dysk", "%"),
    "temp_c": ("Temperatura (każdy czujnik: serwer z agentem, MikroTik)", "°C"),
    "sfp_rx_dbm": ("SFP: moc odbierana (każdy moduł SFP: MikroTik, switche TP-Link)", " dBm"),
    "smart_reallocated": ("SMART: realokowane sektory (każdy dysk serwera z agentem)", ""),
    "backup_age_h": ("Proxmox: godziny od ostatniej kopii (każda VM i LXC)", " h"),
    "check_latency_ms": ("Sprawdzenie dostępności: opóźnienie", " ms"),
    "check_loss_percent": ("Sprawdzenie dostępności: utrata pakietów (ping)", "%"),
    "check_cert_days": ("Sprawdzenie dostępności: dni do wygaśnięcia certyfikatu", " dni"),
    "wan_latency_ms": ("Łącze WAN: opóźnienie (pomiar bramy UniFi albo OPNsense)", " ms"),
    "wan_loss_percent": ("Łącze WAN: utrata pakietów (pomiar bramy OPNsense)", "%"),
}
DEVICE_METRICS = ("cpu_percent", "mem_used_percent", "load1")
DISK_METRICS = ("disk_used_percent",)
PORT_METRICS = ("port_errors",)
# Metryki serwera, na którym działa UplinkView → kolumna w `system_metrics`
SYSTEM_METRICS = {
    "system_cpu_percent": "cpu_percent",
    "system_mem_used_percent": "mem_used_percent",
    "system_disk_used_percent": "disk_used_percent",
}
# Metryki z ogólnej tabeli `metrics` (agent, Proxmox, czujniki SNMP): nazwa reguły → nazwa w tabeli
# (jeden alert na klucz, np. czujnik, dysk albo port SFP)
AGENT_METRICS = {
    "temp_c": "temp_c", "smart_reallocated": "smart_reallocated", "backup_age_h": "backup_age_h", "sfp_rx_dbm": "sfp_rx_dbm",
    "wan_latency_ms": "wan_latency_ms", "wan_loss_percent": "wan_loss_percent",
}  # fmt: skip
# Tytuł alertu progu: „<urządzenie>: <co> <klucz> <wartość>”
AGENT_METRIC_WHAT = {
    "temp_c": "temperatura",
    "smart_reallocated": "realokowane sektory",
    "backup_age_h": "ostatnia kopia",
    "sfp_rx_dbm": "SFP moc odbierana",
    "wan_latency_ms": "opóźnienie łącza",
    "wan_loss_percent": "utrata pakietów łącza",
}
# Można je zawęzić do jednego urządzenia; pozostałe (WAN, serwer UplinkView) są globalne
PER_DEVICE_METRICS = DEVICE_METRICS + DISK_METRICS + PORT_METRICS + tuple(AGENT_METRICS)
# Sprawdzenia dostępności (od 0.30.0): metryka reguły → kolumna `check_metrics`; alert na każde sprawdzenie
CHECK_METRICS = {"check_latency_ms": "latency_ms", "check_loss_percent": "loss_percent", "check_cert_days": "cert_days"}
CHECK_METRIC_WHAT = {"check_latency_ms": "opóźnienie", "check_loss_percent": "utrata pakietów", "check_cert_days": "certyfikat wygasa za"}
# Reguły, które można zawęzić wzorcem nazwy (pole `match`)
MATCHABLE_METRICS = tuple(AGENT_METRICS) + tuple(CHECK_METRICS)

# Rodzaj reguły z agenta → (metryka w `metrics`, co jest podmiotem, opis stanu w tytule alertu)
AGENT_STATES = {
    "container_stopped": ("container_up", "kontener", "zatrzymany"),
    "service_failed": ("service_up", "usługa", "nie działa"),
    "smart_failed": ("smart_ok", "dysk", "zgłasza błąd SMART"),
    "guest_stopped": ("guest_up", "maszyna", "zatrzymana"),
    "backup_failed": ("backup_task_ok", "kopia zapasowa", "zakończyła się błędem"),
    "gateway_down": ("gateway_up", "brama", "nie działa"),
    "opnsense_service_failed": ("opnsense_service_up", "usługa", "nie działa"),
}
# Jak daleko wstecz szukać stanu portu sprzed przerwy w odczytach (restart switcha trwa minuty, nie godziny)
BREAK_LOOKBACK = timedelta(hours=1)
# Bez filtru nazwy alarm tylko dla tych, które przed chwilą działały (zatrzymane od dawna są zamierzone)
WENT_DOWN_KINDS = ("container_stopped", "guest_stopped")

# Reguły domyślne w kolejnych wersjach. Instalacja dostaje każdy zestaw raz (znacznik w app_settings),
# więc reguła usunięta przez użytkownika nie wraca po restarcie.
DEFAULT_RULE_SETS = (
    (
        dict(name="Urządzenie nie odpowiada", kind="device_offline", duration_s=120, severity="critical"),
        dict(name="Port przeszedł w stan down", kind="port_down", duration_s=0, severity="warning"),
    ),
    (
        dict(name="Kontener zatrzymany", kind="container_stopped", duration_s=60, severity="warning"),
        dict(name="Usługa systemd nie działa", kind="service_failed", duration_s=60, severity="warning"),
        dict(name="SMART: dysk zgłasza błąd", kind="smart_failed", duration_s=0, severity="critical"),
        dict(name="Wysoka temperatura", kind="metric", metric="temp_c", op=">", threshold=85.0, duration_s=300, severity="warning"),
    ),
    (
        dict(name="Proxmox: maszyna zatrzymana", kind="guest_stopped", duration_s=60, severity="warning"),
        dict(name="Proxmox: kopia zapasowa nie powiodła się", kind="backup_failed", duration_s=0, severity="critical"),
        dict(name="Proxmox: brak świeżej kopii VM", kind="metric", metric="backup_age_h", op=">", threshold=36.0, duration_s=0, severity="warning"),
    ),
    (
        dict(name="Sprawdzenie dostępności nie przechodzi", kind="check_down", duration_s=60, severity="warning"),
        dict(name="Certyfikat HTTPS wkrótce wygaśnie", kind="metric", metric="check_cert_days", op="<", threshold=14.0, duration_s=0, severity="warning"),
    ),
    (dict(name="Fabryczne community SNMP", kind="default_community", duration_s=0, severity="warning"),),
    (
        dict(name="Przełączenie łącza WAN", kind="wan_switch", duration_s=0, severity="warning"),
        dict(name="Restart urządzenia", kind="device_restart", duration_s=0, severity="info"),
    ),
    (dict(name="Nowe połączenie VPN", kind="vpn_connect", duration_s=0, severity="info"),),
    (
        dict(name="OPNsense: brama nie działa", kind="gateway_down", duration_s=60, severity="critical"),
        dict(name="OPNsense: usługa nie działa", kind="opnsense_service_failed", duration_s=120, severity="warning"),
        dict(name="Duża utrata pakietów na łączu WAN", kind="metric", metric="wan_loss_percent", op=">", threshold=20.0, duration_s=300, severity="warning"),
    ),
)
DEFAULTS_KEY = "alert_defaults"
DEFAULT_COMMUNITY_HINT = (
    "Community „public” albo „private” zna każdy – każdy w sieci może odczytać to urządzenie. "
    "Ustaw na urządzeniu własne community (albo SNMPv3) i wpisz je w UplinkView: Ustawienia → Urządzenia."
)


# Reguły zależne od modułu: rodzaj albo metryka → moduł (Ustawienia → Moduły)
KIND_MODULE = {
    "container_stopped": "agents", "service_failed": "agents", "smart_failed": "agents",
    "guest_stopped": "proxmox", "backup_failed": "proxmox", "vpn_connect": "unifi",
    "gateway_down": "opnsense", "opnsense_service_failed": "opnsense",
}  # fmt: skip
# Temperatura nie zależy od modułu: czujniki ma też MikroTik przez SNMP (od 0.50.0)
METRIC_MODULE = {"smart_reallocated": "agents", "backup_age_h": "proxmox", "wan_loss_percent": "opnsense"}


def rule_module(rule) -> str | None:
    return KIND_MODULE.get(rule.kind) or (METRIC_MODULE.get(rule.metric) if rule.kind == "metric" else None)


def subject_key(prefix: str, key: str) -> str:
    """Podmiot alertu ma najwyżej 64 znaki; długie nazwy (kontenery, punkty montowania) skracamy skrótem."""
    full = f"{prefix}:{key}"
    return full if len(full) <= 64 else f"{prefix}:#{hashlib.sha1(key.encode()).hexdigest()[:16]}"


def matches(pattern: str | None, name: str) -> bool:
    """Filtr nazwy z reguły: pusty = wszystko, `*` i `?` jak w powłoce, bez rozróżniania wielkości liter.
    Usługę można podać bez `.service`."""
    if not pattern:
        return True
    name, pattern = name.lower(), pattern.strip().lower()
    return fnmatchcase(name, pattern) or fnmatchcase(name.removesuffix(".service"), pattern)


def breaches(op: str, value: float | None, threshold: float) -> bool:
    if value is None:
        return False
    return value > threshold if op == ">" else value < threshold


def sustained(
    samples: list[tuple[datetime, float | None]], now: datetime, duration_s: int, op: str, threshold: float, interval_s: float
) -> bool:
    """Czy warunek trwa nieprzerwanie od `duration_s`? Próbki od najstarszej; potrzebne pokrycie całego okna,
    żeby świeżo dodane urządzenie albo luka w danych nie dawały fałszywych alarmów."""
    if not samples:
        return False
    samples = sorted(samples, key=lambda s: s[0])
    if not breaches(op, samples[-1][1], threshold):
        return False
    if duration_s <= 0:
        return True
    start = now - timedelta(seconds=duration_s)
    window = [s for s in samples if s[0] >= start - timedelta(seconds=interval_s)]
    if not window or window[0][0] > start + timedelta(seconds=interval_s * 1.5):
        return False  # dane zaczynają się później niż początek okna
    return all(breaches(op, v, threshold) for t, v in window if t >= start)


def format_uptime(seconds: float) -> str:
    """Czas pracy po restarcie: „45 s”, „3 min”, „2 h 5 min”."""
    s = int(seconds)
    if s < 60:
        return f"{s} s"
    if s < 3600:
        return f"{s // 60} min"
    return f"{s // 3600} h {s % 3600 // 60} min"


def format_value(metric: str, value: float) -> str:
    if metric in ("port_errors", "smart_reallocated"):
        return f"{value:.0f}"
    unit = METRICS[metric][1]
    if unit == "b/s":
        for suffix, div in (("Gb/s", 1e9), ("Mb/s", 1e6), ("kb/s", 1e3)):
            if abs(value) >= div:
                return f"{value / div:.1f} {suffix}".replace(".", ",")
        return f"{value:.0f} b/s"
    return f"{value:.1f}{unit}".replace(".", ",")


def upstream_parents(devices: dict[int, Device], links: list[TopologyLink]) -> dict[int, int]:
    """Rodzic każdego urządzenia na drodze do routera (z tablic LLDP, jak mapa sieci). Bez routera na mapie – pusto."""
    mac_to_device = {link.local_mac: link.device_id for link in links}
    adjacent: dict[int, set[int]] = defaultdict(set)
    for link in links:
        remote = mac_to_device.get(link.remote_mac)
        if remote is not None and remote != link.device_id and remote in devices and link.device_id in devices:
            adjacent[link.device_id].add(remote)
            adjacent[remote].add(link.device_id)
    roots = sorted(d for d in adjacent if devices[d].kind == "router")
    parent: dict[int, int] = {}
    seen, queue = set(roots), deque(roots)
    while queue:
        current = queue.popleft()
        for neighbour in sorted(adjacent[current]):
            if neighbour not in seen:
                seen.add(neighbour)
                parent[neighbour] = current
                queue.append(neighbour)
    return parent


def down_root(device_id: int, parent: dict[int, int], devices: dict[int, Device]) -> int | None:
    """Najwyższe niedziałające urządzenie nad `device_id` (przyczyna), albo None, gdy droga do routera działa."""
    root, current = None, parent.get(device_id)
    while current is not None:
        if devices[current].status == "down":
            root = current
        current = parent.get(current)
    return root


@dataclass
class Hit:
    """Podmiot, dla którego warunek reguły jest teraz spełniony."""

    subject: str
    title: str
    message: str | None
    device_id: int | None
    value: float | None


class AlertEngine:
    def __init__(self, now_fn=lambda: datetime.now(UTC), notifier: Notifier | None = None) -> None:
        self.now_fn = now_fn
        self.notifier = notifier

    async def ensure_default_rules(self) -> None:
        """Dodaje zestawy reguł domyślnych, których ta instalacja jeszcze nie dostała.

        Nowa instalacja dostaje wszystkie. Instalacja sprzed znacznika (≤ 0.11) miała już pierwszy zestaw,
        o ile cokolwiek było skonfigurowane (reguły albo historia) – wtedy dochodzą tylko nowsze."""
        async with Session() as session, session.begin():
            marker = await session.get(AppSetting, DEFAULTS_KEY, with_for_update=True)
            if marker is not None:
                applied = int(marker.value.get("sets", 0))
            else:
                has_rules = await session.scalar(select(func.count()).select_from(AlertRule))
                has_alerts = await session.scalar(select(func.count()).select_from(Alert))
                applied = 1 if (has_rules or has_alerts) else 0
                marker = AppSetting(key=DEFAULTS_KEY, value={})
                session.add(marker)
            for rule_set in DEFAULT_RULE_SETS[applied:]:
                session.add_all(AlertRule(**r) for r in rule_set)
            marker.value = {"sets": len(DEFAULT_RULE_SETS)}
            marker.updated_at = datetime.now(UTC)

    async def evaluate(self) -> list[AlertEvent]:
        """Ocenia reguły, zapisuje zmiany stanu alertów, rozsyła powiadomienia i zwraca zdarzenia tego cyklu."""
        events = await self._evaluate()
        if self.notifier is not None:
            await self.notifier.send(events)  # także bez zdarzeń: po cichych godzinach idą zaległości
        return events

    async def _evaluate(self) -> list[AlertEvent]:
        now = self.now_fn()
        events: list[AlertEvent] = []
        async with Session() as session, session.begin():
            # Wyłączony moduł: jego reguły nie działają (ich alerty się kończą), a urządzenia są pomijane
            mods = await read_modules(session)
            rules = [r for r in (await session.scalars(select(AlertRule).where(AlertRule.enabled))).all() if mods.get(rule_module(r), True)]
            hidden = hidden_drivers(mods)
            devices = {d.id: d for d in (await session.scalars(select(Device).where(Device.enabled))).all() if d.driver not in hidden}
            firing = (await session.scalars(select(Alert).where(Alert.state == "firing"))).all()
            by_key = {(a.rule_id, a.subject): a for a in firing}
            active_rules = {r.id for r in rules}
            rule_kind = {r.id: r.kind for r in rules}
            # Brak świeżego werdyktu (pętla kolektora albo integracji stoi): brak danych to nie awaria ani powrót
            # do normy – takie urządzenie nie otwiera alertu „nie odpowiada”, a jego otwarte alerty trwają bez zmian
            stale = {d.id for d in devices.values() if is_stale(d.last_polled_at, now)}
            # Okna serwisowe: alert powstaje w panelu, ale bez powiadomienia (początku ani końca); trwa po oknie –
            # powiadomienie wtedy (maintenance.py)
            windows = maintenance.active(await maintenance.load(session), now)

            def in_window(device_id: int | None) -> bool:
                return maintenance.in_maintenance(windows, device_id)

            # Grupowanie: urządzenie za niedziałającym urządzeniem (np. AP za switchem) nie dostaje osobnego
            # powiadomienia – wymieniamy je w wiadomości o przyczynie. Alert w panelu powstaje normalnie.
            links = list((await session.scalars(select(TopologyLink))).all())
            parent = upstream_parents(devices, links)
            behind: dict[int, list[str]] = defaultdict(list)
            offline_event: dict[int, int] = {}  # urządzenie → indeks jego zdarzenia „nie odpowiada” w `events`

            seen: set[tuple[int | None, str]] = set()
            for rule in rules:
                for hit in await self._hits(session, rule, devices, now):
                    key = (rule.id, hit.subject)
                    seen.add(key)
                    alert = by_key.get(key)
                    offline = rule.kind == "device_offline" and hit.device_id is not None
                    root = down_root(hit.device_id, parent, devices) if offline else None
                    device = devices.get(hit.device_id) if hit.device_id is not None else None
                    planned = in_window(hit.device_id)
                    if alert is None:
                        session.add(
                            Alert(
                                rule_id=rule.id,
                                subject=hit.subject,
                                state="firing",
                                severity=rule.severity,
                                title=hit.title,
                                message=hit.message,
                                device_id=hit.device_id,
                                value=hit.value,
                                peak=hit.value,
                                started_at=now,
                                muted=root is not None or planned,
                                maintenance=planned,
                            )
                        )
                        log.info("ALERT: %s%s", hit.title, " (okno serwisowe)" if planned else "")
                        if planned:
                            continue
                        if root is not None:
                            behind[root].append(device.name if device else hit.title)
                            continue
                        if offline:
                            offline_event[hit.device_id] = len(events)
                        events.append(
                            AlertEvent(
                                "firing", rule.severity, hit.title, hit.message, device.name if device else None, hit.value, now
                            )
                        )
                    else:
                        if alert.muted and root is None and not planned:
                            # Przyczyna wróciła (albo skończyło się okno serwisowe), a problem trwa – teraz powiadomienie
                            alert.muted = alert.maintenance = False
                            events.append(
                                AlertEvent(
                                    "firing", alert.severity, hit.title, hit.message, device.name if device else None,
                                    hit.value, alert.started_at,
                                )
                            )
                        alert.value = hit.value
                        alert.message = hit.message
                        if hit.value is not None:
                            peaks = [p for p in (alert.peak, hit.value) if p is not None]
                            alert.peak = max(peaks) if rule.op != "<" else min(peaks)

            for root, names in behind.items():
                if root in offline_event:
                    i = offline_event[root]
                    extra = f"Za nim nie odpowiada też: {', '.join(sorted(names))}"
                    events[i] = replace(events[i], message=f"{events[i].message}\n{extra}" if events[i].message else extra)

            for key, alert in by_key.items():
                held = alert.device_id in stale and rule_kind.get(alert.rule_id) not in EVENT_KINDS
                if (key not in seen and not held) or alert.rule_id not in active_rules:
                    alert.state = "resolved"
                    alert.resolved_at = now
                    log.info("Alert zakończony: %s", alert.title)
                    if alert.muted or rule_kind.get(alert.rule_id) in EVENT_KINDS or in_window(alert.device_id):
                        # nie było powiadomienia o początku, zdarzenie chwilowe albo koniec w trakcie prac – bez „zakończony”
                        continue
                    device = devices.get(alert.device_id) if alert.device_id is not None else None
                    events.append(
                        AlertEvent(
                            "resolved", alert.severity, alert.title, None, device.name if device else None,
                            alert.value, alert.started_at, now,
                        )
                    )
        return events

    # --- rodzaje reguł ----------------------------------------------------------------

    async def _hits(self, session, rule: AlertRule, devices: dict[int, Device], now: datetime) -> list[Hit]:
        scope = [d for d in devices.values() if rule.device_id in (None, d.id)]
        if rule.kind == "device_offline":
            return self._offline(rule, [d for d in scope if not is_stale(d.last_polled_at, now)], now)
        if rule.kind == "default_community":
            return self._default_community(scope)
        if rule.kind == "port_down":
            return await self._port_down(session, rule, scope, now)
        if rule.kind in AGENT_STATES:
            return await self._agent_state(session, rule, scope, now)
        if rule.kind == "check_down":
            return await self._check_down(session, rule, now)
        if rule.kind == "device_restart":
            return await self._restarts(session, scope, now)
        if rule.kind == "wan_switch":
            return await self._wan_switches(session, devices, now)
        if rule.kind == "vpn_connect":
            return await self._vpn_connections(session, scope, now)
        if rule.kind == "metric" and rule.metric in METRICS and rule.op in OPS and rule.threshold is not None:
            return await self._metric(session, rule, scope, now)
        return []

    async def _restarts(self, session, scope: list[Device], now: datetime) -> list[Hit]:
        """Urządzenie uruchomiło się ponownie (spadek czasu pracy) w ostatnich EVENT_HOLD – osobny alert na restart."""
        names = {d.id: d.name for d in scope}
        return [
            Hit(
                f"r{r.device_id}:{int(r.detected.timestamp())}",
                f"{names[r.device_id]}: restart urządzenia",
                f"Czas pracy po restarcie: {format_uptime(r.uptime_s)}",
                r.device_id,
                r.uptime_s,
            )
            for r in await restarts(session, names, now - EVENT_HOLD, now + timedelta(seconds=1))
        ]

    async def _wan_switches(self, session, devices: dict[int, Device], now: datetime) -> list[Hit]:
        """Ruch przeszedł na inne łącze WAN w ostatnich EVENT_HOLD – osobny alert na przełączenie."""
        since = now - EVENT_HOLD
        # Próbki sprzed okna: stan wyjściowy łączy, bez niego przełączenia nie widać
        found = await wan_switches(session, devices, since - 3 * wan_links.stale_after(), now + timedelta(seconds=1))
        return [
            Hit(
                f"wan:{int(sw.time.timestamp())}",
                f"Przełączenie WAN: {sw.from_names} → {sw.to_names}",
                f"Ruch idzie teraz łączem {sw.to_names}.",
                sw.device_id,
                None,
            )
            for sw in found
            if sw.time >= since
        ]

    async def _vpn_connections(self, session, scope: list[Device], now: datetime) -> list[Hit]:
        """Klient VPN połączył się w ostatnich EVENT_HOLD (od 0.57.0) – osobny alert na połączenie."""
        names = {d.id: d.name for d in scope}
        return [
            Hit(
                subject_key("vpn", f"{c.user}:{int(c.time.timestamp())}"),
                f"VPN: połączenie – {c.user}",
                f"Klient {c.user} połączył się z VPN na {names[c.device_id]}.",
                c.device_id,
                None,
            )
            for c in await vpn.connections(session, names, now - EVENT_HOLD, now + timedelta(seconds=1))
        ]

    def _default_community(self, scope: list[Device]) -> list[Hit]:
        """Urządzenie SNMP v1/v2c z community „public” albo „private” – trwa, dopóki community się nie zmieni."""
        return [
            Hit(f"d{d.id}", f"{d.name}: fabryczne community SNMP", DEFAULT_COMMUNITY_HINT, d.id, None)
            for d in scope
            if d.uses_default_community
        ]

    def _offline(self, rule: AlertRule, scope: list[Device], now: datetime) -> list[Hit]:
        hits = []
        for d in scope:
            if d.status != "down":
                continue
            since = d.last_ok_at or d.created_at
            offline_s = (now - since).total_seconds() if since else 0
            if offline_s >= rule.duration_s:
                hits.append(Hit(f"d{d.id}", f"{d.name} nie odpowiada", d.last_error, d.id, offline_s))
        return hits

    async def _port_down(self, session, rule: AlertRule, scope: list[Device], now: datetime) -> list[Hit]:
        """Port, który jeszcze przed chwilą działał, a teraz jest down (puste porty nie dają alertu).
        Alert trwa, dopóki świeży odczyt nie pokaże portu w górze – także gdy urządzenie chwilę nie odpowiada
        (restart switcha) albo brakuje odczytów; inaczej zamknąłby się i po powrocie switcha już nie wrócił.
        Port, który działał przed przerwą w odczytach, a po niej jest down, też alarmuje (padł w trakcie restartu)."""
        up = {d.id: d for d in scope if d.status == "up"}
        by_id = {d.id: d for d in scope}
        since = now - timedelta(seconds=settings.poll_interval * 3 + 30)
        rows = (
            await session.execute(
                select(InterfaceMetric.interface_id, InterfaceMetric.oper_up, InterfaceMetric.time)
                .join(Interface, Interface.id == InterfaceMetric.interface_id)
                .where(Interface.device_id.in_(up), Interface.hidden.is_(False), InterfaceMetric.time >= since)
                .order_by(InterfaceMetric.interface_id, InterfaceMetric.time.desc())
            )
        ).all()
        recent: dict[int, list[bool | None]] = defaultdict(list)
        oldest: dict[int, datetime] = {}
        for iface_id, oper_up, at in rows:
            recent[iface_id].append(oper_up)
            oldest[iface_id] = at
        firing = (await session.scalars(select(Alert).where(Alert.rule_id == rule.id, Alert.state == "firing"))).all()
        already = {a.subject for a in firing}
        held = [int(a.subject[1:]) for a in firing if a.subject[1:].isdigit() and int(a.subject[1:]) not in recent]
        interfaces = {
            i.id: i for i in (await session.scalars(select(Interface).where(Interface.id.in_([*recent, *held] or [0])))).all()
        }
        # Wszystkie świeże odczyty down (co najmniej dwa: po starcie switcha porty chwilę negocjują link), bez przejścia
        # w oknie – czy port działał tuż przed przerwą w odczytach?
        candidates = [
            i for i, states in recent.items()
            if f"i{i}" not in already and len(states) >= 2 and all(s is False for s in states)
        ]  # fmt: skip
        before_break = await self._up_before_break(session, candidates, oldest, since) if candidates else set()
        hits = []
        for iface_id in held:  # brak świeżego odczytu: port nie wrócił, alert trwa
            iface = interfaces.get(iface_id)
            device = by_id.get(iface.device_id) if iface else None
            if device and not iface.hidden:
                label = iface.alias or iface.label or iface.name
                hits.append(Hit(f"i{iface_id}", f"Port {label} ({device.name}) jest wyłączony", None, device.id, 0.0))
        for iface_id, states in recent.items():
            if states[0] is not False:
                continue
            went_down = len(states) > 1 and states[1] is True
            if not (went_down or iface_id in before_break or f"i{iface_id}" in already):
                continue
            iface = interfaces[iface_id]
            device = up[iface.device_id]
            label = iface.alias or iface.label or iface.name
            hits.append(Hit(f"i{iface_id}", f"Port {label} ({device.name}) jest wyłączony", None, device.id, 0.0))
        return hits

    async def _up_before_break(self, session, candidates: list[int], oldest: dict[int, datetime], since: datetime) -> set[int]:
        """Porty, których ostatni odczyt przed oknem był „up” i od którego do pierwszego odczytu w oknie minęła przerwa
        (urządzenie nie odpowiadało). Bez przerwy port padł wcześniej i alarmowałby już wtedy – tu go nie wskrzeszamy."""
        interval = float(settings.poll_interval)
        rows = (
            await session.execute(
                select(InterfaceMetric.interface_id, InterfaceMetric.oper_up, InterfaceMetric.time)
                .ext(distinct_on(InterfaceMetric.interface_id))
                .where(
                    InterfaceMetric.interface_id.in_(candidates),
                    InterfaceMetric.oper_up.is_not(None),
                    InterfaceMetric.time >= since - BREAK_LOOKBACK,
                    InterfaceMetric.time < since,
                )
                .order_by(InterfaceMetric.interface_id, InterfaceMetric.time.desc())
            )
        ).all()
        return {
            i for i, oper_up, at in rows
            if oper_up and (oldest[i] - at).total_seconds() > interval * 2.5
        }  # fmt: skip

    async def _metric(self, session, rule: AlertRule, scope: list[Device], now: datetime) -> list[Hit]:
        metric, op, threshold = rule.metric, rule.op, float(rule.threshold)
        interval = float(settings.poll_interval)
        since = now - timedelta(seconds=rule.duration_s + interval * 2)
        label = METRICS[metric][0]
        hits = []
        if metric in DEVICE_METRICS:
            column = getattr(DeviceMetric, metric)
            rows = (
                await session.execute(
                    select(DeviceMetric.device_id, DeviceMetric.time, column)
                    .where(DeviceMetric.device_id.in_([d.id for d in scope] or [0]), DeviceMetric.time >= since)
                    .order_by(DeviceMetric.device_id, DeviceMetric.time)
                )
            ).all()
            samples: dict[int, list[tuple[datetime, float | None]]] = defaultdict(list)
            for dev_id, t, v in rows:
                samples[dev_id].append((t, v))
            names = {d.id: d.name for d in scope}
            for dev_id, series in samples.items():
                if sustained(series, now, rule.duration_s, op, threshold, interval):
                    v = series[-1][1]
                    hits.append(
                        Hit(f"d{dev_id}", f"{names[dev_id]}: {label} {format_value(metric, v)}", self._detail(rule, metric), dev_id, v)
                    )
            return hits

        if metric in DISK_METRICS:
            return await self._disk(session, rule, scope, since, now)
        if metric in PORT_METRICS:
            return await self._port_errors(session, rule, scope, since, now)
        if metric in SYSTEM_METRICS:
            return await self._system(session, rule, since, now)
        if metric in AGENT_METRICS:
            return await self._agent_metric(session, rule, scope, since, now)
        if metric in CHECK_METRICS:
            return await self._check_metric(session, rule, now)

        # WAN: suma po wszystkich interfejsach WAN włączonych routerów (w zakresie reguły)
        column = InterfaceMetric.in_bps if metric == "wan_in_bps" else InterfaceMetric.out_bps
        rows = (
            await session.execute(
                select(InterfaceMetric.time, func.sum(column))
                .join(Interface, Interface.id == InterfaceMetric.interface_id)
                .where(
                    Interface.role == "wan",
                    Interface.device_id.in_([d.id for d in scope] or [0]),
                    InterfaceMetric.time >= since,
                )
                .group_by(InterfaceMetric.time)
                .order_by(InterfaceMetric.time)
            )
        ).all()
        series = [(t, v) for t, v in rows]
        if sustained(series, now, rule.duration_s, op, threshold, interval):
            v = series[-1][1]
            hits.append(Hit("wan", f"{label} {format_value(metric, v)}", self._detail(rule, metric), rule.device_id, v))
        return hits

    async def _checks(self, session, rule: AlertRule) -> list[Check]:
        rows = (await session.scalars(select(Check).where(Check.enabled))).all()
        return [c for c in rows if matches(rule.match, c.name)]

    async def _check_down(self, session, rule: AlertRule, now: datetime) -> list[Hit]:
        """Sprawdzenie nie przechodzi nieprzerwanie od `duration_s` (stan liczy checks_collector)."""
        hits = []
        for c in await self._checks(session, rule):
            if c.status != "down" or c.status_since is None:
                continue
            down_s = (now - c.status_since).total_seconds()
            if down_s >= rule.duration_s:
                hits.append(Hit(f"c{c.id}", f"{c.name}: niedostępne", c.last_error, None, down_s))
        return hits

    async def _check_metric(self, session, rule: AlertRule, now: datetime) -> list[Hit]:
        """Próg na wyniku sprawdzenia (opóźnienie, utrata pakietów, ważność certyfikatu) – osobno dla każdego."""
        metric, op, threshold = rule.metric, rule.op, float(rule.threshold)
        checks = {c.id: c for c in await self._checks(session, rule)}
        if not checks:
            return []
        longest = max(c.interval_s for c in checks.values())
        column = getattr(CheckMetric, CHECK_METRICS[metric])
        rows = (
            await session.execute(
                select(CheckMetric.check_id, CheckMetric.time, column)
                .where(CheckMetric.check_id.in_(list(checks)), CheckMetric.time >= now - timedelta(seconds=rule.duration_s + longest * 2))
                .order_by(CheckMetric.check_id, CheckMetric.time)
            )
        ).all()
        samples: dict[int, list[tuple[datetime, float | None]]] = defaultdict(list)
        for check_id, t, v in rows:
            samples[check_id].append((t, v))
        hits = []
        for check_id, series in samples.items():
            c = checks[check_id]
            if sustained(series, now, rule.duration_s, op, threshold, float(c.interval_s)):
                v = series[-1][1]
                title = f"{c.name}: {CHECK_METRIC_WHAT[metric]} {format_value(metric, v)}"
                hits.append(Hit(f"c{check_id}", title, self._detail(rule, metric), None, v))
        return hits

    async def _disk(self, session, rule: AlertRule, scope: list[Device], since: datetime, now: datetime) -> list[Hit]:
        """Zajętość każdej partycji serwera osobno (alert na partycję), liczona z ostatnich próbek."""
        metric, op, threshold = rule.metric, rule.op, float(rule.threshold)
        rows = (
            await session.execute(
                select(DiskMetric.device_id, DiskMetric.mount, DiskMetric.time, DiskMetric.used_bytes, DiskMetric.total_bytes)
                .where(DiskMetric.device_id.in_([d.id for d in scope] or [0]), DiskMetric.time >= since)
                .order_by(DiskMetric.device_id, DiskMetric.mount, DiskMetric.time)
            )
        ).all()
        samples: dict[tuple[int, str], list[tuple[datetime, float | None]]] = defaultdict(list)
        for dev_id, mount, t, used, total in rows:
            samples[(dev_id, mount)].append((t, 100.0 * used / total if total else None))
        names = {d.id: d.name for d in scope}
        hits = []
        for (dev_id, mount), series in samples.items():
            if sustained(series, now, rule.duration_s, op, threshold, float(settings.poll_interval)):
                v = series[-1][1]
                title = f"{names[dev_id]}: dysk {mount} zajęty w {format_value(metric, v)}"
                hits.append(Hit(subject_key(f"d{dev_id}", mount), title, self._detail(rule, metric), dev_id, v))
        return hits

    async def _port_errors(
        self, session, rule: AlertRule, scope: list[Device], since: datetime, now: datetime
    ) -> list[Hit]:
        """Błędy wejścia i wyjścia na porcie w jednym cyklu odczytu (kolektor zapisuje przyrost)."""
        metric, op, threshold = rule.metric, rule.op, float(rule.threshold)
        rows = (
            await session.execute(
                select(InterfaceMetric.interface_id, InterfaceMetric.time, InterfaceMetric.in_errors, InterfaceMetric.out_errors)
                .join(Interface, Interface.id == InterfaceMetric.interface_id)
                .where(
                    Interface.device_id.in_([d.id for d in scope] or [0]),
                    Interface.hidden.is_(False),
                    InterfaceMetric.time >= since,
                )
                .order_by(InterfaceMetric.interface_id, InterfaceMetric.time)
            )
        ).all()
        samples: dict[int, list[tuple[datetime, float | None]]] = defaultdict(list)
        for iface_id, t, err_in, err_out in rows:
            both_missing = err_in is None and err_out is None  # pierwszy odczyt: nie ma jeszcze przyrostu
            samples[iface_id].append((t, None if both_missing else float((err_in or 0) + (err_out or 0))))
        if not samples:
            return []
        interfaces = {i.id: i for i in (await session.scalars(select(Interface).where(Interface.id.in_(list(samples))))).all()}
        names = {d.id: d.name for d in scope}
        hits = []
        for iface_id, series in samples.items():
            if sustained(series, now, rule.duration_s, op, threshold, float(settings.poll_interval)):
                iface = interfaces[iface_id]
                label = iface.alias or iface.label or iface.name
                v = series[-1][1]
                title = f"Błędy na porcie {label} ({names[iface.device_id]}): {format_value(metric, v)}"
                hits.append(Hit(f"i{iface_id}", title, self._detail(rule, metric), iface.device_id, v))
        return hits

    async def _system(self, session, rule: AlertRule, since: datetime, now: datetime) -> list[Hit]:
        """Serwer, na którym działa UplinkView (CPU, RAM, dysk): jeden alert na regułę."""
        metric, op, threshold = rule.metric, rule.op, float(rule.threshold)
        column = getattr(SystemMetric, SYSTEM_METRICS[metric])
        rows = (await session.execute(select(SystemMetric.time, column).where(SystemMetric.time >= since).order_by(SystemMetric.time))).all()
        series = [(t, v) for t, v in rows]
        if sustained(series, now, rule.duration_s, op, threshold, float(settings.poll_interval)):
            v = series[-1][1]
            return [Hit("system", f"{METRICS[metric][0]} {format_value(metric, v)}", self._detail(rule, metric), None, v)]
        return []

    async def _series(
        self, session, name: str, scope: list[Device], since: datetime, pattern: str | None
    ) -> dict[tuple[int, str], list[tuple[datetime, float | None]]]:
        """Próbki z ogólnej tabeli `metrics` (od najstarszej) na urządzenie i klucz, po filtrze nazwy."""
        rows = (
            await session.execute(
                select(Metric.device_id, Metric.key, Metric.time, Metric.value)
                .where(Metric.name == name, Metric.device_id.in_([d.id for d in scope] or [0]), Metric.time >= since)
                .order_by(Metric.device_id, Metric.key, Metric.time)
            )
        ).all()
        samples: dict[tuple[int, str], list[tuple[datetime, float | None]]] = defaultdict(list)
        for dev_id, key, t, v in rows:
            if matches(pattern, key):
                samples[(dev_id, key)].append((t, v))
        return samples

    async def _agent_metric(self, session, rule: AlertRule, scope: list[Device], since: datetime, now: datetime) -> list[Hit]:
        """Próg na metryce z agenta (temperatura czujnika, realokowane sektory dysku) – alert na klucz."""
        metric, op, threshold = rule.metric, rule.op, float(rule.threshold)
        names = {d.id: d.name for d in scope}
        hits = []
        for (dev_id, key), series in (await self._series(session, AGENT_METRICS[metric], scope, since, rule.match)).items():
            if sustained(series, now, rule.duration_s, op, threshold, float(settings.poll_interval)):
                v = series[-1][1]
                title = f"{names[dev_id]}: {AGENT_METRIC_WHAT[metric]} {key} {format_value(metric, v)}"
                hits.append(Hit(subject_key(f"d{dev_id}:{metric}", key), title, self._detail(rule, metric), dev_id, v))
        return hits

    async def _agent_state(self, session, rule: AlertRule, scope: list[Device], now: datetime) -> list[Hit]:
        """Kontener albo maszyna zatrzymana, usługa nie działa, SMART albo kopia zgłasza błąd (wartość 0 w `metrics`).

        Kontener i maszyna bez filtru nazwy alarmują tylko, jeśli przed chwilą działały: zatrzymane od dawna
        (np. jednorazowe zadania, zapasowe VM) nie dają alarmu. Z filtrem nazwy – zawsze, bo o nie chodzi."""
        name, what, state = AGENT_STATES[rule.kind]
        interval = float(settings.poll_interval)
        since = now - timedelta(seconds=rule.duration_s + interval * 3)
        already = {
            a.subject for a in (await session.scalars(select(Alert).where(Alert.rule_id == rule.id, Alert.state == "firing"))).all()
        }
        names = {d.id: d.name for d in scope}
        hits = []
        for (dev_id, key), series in (await self._series(session, name, scope, since, rule.match)).items():
            if not sustained(series, now, rule.duration_s, "<", 1.0, interval):
                continue
            subject = subject_key(f"d{dev_id}:{rule.kind[0]}", key)
            if rule.kind in WENT_DOWN_KINDS and not rule.match and subject not in already:
                if not any(v is not None and v >= 1 for _t, v in series):
                    continue
            label = key.removesuffix(".service") if rule.kind == "service_failed" else key
            hits.append(Hit(subject, f"{names[dev_id]}: {what} {label} {state}", self._state_detail(rule), dev_id, None))
        return hits

    @staticmethod
    def _state_detail(rule: AlertRule) -> str:
        if rule.kind in ("gateway_down", "opnsense_service_failed"):
            text = f"Stan z API OPNsense od {rule.duration_s // 60} min" if rule.duration_s >= 60 else "Stan z API OPNsense"
        else:
            text = f"Stan z agenta UplinkView od {rule.duration_s // 60} min" if rule.duration_s >= 60 else "Stan z agenta UplinkView"
        return f"{text} (filtr: {rule.match})" if rule.match else text

    @staticmethod
    def _detail(rule: AlertRule, metric: str) -> str:
        text = f"Warunek: {METRICS[metric][0]} {rule.op} {format_value(metric, float(rule.threshold))}"
        return f"{text} przez {rule.duration_s // 60} min" if rule.duration_s >= 60 else text
