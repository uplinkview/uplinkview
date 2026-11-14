"""Schemat układu pulpitu (wersja 1) – to samo JSON-owe wejście i wyjście dla panelu, aplikacji mobilnej
i pulpitów publicznych. Wykres od 0.26.0 ma zapytania (wiele źródeł), osie, progi i legendę; starsza konfiguracja
wykresu jest zamieniana przy odczycie (`upgrade_chart`). Walidacja jest ścisła (brak nieznanych pól, ograniczone liczby i
długości), bo układ jest danymi od użytkownika zapisywanymi w bazie."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = 1
MAX_WIDGETS = 60

GridWidth = Annotated[int, Field(ge=1, le=12)]  # szerokość w kolumnach siatki 12-kolumnowej (do 0.27: 3/4/6/8/12)
GRID_COLS = 12
MAX_ROW = 2000
MAX_HEIGHT = 40  # wysokość w wierszach siatki (wiersz = 30 px + odstęp)
RangeMinutes = Literal[15, 60, 360, 1440, 10080, 43200, 525600]  # do 1 roku (agregaty godzinowe)
RefreshSeconds = Literal[0, 5, 10, 30, 60, 300]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- źródła danych wykresu -----------------------------------------------------------


class WanSource(Strict):
    kind: Literal["wan"]


class WifiTotalSource(Strict):
    kind: Literal["wifi_total"]


class InterfaceSource(Strict):
    kind: Literal["interface"]
    id: int = Field(ge=1)
    device_id: int | None = Field(None, ge=1)  # tylko dla edytora: z którego urządzenia wybrano port


class DeviceSource(Strict):
    kind: Literal["device"]
    id: int = Field(ge=1)


class WifiNetworkSource(Strict):
    kind: Literal["wifi_network"]
    id: int = Field(ge=1)
    device_id: int | None = Field(None, ge=1)  # tylko dla edytora: z którego urządzenia wybrano sieć


class CheckSource(Strict):
    kind: Literal["check"]  # sprawdzenie dostępności (ping, HTTP, TCP)
    id: int = Field(ge=1)


class ServerSource(Strict):
    kind: Literal["server"]  # serwer, na którym działa UplinkView


class AgentSource(Strict):
    """Dane z tabeli `metrics`: agent serwera (CPU na rdzeniach, sieć, dysk, czujnik, kontener), maszyna Proxmox
    i czujniki urządzeń SNMP (`snmp_*`, od 0.50.0: czujnik, PoE i SFP portu MikroTika)."""

    kind: Literal[
        "agent_cpu",
        "agent_net",
        "agent_disk",
        "agent_temp",
        "agent_container",
        "pve_guest",
        "snmp_sensor",
        "snmp_poe",
        "snmp_sfp",
        "wan_latency",
        "wan_ping",
        "speedtest",
        "vpn",
        "lan_client",
    ]
    id: int = Field(ge=1)  # urządzenie (serwer z agentem, węzeł Proxmox, urządzenie SNMP albo brama – `wan_*`)
    key: str = Field("", max_length=255)  # interfejs, dysk, czujnik, kontener, port albo łącze WAN; dla agent_cpu puste

    @model_validator(mode="after")
    def _key_required(self) -> AgentSource:
        self.key = self.key.strip()
        if self.kind != "agent_cpu" and not self.key:
            raise ValueError("Wybierz interfejs, dysk, czujnik, kontener, port albo maszynę")
        if self.kind == "agent_cpu":
            self.key = ""
        return self


Source = Annotated[
    WanSource | WifiTotalSource | InterfaceSource | DeviceSource | WifiNetworkSource | ServerSource | AgentSource | CheckSource,
    Field(discriminator="kind"),
]

# Metryki dostępne dla źródła (klucze z odpowiedzi endpointów metryk)
ALLOWED_METRICS: dict[str, tuple[str, ...]] = {
    "wan": ("in_bps", "out_bps", "in_bps_max", "out_bps_max"),
    "interface": ("in_bps", "out_bps", "in_errors", "out_errors", "in_discards", "out_discards", "in_bps_max", "out_bps_max"),
    "device": ("cpu_percent", "mem_used_percent", "load1", "poll_ms"),
    "wifi_total": ("clients",),
    "wifi_network": ("clients", "rx_bps", "tx_bps"),
    "server": ("cpu_percent", "mem_used_percent", "swap_used_percent", "disk_used_percent", "load1", "temp_c", "db_size_bytes"),
    "agent_cpu": ("core_max_percent", "core_avg_percent"),
    "agent_net": ("rx_bps", "tx_bps"),
    "agent_disk": ("read_bps", "write_bps"),
    "agent_temp": ("temp_c",),
    "agent_container": ("container_cpu_percent", "container_mem_bytes"),
    "pve_guest": ("guest_cpu_percent", "guest_mem_bytes", "rx_bps", "tx_bps", "read_bps", "write_bps"),
    "snmp_sensor": ("temp_c", "fan_rpm", "voltage_v", "current_a", "power_w", "channel_util_percent"),
    "snmp_poe": ("poe_power_w", "poe_voltage_v"),
    "snmp_sfp": ("sfp_rx_dbm", "sfp_tx_dbm", "sfp_temp_c", "sfp_voltage_v"),
    "wan_latency": ("latency_ms", "loss_percent", "jitter_ms", "availability_percent"),
    "speedtest": ("down_bps", "up_bps", "ping_ms"),
    "wan_ping": ("latency_ms",),
    "vpn": ("down_bps", "up_bps", "connected"),
    "lan_client": ("down_bps", "up_bps"),
    "check": ("latency_ms", "loss_percent", "jitter_ms", "availability_percent", "cert_days"),
}


ColorIndex = Literal[1, 2, 3, 4, 5, 6, 7, 8]  # numer koloru z palety motywu (--chart-1…8)
OffsetMinutes = Literal[0, 60, 1440, 10080]  # porównanie w czasie: bez przesunięcia, godzina, dzień, tydzień wcześniej
LegendValue = Literal["last", "min", "max", "avg"]
MAX_QUERIES = 6
MAX_SERIES = 12


class SeriesConfig(Strict):
    key: str = Field(max_length=32)
    color: ColorIndex | None = None  # puste = kolejny kolor
    label: str | None = Field(None, max_length=40)
    axis: Literal["left", "right"] = "left"


class ChartQuery(Strict):
    """Jedno źródło danych wykresu i jego serie; `offset_min` przesuwa okno wstecz (porównanie z wcześniej)."""

    id: str = Field(pattern=r"^[A-Z]$")
    source: Source
    series: list[SeriesConfig] = Field(min_length=1, max_length=6)
    offset_min: OffsetMinutes = 0

    @model_validator(mode="after")
    def _metrics_match_source(self) -> ChartQuery:
        allowed = ALLOWED_METRICS[self.source.kind]
        keys = [s.key for s in self.series]
        bad = [k for k in keys if k not in allowed]
        if bad:
            raise ValueError(f"Metryka {bad[0]!r} nie jest dostępna dla źródła {self.source.kind!r}")
        if len(set(keys)) != len(keys):
            raise ValueError("Metryki w jednym zapytaniu nie mogą się powtarzać")
        return self


class AxisConfig(Strict):
    """Zakres osi w jednostkach surowych metryki (przepustowość w bit/s); puste = automatycznie."""

    min: float | None = Field(None, ge=-1e15, le=1e15)
    max: float | None = Field(None, gt=-1e15, le=1e15)
    label: str | None = Field(None, max_length=40)

    @model_validator(mode="after")
    def _order(self) -> AxisConfig:
        if self.min is not None and self.max is not None and self.min >= self.max:
            raise ValueError("Minimum osi musi być mniejsze niż maksimum")
        return self


class Axes(Strict):
    left: AxisConfig = AxisConfig()
    right: AxisConfig = AxisConfig()


class Threshold(Strict):
    value: float = Field(ge=-1e15, le=1e15)  # w jednostkach surowych osi lewej
    color: ColorIndex = 4


class LegendConfig(Strict):
    mode: Literal["list", "table", "hidden"] = "list"
    placement: Literal["bottom", "right"] = "bottom"
    values: list[LegendValue] = Field([], max_length=4)

    @field_validator("values")
    @classmethod
    def _unique(cls, v: list[str]) -> list[str]:
        return list(dict.fromkeys(v))


def upgrade_chart(data):
    """Konfiguracja sprzed 0.26.0 (jedno `source` + `series`, `y_max`) → zapytania, osie i legenda."""
    if not isinstance(data, dict) or "source" not in data or "queries" in data:
        return data
    data = dict(data)
    source, series, y_max = data.pop("source"), data.pop("series", []), data.pop("y_max", None)
    data["queries"] = [{"id": "A", "source": source, "series": series}]
    if y_max is not None:
        if not isinstance(y_max, int | float) or y_max <= 0:
            raise ValueError("Maksimum osi Y musi być większe od zera")
        data["axes"] = {"left": {"max": y_max}}
    return data


class ChartConfig(Strict):
    title: str | None = Field(None, max_length=80)
    queries: list[ChartQuery] = Field(min_length=1, max_length=MAX_QUERIES)
    chart: Literal["line", "area", "bar"] = "area"
    stack: bool = False  # serie piętrowane (osobno na osi lewej i prawej)
    unit: Literal["bits", "bytes"] = "bits"  # dla metryk przepustowości: bit/s albo bajty/s
    smooth: bool = False
    axes: Axes = Axes()
    thresholds: list[Threshold] = Field([], max_length=4)
    threshold_style: Literal["off", "line", "area", "line_area"] = "line"
    legend: LegendConfig = LegendConfig()
    range_min: RangeMinutes | None = None  # puste = zakres globalny
    refresh_s: RefreshSeconds | None = None  # puste = interwał globalny
    height: Literal["sm", "md", "lg"] = "md"
    # Od 0.55.0: odcinki, w których internet szedł łączem zapasowym (nie WAN 1), rysowane innym kolorem
    wan_backup: bool = False
    # Zdarzenia na osi czasu (0.34.0): auto – dotyczące urządzeń i portów wykresu, all – wszystkie, off – żadne
    annotations: Literal["auto", "all", "off"] = "auto"  # dawne zdarzenia na wykresie (do 0.48.0) – bez znaczenia

    @model_validator(mode="before")
    @classmethod
    def _upgrade(cls, data):
        return upgrade_chart(data)

    @field_validator("title")
    @classmethod
    def _strip_title(cls, v: str | None) -> str | None:
        v = v.strip() if v else v
        return v or None

    @model_validator(mode="after")
    def _limits(self) -> ChartConfig:
        ids = [q.id for q in self.queries]
        if len(set(ids)) != len(ids):
            raise ValueError("Identyfikatory zapytań muszą być unikalne")
        if sum(len(q.series) for q in self.queries) > MAX_SERIES:
            raise ValueError(f"Wykres może mieć najwyżej {MAX_SERIES} serii")
        return self


# --- panele (od 0.27.0): liczba, paski, tabela, oś stanów -------------------------------

# Wartości w wierszach kolekcji (api/panels.py) – to samo w panelu: lib/panels.ts
COLLECTION_METRICS: dict[str, tuple[str, ...]] = {
    "devices": ("up", "cpu_percent", "mem_used_percent", "poll_ms", "uptime_s"),
    "ports": ("up", "in_bps", "out_bps", "speed_mbps"),
    "disks": ("used_percent", "used_bytes", "free_bytes", "total_bytes"),
    "wifi": ("clients", "rx_bps", "tx_bps"),
    "containers": ("up", "cpu_percent", "mem_bytes"),
    "services": ("up", "mem_bytes", "uptime_s"),
    "checks": ("up", "latency_ms", "loss_percent", "availability_percent", "cert_days"),
    "guests": ("up", "cpu_percent", "mem_bytes", "mem_percent", "rx_bps", "tx_bps", "uptime_s", "backup_age_h"),
    "clients": ("signal_dbm", "rx_rate_kbps", "tx_rate_kbps", "connected_s"),
}
COLLECTIONS_WITH_DEVICE = ("ports", "disks", "containers", "services")  # wymagają urządzenia; wifi, guests – opcjonalnie


class Collection(Strict):
    kind: Literal["devices", "ports", "disks", "wifi", "containers", "services", "clients", "checks", "guests"]
    device_id: int | None = Field(None, ge=1)

    @model_validator(mode="after")
    def _device(self) -> Collection:
        if self.kind in COLLECTIONS_WITH_DEVICE and self.device_id is None:
            raise ValueError("Wybierz urządzenie")
        if self.kind in ("devices", "clients", "checks"):
            self.device_id = None
        return self


def _title(v: str | None) -> str | None:
    v = v.strip() if v else v
    return v or None


class StatConfig(Strict):
    """Liczba z mini-wykresem: jedna metryka ze źródła wykresu, wartość ostatnia albo z zakresu, kolor z progów."""

    title: str | None = Field(None, max_length=80)
    source: Source
    key: str = Field(max_length=32)
    reduce: Literal["last", "avg", "max", "min"] = "last"
    unit: Literal["bits", "bytes"] = "bits"
    sparkline: bool = True
    color: ColorIndex = 1  # kolor bazowy (poniżej pierwszego progu)
    color_mode: Literal["value", "background"] = "value"
    thresholds: list[Threshold] = Field([], max_length=4)
    range_min: RangeMinutes | None = None
    refresh_s: RefreshSeconds | None = None
    # Od 0.33.0: wskaźnik kołowy (max – koniec skali; puste = 100 dla %, inaczej maksimum z zakresu)
    # i zmiana względem poprzedniego okresu tej samej długości
    display: Literal["number", "gauge"] = "number"
    max: float | None = Field(None, gt=0)
    show_change: bool = False

    _strip = field_validator("title")(lambda cls, v: _title(v))

    @model_validator(mode="after")
    def _metric(self) -> StatConfig:
        if self.key not in ALLOWED_METRICS[self.source.kind]:
            raise ValueError(f"Metryka {self.key!r} nie jest dostępna dla źródła {self.source.kind!r}")
        return self


class BarGaugeConfig(Strict):
    """Paski: jedna wartość dla każdego wiersza kolekcji (np. zajętość wszystkich dysków serwera)."""

    title: str | None = Field(None, max_length=80)
    collection: Collection
    key: str = Field(max_length=32)
    min: float = Field(0, ge=-1e15, le=1e15)
    max: float | None = Field(None, gt=-1e15, le=1e15)  # puste = 100 dla %, inaczej największa wartość
    unit: Literal["bits", "bytes"] = "bits"
    color: ColorIndex = 1
    thresholds: list[Threshold] = Field([], max_length=4)
    orientation: Literal["horizontal", "vertical"] = "horizontal"
    sort: Literal["none", "asc", "desc"] = "none"
    limit: int = Field(12, ge=1, le=50)

    _strip = field_validator("title")(lambda cls, v: _title(v))

    @model_validator(mode="after")
    def _metric(self) -> BarGaugeConfig:
        if self.key not in COLLECTION_METRICS[self.collection.kind]:
            raise ValueError(f"Wartość {self.key!r} nie jest dostępna dla {self.collection.kind!r}")
        if self.max is not None and self.max <= self.min:
            raise ValueError("Maksimum musi być większe niż minimum")
        return self


class TableConfig(Strict):
    """Tabela wierszy kolekcji z wybranymi kolumnami i sortowaniem."""

    title: str | None = Field(None, max_length=80)
    collection: Collection
    columns: list[str] = Field(min_length=1, max_length=8)
    sort_by: str | None = Field(None, max_length=32)  # puste = nazwa
    sort_desc: bool = False
    limit: int = Field(20, ge=1, le=100)
    unit: Literal["bits", "bytes"] = "bits"

    _strip = field_validator("title")(lambda cls, v: _title(v))

    @model_validator(mode="after")
    def _columns(self) -> TableConfig:
        allowed = COLLECTION_METRICS[self.collection.kind]
        bad = [c for c in self.columns if c not in allowed]
        if bad:
            raise ValueError(f"Kolumna {bad[0]!r} nie jest dostępna dla {self.collection.kind!r}")
        if len(set(self.columns)) != len(self.columns):
            raise ValueError("Kolumny nie mogą się powtarzać")
        if self.sort_by is not None and self.sort_by not in self.columns:
            raise ValueError("Sortować można tylko po wybranej kolumnie")
        return self


class StateItemRef(Strict):
    kind: Literal["device", "interface", "check"]
    id: int = Field(ge=1)
    device_id: int | None = Field(None, ge=1)  # tylko dla edytora: urządzenie portu


class StateTimelineConfig(Strict):
    """Oś stanów: działa / nie działa w czasie dla urządzeń i portów. Pusta lista = wszystkie urządzenia."""

    title: str | None = Field(None, max_length=80)
    items: list[StateItemRef] = Field([], max_length=20)
    range_min: RangeMinutes | None = None
    refresh_s: RefreshSeconds | None = None

    _strip = field_validator("title")(lambda cls, v: _title(v))

    @field_validator("items")
    @classmethod
    def _unique(cls, v: list[StateItemRef]) -> list[StateItemRef]:
        seen = set()
        out = []
        for item in v:
            if (item.kind, item.id) not in seen:
                seen.add((item.kind, item.id))
                out.append(item)
        return out


# --- widgety -------------------------------------------------------------------------

WIDGET_ID = r"^[A-Za-z0-9_-]{1,40}$"


class SummaryConfig(Strict):
    tiles: list[Literal["devices", "wan_down", "wan_up", "wifi_clients"]] = Field(min_length=1, max_length=4)

    @field_validator("tiles")
    @classmethod
    def _unique(cls, v: list[str]) -> list[str]:
        if len(set(v)) != len(v):
            raise ValueError("Kafelki nie mogą się powtarzać")
        return v


class DevicesConfig(Strict):
    kinds: list[Literal["gateway", "switch", "ap", "server", "other"]] | None = Field(None, max_length=4)  # puste = wszystkie
    display: Literal["cards", "table"] = "cards"  # od 0.42.0 tabela z CPU i RAM


class StatusConfig(Strict):
    """Pasek „Sieć działa prawidłowo” (od 0.42.0) – bez ustawień."""


class AlertsConfig(Strict):
    limit: Literal[3, 5, 8, 10] = 5  # ostatnie alerty, aktywne na górze


class ChecksConfig(Strict):
    days: Literal[7, 30] = 30  # paski dostępności dzień po dniu


class EventsConfig(Strict):
    """Kafelek „Zdarzenia” (od 0.49.0): przełączenia WAN i restarty urządzeń z ostatnich `days` dni."""

    days: Literal[1, 7, 30] = 7
    limit: Literal[3, 5, 8, 10] = 8


class VpnConfig(Strict):
    """Kafelek „VPN” (od 0.57.0): serwery VPN bramy UniFi i klienci – kto jest połączony, od kiedy, ruch."""

    title: str | None = Field(None, max_length=80)
    show_offline: bool = True  # pokazywać rozłączonych klientów (z czasem ostatniego połączenia)

    _strip = field_validator("title")(lambda cls, v: _title(v))


class ServerConfig(Strict):
    pass  # karta stanu serwera UplinkView nie ma ustawień


class PoeConfig(Strict):
    device_id: int | None = Field(None, ge=1)  # puste = wszystkie switche z danymi PoE


class WanStatusConfig(Strict):
    device_id: int | None = Field(None, ge=1)  # router; puste = łącza WAN wszystkich routerów


class WanChartConfig(Strict):
    device_id: int | None = Field(None, ge=1)
    metric: Literal["in_bps", "out_bps"] = "in_bps"  # pobieranie albo wysyłanie aktywnego łącza
    range_min: RangeMinutes | None = None  # puste = zakres globalny
    height: Literal["sm", "md", "lg"] = "md"


class WanSlaConfig(Strict):
    device_id: int | None = Field(None, ge=1)
    days: Literal[1, 7, 30] = 7


class WanUsageConfig(Strict):
    """Licznik zużycia transferu (od 0.82.0): dziś i w okresie rozliczeniowym, opcjonalnie z limitem pakietu."""

    device_id: int | None = Field(None, ge=1)
    reset_day: int = Field(1, ge=1, le=28)  # dzień miesiąca, od którego liczy się okres (1 = miesiąc kalendarzowy)
    limit_gb: float | None = Field(None, gt=0, le=1_000_000)  # pakiet na okres (pobrane + wysłane); puste = bez limitu


class SummaryWidget(Strict):
    id: str = Field(pattern=WIDGET_ID)
    type: Literal["summary"]
    w: GridWidth
    x: int | None = Field(None, ge=0, lt=GRID_COLS)
    y: int | None = Field(None, ge=0, le=MAX_ROW)
    h: int | None = Field(None, ge=1, le=MAX_HEIGHT)
    config: SummaryConfig


class ChartWidget(Strict):
    id: str = Field(pattern=WIDGET_ID)
    type: Literal["chart"]
    w: GridWidth
    x: int | None = Field(None, ge=0, lt=GRID_COLS)
    y: int | None = Field(None, ge=0, le=MAX_ROW)
    h: int | None = Field(None, ge=1, le=MAX_HEIGHT)
    config: ChartConfig


class DevicesWidget(Strict):
    id: str = Field(pattern=WIDGET_ID)
    type: Literal["devices"]
    w: GridWidth
    x: int | None = Field(None, ge=0, lt=GRID_COLS)
    y: int | None = Field(None, ge=0, le=MAX_ROW)
    h: int | None = Field(None, ge=1, le=MAX_HEIGHT)
    config: DevicesConfig = DevicesConfig()


class StatusWidget(Strict):
    id: str = Field(pattern=WIDGET_ID)
    type: Literal["status"]
    w: GridWidth
    x: int | None = Field(None, ge=0, lt=GRID_COLS)
    y: int | None = Field(None, ge=0, le=MAX_ROW)
    h: int | None = Field(None, ge=1, le=MAX_HEIGHT)
    config: StatusConfig = StatusConfig()


class AlertsWidget(Strict):
    id: str = Field(pattern=WIDGET_ID)
    type: Literal["alerts"]
    w: GridWidth
    x: int | None = Field(None, ge=0, lt=GRID_COLS)
    y: int | None = Field(None, ge=0, le=MAX_ROW)
    h: int | None = Field(None, ge=1, le=MAX_HEIGHT)
    config: AlertsConfig = AlertsConfig()


class ChecksWidget(Strict):
    id: str = Field(pattern=WIDGET_ID)
    type: Literal["checks"]
    w: GridWidth
    x: int | None = Field(None, ge=0, lt=GRID_COLS)
    y: int | None = Field(None, ge=0, le=MAX_ROW)
    h: int | None = Field(None, ge=1, le=MAX_HEIGHT)
    config: ChecksConfig = ChecksConfig()


class EventsWidget(Strict):
    id: str = Field(pattern=WIDGET_ID)
    type: Literal["events"]
    w: GridWidth
    x: int | None = Field(None, ge=0, lt=GRID_COLS)
    y: int | None = Field(None, ge=0, le=MAX_ROW)
    h: int | None = Field(None, ge=1, le=MAX_HEIGHT)
    config: EventsConfig = EventsConfig()


class VpnWidget(Strict):
    id: str = Field(pattern=WIDGET_ID)
    type: Literal["vpn"]
    w: GridWidth
    x: int | None = Field(None, ge=0, lt=GRID_COLS)
    y: int | None = Field(None, ge=0, le=MAX_ROW)
    h: int | None = Field(None, ge=1, le=MAX_HEIGHT)
    config: VpnConfig = VpnConfig()


class PoeWidget(Strict):
    id: str = Field(pattern=WIDGET_ID)
    type: Literal["poe"]
    w: GridWidth
    x: int | None = Field(None, ge=0, lt=GRID_COLS)
    y: int | None = Field(None, ge=0, le=MAX_ROW)
    h: int | None = Field(None, ge=1, le=MAX_HEIGHT)
    config: PoeConfig = PoeConfig()


class ServerWidget(Strict):
    id: str = Field(pattern=WIDGET_ID)
    type: Literal["server"]
    w: GridWidth
    x: int | None = Field(None, ge=0, lt=GRID_COLS)
    y: int | None = Field(None, ge=0, le=MAX_ROW)
    h: int | None = Field(None, ge=1, le=MAX_HEIGHT)
    config: ServerConfig = ServerConfig()


class WanStatusWidget(Strict):
    id: str = Field(pattern=WIDGET_ID)
    type: Literal["wan_status"]
    w: GridWidth
    x: int | None = Field(None, ge=0, lt=GRID_COLS)
    y: int | None = Field(None, ge=0, le=MAX_ROW)
    h: int | None = Field(None, ge=1, le=MAX_HEIGHT)
    config: WanStatusConfig = WanStatusConfig()


class WanChartWidget(Strict):
    id: str = Field(pattern=WIDGET_ID)
    type: Literal["wan_chart"]
    w: GridWidth
    x: int | None = Field(None, ge=0, lt=GRID_COLS)
    y: int | None = Field(None, ge=0, le=MAX_ROW)
    h: int | None = Field(None, ge=1, le=MAX_HEIGHT)
    config: WanChartConfig = WanChartConfig()


class WanSlaWidget(Strict):
    id: str = Field(pattern=WIDGET_ID)
    type: Literal["wan_sla"]
    w: GridWidth
    x: int | None = Field(None, ge=0, lt=GRID_COLS)
    y: int | None = Field(None, ge=0, le=MAX_ROW)
    h: int | None = Field(None, ge=1, le=MAX_HEIGHT)
    config: WanSlaConfig = WanSlaConfig()


class WanUsageWidget(Strict):
    id: str = Field(pattern=WIDGET_ID)
    type: Literal["wan_usage"]
    w: GridWidth
    x: int | None = Field(None, ge=0, lt=GRID_COLS)
    y: int | None = Field(None, ge=0, le=MAX_ROW)
    h: int | None = Field(None, ge=1, le=MAX_HEIGHT)
    config: WanUsageConfig = WanUsageConfig()


class StatWidget(Strict):
    id: str = Field(pattern=WIDGET_ID)
    type: Literal["stat"]
    w: GridWidth
    x: int | None = Field(None, ge=0, lt=GRID_COLS)
    y: int | None = Field(None, ge=0, le=MAX_ROW)
    h: int | None = Field(None, ge=1, le=MAX_HEIGHT)
    config: StatConfig


class BarGaugeWidget(Strict):
    id: str = Field(pattern=WIDGET_ID)
    type: Literal["bargauge"]
    w: GridWidth
    x: int | None = Field(None, ge=0, lt=GRID_COLS)
    y: int | None = Field(None, ge=0, le=MAX_ROW)
    h: int | None = Field(None, ge=1, le=MAX_HEIGHT)
    config: BarGaugeConfig


class TableWidget(Strict):
    id: str = Field(pattern=WIDGET_ID)
    type: Literal["table"]
    w: GridWidth
    x: int | None = Field(None, ge=0, lt=GRID_COLS)
    y: int | None = Field(None, ge=0, le=MAX_ROW)
    h: int | None = Field(None, ge=1, le=MAX_HEIGHT)
    config: TableConfig


class StateTimelineWidget(Strict):
    id: str = Field(pattern=WIDGET_ID)
    type: Literal["state_timeline"]
    w: GridWidth
    x: int | None = Field(None, ge=0, lt=GRID_COLS)
    y: int | None = Field(None, ge=0, le=MAX_ROW)
    h: int | None = Field(None, ge=1, le=MAX_HEIGHT)
    config: StateTimelineConfig = StateTimelineConfig()


class HeatmapConfig(Strict):
    """Mapa cieplna (0.37.0): jedna metryka źródła wykresu w kratkach godzina × dzień tygodnia albo × data.

    Dane z `weeks` tygodni (osobne zapytania o 7 dni wstecz, przesunięte o kolejne tygodnie), grupowane w panelu
    w strefie czasowej przeglądarki; wartość kratki to średnia albo maksimum z próbek tej godziny."""

    title: str | None = Field(None, max_length=80)
    source: Source
    key: str = Field(max_length=32)
    reduce: Literal["avg", "max"] = "avg"
    group: Literal["weekday", "date"] = "weekday"
    weeks: Literal[1, 4, 12] = 4
    unit: Literal["bits", "bytes"] = "bits"
    color: ColorIndex = 1

    _strip = field_validator("title")(lambda cls, v: _title(v))

    @model_validator(mode="after")
    def _metric(self) -> HeatmapConfig:
        if self.key not in ALLOWED_METRICS[self.source.kind]:
            raise ValueError(f"Metryka {self.key!r} nie jest dostępna dla źródła {self.source.kind!r}")
        if self.group == "date" and self.weeks > 4:
            raise ValueError("Układ dzień po dniu – najwyżej 4 tygodnie")
        return self


class HeatmapWidget(Strict):
    id: str = Field(pattern=WIDGET_ID)
    type: Literal["heatmap"]
    w: GridWidth
    x: int | None = Field(None, ge=0, lt=GRID_COLS)
    y: int | None = Field(None, ge=0, le=MAX_ROW)
    h: int | None = Field(None, ge=1, le=MAX_HEIGHT)
    config: HeatmapConfig


PieMetric = Literal[
    "cpu", "mem", "disk", "disks_share",
    "port_load", "port_dir",
    "ports_in", "ports_out", "ports_state",
    "wifi_clients",
    "containers_mem", "containers_cpu", "services_state",
    "guests_mem", "guests_state",
    "devices_state", "checks_state",
]
# Co monitoruje wykres kołowy → kolekcja z danymi (pulpit publiczny przepuszcza tylko ją)
PIE_COLLECTION: dict[str, str] = {
    "cpu": "devices", "mem": "devices", "devices_state": "devices",
    "disk": "disks", "disks_share": "disks",
    "port_load": "ports", "port_dir": "ports",
    "ports_in": "ports", "ports_out": "ports", "ports_state": "ports",
    "wifi_clients": "wifi",
    "containers_mem": "containers", "containers_cpu": "containers", "services_state": "services",
    "guests_mem": "guests", "guests_state": "guests",
    "checks_state": "checks",
}
PIE_GLOBAL = {"devices_state", "checks_state"}  # cała sieć, bez urządzenia
PIE_DEVICE_OPTIONAL = {"wifi_clients", "guests_mem", "guests_state"}  # puste urządzenie = wszystkie
PIE_ITEM = {"disk", "port_load", "port_dir"}  # wybrany dysk albo port (`item`)


class PieConfig(Strict):
    """Wykres kołowy (0.39.0): urządzenie i to, co na nim monitorować – zajętość (CPU, RAM, dysk), udział
    (klienci sieci WiFi, kontenery, maszyny) albo stan (działa / nie działa). Od 0.40.0 jeden wybrany port:
    obciążenie (`port_load`) albo odbierane / wysyłane (`port_dir`); `ports_in` / `ports_out` (wszystkie porty
    na jednym wykresie) zostają tylko dla zapisanych pulpitów."""

    title: str | None = Field(None, max_length=80)
    device_id: int | None = Field(None, ge=1)
    metric: PieMetric
    item: str | None = Field(None, max_length=255)  # dysk (punkt montowania; puste = pierwszy) albo id portu
    limit: int = Field(8, ge=2, le=12)  # najwięcej kawałków, reszta jako „Pozostałe”

    _strip = field_validator("title")(lambda cls, v: _title(v))

    @model_validator(mode="after")
    def _device(self) -> PieConfig:
        if self.metric in PIE_GLOBAL:
            self.device_id = None
        elif self.device_id is None and self.metric not in PIE_DEVICE_OPTIONAL:
            raise ValueError("Wybierz urządzenie")
        if self.metric not in PIE_ITEM:
            self.item = None
        elif self.metric != "disk" and not (self.item or "").isdigit():
            raise ValueError("Wybierz port")
        return self

    def collection(self) -> tuple[str, int | None]:
        """Kolekcja i urządzenie, o które pyta panel (`/api/collections/{kind}?device_id=`)."""
        kind = PIE_COLLECTION[self.metric]
        return kind, None if kind in ("devices", "checks") else self.device_id


class PieWidget(Strict):
    id: str = Field(pattern=WIDGET_ID)
    type: Literal["pie"]
    w: GridWidth
    x: int | None = Field(None, ge=0, lt=GRID_COLS)
    y: int | None = Field(None, ge=0, le=MAX_ROW)
    h: int | None = Field(None, ge=1, le=MAX_HEIGHT)
    config: PieConfig


class SectionConfig(Strict):
    """Nagłówek sekcji pulpitu: widgety pod nim (do następnej sekcji) można zwinąć."""

    title: str = Field(min_length=1, max_length=80)
    collapsed: bool = False  # zwinięta przy otwarciu pulpitu

    @field_validator("title")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Podaj nazwę sekcji")
        return v


class SectionWidget(Strict):
    id: str = Field(pattern=WIDGET_ID)
    type: Literal["section"]
    w: GridWidth = GRID_COLS
    x: int | None = Field(None, ge=0, lt=GRID_COLS)
    y: int | None = Field(None, ge=0, le=MAX_ROW)
    h: int | None = Field(None, ge=1, le=MAX_HEIGHT)
    config: SectionConfig


Widget = Annotated[
    SummaryWidget
    | ChartWidget
    | DevicesWidget
    | PoeWidget
    | ServerWidget
    | WanStatusWidget
    | WanChartWidget
    | WanSlaWidget
    | WanUsageWidget
    | StatWidget
    | BarGaugeWidget
    | TableWidget
    | StateTimelineWidget
    | HeatmapWidget
    | PieWidget
    | SectionWidget
    | StatusWidget
    | AlertsWidget
    | ChecksWidget
    | EventsWidget
    | VpnWidget,
    Field(discriminator="type"),
]


class DashboardLayout(Strict):
    version: Literal[1] = SCHEMA_VERSION
    widgets: list[Widget] = Field(max_length=MAX_WIDGETS)

    @field_validator("widgets")
    @classmethod
    def _unique_ids(cls, v: list) -> list:
        ids = [w.id for w in v]
        if len(set(ids)) != len(ids):
            raise ValueError("Identyfikatory widgetów muszą być unikalne")
        for w in v:
            if w.x is not None and w.x + w.w > GRID_COLS:
                raise ValueError(f"Widget {w.id!r} wychodzi poza siatkę ({GRID_COLS} kolumn)")
        return v


# --- preferencje (odświeżanie) -------------------------------------------------------


class RefreshPrefs(Strict):
    interval_s: RefreshSeconds
    range_min: RangeMinutes


# --- pulpit publiczny -----------------------------------------------------------------

PublicRefresh = Literal[10, 30, 60, 300]  # wyświetlacz ścienny odświeża się nie częściej niż co 10 s


class PublicOptions(Strict):
    """Ustawienia pulpitu publicznego: odświeżanie, zakres wykresów i ukrywanie adresów urządzeń."""

    refresh_s: PublicRefresh = 30
    range_min: RangeMinutes = 60
    hide_hosts: bool = True
