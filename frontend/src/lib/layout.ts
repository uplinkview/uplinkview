/**
 * Model układu pulpitu (wersja 1) – odpowiada schematowi w backend/netpulse/api/layout_schemas.py.
 * Czyste funkcje (bez Reacta): układ domyślny i operacje edytora, żeby łatwo je testować.
 */
import type { TextKey } from "../i18n";
import type { RangeMinutes, RefreshSeconds } from "./refresh";

/** Szerokość w kolumnach siatki 12-kolumnowej (od 0.28.0 dowolna 1–12; kreator proponuje typowe). */
export type GridWidth = number;
export const GRID_WIDTHS: GridWidth[] = [3, 4, 6, 8, 12];
export const GRID_COLS = 12;
/** Wiersz siatki: 30 px wysokości + 12 px odstępu (widget o h wierszach ma 42·h − 12 px) */
export const ROW_HEIGHT = 30;
export const GRID_MARGIN = 12;
export const MAX_HEIGHT = 40;
export const rowsToPx = (h: number) => h * ROW_HEIGHT + (h - 1) * GRID_MARGIN;
export const MAX_WIDGETS = 60;

export type ChartKind = "line" | "area" | "bar";
export type ChartUnit = "bits" | "bytes";
export type ChartHeight = "sm" | "md" | "lg";
/** Numer koloru z palety motywu (--chart-1…8 w index.css; ta sama lista w layout_schemas.py). */
export type ColorIndex = 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8;
export const COLOR_INDEXES: ColorIndex[] = [1, 2, 3, 4, 5, 6, 7, 8];
/** Kolor kolejnej serii bez wybranego koloru. */
export const autoColor = (i: number): ColorIndex => ((i % COLOR_INDEXES.length) + 1) as ColorIndex;
export type DeviceKind = "gateway" | "switch" | "ap" | "server" | "other";
export type SummaryTile = "devices" | "wan_down" | "wan_up" | "wifi_clients";
export const SUMMARY_TILES: SummaryTile[] = ["devices", "wan_down", "wan_up", "wifi_clients"];
export const DEVICE_KINDS: DeviceKind[] = ["gateway", "switch", "ap", "server", "other"];

export type Source =
  | { kind: "wan" }
  | { kind: "wifi_total" }
  | { kind: "interface"; id: number; device_id?: number | null }
  | { kind: "device"; id: number }
  | { kind: "wifi_network"; id: number; device_id?: number | null }
  | { kind: "server" }
  | { kind: "check"; id: number }
  | { kind: AgentSourceKind; id: number; key: string };
export type SourceKind = Source["kind"];
/** Źródła z agenta serwera: urządzenie (`id`) i wybrany interfejs, dysk, czujnik albo kontener (`key`). */
export type AgentSourceKind =
  | "agent_cpu"
  | "agent_net"
  | "agent_disk"
  | "agent_temp"
  | "agent_container"
  | "pve_guest"
  | "snmp_sensor"
  | "snmp_poe"
  | "snmp_sfp"
  | "wan_latency"
  | "wan_ping"
  | "speedtest"
  | "vpn"
  | "lan_client";
export const AGENT_SOURCE_KINDS: AgentSourceKind[] = [
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
];
/** Pingi łączy WAN mierzone przez bramę UniFi (od 0.55.0): urządzenie = brama, klucz = interfejs łącza (`eth3`)
 * albo interfejs i serwer (`eth3 · google.com`). */
export const isWanPingSource = (kind: SourceKind): boolean => kind === "wan_latency" || kind === "wan_ping";
/** Testy prędkości bramy UniFi (od 0.70.0): urządzenie = brama, klucz = interfejs łącza; punkt w chwili testu. */
export const isSpeedtestSource = (kind: SourceKind): boolean => kind === "speedtest";
/** Separator w kluczu pingu bramy do serwera (jak WAN_PING_SEP w unifi_collector.py) */
export const WAN_PING_SEP = " · ";
/** Czujniki urządzeń SNMP (od 0.50.0: MikroTik) – te same endpointy co agent, inne urządzenia do wyboru. */
export const isSnmpSensorSource = (kind: SourceKind): boolean => kind === "snmp_sensor" || kind === "snmp_poe" || kind === "snmp_sfp";
export const isAgentSource = (kind: SourceKind): kind is AgentSourceKind => (AGENT_SOURCE_KINDS as string[]).includes(kind);
export const SOURCE_KINDS: SourceKind[] = ["wan", "interface", "device", "wifi_total", "wifi_network", "server", "check", ...AGENT_SOURCE_KINDS];

export type Axis = "left" | "right";
/** Porównanie w czasie: to samo okno godzinę, dzień albo tydzień wcześniej (parametr `offset` API metryk). */
export type OffsetMinutes = 0 | 60 | 1440 | 10080;
export const OFFSET_OPTIONS: OffsetMinutes[] = [0, 60, 1440, 10080];
export type LegendValue = "last" | "min" | "max" | "avg";
export const LEGEND_VALUES: LegendValue[] = ["last", "min", "max", "avg"];
export type LegendMode = "list" | "table" | "hidden";
export type ThresholdStyle = "off" | "line" | "area" | "line_area";
export const MAX_QUERIES = 6;
export const MAX_SERIES = 12;
const QUERY_IDS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";

export interface SeriesConfig {
  key: string;
  color?: ColorIndex | null;
  label?: string | null;
  axis?: Axis;
}

/** Jedno źródło danych wykresu (schemat: backend/netpulse/api/layout_schemas.py ChartQuery). */
export interface ChartQuery {
  id: string;
  source: Source;
  series: SeriesConfig[];
  offset_min?: OffsetMinutes;
}

/** Zakres osi w jednostkach surowych metryki (przepustowość w bit/s); puste = automatycznie. */
export interface AxisConfig {
  min?: number | null;
  max?: number | null;
  label?: string | null;
}

/** Próg w jednostkach surowych osi lewej. */
export interface Threshold {
  value: number;
  color: ColorIndex;
}

/** Brak progów jako jedna stała tablica: nowa `[]` przy każdym renderze przerysowywała cały wykres (0.65.4). */
export const NO_THRESHOLDS: Threshold[] = [];

export interface LegendConfig {
  mode: LegendMode;
  placement: "bottom" | "right";
  values: LegendValue[];
}

export interface ChartConfig {
  title?: string | null;
  queries: ChartQuery[];
  chart: ChartKind;
  stack?: boolean;
  unit: ChartUnit;
  smooth: boolean;
  axes?: { left?: AxisConfig; right?: AxisConfig };
  thresholds?: Threshold[];
  threshold_style?: ThresholdStyle;
  legend?: LegendConfig;
  range_min?: RangeMinutes | null;
  refresh_s?: RefreshSeconds | null;
  height: ChartHeight;
  /** Od 0.55.0: odcinki, w których internet szedł łączem zapasowym (nie WAN 1), innym kolorem */
  wan_backup?: boolean;
  /** Dawne zdarzenia na osi czasu (0.34.0–0.48.0) – zostaje w zapisanych pulpitach, od 0.49.0 bez znaczenia */
  annotations?: Annotations;
}
export type Annotations = "auto" | "all" | "off";

/** Konfiguracja wykresu sprzed 0.26.0: jedno źródło i `y_max`. Serwer zamienia ją przy odczycie; tu na wszelki wypadek. */
export type LegacyChartConfig = Omit<ChartConfig, "queries"> & { source: Source; series: SeriesConfig[]; y_max?: number | null };

export function upgradeChartConfig(c: ChartConfig | LegacyChartConfig): ChartConfig {
  if (!("source" in c) || "queries" in c) return c as ChartConfig;
  const { source, series, y_max, ...rest } = c;
  return { ...rest, queries: [{ id: "A", source, series, offset_min: 0 }], axes: y_max != null ? { left: { max: y_max } } : rest.axes };
}

export const DEFAULT_LEGEND: LegendConfig = { mode: "list", placement: "bottom", values: [] };

/** Wszystkie serie wykresu w kolejności zapytań, z zapytaniem, do którego należą. */
export function allSeries(c: ChartConfig): { query: ChartQuery; series: SeriesConfig }[] {
  return c.queries.flatMap((query) => query.series.map((series) => ({ query, series })));
}

/** Jednostka osi = jednostka pierwszej serii na tej osi; null, gdy oś jest pusta. */
export function axisClass(c: ChartConfig, axis: Axis): UnitClass | null {
  const first = allSeries(c).find(({ series }) => (series.axis ?? "left") === axis);
  return first ? unitClassOf(first.series.key) : null;
}

/** Kolejny wolny identyfikator zapytania: A, B, C… */
export function nextQueryId(c: ChartConfig): string {
  const used = new Set(c.queries.map((q) => q.id));
  return [...QUERY_IDS].find((id) => !used.has(id)) ?? "Z";
}

/** Pierwszy kolor palety, którego nie używa jeszcze żadna seria wykresu. */
export function freeColor(c: ChartConfig): ColorIndex {
  const used = new Set(allSeries(c).map(({ series }) => series.color));
  return COLOR_INDEXES.find((i) => !used.has(i)) ?? 1;
}

interface WidgetBase {
  id: string;
  w: GridWidth;
  /** Pozycja i wysokość w siatce (od 0.28.0); brak = ułożenie po kolei jak dawniej (placeWidgets) */
  x?: number | null;
  y?: number | null;
  h?: number | null;
}
export type SummaryWidgetModel = WidgetBase & { type: "summary"; config: { tiles: SummaryTile[] } };
export type ChartWidgetModel = WidgetBase & { type: "chart"; config: ChartConfig };
export type DevicesDisplay = "cards" | "table";
export type DevicesWidgetModel = WidgetBase & { type: "devices"; config: { kinds?: DeviceKind[] | null; display?: DevicesDisplay } };
/** Od 0.42.0: pasek stanu sieci, ostatnie alerty i paski dostępności sprawdzeń (dzień po dniu). */
export type StatusWidgetModel = WidgetBase & { type: "status"; config: Record<string, never> };
export type AlertsLimit = 3 | 5 | 8 | 10;
export const ALERTS_LIMITS: AlertsLimit[] = [3, 5, 8, 10];
export type AlertsWidgetModel = WidgetBase & { type: "alerts"; config: { limit: AlertsLimit } };
/** Kafelek „Zdarzenia” (od 0.49.0): przełączenia WAN i restarty urządzeń z ostatnich `days` dni. */
export type EventsDays = 1 | 7 | 30;
export const EVENTS_DAYS: EventsDays[] = [1, 7, 30];
export type EventsWidgetModel = WidgetBase & { type: "events"; config: { days: EventsDays; limit: AlertsLimit } };
/** Kafelek „VPN” (od 0.57.0): klienci VPN bramy UniFi; `show_offline` – także rozłączeni. */
export type VpnWidgetModel = WidgetBase & { type: "vpn"; config: { title?: string | null; show_offline: boolean } };
export type ChecksDays = 7 | 30;
export type ChecksWidgetModel = WidgetBase & { type: "checks"; config: { days: ChecksDays } };
export type PoeWidgetModel = WidgetBase & { type: "poe"; config: { device_id?: number | null } };
export type ServerWidgetModel = WidgetBase & { type: "server"; config: Record<string, never> };
/** Łącza WAN (dual WAN): `device_id` – router, puste = wszystkie routery. */
export type WanMetric = "in_bps" | "out_bps";
export type WanStatusWidgetModel = WidgetBase & { type: "wan_status"; config: { device_id?: number | null } };
export type WanChartWidgetModel = WidgetBase & {
  type: "wan_chart";
  config: { device_id?: number | null; metric: WanMetric; range_min?: RangeMinutes | null; height: ChartHeight };
};
export type WanSlaWidgetModel = WidgetBase & { type: "wan_sla"; config: { device_id?: number | null; days: 1 | 7 | 30 } };
/** Licznik zużycia transferu (od 0.82.0): dziś i w okresie od dnia `reset_day`, opcjonalnie pakiet `limit_gb` (pobrane + wysłane). */
export type WanUsageWidgetModel = WidgetBase & {
  type: "wan_usage";
  config: { device_id?: number | null; reset_day: number; limit_gb?: number | null };
};

// --- panele od 0.27.0 (schemat: backend/netpulse/api/layout_schemas.py) ---------------------
export type CollectionKind = "devices" | "ports" | "disks" | "wifi" | "containers" | "services" | "clients" | "checks" | "guests";
/** Zestaw obiektów z bieżącymi wartościami (GET /api/collections/{kind}); porty, dyski i kontenery – jednego urządzenia. */
export interface Collection {
  kind: CollectionKind;
  device_id?: number | null;
}
export type Reduce = "last" | "avg" | "max" | "min";
export interface StatConfig {
  title?: string | null;
  source: Source;
  key: string;
  reduce: Reduce;
  unit: ChartUnit;
  sparkline: boolean;
  color: ColorIndex;
  color_mode: "value" | "background";
  thresholds: Threshold[];
  range_min?: RangeMinutes | null;
  refresh_s?: RefreshSeconds | null;
  /** Od 0.33.0: liczba albo wskaźnik kołowy (`max` – koniec skali; puste = 100 dla %, inaczej maksimum z zakresu) */
  display?: "number" | "gauge";
  max?: number | null;
  /** Zmiana względem poprzedniego okresu tej samej długości */
  show_change?: boolean;
}
/** Mapa cieplna (0.37.0): metryka w kratkach godzina × dzień tygodnia albo × data, z `weeks` tygodni. */
export interface HeatmapConfig {
  title?: string | null;
  source: Source;
  key: string;
  reduce: "avg" | "max";
  group: "weekday" | "date";
  weeks: 1 | 4 | 12;
  unit: ChartUnit;
  color: ColorIndex;
}
export interface BarGaugeConfig {
  title?: string | null;
  collection: Collection;
  key: string;
  min: number;
  max?: number | null;
  unit: ChartUnit;
  color: ColorIndex;
  thresholds: Threshold[];
  orientation: "horizontal" | "vertical";
  sort: "none" | "asc" | "desc";
  limit: number;
}
export interface TableConfig {
  title?: string | null;
  collection: Collection;
  columns: string[];
  sort_by?: string | null;
  sort_desc: boolean;
  limit: number;
  unit: ChartUnit;
}
export interface StateItemRef {
  kind: "device" | "interface" | "check";
  id: number;
  /** Tylko dla edytora: urządzenie portu */
  device_id?: number | null;
}
export interface StateTimelineConfig {
  title?: string | null;
  /** Pusta lista = wszystkie urządzenia */
  items: StateItemRef[];
  range_min?: RangeMinutes | null;
  refresh_s?: RefreshSeconds | null;
}
/** Co monitoruje wykres kołowy (lista i kolekcje: lib/pie.ts). */
export type PieMetric =
  | "cpu"
  | "mem"
  | "disk"
  | "disks_share"
  | "port_load"
  | "port_dir"
  | "ports_in"
  | "ports_out"
  | "ports_state"
  | "wifi_clients"
  | "containers_mem"
  | "containers_cpu"
  | "services_state"
  | "guests_mem"
  | "guests_state"
  | "devices_state"
  | "checks_state";
/** Wykres kołowy (0.39.0): urządzenie (puste = cała sieć) i to, co na nim monitorować. */
export interface PieConfig {
  title?: string | null;
  device_id?: number | null;
  metric: PieMetric;
  /** Dysk (punkt montowania; puste = pierwszy) albo id portu dla „port_load” / „port_dir” */
  item?: string | null;
  /** Najwięcej kawałków, reszta jako „Pozostałe” */
  limit: number;
}
export type StatWidgetModel = WidgetBase & { type: "stat"; config: StatConfig };
export type PieWidgetModel = WidgetBase & { type: "pie"; config: PieConfig };
export type BarGaugeWidgetModel = WidgetBase & { type: "bargauge"; config: BarGaugeConfig };
export type TableWidgetModel = WidgetBase & { type: "table"; config: TableConfig };
export type StateTimelineWidgetModel = WidgetBase & { type: "state_timeline"; config: StateTimelineConfig };
export type HeatmapWidgetModel = WidgetBase & { type: "heatmap"; config: HeatmapConfig };
/** Nagłówek sekcji: widgety pod nim (do następnej sekcji) można zwinąć. */
export type SectionWidgetModel = WidgetBase & { type: "section"; config: { title: string; collapsed: boolean } };

export type Widget =
  | SummaryWidgetModel
  | ChartWidgetModel
  | DevicesWidgetModel
  | PoeWidgetModel
  | ServerWidgetModel
  | WanStatusWidgetModel
  | WanChartWidgetModel
  | WanSlaWidgetModel
  | WanUsageWidgetModel
  | StatWidgetModel
  | BarGaugeWidgetModel
  | TableWidgetModel
  | StateTimelineWidgetModel
  | SectionWidgetModel
  | HeatmapWidgetModel
  | PieWidgetModel
  | StatusWidgetModel
  | AlertsWidgetModel
  | ChecksWidgetModel
  | EventsWidgetModel
  | VpnWidgetModel;
export type WidgetType = Widget["type"];

export interface DashboardLayout {
  version: 1;
  widgets: Widget[];
}

export interface DashboardResponse {
  layout: DashboardLayout | null;
  updated_at: string | null;
}

// --- metryki ---------------------------------------------------------------------------

/** Klasa jednostki: metryki w jednym wykresie muszą należeć do tej samej klasy (wspólna oś Y). */
export type UnitClass =
  | "rate"
  | "count"
  | "percent"
  | "load"
  | "ms"
  | "temp"
  | "size"
  | "state"
  | "duration"
  | "dbm"
  | "linkrate"
  | "mbps"
  | "days"
  | "hours"
  | "volt"
  | "amp"
  | "watt"
  | "rpm";

export const METRICS: Record<string, { label: TextKey; unitClass: UnitClass }> = {
  in_bps: { label: "metric.in_bps", unitClass: "rate" },
  out_bps: { label: "metric.out_bps", unitClass: "rate" },
  // Szczyt w cyklu (od 0.70.0, porty WAN): najwyższa średnia z ok. 5 s
  ping_ms: { label: "metric.ping_ms", unitClass: "ms" },
  rx_bps: { label: "metric.rx_bps", unitClass: "rate" },
  tx_bps: { label: "metric.tx_bps", unitClass: "rate" },
  in_errors: { label: "metric.in_errors", unitClass: "count" },
  out_errors: { label: "metric.out_errors", unitClass: "count" },
  in_discards: { label: "metric.in_discards", unitClass: "count" },
  out_discards: { label: "metric.out_discards", unitClass: "count" },
  clients: { label: "metric.clients", unitClass: "count" },
  cpu_percent: { label: "metric.cpu_percent", unitClass: "percent" },
  mem_used_percent: { label: "metric.mem_used_percent", unitClass: "percent" },
  load1: { label: "metric.load1", unitClass: "load" },
  poll_ms: { label: "metric.poll_ms", unitClass: "ms" },
  swap_used_percent: { label: "metric.swap_used_percent", unitClass: "percent" },
  disk_used_percent: { label: "metric.disk_used_percent", unitClass: "percent" },
  temp_c: { label: "metric.temp_c", unitClass: "temp" },
  // Czujniki urządzeń SNMP (MikroTik): sprzęt, PoE, SFP
  fan_rpm: { label: "metric.fan_rpm", unitClass: "rpm" },
  channel_util_percent: { label: "metric.channel_util_percent", unitClass: "percent" },
  voltage_v: { label: "metric.voltage_v", unitClass: "volt" },
  current_a: { label: "metric.current_a", unitClass: "amp" },
  power_w: { label: "metric.power_w", unitClass: "watt" },
  poe_power_w: { label: "metric.poe_power_w", unitClass: "watt" },
  poe_voltage_v: { label: "metric.poe_voltage_v", unitClass: "volt" },
  sfp_rx_dbm: { label: "metric.sfp_rx_dbm", unitClass: "dbm" },
  sfp_tx_dbm: { label: "metric.sfp_tx_dbm", unitClass: "dbm" },
  sfp_temp_c: { label: "metric.sfp_temp_c", unitClass: "temp" },
  sfp_voltage_v: { label: "metric.sfp_voltage_v", unitClass: "volt" },
  db_size_bytes: { label: "metric.db_size_bytes", unitClass: "size" },
  core_max_percent: { label: "metric.core_max_percent", unitClass: "percent" },
  core_avg_percent: { label: "metric.core_avg_percent", unitClass: "percent" },
  read_bps: { label: "metric.read_bps", unitClass: "rate" },
  write_bps: { label: "metric.write_bps", unitClass: "rate" },
  container_cpu_percent: { label: "metric.container_cpu_percent", unitClass: "percent" },
  container_mem_bytes: { label: "metric.container_mem_bytes", unitClass: "size" },
  guest_cpu_percent: { label: "metric.guest_cpu_percent", unitClass: "percent" },
  guest_mem_bytes: { label: "metric.guest_mem_bytes", unitClass: "size" },
  // Sprawdzenia dostępności (ping, HTTP, TCP)
  latency_ms: { label: "metric.latency_ms", unitClass: "ms" },
  // Klient VPN (od 0.57.0): jego pobieranie i wysyłanie, połączony 1/0
  down_bps: { label: "metric.down_bps", unitClass: "rate" },
  up_bps: { label: "metric.up_bps", unitClass: "rate" },
  connected: { label: "metric.connected", unitClass: "state" },
  jitter_ms: { label: "metric.jitter_ms", unitClass: "ms" },
  loss_percent: { label: "metric.loss_percent", unitClass: "percent" },
  availability_percent: { label: "metric.availability_percent", unitClass: "percent" },
  cert_days: { label: "metric.cert_days", unitClass: "days" },
  // Wartości kolekcji (paski, tabela)
  up: { label: "metric.up", unitClass: "state" },
  uptime_s: { label: "metric.uptime_s", unitClass: "duration" },
  speed_mbps: { label: "metric.speed_mbps", unitClass: "mbps" },
  used_percent: { label: "metric.used_percent", unitClass: "percent" },
  used_bytes: { label: "metric.used_bytes", unitClass: "size" },
  free_bytes: { label: "metric.free_bytes", unitClass: "size" },
  total_bytes: { label: "metric.total_bytes", unitClass: "size" },
  mem_bytes: { label: "metric.mem_bytes", unitClass: "size" },
  mem_percent: { label: "metric.mem_percent", unitClass: "percent" },
  backup_age_h: { label: "metric.backup_age_h", unitClass: "hours" },
  signal_dbm: { label: "metric.signal_dbm", unitClass: "dbm" },
  rx_rate_kbps: { label: "metric.rx_rate_kbps", unitClass: "linkrate" },
  tx_rate_kbps: { label: "metric.tx_rate_kbps", unitClass: "linkrate" },
  connected_s: { label: "metric.connected_s", unitClass: "duration" },
};

/** Metryki dostępne dla źródła (zgodnie z endpointami metryk i schematem serwera). */
export const SOURCE_METRICS: Record<SourceKind, string[]> = {
  wan: ["in_bps", "out_bps"],
  interface: ["in_bps", "out_bps", "in_errors", "out_errors", "in_discards", "out_discards"],
  device: ["cpu_percent", "mem_used_percent", "load1", "poll_ms"],
  wifi_total: ["clients"],
  wifi_network: ["clients", "rx_bps", "tx_bps"],
  server: ["cpu_percent", "mem_used_percent", "swap_used_percent", "disk_used_percent", "load1", "temp_c", "db_size_bytes"],
  agent_cpu: ["core_max_percent", "core_avg_percent"],
  agent_net: ["rx_bps", "tx_bps"],
  agent_disk: ["read_bps", "write_bps"],
  agent_temp: ["temp_c"],
  agent_container: ["container_cpu_percent", "container_mem_bytes"],
  pve_guest: ["guest_cpu_percent", "guest_mem_bytes", "rx_bps", "tx_bps", "read_bps", "write_bps"],
  snmp_sensor: ["temp_c", "fan_rpm", "voltage_v", "current_a", "power_w", "channel_util_percent"],
  snmp_poe: ["poe_power_w", "poe_voltage_v"],
  snmp_sfp: ["sfp_rx_dbm", "sfp_tx_dbm", "sfp_temp_c", "sfp_voltage_v"],
  wan_latency: ["latency_ms", "loss_percent", "jitter_ms", "availability_percent"], // utrata i jitter – z OPNsense (0.81.0)
  wan_ping: ["latency_ms"],
  speedtest: ["down_bps", "up_bps", "ping_ms"],
  vpn: ["down_bps", "up_bps", "connected"],
  lan_client: ["down_bps", "up_bps"], // urządzenie w sieci za OPNsense (od 0.83.0), klucz = MAC
  check: ["latency_ms", "loss_percent", "jitter_ms", "availability_percent", "cert_days"],
};

export const unitClassOf = (key: string): UnitClass => METRICS[key]?.unitClass ?? "count";

/** Domyślne serie dla źródła: dla przepustowości wejście i wyjście, dla reszty pierwsza metryka.
 * Styl B (0.43.0): pierwsza seria w akcencie (1), druga szara (8). */
export function defaultSeries(kind: SourceKind): SeriesConfig[] {
  switch (kind) {
    case "wan":
    case "interface":
      return [
        { key: "in_bps", color: 1 },
        { key: "out_bps", color: 8 },
      ];
    case "device":
      return [{ key: "cpu_percent", color: 1 }];
    case "wifi_total":
    case "wifi_network":
      return [{ key: "clients", color: 3 }];
    case "server":
      return [
        { key: "cpu_percent", color: 1 },
        { key: "mem_used_percent", color: 8 },
      ];
    case "agent_cpu":
      return [
        { key: "core_max_percent", color: 1 },
        { key: "core_avg_percent", color: 8 },
      ];
    case "agent_net":
      return [
        { key: "rx_bps", color: 1 },
        { key: "tx_bps", color: 8 },
      ];
    case "agent_disk":
      return [
        { key: "read_bps", color: 1 },
        { key: "write_bps", color: 8 },
      ];
    case "agent_temp":
      return [{ key: "temp_c", color: 3 }];
    case "agent_container":
      return [{ key: "container_cpu_percent", color: 1 }];
    case "pve_guest":
      return [{ key: "guest_cpu_percent", color: 1 }];
    case "snmp_sensor":
      return [{ key: "temp_c", color: 3 }];
    case "snmp_poe":
      return [{ key: "poe_power_w", color: 1 }];
    case "snmp_sfp":
      return [
        { key: "sfp_rx_dbm", color: 1 },
        { key: "sfp_tx_dbm", color: 8 },
      ];
    case "check":
    case "wan_latency":
    case "wan_ping":
      return [{ key: "latency_ms", color: 1 }];
    case "vpn":
    case "speedtest":
    case "lan_client":
      return [
        { key: "down_bps", color: 1 },
        { key: "up_bps", color: 8 },
      ];
  }
}

/** Włącza albo wyłącza metrykę w zapytaniu. Nowa seria o innej jednostce niż oś lewa trafia na oś prawą. */
export function toggleMetric(c: ChartConfig, queryId: string, key: string, enabled: boolean): ChartConfig {
  const queries = c.queries.map((q) => {
    if (q.id !== queryId) return q;
    if (!enabled) return { ...q, series: q.series.filter((s) => s.key !== key) };
    if (q.series.some((s) => s.key === key)) return q;
    const left = axisClass(c, "left");
    const axis: Axis = left && left !== unitClassOf(key) ? "right" : "left";
    return { ...q, series: [...q.series, { key, color: freeColor(c), axis }] };
  });
  return { ...c, queries };
}

// --- fabryki widgetów ------------------------------------------------------------------

export function newId(): string {
  return `w${Math.random().toString(36).slice(2, 8)}${Date.now().toString(36).slice(-3)}`;
}

export function newQuery(id: string, source: Source, series: SeriesConfig[] = defaultSeries(source.kind)): ChartQuery {
  return { id, source, series, offset_min: 0 };
}

/** Wykres z jednym źródłem; `series` domyślnie jak dla źródła. */
export function newChartConfig(source: Source = { kind: "wan" }, series?: SeriesConfig[]): ChartConfig {
  return {
    title: null,
    queries: [newQuery("A", source, series)],
    chart: "area",
    stack: false,
    unit: "bits",
    smooth: false,
    axes: { left: { min: null, max: null, label: null }, right: { min: null, max: null, label: null } },
    thresholds: [],
    threshold_style: "line",
    legend: { ...DEFAULT_LEGEND },
    range_min: null,
    refresh_s: null,
    height: "md",
  };
}

export function newWidget(type: WidgetType, id: string = newId()): Widget {
  switch (type) {
    case "summary":
      return { id, type, w: 12, config: { tiles: [...SUMMARY_TILES] } };
    case "chart":
      return { id, type, w: 6, config: newChartConfig() };
    case "devices":
      return { id, type, w: 8, config: { kinds: null, display: "table" } };
    case "status":
      return { id, type, w: 12, config: {} };
    case "alerts":
      return { id, type, w: 4, config: { limit: 5 } };
    case "checks":
      return { id, type, w: 4, config: { days: 30 } };
    case "events":
      return { id, type, w: 4, config: { days: 7, limit: 8 } };
    case "vpn":
      return { id, type, w: 4, config: { title: null, show_offline: true } };
    case "poe":
      return { id, type, w: 12, config: { device_id: null } };
    case "server":
      return { id, type, w: 4, config: {} };
    case "wan_status":
      return { id, type, w: 4, config: { device_id: null } };
    case "wan_chart":
      return { id, type, w: 8, config: { device_id: null, metric: "in_bps", range_min: null, height: "md" } };
    case "wan_sla":
      return { id, type, w: 12, config: { device_id: null, days: 7 } };
    case "wan_usage":
      return { id, type, w: 4, config: { device_id: null, reset_day: 1, limit_gb: null } };
    case "stat":
      return {
        id,
        type,
        w: 3,
        config: { title: null, source: { kind: "wan" }, key: "in_bps", reduce: "last", unit: "bits", sparkline: true, color: 1, color_mode: "value", thresholds: [] },
      };
    case "bargauge":
      return {
        id,
        type,
        w: 6,
        config: {
          title: null,
          collection: { kind: "devices" },
          key: "cpu_percent",
          min: 0,
          max: null,
          unit: "bits",
          color: 1,
          thresholds: [
            { value: 70, color: 4 },
            { value: 90, color: 5 },
          ],
          orientation: "horizontal",
          sort: "none",
          limit: 12,
        },
      };
    case "table":
      return {
        id,
        type,
        w: 6,
        config: { title: null, collection: { kind: "devices" }, columns: ["up", "cpu_percent", "mem_used_percent"], sort_by: null, sort_desc: false, limit: 20, unit: "bits" },
      };
    case "state_timeline":
      return { id, type, w: 12, config: { title: null, items: [] } };
    case "heatmap":
      return { id, type, w: 12, config: { title: null, source: { kind: "wan" }, key: "in_bps", reduce: "avg", group: "weekday", weeks: 4, unit: "bits", color: 1 } };
    case "pie":
      return { id, type, w: 4, config: { title: null, device_id: null, metric: "devices_state", item: null, limit: 8 } };
    case "section":
      return { id, type, w: 12, h: 1, config: { title: "", collapsed: false } };
  }
}

// --- swobodna siatka (od 0.28.0) ---------------------------------------------------------------

const CHART_ROWS: Record<ChartHeight, number> = { sm: 7, md: 8, lg: 10 };

/** Wysokość widgetu bez zapisanej pozycji (pulpity sprzed 0.28.0 i nowe widgety): mniej więcej jak dawniej. */
export function defaultHeight(w: Widget): number {
  switch (w.type) {
    case "section":
      return 1;
    case "summary":
      return 4;
    case "status":
      return 2;
    case "alerts":
    case "events":
      return 10;
    case "vpn":
      return 8;
    case "checks":
      return 11;
    case "devices":
      return w.config.display === "table" ? 11 : 8;
    case "stat":
      return 4;
    case "chart":
      return CHART_ROWS[upgradeChartConfig(w.config).height] ?? 8;
    case "wan_chart":
      return CHART_ROWS[w.config.height] + 2;
    case "wan_status":
    case "wan_sla":
    case "state_timeline":
      return 6;
    case "wan_usage":
      return 7;
    case "heatmap":
      return 7;
    case "bargauge":
      return 6;
    case "pie":
      return 7;
    default:
      return 8;
  }
}

const placed = (w: Widget) => w.x != null && w.y != null;
const bottomOf = (widgets: Widget[]) => widgets.reduce((max, w) => Math.max(max, (w.y ?? 0) + (w.h ?? defaultHeight(w))), 0);

/** Uzupełnia pozycje: widgety bez pozycji układa po kolei od lewej (jak dawny układ kolumnowy), pod tymi z pozycją. */
export function placeWidgets(widgets: Widget[]): Widget[] {
  let x = 0;
  let y = bottomOf(widgets.filter(placed));
  let rowH = 0;
  return widgets.map((w) => {
    const width = Math.min(GRID_COLS, Math.max(1, w.w));
    const h = w.h ?? defaultHeight(w);
    if (placed(w)) return { ...w, w: width, h };
    if (x + width > GRID_COLS) {
      y += rowH;
      x = 0;
      rowH = 0;
    }
    const out = { ...w, w: width, x, y, h };
    x += width;
    rowH = Math.max(rowH, h);
    return out;
  });
}

/** Widgety w kolejności czytania: z góry na dół, w wierszu od lewej (telefon, czytnik ekranu). */
export function readingOrder(widgets: Widget[]): Widget[] {
  return [...widgets].sort((a, b) => (a.y ?? 0) - (b.y ?? 0) || (a.x ?? 0) - (b.x ?? 0));
}

/** Widgety ukryte przez zwinięte sekcje: wszystko pod nagłówkiem sekcji, do następnego nagłówka. */
export function hiddenBySections(widgets: Widget[], collapsed: Set<string>): Set<string> {
  const hidden = new Set<string>();
  let current: string | null = null;
  for (const w of readingOrder(widgets)) {
    if (w.type === "section") current = w.id;
    else if (current && collapsed.has(current)) hidden.add(w.id);
  }
  return hidden;
}

/** Przesunięcie (dx, dy) albo zmiana rozmiaru (dw, dh) widgetu z klawiatury – w granicach siatki. */
export function nudgeWidget(l: DashboardLayout, id: string, d: { dx?: number; dy?: number; dw?: number; dh?: number }): DashboardLayout {
  const widgets = placeWidgets(l.widgets).map((w) => {
    if (w.id !== id) return w;
    const width = Math.min(GRID_COLS, Math.max(1, w.w + (d.dw ?? 0)));
    const h = Math.min(MAX_HEIGHT, Math.max(1, (w.h ?? 1) + (d.dh ?? 0)));
    const x = Math.min(GRID_COLS - width, Math.max(0, (w.x ?? 0) + (d.dx ?? 0)));
    const y = Math.max(0, (w.y ?? 0) + (d.dy ?? 0));
    return { ...w, w: w.type === "section" ? GRID_COLS : width, h: w.type === "section" ? 1 : h, x: w.type === "section" ? 0 : x, y };
  });
  return { ...l, widgets };
}

/** Zamiana miejscami z poprzednim (-1) albo następnym (1) widgetem w kolejności czytania – przestawianie na telefonie
 * i tablecie, gdzie nie ma przeciągania. Na komputerze nakładające się widgety rozsuwa siatka. */
export function swapInReadingOrder(l: DashboardLayout, id: string, dir: -1 | 1): DashboardLayout {
  const all = placeWidgets(l.widgets);
  const order = readingOrder(all);
  const i = order.findIndex((w) => w.id === id);
  const other = order[i + dir];
  if (i < 0 || !other) return l;
  const a = order[i];
  const at = (w: Widget, to: Widget): Widget => ({ ...w, x: w.type === "section" ? 0 : Math.min(GRID_COLS - w.w, to.x ?? 0), y: to.y });
  // Ten sam wiersz – zamiana kolumn; inaczej przesunięty w górę ląduje w wierszu sąsiada przed nim
  const moved = new Map<string, Widget>([
    [a.id, at(a, other)],
    [other.id, at(other, a)],
  ]);
  if (a.y === other.y) {
    const [left, right] = dir < 0 ? [other, a] : [a, other];
    const x = left.x ?? 0;
    moved.set(right.id, { ...right, x });
    moved.set(left.id, { ...left, x: Math.min(GRID_COLS - left.w, x + right.w) });
  }
  return { ...l, widgets: all.map((w) => moved.get(w.id) ?? w) };
}

/** Widgety z listą (od 0.56.0): ich treść rośnie z danymi (porty, zdarzenia, alerty), więc w podglądzie karta
 * wydłuża się, gdy treść się nie mieści, zamiast pokazywać pasek przewijania. Wykresy i liczby skalują się do karty. */
export const AUTO_HEIGHT = new Set<Widget["type"]>([
  "table", "bargauge", "poe", "state_timeline", "alerts", "events", "checks", "wan_status", "wan_sla", "wan_usage", "devices", "server", "status", "vpn",
]);

/** Ile wierszy siatki potrzeba, żeby zmieścić `px` treści (odwrotność `rowsToPx`; do 2 px zapasu na zaokrąglenia).
 * Liczone z pełnej wysokości treści, a nie z tego, o ile wystaje – siatka animuje zmianę wysokości, więc w trakcie
 * animacji treść „wystaje” dalej i dodawanie wierszy przy każdym pomiarze dawało za wysokie karty. */
export function rowsFor(px: number): number {
  return Math.max(1, Math.ceil((px - 2 + GRID_MARGIN) / (ROW_HEIGHT + GRID_MARGIN)));
}

export interface GridBox {
  i: string;
  x: number;
  y: number;
  w: number;
  h: number;
}

/** Usuwa nakładanie się po wydłużeniu kart: od góry, każdy widget, który zachodzi na już ułożony, schodzi tuż pod
 * niego (tylko w dół – nic nie podjeżdża do góry, więc układ z pulpitu zostaje, przesuwa się tylko to, co pod spodem). */
export function pushDown<T extends GridBox>(items: T[]): T[] {
  const placed: T[] = [];
  for (const it of [...items].sort((a, b) => a.y - b.y || a.x - b.x)) {
    let y = it.y;
    for (;;) {
      const hit = placed.find((p) => p.x < it.x + it.w && it.x < p.x + p.w && p.y < y + it.h && y < p.y + p.h);
      if (!hit) break;
      y = hit.y + hit.h;
    }
    placed.push({ ...it, y });
  }
  const byId = new Map(placed.map((p) => [p.i, p]));
  return items.map((it) => byId.get(it.i)!);
}

/** Pozycje z siatki po przeciągnięciu albo rozciągnięciu myszką. */
export function applyPositions(l: DashboardLayout, items: { i: string; x: number; y: number; w: number; h: number }[]): DashboardLayout {
  const byId = new Map(items.map((it) => [it.i, it]));
  return {
    ...l,
    widgets: placeWidgets(l.widgets).map((w) => {
      const it = byId.get(w.id);
      return it ? { ...w, x: it.x, y: it.y, w: it.w, h: it.h } : w;
    }),
  };
}

/** Układ domyślny (od 0.42.0, wariant A): stan sieci, liczby, ruch WAN z alertami, urządzenia z dostępnością. */
export const DEFAULT_LAYOUT: DashboardLayout = {
  version: 1,
  widgets: [
    { id: "stan-sieci", type: "status", w: 12, config: {} },
    { id: "podsumowanie", type: "summary", w: 12, config: { tiles: [...SUMMARY_TILES] } },
    {
      id: "ruch-wan",
      type: "chart",
      w: 8,
      config: newChartConfig({ kind: "wan" }),
    },
    { id: "alerty", type: "alerts", w: 4, config: { limit: 5 } },
    { id: "urzadzenia", type: "devices", w: 8, config: { kinds: null, display: "table" } },
    { id: "dostepnosc", type: "checks", w: 4, config: { days: 30 } },
  ],
};

// --- operacje edytora (zwracają nowy układ, niczego nie mutują) ------------------------

const indexOf = (l: DashboardLayout, id: string) => l.widgets.findIndex((w) => w.id === id);

/** Przenosi widget na pozycję `to` (0 = pierwszy). */
export function moveWidget(l: DashboardLayout, id: string, to: number): DashboardLayout {
  const from = indexOf(l, id);
  if (from < 0) return l;
  const clamped = Math.max(0, Math.min(l.widgets.length - 1, to));
  if (clamped === from) return l;
  const widgets = [...l.widgets];
  const [item] = widgets.splice(from, 1);
  widgets.splice(clamped, 0, item);
  return { ...l, widgets };
}

/** Przesuwa o jedno miejsce wcześniej (-1) albo później (+1). */
export function shiftWidget(l: DashboardLayout, id: string, delta: -1 | 1): DashboardLayout {
  const from = indexOf(l, id);
  return from < 0 ? l : moveWidget(l, id, from + delta);
}

/** Upuszczenie widgetu `id` na widget `targetId`: trafia na jego miejsce (przesuwając resztę). */
export function dropOn(l: DashboardLayout, id: string, targetId: string): DashboardLayout {
  const to = indexOf(l, targetId);
  return to < 0 || id === targetId ? l : moveWidget(l, id, to);
}

export function resizeWidget(l: DashboardLayout, id: string, w: GridWidth): DashboardLayout {
  return { ...l, widgets: l.widgets.map((x) => (x.id === id ? { ...x, w } : x)) };
}

export function removeWidget(l: DashboardLayout, id: string): DashboardLayout {
  return { ...l, widgets: l.widgets.filter((x) => x.id !== id) };
}

/** Nowy widget trafia na dół pulpitu, od lewej. */
/** Nowy widget trafia na górę pulpitu (od 0.43.4) – widać go od razu, bez szukania na końcu długiego pulpitu.
 * Przy zapisanych pozycjach reszta zjeżdża w dół o jego wysokość. */
export function addWidget(l: DashboardLayout, widget: Widget): DashboardLayout {
  if (l.widgets.length >= MAX_WIDGETS) return l;
  if (!l.widgets.some(placed)) return { ...l, widgets: [widget, ...l.widgets] };
  const h = widget.h ?? defaultHeight(widget);
  const shifted = placeWidgets(l.widgets).map((w) => ({ ...w, y: (w.y ?? 0) + h }));
  return { ...l, widgets: [{ ...widget, x: 0, y: 0, h }, ...shifted] };
}

/** Kilka widgetów naraz (szablony, cała sekcja urządzenia – 0.44.0): ułożone ciasno w bloku na górze pulpitu,
 * każdy możliwie wysoko; reszta zjeżdża w dół o wysokość bloku. Sekcja zaczyna nowy pas. */
export function addWidgets(l: DashboardLayout, added: Widget[]): DashboardLayout {
  const room = MAX_WIDGETS - l.widgets.length;
  const list = added.slice(0, Math.max(0, room));
  if (list.length === 0) return l;
  if (!l.widgets.some(placed)) return { ...l, widgets: [...list, ...l.widgets] };
  const heights = Array<number>(GRID_COLS).fill(0);
  const block = list.map((w) => {
    const width = Math.min(GRID_COLS, Math.max(1, w.w));
    const h = w.h ?? defaultHeight(w);
    let x = 0;
    let y = Math.max(...heights);
    if (w.type !== "section") {
      for (let c = 0; c + width <= GRID_COLS; c++) {
        const top = Math.max(...heights.slice(c, c + width));
        if (top < y) [x, y] = [c, top];
      }
    }
    for (let c = x; c < x + width; c++) heights[c] = y + h;
    return { ...w, w: width, x, y, h };
  });
  const blockH = Math.max(...heights);
  const shifted = placeWidgets(l.widgets).map((w) => ({ ...w, y: (w.y ?? 0) + blockH }));
  return { ...l, widgets: [...block, ...shifted] };
}

/** Podmienia widget o tym samym id (np. po edycji konfiguracji). */
export function replaceWidget(l: DashboardLayout, widget: Widget): DashboardLayout {
  return { ...l, widgets: l.widgets.map((x) => (x.id === widget.id ? widget : x)) };
}

export function sameLayout(a: DashboardLayout, b: DashboardLayout): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

// --- przeliczanie osi i progów: wartość w jednostce widocznej dla użytkownika ↔ surowa z API ---

/** Surowa metryka przepustowości jest w bitach/s: wyświetlamy Mb/s albo MB/s. Rozmiar (bajty) – w GB. */
const MB = 1_000_000;
const GB = 1_000_000_000;

export function valueToRaw(display: number, cls: UnitClass | null, unit: ChartUnit): number {
  if (cls === "rate") return unit === "bytes" ? display * MB * 8 : display * MB;
  if (cls === "size") return display * GB;
  return display;
}

export function valueFromRaw(raw: number, cls: UnitClass | null, unit: ChartUnit): number {
  if (cls === "rate") return unit === "bytes" ? raw / (MB * 8) : raw / MB;
  if (cls === "size") return raw / GB;
  return raw;
}
