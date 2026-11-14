/**
 * Szablony widgetów (od 0.44.0): gotowe widgety, które pytają tylko o urządzenie, port albo sprawdzenie.
 * Okno „Dodaj widget” pokazuje je według rodzaju albo według urządzenia; pełny edytor zostaje pod „Własny”.
 * Każdy szablon buduje zwykły widget z `layout.ts` – zapisuje się tak samo jak zrobiony w edytorze.
 */
import { t, type TextKey } from "../i18n";
import type { Device } from "./api";
import type { InterfaceItem, WifiItem } from "./details";
import { newChartConfig, newId, newWidget, type ColorIndex, type Widget } from "./layout";
import type { ModuleId } from "./modules";

export type TemplateGroup = "overview" | "internet" | "device" | "port" | "wifi" | "server" | "checks";
export const TEMPLATE_GROUPS: TemplateGroup[] = ["overview", "internet", "device", "port", "wifi", "server", "checks"];

/** O co pyta szablon przed dodaniem. */
export type Ask = "device" | "port" | "check";
/** Opcje do włączenia w kroku pytań. */
export type TemplateOption = "limitLine" | "compare";
/** Kształt miniatury w oknie (`WidgetThumb`). */
export type ThumbKind = "line" | "lineth" | "bars" | "table" | "gauge" | "heat" | "stat" | "status" | "list" | "timeline" | "poe";

export interface TemplateCtx {
  device?: Device | null;
  port?: InterfaceItem | null;
  /** Porty urządzenia (oś stanów portów) */
  ports?: InterfaceItem[];
  /** Sieci WiFi access pointa (klienci według sieci) */
  networks?: WifiItem[];
  check?: { id: number; name: string } | null;
  options?: Partial<Record<TemplateOption, boolean>>;
  /** Szerokość w kolumnach siatki (z 12); puste = domyślna szablonu */
  w?: number;
  title?: string | null;
}

export interface WidgetTemplate {
  id: string;
  group: TemplateGroup;
  thumb: ThumbKind;
  asks: Ask[];
  /** Jakie urządzenia pasują (gdy pyta o urządzenie) */
  fits?: (d: Device) => boolean;
  options?: TemplateOption[];
  /** Szerokości do wyboru; pierwsza – domyślna */
  sizes: number[];
  /** Wchodzi do „całej sekcji” urządzenia (nie pyta o nic poza urządzeniem) */
  section?: boolean;
  recommended?: boolean;
  module?: ModuleId;
  build: (ctx: TemplateCtx) => Widget;
}

export const templateLabel = (tpl: WidgetTemplate) => `tpl.${tpl.id}` as TextKey;
export const templateDesc = (tpl: WidgetTemplate) => `tpl.${tpl.id}.desc` as TextKey;

const MS = 1;
const network = (d: Device) => d.kind === "gateway" || d.kind === "switch";
const agent = (d: Device) => d.driver === "agent";
const sized = <T extends Widget>(w: T, ctx: TemplateCtx, fallback: number): T => ({ ...w, w: ctx.w ?? fallback });
const titled = (ctx: TemplateCtx, auto: string | null) => (ctx.title?.trim() ? ctx.title.trim() : auto);

function chart(ctx: TemplateCtx, w: number, config: Parameters<typeof newChartConfig>, patch: Partial<ReturnType<typeof newChartConfig>> = {}): Widget {
  return { id: newId(), type: "chart", w: ctx.w ?? w, config: { ...newChartConfig(...config), ...patch } };
}

function gauge(ctx: TemplateCtx, key: "cpu_percent" | "mem_used_percent", title: string): Widget {
  const device = ctx.device!;
  return {
    id: newId(),
    type: "stat",
    w: ctx.w ?? 3,
    config: {
      title: titled(ctx, t("tplt.metric", { metric: title, name: device.name })),
      source: { kind: "device", id: device.id },
      key,
      reduce: "last",
      unit: "bits",
      sparkline: false,
      color: 1,
      color_mode: "value",
      thresholds: [
        { value: 75, color: 4 },
        { value: 90, color: 5 },
      ],
      display: "gauge",
      max: 100,
      show_change: true,
    },
  };
}

const portName = (p: InterfaceItem) => p.alias || p.label || p.name;

export const WIDGET_TEMPLATES: WidgetTemplate[] = [
  // --- przegląd ---
  { id: "status", group: "overview", thumb: "status", asks: [], sizes: [12], recommended: true, build: (ctx) => sized(newWidget("status"), ctx, 12) },
  { id: "summary", group: "overview", thumb: "stat", asks: [], sizes: [12], build: (ctx) => sized(newWidget("summary"), ctx, 12) },
  { id: "alerts", group: "overview", thumb: "list", asks: [], sizes: [4, 6], build: (ctx) => sized(newWidget("alerts"), ctx, 4) },
  { id: "events", group: "overview", thumb: "list", asks: [], sizes: [4, 6], build: (ctx) => sized(newWidget("events"), ctx, 4) },
  {
    id: "devices_table",
    group: "overview",
    thumb: "table",
    asks: [],
    sizes: [12, 8],
    build: (ctx) => ({ id: newId(), type: "devices", w: ctx.w ?? 12, config: { kinds: null, display: "table" } }),
  },

  // --- Internet i WAN ---
  {
    id: "wan_traffic",
    group: "internet",
    thumb: "line",
    asks: [],
    options: ["compare"],
    sizes: [8, 12, 6],
    recommended: true,
    build: (ctx) => {
      // Linia = średnia z kubełka, najwyższa prędkość w kubełku jest w dymku (od 0.71.0, jak w UniFi) – bez osobnej serii
      const w = chart(ctx, 8, [{ kind: "wan" }], { title: titled(ctx, null), legend: { mode: "table", placement: "bottom", values: ["last", "max", "avg"] } });
      if (w.type === "chart" && ctx.options?.compare) {
        w.config.queries.push({ id: "B", source: { kind: "wan" }, series: [{ key: "in_bps", color: 8 }], offset_min: 1440 });
      }
      return w;
    },
  },
  {
    // Testy prędkości bramy UniFi (od 0.70.0): wyniki dokładnie z bramy, słupek w chwili każdego testu
    id: "speedtest",
    group: "internet",
    thumb: "bars",
    asks: ["device", "port"],
    fits: (d) => d.kind === "gateway",
    sizes: [6, 8, 12],
    module: "unifi",
    build: (ctx) =>
      chart(ctx, 6, [{ kind: "speedtest", id: ctx.device!.id, key: ctx.port!.name }], {
        title: titled(ctx, t("tplt.speedtest", { name: portName(ctx.port!) })),
        chart: "bar",
        range_min: 10080,
        legend: { mode: "table", placement: "bottom", values: ["last", "max", "avg"] },
      }),
  },
  { id: "wan_status", group: "internet", thumb: "status", asks: [], sizes: [4, 6], build: (ctx) => sized(newWidget("wan_status"), ctx, 4) },
  { id: "vpn", group: "internet", thumb: "list", asks: [], sizes: [4, 6], module: "unifi", build: (ctx) => sized(newWidget("vpn"), ctx, 4) },
  { id: "wan_usage", group: "internet", thumb: "stat", asks: [], sizes: [4, 6, 12], recommended: true, build: (ctx) => sized(newWidget("wan_usage"), ctx, 4) },
  { id: "wan_sla", group: "internet", thumb: "stat", asks: [], sizes: [4, 6, 12], build: (ctx) => sized(newWidget("wan_sla"), ctx, 4) },
  {
    id: "check_latency",
    group: "internet",
    thumb: "lineth",
    asks: ["check"],
    options: ["compare"],
    sizes: [6, 4, 12],
    build: (ctx) => {
      const check = ctx.check!;
      const w = chart(ctx, 6, [{ kind: "check", id: check.id }, [{ key: "latency_ms", color: 1 }]], {
        chart: "line",
        title: titled(ctx, t("tplt.latency", { name: check.name })),
        thresholds: [{ value: 50 * MS, color: 4 }],
      });
      if (w.type === "chart" && ctx.options?.compare) {
        w.config.queries.push({ id: "B", source: { kind: "check", id: check.id }, series: [{ key: "latency_ms", color: 8 }], offset_min: 1440 });
      }
      return w;
    },
  },
  {
    id: "check_quality",
    group: "internet",
    thumb: "lineth",
    asks: ["check"],
    sizes: [6, 4, 12],
    build: (ctx) =>
      chart(
        ctx,
        6,
        [
          { kind: "check", id: ctx.check!.id },
          [
            { key: "loss_percent", color: 5 },
            { key: "jitter_ms", color: 3, axis: "right" },
          ],
        ],
        { chart: "line", title: titled(ctx, t("tplt.quality", { name: ctx.check!.name })) },
      ),
  },

  // --- urządzenie ---
  {
    id: "device_cpu_ram",
    group: "device",
    thumb: "line",
    asks: ["device"],
    sizes: [6, 4, 12],
    section: true,
    recommended: true,
    build: (ctx) =>
      chart(
        ctx,
        6,
        [
          { kind: "device", id: ctx.device!.id },
          [
            { key: "cpu_percent", color: 1 },
            { key: "mem_used_percent", color: 8 },
          ],
        ],
        { chart: "line", title: titled(ctx, t("tplt.cpuRam", { name: ctx.device!.name })), axes: { left: { min: 0, max: 100, label: null }, right: { min: null, max: null, label: null } } },
      ),
  },
  { id: "device_cpu", group: "device", thumb: "gauge", asks: ["device"], sizes: [3, 4], section: true, build: (ctx) => gauge(ctx, "cpu_percent", "CPU") },
  { id: "device_ram", group: "device", thumb: "gauge", asks: ["device"], sizes: [3, 4], section: true, build: (ctx) => gauge(ctx, "mem_used_percent", "RAM") },
  {
    id: "device_poll",
    group: "device",
    thumb: "line",
    asks: ["device"],
    sizes: [6, 4, 12],
    build: (ctx) => chart(ctx, 6, [{ kind: "device", id: ctx.device!.id }, [{ key: "poll_ms", color: 1 }]], { chart: "line", title: titled(ctx, t("tplt.poll", { name: ctx.device!.name })) }),
  },

  // --- port ---
  {
    id: "port_traffic",
    group: "port",
    thumb: "line",
    asks: ["device", "port"],
    fits: network,
    options: ["limitLine", "compare"],
    sizes: [6, 8, 12],
    recommended: true,
    build: (ctx) => {
      const port = ctx.port!;
      const w = chart(ctx, 6, [{ kind: "interface", id: port.id, device_id: ctx.device?.id ?? null }], { title: titled(ctx, `${portName(port)} – ${ctx.device?.name ?? ""}`.trim()) });
      if (w.type !== "chart") return w;
      if (ctx.options?.limitLine && port.speed_mbps) w.config.thresholds = [{ value: port.speed_mbps * 1_000_000, color: 4 }];
      if (ctx.options?.compare) {
        w.config.queries.push({ id: "B", source: { kind: "interface", id: port.id, device_id: ctx.device?.id ?? null }, series: [{ key: "in_bps", color: 8 }], offset_min: 1440 });
      }
      return w;
    },
  },
  {
    id: "port_errors",
    group: "port",
    thumb: "lineth",
    asks: ["device", "port"],
    fits: network,
    sizes: [6, 12],
    build: (ctx) => {
      const port = ctx.port!;
      const colors: ColorIndex[] = [5, 4, 6, 3];
      return chart(
        ctx,
        6,
        [{ kind: "interface", id: port.id, device_id: ctx.device?.id ?? null }, ["in_errors", "out_errors", "in_discards", "out_discards"].map((key, i) => ({ key, color: colors[i] }))],
        { chart: "bar", stack: true, title: titled(ctx, t("tplt.errors", { name: portName(port) })) },
      );
    },
  },
  {
    id: "ports_table",
    group: "port",
    thumb: "table",
    asks: ["device"],
    fits: network,
    sizes: [6, 8, 12],
    section: true,
    build: (ctx) => ({
      id: newId(),
      type: "table",
      w: ctx.w ?? 6,
      config: {
        title: titled(ctx, t("tplt.ports", { name: ctx.device!.name })),
        collection: { kind: "ports", device_id: ctx.device!.id },
        columns: ["up", "in_bps", "out_bps", "speed_mbps"],
        sort_by: "in_bps",
        sort_desc: true,
        limit: 20,
        unit: "bits",
      },
    }),
  },
  {
    id: "ports_top",
    group: "port",
    thumb: "bars",
    asks: ["device"],
    fits: network,
    sizes: [4, 6],
    section: true,
    build: (ctx) => ({
      id: newId(),
      type: "bargauge",
      w: ctx.w ?? 4,
      config: {
        title: titled(ctx, t("tplt.portsTop", { name: ctx.device!.name })),
        collection: { kind: "ports", device_id: ctx.device!.id },
        key: "in_bps",
        min: 0,
        max: null,
        unit: "bits",
        color: 1,
        thresholds: [],
        orientation: "horizontal",
        sort: "desc",
        limit: 8,
      },
    }),
  },
  {
    id: "poe",
    group: "port",
    thumb: "poe",
    asks: ["device"],
    fits: (d) => d.kind === "switch",
    sizes: [4, 6],
    section: true,
    module: "unifi",
    build: (ctx) => ({ id: newId(), type: "poe", w: ctx.w ?? 4, config: { device_id: ctx.device!.id } }),
  },
  {
    id: "ports_timeline",
    group: "port",
    thumb: "timeline",
    asks: ["device"],
    fits: network,
    sizes: [12, 8],
    build: (ctx) => ({
      id: newId(),
      type: "state_timeline",
      w: ctx.w ?? 12,
      config: {
        title: titled(ctx, t("tplt.portsTimeline", { name: ctx.device!.name })),
        items: (ctx.ports ?? []).filter((p) => !p.hidden).slice(0, 12).map((p) => ({ kind: "interface" as const, id: p.id, device_id: ctx.device!.id })),
      },
    }),
  },

  // --- WiFi ---
  {
    id: "wifi_total",
    group: "wifi",
    thumb: "line",
    asks: [],
    sizes: [6, 4, 12],
    build: (ctx) => chart(ctx, 6, [{ kind: "wifi_total" }], { title: titled(ctx, null) }),
  },
  {
    id: "wifi_networks",
    group: "wifi",
    thumb: "bars",
    asks: ["device"],
    fits: (d) => d.kind === "ap",
    sizes: [6, 12],
    section: true,
    build: (ctx) => {
      const nets = (ctx.networks ?? []).filter((n) => !n.hidden).slice(0, 6);
      const w = chart(ctx, 6, [{ kind: "wifi_total" }], { chart: "bar", stack: true, title: titled(ctx, t("tplt.wifiNets", { name: ctx.device!.name })) });
      if (w.type === "chart" && nets.length) {
        w.config.queries = nets.map((n, i) => ({
          id: "ABCDEF"[i],
          source: { kind: "wifi_network" as const, id: n.id, device_id: ctx.device!.id },
          series: [{ key: "clients", color: (i + 1) as ColorIndex, label: `${n.ssid}${n.radio ? ` (${n.radio})` : ""}` }],
          offset_min: 0 as const,
        }));
      }
      return w;
    },
  },
  {
    id: "wifi_bars",
    group: "wifi",
    thumb: "bars",
    asks: ["device"],
    fits: (d) => d.kind === "ap",
    sizes: [4, 6],
    section: true,
    build: (ctx) => ({
      id: newId(),
      type: "bargauge",
      w: ctx.w ?? 4,
      config: { title: titled(ctx, t("tplt.wifiBars", { name: ctx.device!.name })), collection: { kind: "wifi", device_id: ctx.device!.id }, key: "clients", min: 0, max: null, unit: "bits", color: 1, thresholds: [], orientation: "horizontal", sort: "desc", limit: 8 },
    }),
  },
  {
    id: "wifi_clients",
    group: "wifi",
    thumb: "table",
    asks: [],
    sizes: [6, 12],
    module: "unifi",
    build: (ctx) => ({
      id: newId(),
      type: "table",
      w: ctx.w ?? 6,
      config: { title: titled(ctx, null), collection: { kind: "clients" }, columns: ["signal_dbm", "rx_rate_kbps", "tx_rate_kbps", "connected_s"], sort_by: "signal_dbm", sort_desc: true, limit: 20, unit: "bits" },
    }),
  },

  // --- serwer ---
  { id: "server_card", group: "server", thumb: "list", asks: [], sizes: [4, 6], build: (ctx) => sized(newWidget("server"), ctx, 4) },
  {
    id: "disks",
    group: "server",
    thumb: "bars",
    asks: ["device"],
    fits: (d) => d.kind === "server",
    sizes: [6, 4, 12],
    section: true,
    build: (ctx) => ({
      id: newId(),
      type: "bargauge",
      w: ctx.w ?? 6,
      config: {
        title: titled(ctx, t("tplt.disks", { name: ctx.device!.name })),
        collection: { kind: "disks", device_id: ctx.device!.id },
        key: "used_percent",
        min: 0,
        max: 100,
        unit: "bits",
        color: 1,
        thresholds: [
          { value: 80, color: 4 },
          { value: 90, color: 5 },
        ],
        orientation: "horizontal",
        sort: "desc",
        limit: 8,
      },
    }),
  },
  {
    id: "containers",
    group: "server",
    thumb: "table",
    asks: ["device"],
    fits: agent,
    sizes: [6, 12],
    section: true,
    module: "agents",
    build: (ctx) => ({
      id: newId(),
      type: "table",
      w: ctx.w ?? 6,
      config: { title: titled(ctx, t("tplt.containers", { name: ctx.device!.name })), collection: { kind: "containers", device_id: ctx.device!.id }, columns: ["up", "cpu_percent", "mem_bytes"], sort_by: "cpu_percent", sort_desc: true, limit: 20, unit: "bits" },
    }),
  },

  // --- dostępność ---
  { id: "checks", group: "checks", thumb: "heat", asks: [], sizes: [4, 6], recommended: true, build: (ctx) => sized(newWidget("checks"), ctx, 4) },
  {
    id: "devices_timeline",
    group: "checks",
    thumb: "timeline",
    asks: [],
    sizes: [12, 8],
    build: (ctx) => ({ id: newId(), type: "state_timeline", w: ctx.w ?? 12, config: { title: titled(ctx, null), items: [] } }),
  },
];

/** Czy szablon pyta o coś (albo ma opcje) – inaczej dodaje się od razu. */
export const needsSetup = (tpl: WidgetTemplate) => tpl.asks.length > 0 || (tpl.options?.length ?? 0) > 0 || tpl.sizes.length > 1;

/** Szablony pasujące do urządzenia (zakładka „Według urządzenia”). */
export function templatesForDevice(device: Device, modulesOn: (m?: ModuleId) => boolean = () => true): WidgetTemplate[] {
  return WIDGET_TEMPLATES.filter((tpl) => tpl.asks.includes("device") && (!tpl.fits || tpl.fits(device)) && modulesOn(tpl.module));
}

/** Szukanie bez wielkości liter i polskich znaków („porty” znajdzie „Porty switcha”). */
export const normalize = (s: string) =>
  s
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/ł/g, "l");

/** Cała sekcja urządzenia: nagłówek i widgety szablonów z `section` (tylko te, które nie pytają o port). */
export function deviceSection(device: Device, ctx: Omit<TemplateCtx, "device">, modulesOn?: (m?: ModuleId) => boolean): Widget[] {
  const header: Widget = { id: newId(), type: "section", w: 12, h: 1, config: { title: device.name, collapsed: false } };
  const body = templatesForDevice(device, modulesOn)
    .filter((tpl) => tpl.section && !tpl.asks.includes("port"))
    .map((tpl) => tpl.build({ ...ctx, device }));
  return [header, ...body];
}
