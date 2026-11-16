"""Raport miesięczny (od 0.65.0): dostępność urządzeń, sprawdzeń i łączy WAN, ruch WAN i alerty z jednego miesiąca.

Dane:
- urządzenia – jak strona dostępności (`api/availability.py`): agregaty godzinowe TimescaleDB (rok wstecz);
- sprawdzenia i SLA łączy WAN – surowe próbki (`check_metrics`, `wan_link_metrics`), więc tylko z ostatnich
  `retention_days` (domyślnie 30 dni) – raport mówi wtedy, od kiedy są dane;
- ruch WAN – porty z rolą `wan`: średnia godzinowa × czas (agregat `interface_metrics_1h`);
- alerty rozpoczęte w miesiącu (tabela `alerts`).

Miesiąc liczony w strefie czasowej instalacji (TZ). Bieżący miesiąc kończy się „teraz”.
Wyjście: `build()` → `Report`, potem `to_csv()` (średnik, przecinek dziesiętny, BOM – Excel po polsku) albo `to_pdf()`.
Od 0.76.0 oba w języku `lang` (pl/en) – panel podaje swój język w `?lang=`.
"""

from __future__ import annotations

import csv
import io
import os
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import select, text

from . import __version__, wan_links
from .config import settings
from .db import Session, timescale_available
from .db.models import Alert, Check, Device, Interface, WanLink, WanLinkMetric
from .i18n import translate
from .modules import hidden_drivers, read_modules
from .wan import Sample, compute_sla

MONTHS = ("styczeń", "luty", "marzec", "kwiecień", "maj", "czerwiec", "lipiec", "sierpień", "wrzesień", "październik", "listopad", "grudzień")
MONTHS_EN = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")
SEVERITY_LABEL = {"critical": "krytyczny", "warning": "ostrzeżenie", "info": "informacja"}
KIND_LABEL = {"gateway": "router", "switch": "switch", "ap": "access point", "server": "serwer"}
MAX_ALERTS = 500  # w raporcie (CSV); PDF pokazuje PDF_ALERTS najdłuższych


@dataclass
class DeviceRow:
    id: int
    name: str
    host: str
    kind: str
    percent: float | None
    down_s: int
    samples: int


@dataclass
class CheckRow:
    id: int
    name: str
    kind: str
    target: str
    percent: float | None
    samples: int
    failed: int
    avg_latency_ms: float | None
    max_latency_ms: float | None


@dataclass
class WanRow:
    name: str
    device: str
    rx_bytes: float  # pobrane (do sieci)
    tx_bytes: float  # wysłane
    percent: float | None = None  # SLA łącza (None = brak danych albo port spoza Łączy WAN)
    down_s: float | None = None
    outages: int | None = None
    longest_outage_s: float | None = None


@dataclass
class AlertRow:
    id: int
    title: str
    severity: str
    device: str | None
    started_at: datetime
    resolved_at: datetime | None
    duration_s: float


@dataclass
class Report:
    year: int
    month: int
    start: datetime
    end: datetime
    generated_at: datetime
    timezone: str
    version: str
    # Od kiedy są surowe dane (sprawdzenia, SLA WAN), gdy retencja nie obejmuje całego miesiąca
    raw_from: datetime | None
    devices: list[DeviceRow] = field(default_factory=list)
    checks: list[CheckRow] = field(default_factory=list)
    wan: list[WanRow] = field(default_factory=list)
    alerts: list[AlertRow] = field(default_factory=list)
    alerts_total: int = 0
    alerts_by_severity: dict[str, int] = field(default_factory=dict)

    @property
    def title(self) -> str:
        return f"{MONTHS[self.month - 1]} {self.year}"

    @property
    def devices_percent(self) -> float | None:
        """Średnia dostępność urządzeń (ważona próbkami)."""
        return _weighted([(d.percent, d.samples) for d in self.devices])

    @property
    def checks_percent(self) -> float | None:
        return _weighted([(c.percent, c.samples) for c in self.checks])

    def as_dict(self) -> dict:
        d = asdict(self)
        d.update(title=self.title, devices_percent=self.devices_percent, checks_percent=self.checks_percent)
        return d


def _weighted(items: list[tuple[float | None, int]]) -> float | None:
    known = [(p, n) for p, n in items if p is not None and n]
    total = sum(n for _, n in known)
    return sum(p * n for p, n in known) / total if total else None


def month_range(year: int, month: int, tz: ZoneInfo | None = None, now: datetime | None = None) -> tuple[datetime, datetime]:
    """Początek i koniec miesiąca w strefie instalacji (UTC); bieżący miesiąc kończy się teraz."""
    tz = tz or ZoneInfo(settings.timezone)
    start = datetime(year, month, 1, tzinfo=tz)
    end = datetime(year + (month == 12), month % 12 + 1, 1, tzinfo=tz)
    now = now or datetime.now(UTC)
    return start.astimezone(UTC), min(end.astimezone(UTC), now)


def parse_month(value: str | None, now: datetime | None = None, tz: ZoneInfo | None = None) -> tuple[int, int]:
    """„2026-11” → (2026, 11); puste = poprzedni pełny miesiąc. Miesiąc z przyszłości – ValueError."""
    now = (now or datetime.now(UTC)).astimezone(tz or ZoneInfo(settings.timezone))
    if not value:
        first = now.date().replace(day=1)
        prev = first - timedelta(days=1)
        return prev.year, prev.month
    try:
        y, m = (int(x) for x in value.split("-", 1))
        date(y, m, 1)
    except ValueError as exc:
        raise ValueError("Podaj miesiąc w postaci RRRR-MM") from exc
    if (y, m) > (now.year, now.month):
        raise ValueError("Ten miesiąc jeszcze się nie zaczął")
    if y < 2000:
        raise ValueError("Podaj miesiąc w postaci RRRR-MM")
    return y, m


# --- zbieranie danych ------------------------------------------------------------------------------


async def _devices(session, start: datetime, end: datetime, timescale: bool, hidden: tuple[str, ...]) -> list[DeviceRow]:
    if timescale:
        sql = "SELECT device_id, sum(samples) AS total, sum(up_samples) AS up FROM device_metrics_1h WHERE bucket >= :s AND bucket < :e GROUP BY 1"
    else:
        sql = (
            "SELECT device_id, count(*) AS total, count(*) FILTER (WHERE reachable) AS up FROM device_metrics "
            "WHERE time >= :s AND time < :e GROUP BY 1"
        )
    counts = {r.device_id: (int(r.total), int(r.up)) for r in (await session.execute(text(sql), {"s": start, "e": end})).all()}
    devices = (await session.scalars(select(Device).where(Device.driver.not_in(hidden or ("",))).order_by(Device.name))).all()
    rows = []
    for d in devices:
        total, up = counts.get(d.id, (0, 0))
        if not total and not d.enabled:
            continue  # wyłączone i bez danych w miesiącu – nie ma o czym pisać
        rows.append(
            DeviceRow(
                id=d.id,
                name=d.name,
                host=d.host,
                kind=d.kind,
                percent=up * 100.0 / total if total else None,
                down_s=(total - up) * settings.poll_interval,
                samples=total,
            )
        )
    return rows


async def _checks(session, start: datetime, end: datetime) -> list[CheckRow]:
    q = text(
        "SELECT check_id, count(*) AS total, count(*) FILTER (WHERE up) AS up, avg(latency_ms) FILTER (WHERE up) AS avg_ms, "
        "max(latency_ms) FILTER (WHERE up) AS max_ms FROM check_metrics WHERE time >= :s AND time < :e GROUP BY 1"
    )
    stats = {r.check_id: r for r in (await session.execute(q, {"s": start, "e": end})).all()}
    rows = []
    for c in (await session.scalars(select(Check).order_by(Check.name))).all():
        r = stats.get(c.id)
        if r is None and not c.enabled:
            continue
        total, up = (int(r.total), int(r.up)) if r else (0, 0)
        target = f"{c.target}:{c.port}" if c.kind == "tcp" and c.port else f"{c.dns_type or 'A'} {c.target}" if c.kind == "dns" else c.target
        rows.append(
            CheckRow(
                id=c.id,
                name=c.name,
                kind=c.kind,
                target=target,
                percent=up * 100.0 / total if total else None,
                samples=total,
                failed=total - up,
                avg_latency_ms=round(r.avg_ms, 2) if r is not None and r.avg_ms is not None else None,
                max_latency_ms=round(r.max_ms, 2) if r is not None and r.max_ms is not None else None,
            )
        )
    return rows


async def _wan(session, start: datetime, end: datetime, timescale: bool, hidden: tuple[str, ...]) -> list[WanRow]:
    ports = (
        await session.execute(
            select(Interface, Device.name)
            .join(Device, Device.id == Interface.device_id)
            .where(Interface.role == "wan", Device.driver.not_in(hidden or ("",)))
            .order_by(Device.name, Interface.if_index)
        )
    ).all()
    if not ports:
        return []
    ids = [p.id for p, _ in ports]
    if timescale:
        q = (
            "SELECT interface_id, coalesce(sum(in_bps), 0) * 3600 / 8 AS rx, coalesce(sum(out_bps), 0) * 3600 / 8 AS tx "
            "FROM interface_metrics_1h WHERE interface_id = ANY(:ids) AND bucket >= :s AND bucket < :e GROUP BY 1"
        )
        params = {"ids": ids, "s": start, "e": end}
    else:
        q = (
            "SELECT interface_id, coalesce(sum(in_bps), 0) * :step / 8 AS rx, coalesce(sum(out_bps), 0) * :step / 8 AS tx "
            "FROM interface_metrics WHERE interface_id = ANY(:ids) AND time >= :s AND time < :e GROUP BY 1"
        )
        params = {"ids": ids, "s": start, "e": end, "step": settings.poll_interval}
    traffic = {r.interface_id: (float(r.rx), float(r.tx)) for r in (await session.execute(text(q), params)).all()}

    links = {x.interface_id: x for x in (await session.scalars(select(WanLink).order_by(WanLink.position))).all()}
    max_gap = wan_links.stale_after()
    samples: dict[int, list[Sample]] = defaultdict(list)
    if links:
        rows = await session.execute(
            select(WanLinkMetric.wan_link_id, WanLinkMetric.time, WanLinkMetric.up, WanLinkMetric.active)
            .where(WanLinkMetric.wan_link_id.in_([x.id for x in links.values()]), WanLinkMetric.time >= start - max_gap, WanLinkMetric.time < end)
            .order_by(WanLinkMetric.time)
        )
        for link_id, t, up, active in rows:
            samples[link_id].append(Sample(t, up, active))

    out = []
    order = {iface_id: x.position for iface_id, x in links.items()}
    for iface, device_name in sorted(ports, key=lambda p: (order.get(p[0].id, 99), p[1], p[0].if_index)):
        rx, tx = traffic.get(iface.id, (0.0, 0.0))
        link = links.get(iface.id)
        row = WanRow(name=link.name if link else iface.label or iface.name, device=device_name, rx_bytes=rx, tx_bytes=tx)
        if link is not None and samples.get(link.id):
            sla = compute_sla(samples[link.id], start, end, max_gap)
            row.percent = sla.availability
            row.down_s = round(sla.down_s, 1)
            row.outages = len(sla.outages)
            row.longest_outage_s = round(max((o.seconds for o in sla.outages), default=0.0), 1)
        out.append(row)
    return out


async def _alerts(session, start: datetime, end: datetime) -> tuple[list[AlertRow], int, dict[str, int]]:
    rows = (
        await session.execute(
            select(Alert, Device.name)
            .outerjoin(Device, Device.id == Alert.device_id)
            .where(Alert.started_at >= start, Alert.started_at < end)
            .order_by(Alert.started_at)
        )
    ).all()
    out = []
    for a, device_name in rows:
        finish = a.resolved_at or end
        out.append(
            AlertRow(
                id=a.id,
                title=a.title,
                severity=a.severity,
                device=device_name,
                started_at=a.started_at,
                resolved_at=a.resolved_at,
                duration_s=max(0.0, (min(finish, end) - a.started_at).total_seconds()),
            )
        )
    by_severity = dict(Counter(a.severity for a in out))
    return out[:MAX_ALERTS], len(out), by_severity


async def build(year: int, month: int, now: datetime | None = None) -> Report:
    now = now or datetime.now(UTC)
    start, end = month_range(year, month, now=now)
    timescale = await timescale_available()
    raw_limit = now - timedelta(days=settings.retention_days)
    report = Report(
        year=year,
        month=month,
        start=start,
        end=end,
        generated_at=now,
        timezone=settings.timezone,
        version=__version__,
        raw_from=raw_limit if raw_limit > start else None,
    )
    async with Session() as session:
        hidden = hidden_drivers(await read_modules(session))
        report.devices = await _devices(session, start, end, timescale, hidden)
        report.checks = await _checks(session, start, end)
        report.wan = await _wan(session, start, end, timescale, hidden)
        report.alerts, report.alerts_total, report.alerts_by_severity = await _alerts(session, start, end)
    return report


# --- formatowanie ----------------------------------------------------------------------------------
# Język raportu (od 0.76.0): `lang` – język panelu, z którego pobrano plik. Teksty tłumaczy `i18n.translate`
# (katalog `messages.py`), po angielsku liczby z kropką, daty RRRR-MM-DD i CSV z przecinkiem.


def report_title(report: Report, lang: str = "pl") -> str:
    months = MONTHS_EN if lang == "en" else MONTHS
    return f"{months[report.month - 1]} {report.year}"


def fmt_num(value: float | None, digits: int = 2, lang: str = "pl") -> str:
    if value is None:
        return "–"
    if lang == "en":
        return f"{value:,.{digits}f}"
    return f"{value:,.{digits}f}".replace(",", " ").replace(".", ",")


def fmt_percent(value: float | None, lang: str = "pl") -> str:
    if value is None:
        return "–"
    # 99,999% nie zaokrąglamy do 100%: dwa miejsca, a gdy wyjdzie 100,00 przy przerwie – trzy
    text_ = fmt_num(value, 2, lang)
    if text_ in ("100,00", "100.00") and value < 100:
        text_ = fmt_num(value, 3, lang)
    return f"{text_}%"


def fmt_duration(seconds: float | None) -> str:
    if seconds is None:
        return "–"
    s = int(round(seconds))
    if s < 60:
        return f"{s} s"
    m = s // 60
    if m < 60:
        return f"{m} min"
    h, m = divmod(m, 60)
    if h < 48:
        return f"{h} h {m} min" if m else f"{h} h"
    d, h = divmod(h, 24)
    return f"{d} d {h} h" if h else f"{d} d"


def fmt_bytes(value: float | None, lang: str = "pl") -> str:
    if value is None:
        return "–"
    units = ("B", "kB", "MB", "GB", "TB", "PB")
    i = 0
    while value >= 1000 and i < len(units) - 1:
        value /= 1000
        i += 1
    return f"{fmt_num(value, 0 if i == 0 else 1, lang)} {units[i]}"


def fmt_time(value: datetime | None, tz: ZoneInfo, lang: str = "pl") -> str:
    if not value:
        return "–"
    return value.astimezone(tz).strftime("%Y-%m-%d %H:%M" if lang == "en" else "%d.%m.%Y %H:%M")


def filename(report: Report, ext: str, lang: str = "pl") -> str:
    return f"uplinkview-{'report' if lang == 'en' else 'raport'}-{report.year}-{report.month:02d}.{ext}"


def to_csv(report: Report, lang: str = "pl") -> bytes:
    """Jeden plik, sekcje oddzielone pustym wierszem, każda z własnym nagłówkiem. Po polsku średnik i przecinek
    dziesiętny (Excel po polsku), po angielsku przecinek i kropka."""
    tz = ZoneInfo(report.timezone)

    def t(s: str) -> str:
        return translate(s, lang)

    def num(value: float | None, digits: int) -> str:
        if lang != "en":
            return fmt_num(value, digits)
        return "" if value is None else f"{value:.{digits}f}"

    def when(value: datetime | None) -> str:
        return fmt_time(value, tz, lang)

    buf = io.StringIO()
    w = csv.writer(buf, delimiter="," if lang == "en" else ";", lineterminator="\r\n")
    w.writerow([t("Raport UplinkView"), report_title(report, lang)])
    w.writerow([t("Okres"), when(report.start), when(report.end)])
    w.writerow([t("Wygenerowano"), when(report.generated_at), f"UplinkView {report.version}"])
    if report.raw_from:
        w.writerow([t("Sprawdzenia i SLA WAN od"), when(report.raw_from)])
    w.writerow([])
    w.writerow([t("Urządzenia")])
    w.writerow([t(h) for h in ("Nazwa", "Adres", "Rodzaj", "Dostępność %", "Niedostępność (min)", "Próbki")])
    for d in report.devices:
        w.writerow([d.name, d.host, t(KIND_LABEL.get(d.kind, d.kind)), num(d.percent, 3), num(d.down_s / 60, 1), d.samples])
    w.writerow([])
    w.writerow([t("Sprawdzenia dostępności")])
    w.writerow([t(h) for h in ("Nazwa", "Rodzaj", "Cel", "Dostępność %", "Nieudane", "Próbki", "Śr. opóźnienie (ms)", "Maks. opóźnienie (ms)")])
    for c in report.checks:
        w.writerow([c.name, c.kind, c.target, num(c.percent, 3), c.failed, c.samples, num(c.avg_latency_ms, 1), num(c.max_latency_ms, 1)])
    w.writerow([])
    w.writerow([t("Łącza WAN")])
    w.writerow([t(h) for h in ("Łącze", "Urządzenie", "Pobrane (GB)", "Wysłane (GB)", "Dostępność %", "Przerwy", "Czas przerw (min)", "Najdłuższa (min)")])
    for x in report.wan:
        w.writerow([
            x.name, x.device, num(x.rx_bytes / 1e9, 3), num(x.tx_bytes / 1e9, 3), num(x.percent, 3),
            "" if x.outages is None else x.outages,
            num(x.down_s / 60 if x.down_s is not None else None, 1),
            num(x.longest_outage_s / 60 if x.longest_outage_s is not None else None, 1),
        ])  # fmt: skip
    w.writerow([])
    w.writerow([t("Alerty"), report.alerts_total])
    w.writerow([t(h) for h in ("Początek", "Koniec", "Czas (min)", "Waga", "Alert", "Urządzenie")])
    for a in report.alerts:
        w.writerow([
            when(a.started_at), when(a.resolved_at) if a.resolved_at else t("trwa"), num(a.duration_s / 60, 1),
            t(SEVERITY_LABEL.get(a.severity, a.severity)), t(a.title), a.device or "",
        ])  # fmt: skip
    return ("\ufeff" + buf.getvalue()).encode("utf-8")


# --- PDF -------------------------------------------------------------------------------------------

# Czcionka z polskimi znakami: w obrazie Dockera DejaVu (fonts-dejavu-core), na Windowsie Arial; bez niej – Helvetica
# z literami bez ogonków (raport dalej czytelny).
FONT_CANDIDATES = (
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
)
PDF_ALERTS = 40
_ASCII = str.maketrans("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ–—„”’", "acelnoszzACELNOSZZ--\"\"'")


def find_font() -> tuple[str, str] | None:
    custom = os.environ.get("NETPULSE_REPORT_FONT")
    candidates = ((custom, os.environ.get("NETPULSE_REPORT_FONT_BOLD") or custom),) if custom else ()
    for regular, bold in (*candidates, *FONT_CANDIDATES):
        if regular and Path(regular).is_file():
            return regular, bold if bold and Path(bold).is_file() else regular
    return None


def to_pdf(report: Report, font: tuple[str, str] | None | bool = True, lang: str = "pl") -> bytes:
    """PDF A4: podsumowanie, urządzenia, sprawdzenia, łącza WAN, najdłuższe alerty. `font=None` – bez czcionki TTF."""
    from fpdf import FPDF  # import tutaj – CLI i kolektor nie potrzebują
    from fpdf.fonts import FontFace

    tz = ZoneInfo(report.timezone)
    font = find_font() if font is True else font or None
    pdf = FPDF(format="A4", unit="mm")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_margins(15, 15, 15)
    if font:
        pdf.add_font("np", "", font[0])
        pdf.add_font("np", "B", font[1])
        family = "np"

        def tx(s: str) -> str:
            return s
    else:
        family = "helvetica"

        def tx(s: str) -> str:
            return s.translate(_ASCII).encode("latin-1", "replace").decode("latin-1")

    def t(s: str) -> str:
        return translate(s, lang)

    def pct(value: float | None) -> str:
        return fmt_percent(value, lang)

    def when(value: datetime | None) -> str:
        return fmt_time(value, tz, lang)

    title = report_title(report, lang)
    pdf.set_title(tx(t(f"UplinkView – raport {title}")))
    pdf.set_creator(f"UplinkView {report.version}")
    pdf.alias_nb_pages()

    def footer() -> None:
        pdf.set_y(-10)
        pdf.set_font(family, "", 7)
        pdf.set_text_color(120)
        line = t(f"UplinkView {report.version} · wygenerowano {when(report.generated_at)} · strona {pdf.page_no()}/{{nb}}")
        pdf.cell(0, 4, tx(line), align="C")

    pdf.footer = footer  # type: ignore[method-assign]
    pdf.add_page()

    def heading(s: str) -> None:
        pdf.ln(4)
        pdf.set_font(family, "B", 12)
        pdf.set_text_color(31, 111, 235)
        pdf.cell(0, 7, tx(t(s)), new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0)

    def note(s: str) -> None:
        pdf.set_font(family, "", 8)
        pdf.set_text_color(100)
        pdf.multi_cell(0, 4, tx(t(s)), new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0)

    def table(header: list[str], rows: list[list[str]], widths: tuple[int, ...], align: str) -> None:
        if not rows:
            note("Brak danych w tym miesiącu.")
            return
        pdf.set_font(family, "", 8)
        with pdf.table(
            col_widths=widths,
            text_align=tuple("RIGHT" if a == "r" else "LEFT" for a in align),
            line_height=4.6,
            first_row_as_headings=True,
            headings_style=FontFace(emphasis="BOLD", fill_color=(226, 234, 248)),
            borders_layout="HORIZONTAL_LINES",
            cell_fill_color=(244, 247, 252),
            cell_fill_mode="ROWS",
        ) as tbl:
            head = tbl.row()
            for h in header:
                head.cell(tx(t(h)))
            for r in rows:
                row = tbl.row()
                for v in r:
                    row.cell(tx(v))

    # Nagłówek
    pdf.set_font(family, "B", 18)
    pdf.cell(0, 9, tx(t("Raport miesięczny UplinkView")), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(family, "", 11)
    pdf.set_text_color(80)
    pdf.cell(0, 6, tx(f"{title[:1].upper()}{title[1:]} · {when(report.start)} – {when(report.end)} ({report.timezone})"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0)

    # Podsumowanie w kafelkach
    crit = report.alerts_by_severity.get("critical", 0)
    warn = report.alerts_by_severity.get("warning", 0)
    wan_main = next((x for x in report.wan if x.percent is not None), None)
    tiles = [
        (t("Urządzenia"), pct(report.devices_percent), t(f"liczba urządzeń: {len(report.devices)}")),
        (t("Sprawdzenia"), pct(report.checks_percent), t(f"liczba sprawdzeń: {len(report.checks)}")),
        (t("Łącze WAN"), pct(wan_main.percent) if wan_main else "–", wan_main.name if wan_main else t("brak danych")),
        (t("Alerty"), str(report.alerts_total), t(f"krytyczne {crit} · ostrzeżenia {warn}")),
    ]
    pdf.ln(3)
    x0, y0, w, h, gap = pdf.l_margin, pdf.get_y(), 42.0, 20.0, 2.7
    for i, (label, value, sub) in enumerate(tiles):
        x = x0 + i * (w + gap)
        pdf.set_fill_color(244, 247, 252)
        pdf.set_draw_color(220, 226, 236)
        pdf.rect(x, y0, w, h, style="DF")
        pdf.set_xy(x + 3, y0 + 2)
        pdf.set_font(family, "", 8)
        pdf.set_text_color(100)
        pdf.cell(w - 6, 4, tx(label))
        pdf.set_xy(x + 3, y0 + 6.5)
        pdf.set_font(family, "B", 14)
        pdf.set_text_color(0)
        pdf.cell(w - 6, 7, tx(value))
        pdf.set_xy(x + 3, y0 + 14)
        pdf.set_font(family, "", 7)
        pdf.set_text_color(100)
        pdf.cell(w - 6, 4, tx(sub[:34]))
    pdf.set_text_color(0)
    pdf.set_xy(x0, y0 + h + 2)
    if report.raw_from:
        note(
            f"Sprawdzenia i SLA łączy WAN liczone od {when(report.raw_from)} – szczegółowe próbki są trzymane "
            f"{settings.retention_days} dni. Dostępność urządzeń i ruch WAN obejmują cały miesiąc."
        )
    note("Niedostępność to przybliżenie: próbki bez odpowiedzi × interwał odpytywania.")

    heading("Urządzenia")
    table(
        ["Urządzenie", "Adres", "Rodzaj", "Dostępność", "Niedostępność"],
        [[d.name, d.host, t(KIND_LABEL.get(d.kind, d.kind)), pct(d.percent), fmt_duration(d.down_s) if d.samples else "–"] for d in report.devices],
        (60, 36, 28, 28, 28),
        "lllrr",
    )  # fmt: skip

    heading("Sprawdzenia dostępności")
    table(
        ["Sprawdzenie", "Cel", "Dostępność", "Nieudane", "Śr. opóźnienie", "Maks."],
        [[c.name, c.target, pct(c.percent), str(c.failed), f"{fmt_num(c.avg_latency_ms, 1, lang)} ms" if c.avg_latency_ms is not None else "–", f"{fmt_num(c.max_latency_ms, 0, lang)} ms" if c.max_latency_ms is not None else "–"] for c in report.checks],
        (44, 52, 22, 18, 24, 20),
        "llrrrr",
    )  # fmt: skip

    heading("Łącza WAN")
    table(
        ["Łącze", "Urządzenie", "Pobrane", "Wysłane", "Dostępność", "Przerwy", "Najdłuższa"],
        [[x.name, x.device, fmt_bytes(x.rx_bytes, lang), fmt_bytes(x.tx_bytes, lang), pct(x.percent), "–" if x.outages is None else str(x.outages), fmt_duration(x.longest_outage_s) if x.outages else "–"] for x in report.wan],
        (30, 34, 22, 22, 24, 16, 32),
        "llrrrrr",
    )  # fmt: skip

    heading(f"Alerty ({report.alerts_total})")
    longest = sorted(report.alerts, key=lambda a: a.duration_s, reverse=True)[:PDF_ALERTS]
    if report.alerts_total > len(longest):
        note(f"Najdłuższe {len(longest)} z {report.alerts_total} – pełna lista w pliku CSV.")
    table(
        ["Początek", "Czas", "Waga", "Alert", "Urządzenie"],
        [[when(a.started_at), fmt_duration(a.duration_s) + ("" if a.resolved_at else " " + t("(trwa)")), t(SEVERITY_LABEL.get(a.severity, a.severity)), t(a.title), a.device or ""] for a in longest],
        (28, 24, 28, 68, 32),
        "lllll",
    )  # fmt: skip
    return bytes(pdf.output())
