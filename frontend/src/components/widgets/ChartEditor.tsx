/** Edytor wykresu w czasie (od 0.26.0): zapytania (źródła i serie), wygląd, legenda, osie, progi i czas – z podglądem na żywo. */
import { IconCopy, IconPlus, IconTrash } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { t, type TextKey } from "../../i18n";
import { get, type Device } from "../../lib/api";
import { CHECKS_KEY, type Check } from "../../lib/checks";
import { WAN_LINKS_KEY, type WanLink } from "../../lib/wan";
import { formatRange } from "../../lib/format";
import {
  COLOR_INDEXES,
  DEFAULT_LEGEND,
  LEGEND_VALUES,
  MAX_QUERIES,
  MAX_SERIES,
  METRICS,
  OFFSET_OPTIONS,
  SOURCE_KINDS,
  SOURCE_METRICS,
  allSeries,
  axisClass,
  defaultSeries,
  freeColor,
  isAgentSource,
  isSnmpSensorSource,
  isSpeedtestSource,
  isWanPingSource,
  WAN_PING_SEP,
  newQuery,
  nextQueryId,
  toggleMetric,
  upgradeChartConfig,
  valueFromRaw,
  valueToRaw,
  type AgentSourceKind,
  type Axis,
  type ChartConfig,
  type ChartKind,
  type ChartQuery,
  type ChartUnit,
  type ColorIndex,
  type LegacyChartConfig,
  type LegendMode,
  type LegendValue,
  type OffsetMinutes,
  type SeriesConfig,
  type Source,
  type SourceKind,
  type ThresholdStyle,
  type UnitClass,
} from "../../lib/layout";
import { isOn, sourceModule, useModules } from "../../lib/modules";
import { useDevices } from "../../lib/queries";
import { RANGE_OPTIONS, REFRESH_OPTIONS, type RangeMinutes, type RefreshSeconds } from "../../lib/refresh";
import { seriesName } from "../charts/panelData";
import { Dialog } from "../Dialog";
import { refreshLabel } from "../RefreshControl";
import { Button, Field, Select } from "../ui";
import { ChartWidget } from "./ChartWidget";
import { hostLabel, useOpnsenseDevice } from "../../lib/opnsense";

interface InterfaceItem {
  id: number;
  label: string;
  alias: string | null;
}
interface WifiItem {
  id: number;
  ssid: string;
  radio: string | null;
}

export const SOURCE_LABEL: Record<SourceKind, TextKey> = {
  wan: "ce.source.wan",
  interface: "ce.source.interface",
  device: "ce.source.device",
  wifi_total: "ce.source.wifi_total",
  wifi_network: "ce.source.wifi_network",
  server: "ce.source.server",
  check: "ce.source.check",
  agent_cpu: "ce.source.agent_cpu",
  agent_net: "ce.source.agent_net",
  agent_disk: "ce.source.agent_disk",
  agent_temp: "ce.source.agent_temp",
  agent_container: "ce.source.agent_container",
  pve_guest: "ce.source.pve_guest",
  snmp_sensor: "ce.source.snmp_sensor",
  snmp_poe: "ce.source.snmp_poe",
  snmp_sfp: "ce.source.snmp_sfp",
  wan_latency: "ce.source.wan_latency",
  wan_ping: "ce.source.wan_ping",
  speedtest: "ce.source.speedtest",
  vpn: "ce.source.vpn",
  lan_client: "ce.source.lan_client",
};
/** Lista do wyboru w edytorze dla źródła z tabeli `metrics` (odpowiedź /api/devices/{id}/agent-keys). */
type AgentKeys = Record<Exclude<AgentSourceKind, "agent_cpu">, string[]>;
const AGENT_KEY_LABEL: Record<keyof AgentKeys, TextKey> = {
  agent_net: "ce.agent.key.net",
  agent_disk: "ce.agent.key.disk",
  agent_temp: "ce.agent.key.temp",
  agent_container: "ce.agent.key.container",
  pve_guest: "ce.agent.key.guest",
  snmp_sensor: "ce.agent.key.sensor",
  snmp_poe: "ce.agent.key.port",
  snmp_sfp: "ce.agent.key.port",
  wan_latency: "ce.agent.key.wan",
  wan_ping: "ce.agent.key.wanTarget",
  speedtest: "ce.agent.key.wan",
  vpn: "ce.agent.key.vpn",
  lan_client: "ce.agent.key.lan_client",
};
const KIND_OPTIONS: ChartKind[] = ["area", "line", "bar"];
const LEGEND_MODES: LegendMode[] = ["list", "table", "hidden"];
const THRESHOLD_STYLES: ThresholdStyle[] = ["line", "area", "line_area", "off"];
const MAX_THRESHOLDS = 4;

export function Checkbox({ id, label, checked, onChange }: { id: string; label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label htmlFor={id} className="flex items-center gap-2 text-sm">
      <input id={id} type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} className="size-4 accent-accent" />
      {label}
    </label>
  );
}

export function ColorPicker({ label, value, onChange }: { label: string; value: ColorIndex | null | undefined; onChange: (c: ColorIndex) => void }) {
  return (
    <div role="group" aria-label={label} className="flex gap-1.5">
      {COLOR_INDEXES.map((c) => (
        <button
          key={c}
          type="button"
          aria-label={t("ce.colorN", { n: c })}
          title={t(`ce.colorName.${c}` as TextKey)}
          aria-pressed={value === c}
          onClick={() => onChange(c)}
          style={{ backgroundColor: `var(--chart-${c})` }}
          className={`size-5 rounded-full border-2 ${value === c ? "border-text" : "border-transparent"}`}
        />
      ))}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <fieldset className="flex flex-col gap-3 rounded-xl border border-border p-3">
      <legend className="px-1 text-sm font-medium">{title}</legend>
      {children}
    </fieldset>
  );
}

// --- źródło jednego zapytania ---------------------------------------------------------------------

/** Id urządzenia wybranego w formularzu: dla portu i sieci WiFi zapisane razem ze źródłem. */
const deviceIdOf = (s: Source): number | null =>
  s.kind === "device" || isAgentSource(s.kind)
    ? (s as { id: number }).id || null
    : s.kind === "interface" || s.kind === "wifi_network"
      ? (s.device_id ?? null)
      : null;

/** Źródło wymaga wskazania obiektu (portu, urządzenia, sieci albo – dla agenta – serwera i klucza). */
export const sourceComplete = (s: Source): boolean => {
  if (s.kind === "interface" || s.kind === "device" || s.kind === "wifi_network" || s.kind === "check") return !!s.id;
  if (isAgentSource(s.kind)) {
    const a = s as { id: number; key: string };
    return !!a.id && (s.kind === "agent_cpu" || !!a.key);
  }
  return true;
};

export function SourcePicker({ prefix, source, error, onChange }: { prefix: string; source: Source; error?: string; onChange: (source: Source, resetSeries: boolean) => void }) {
  const devices = useDevices();
  const modulesState = useModules().data;
  const [deviceId, setDeviceId] = useState<number | null>(deviceIdOf(source));
  const needsDevice = source.kind === "interface" || source.kind === "wifi_network";
  const agentKind = isAgentSource(source.kind) ? source.kind : null;
  const agentKeys = useQuery({
    queryKey: ["agent-keys", deviceId],
    queryFn: () => get<AgentKeys>(`/api/devices/${deviceId}/agent-keys`),
    enabled: agentKind != null && agentKind !== "agent_cpu" && deviceId != null,
  });
  // Dla źródeł z agenta tylko serwery z agentem, dla maszyn Proxmox – węzły Proxmox, dla czujników – urządzenia SNMP
  const snmpSensor = agentKind != null && isSnmpSensorSource(agentKind);
  // Pingi łączy WAN mierzy brama (od 0.55.0) – do wyboru tylko bramy, klucze opisane nazwami łączy
  // Klienci VPN (od 0.57.0) też są na bramie
  // Testy prędkości (od 0.70.0) też robi brama, klucz = łącze
  // Urządzenia w sieci za OPNsense (od 0.83.0) też są na bramie, klucz = MAC (opis z DHCP/ARP)
  const lanClient = agentKind === "lan_client";
  const wanPing = agentKind != null && (isWanPingSource(agentKind) || isSpeedtestSource(agentKind) || agentKind === "vpn" || lanClient);
  const wantedDriver = agentKind === "pve_guest" ? "proxmox" : agentKind && !snmpSensor && !wanPing ? "agent" : null;
  const deviceOptions = (devices.data ?? []).filter((d: Device) =>
    wanPing ? d.kind === "gateway" : snmpSensor ? d.driver !== "agent" && d.driver !== "proxmox" : !wantedDriver || d.driver === wantedDriver,
  );
  const wanLinks = useQuery({ queryKey: WAN_LINKS_KEY, queryFn: () => get<WanLink[]>("/api/wan/links"), enabled: wanPing });
  const opnHosts = useOpnsenseDevice(lanClient && deviceId ? deviceId : null);
  const keyLabel = (key: string): string => {
    if (lanClient) return hostLabel(opnHosts.data?.hosts ?? [], key);
    if (!wanPing || agentKind === "vpn") return key;
    const [ifname, ...target] = key.split(WAN_PING_SEP);
    const link = (wanLinks.data ?? []).find((l) => l.device_id === deviceId && l.interface_name === ifname);
    const name = link ? `${link.name} (${ifname})` : ifname;
    return target.length ? `${name}${WAN_PING_SEP}${target.join(WAN_PING_SEP)}` : name;
  };
  const interfaces = useQuery({
    queryKey: ["device-interfaces", deviceId],
    queryFn: () => get<InterfaceItem[]>(`/api/devices/${deviceId}/interfaces`),
    enabled: source.kind === "interface" && deviceId != null,
  });
  const wifi = useQuery({
    queryKey: ["device-wifi", deviceId],
    queryFn: () => get<WifiItem[]>(`/api/devices/${deviceId}/wifi`),
    enabled: source.kind === "wifi_network" && deviceId != null,
  });
  const checks = useQuery({ queryKey: CHECKS_KEY, queryFn: () => get<Check[]>("/api/checks"), enabled: source.kind === "check" });

  const changeKind = (kind: SourceKind) => {
    const next: Source =
      kind === "wan" || kind === "wifi_total" || kind === "server"
        ? { kind }
        : kind === "device"
          ? { kind, id: deviceId ?? 0 }
          : kind === "check"
            ? { kind, id: 0 }
          : isAgentSource(kind)
            ? { kind, id: deviceId ?? 0, key: "" }
            : { kind, id: 0, device_id: deviceId };
    onChange(next, true);
  };
  const changeDevice = (id: number | null) => {
    setDeviceId(id);
    if (source.kind === "device") onChange({ kind: "device", id: id ?? 0 }, false);
    else if (agentKind) onChange({ kind: agentKind, id: id ?? 0, key: "" }, false);
    else if (needsDevice) onChange({ ...source, id: 0, device_id: id } as Source, false);
  };

  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <Select id={`${prefix}-source`} label={t("ce.source")} value={source.kind} error={error} onChange={(e) => changeKind(e.target.value as SourceKind)}>
        {SOURCE_KINDS.filter((k) => isOn(modulesState, sourceModule(k)) || k === source.kind).map((k) => (
          <option key={k} value={k}>
            {t(SOURCE_LABEL[k])}
          </option>
        ))}
      </Select>
      {(needsDevice || source.kind === "device" || agentKind) && (
        <Select id={`${prefix}-device`} label={t("ce.device")} value={deviceId ?? ""} onChange={(e) => changeDevice(e.target.value ? Number(e.target.value) : null)}>
          <option value="">{t("ce.choose")}</option>
          {deviceOptions.map((d: Device) => (
            <option key={d.id} value={d.id}>
              {d.name}
            </option>
          ))}
        </Select>
      )}
      {needsDevice && devices.data?.length === 0 && <p className="text-xs text-text-2">{t("ce.noDevices")}</p>}
      {agentKind && devices.data && deviceOptions.length === 0 && (
        <p className="text-xs text-text-2">{t(agentKind === "pve_guest" ? "ce.pve.none" : agentKind === "vpn" ? "ce.vpn.none" : wanPing ? "ce.wan.none" : "ce.agent.none")}</p>
      )}
      {agentKind && agentKind !== "agent_cpu" && deviceId != null && (
        <Select
          id={`${prefix}-agent-key`}
          label={t(AGENT_KEY_LABEL[agentKind])}
          value={(source as { key: string }).key}
          onChange={(e) => onChange({ kind: agentKind, id: deviceId, key: e.target.value }, false)}
        >
          <option value="">{t("ce.choose")}</option>
          {(agentKeys.data?.[agentKind] ?? []).map((k) => (
            <option key={k} value={k}>
              {keyLabel(k)}
            </option>
          ))}
        </Select>
      )}
      {agentKind && agentKind !== "agent_cpu" && agentKeys.data?.[agentKind]?.length === 0 && <p className="text-xs text-text-2">{t("ce.agent.noKeys")}</p>}
      {source.kind === "interface" && deviceId != null && (
        <Select
          id={`${prefix}-interface`}
          label={t("ce.interface")}
          value={source.id || ""}
          onChange={(e) => onChange({ kind: "interface", id: Number(e.target.value), device_id: deviceId }, false)}
        >
          <option value="">{t("ce.choose")}</option>
          {(interfaces.data ?? []).map((i) => (
            <option key={i.id} value={i.id}>
              {i.alias ? `${i.label} (${i.alias})` : i.label}
            </option>
          ))}
        </Select>
      )}
      {source.kind === "interface" && interfaces.data?.length === 0 && <p className="text-xs text-text-2">{t("ce.noInterfaces")}</p>}
      {source.kind === "wifi_network" && deviceId != null && (
        <Select
          id={`${prefix}-wifi`}
          label={t("ce.wifi")}
          value={source.id || ""}
          onChange={(e) => onChange({ kind: "wifi_network", id: Number(e.target.value), device_id: deviceId }, false)}
        >
          <option value="">{t("ce.choose")}</option>
          {(wifi.data ?? []).map((w) => (
            <option key={w.id} value={w.id}>
              {w.radio ? `${w.ssid} (${w.radio})` : w.ssid}
            </option>
          ))}
        </Select>
      )}
      {source.kind === "wifi_network" && wifi.data?.length === 0 && <p className="text-xs text-text-2">{t("ce.noWifi")}</p>}
      {source.kind === "check" && (
        <Select id={`${prefix}-check`} label={t("ce.check")} value={source.id || ""} onChange={(e) => onChange({ kind: "check", id: Number(e.target.value) }, false)}>
          <option value="">{t("ce.choose")}</option>
          {(checks.data ?? []).map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </Select>
      )}
      {source.kind === "check" && checks.data?.length === 0 && <p className="text-xs text-text-2">{t("ce.noChecks")}</p>}
    </div>
  );
}

// --- zapytanie: źródło, metryki, porównanie w czasie ----------------------------------------------

function QueryCard({
  cfg,
  query,
  error,
  onChange,
  onRemove,
  onCompare,
  canAdd,
}: {
  cfg: ChartConfig;
  query: ChartQuery;
  error?: string;
  onChange: (next: ChartConfig) => void;
  onRemove: (() => void) | null;
  onCompare: (() => void) | null;
  canAdd: boolean;
}) {
  const prefix = `ce-${query.id}`;
  const patchQuery = (patch: Partial<ChartQuery>) => onChange({ ...cfg, queries: cfg.queries.map((q) => (q.id === query.id ? { ...q, ...patch } : q)) });
  const patchSeries = (key: string, patch: Partial<SeriesConfig>) =>
    patchQuery({ series: query.series.map((s) => (s.key === key ? { ...s, ...patch } : s)) });
  const many = cfg.queries.length > 1;

  return (
    <section aria-label={t("ce.query", { id: query.id })} className="flex flex-col gap-3 rounded-xl border border-border p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-medium">
          <span className="mr-1.5 inline-flex size-5 items-center justify-center rounded bg-accent-soft text-xs text-accent-text">{query.id}</span>
          {t("ce.query.title")}
        </h3>
        <div className="flex items-center gap-1">
          {onCompare && (
            <Button variant="ghost" onClick={onCompare} disabled={!canAdd}>
              <IconCopy size={16} aria-hidden="true" />
              {t("ce.query.compare")}
            </Button>
          )}
          {onRemove && (
            <button
              type="button"
              onClick={onRemove}
              aria-label={t("ce.query.remove", { id: query.id })}
              title={t("ce.query.remove", { id: query.id })}
              className="flex size-8 items-center justify-center rounded-lg text-text-2 hover:bg-surface-2 hover:text-danger"
            >
              <IconTrash size={16} aria-hidden="true" />
            </button>
          )}
        </div>
      </div>

      <SourcePicker
        prefix={prefix}
        source={query.source}
        error={error}
        onChange={(source, resetSeries) => {
          if (!resetSeries) return patchQuery({ source });
          // Nowe źródło: domyślne metryki, kolory wolne w całym wykresie, oś wg jednostki
          const rest = { ...cfg, queries: cfg.queries.filter((q) => q.id !== query.id) };
          const left = axisClass(rest, "left");
          let used = rest;
          const series = defaultSeries(source.kind).map((s) => {
            const color = freeColor(used);
            const axis: Axis = left && METRICS[s.key] && left !== METRICS[s.key].unitClass ? "right" : "left";
            const next = { key: s.key, color, axis };
            used = { ...used, queries: [...used.queries, { id: "_", source, series: [next] }] };
            return next;
          });
          patchQuery({ source, series });
        }}
      />

      <Select
        id={`${prefix}-offset`}
        label={t("ce.offset")}
        value={query.offset_min ?? 0}
        onChange={(e) => patchQuery({ offset_min: Number(e.target.value) as OffsetMinutes })}
      >
        {OFFSET_OPTIONS.map((o) => (
          <option key={o} value={o}>
            {t(`ce.offset.${o}` as TextKey)}
          </option>
        ))}
      </Select>

      <fieldset className="flex flex-col gap-2">
        <legend className="text-sm font-medium">{t("ce.metrics")}</legend>
        <p className="text-xs text-muted">{t("ce.metrics.hint")}</p>
        {SOURCE_METRICS[query.source.kind].map((key) => {
          const selected = query.series.find((s) => s.key === key);
          // Ta sama nazwa co w legendzie (dla WAN „Pobieranie/Wysyłanie”) – bez własnej etykiety i przesunięcia
          const name = seriesName(query.source, { key, color: 1 });
          return (
            <div key={key} className="flex flex-col gap-2 rounded-lg py-1">
              <Checkbox
                id={`${prefix}-m-${key}`}
                label={many ? `${name} (${query.id})` : name}
                checked={!!selected}
                onChange={(on) => onChange(toggleMetric(cfg, query.id, key, on))}
              />
              {selected && (
                <div className="ml-6 flex flex-wrap items-end gap-3">
                  <ColorPicker label={t("ce.color", { name })} value={selected.color} onChange={(color) => patchSeries(key, { color })} />
                  <div className="w-40">
                    <Field
                      id={`${prefix}-label-${key}`}
                      label={t("ce.series.label")}
                      placeholder={name}
                      maxLength={40}
                      value={selected.label ?? ""}
                      onChange={(e) => patchSeries(key, { label: e.target.value || null })}
                    />
                  </div>
                  <div className="w-32">
                    <Select id={`${prefix}-axis-${key}`} label={t("ce.series.axis")} value={selected.axis ?? "left"} onChange={(e) => patchSeries(key, { axis: e.target.value as Axis })}>
                      <option value="left">{t("ce.axis.left")}</option>
                      <option value="right">{t("ce.axis.right")}</option>
                    </Select>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </fieldset>
    </section>
  );
}

// --- liczby w polach formularza (jednostka widoczna dla użytkownika) ------------------------------

const toText = (raw: number | null | undefined, cls: UnitClass | null, unit: ChartUnit) => (raw == null ? "" : String(+valueFromRaw(raw, cls, unit).toFixed(6)));
const parse = (text: string): number | null | "bad" => {
  if (text.trim() === "") return null;
  const n = Number(text.replace(",", "."));
  return Number.isFinite(n) ? n : "bad";
};

function unitHint(cls: UnitClass | null, unit: ChartUnit): string {
  switch (cls) {
    case "rate":
      return t(unit === "bytes" ? "ce.unit.hint.rate.bytes" : "ce.unit.hint.rate.bits");
    case "percent":
      return t("ce.unit.hint.percent");
    case "ms":
      return t("ce.unit.hint.ms");
    case "temp":
      return "°C";
    case "size":
      return "GB";
    case "volt":
      return "V";
    case "amp":
      return "A";
    case "watt":
      return "W";
    case "rpm":
      return "obr/min";
    case "dbm":
      return "dBm";
    default:
      return t("ce.unit.hint.other");
  }
}

interface Drafts {
  axes: Record<Axis, { min: string; max: string }>;
  thresholds: { value: string; color: ColorIndex }[];
}

function initialDrafts(c: ChartConfig): Drafts {
  const left = axisClass(c, "left");
  const right = axisClass(c, "right");
  return {
    axes: {
      left: { min: toText(c.axes?.left?.min, left, c.unit), max: toText(c.axes?.left?.max, left, c.unit) },
      right: { min: toText(c.axes?.right?.min, right, c.unit), max: toText(c.axes?.right?.max, right, c.unit) },
    },
    thresholds: (c.thresholds ?? []).map((th) => ({ value: toText(th.value, left, c.unit), color: th.color })),
  };
}

type Errors = Partial<Record<string, string>>;

/** Konfiguracja gotowa do zapisu (albo podglądu): liczby z pól przeliczone na jednostki surowe. */
function compose(cfg: ChartConfig, drafts: Drafts): { config: ChartConfig; errors: Errors } {
  const errors: Errors = {};
  const axes: NonNullable<ChartConfig["axes"]> = {};
  for (const axis of ["left", "right"] as Axis[]) {
    const cls = axisClass(cfg, axis);
    const min = parse(drafts.axes[axis].min);
    const max = parse(drafts.axes[axis].max);
    if (min === "bad") errors[`${axis}-min`] = t("ce.err.number");
    if (max === "bad") errors[`${axis}-max`] = t("ce.err.number");
    const rawMin = typeof min === "number" ? valueToRaw(min, cls, cfg.unit) : null;
    const rawMax = typeof max === "number" ? valueToRaw(max, cls, cfg.unit) : null;
    if (rawMin != null && rawMax != null && rawMin >= rawMax) errors[`${axis}-max`] = t("ce.err.axisOrder");
    axes[axis] = { min: rawMin, max: rawMax, label: cfg.axes?.[axis]?.label?.trim() || null };
  }
  const leftCls = axisClass(cfg, "left");
  const thresholds = drafts.thresholds.flatMap((th, i) => {
    const v = parse(th.value);
    if (v === "bad" || v === null) {
      errors[`th-${i}`] = t("ce.err.number");
      return [];
    }
    return [{ value: valueToRaw(v, leftCls, cfg.unit), color: th.color }];
  });
  cfg.queries.forEach((q) => {
    if (!sourceComplete(q.source)) errors[`q-${q.id}`] = t("ce.err.source");
    else if (q.series.length === 0) errors[`q-${q.id}`] = t("ce.err.metrics");
  });
  if (allSeries(cfg).length > MAX_SERIES) errors.series = t("ce.err.tooMany", { n: MAX_SERIES });
  return { config: { ...cfg, title: cfg.title?.trim() || null, axes, thresholds }, errors };
}

// --- edytor -----------------------------------------------------------------------------------------

export function ChartEditor({ initial, onSave, onClose, isNew }: { initial: ChartConfig | LegacyChartConfig; onSave: (c: ChartConfig) => void; onClose: () => void; isNew: boolean }) {
  const [cfg, setCfg] = useState<ChartConfig>(() => {
    const c = upgradeChartConfig(initial);
    return { ...c, legend: c.legend ?? { ...DEFAULT_LEGEND }, thresholds: c.thresholds ?? [], threshold_style: c.threshold_style ?? "line", stack: c.stack ?? false };
  });
  const [drafts, setDrafts] = useState<Drafts>(() => initialDrafts(upgradeChartConfig(initial)));
  const [errors, setErrors] = useState<Errors>({});
  const set = (patch: Partial<ChartConfig>) => setCfg((c) => ({ ...c, ...patch }));
  const legend = cfg.legend ?? DEFAULT_LEGEND;
  const setLegend = (patch: Partial<typeof legend>) => set({ legend: { ...legend, ...patch } });

  const composed = useMemo(() => compose(cfg, drafts), [cfg, drafts]);
  const previewOk = cfg.queries.every((q) => sourceComplete(q.source) && q.series.length > 0) && allSeries(cfg).length <= MAX_SERIES;
  const totalSeries = allSeries(cfg).length;
  const canAdd = cfg.queries.length < MAX_QUERIES && totalSeries < MAX_SERIES;
  const hasRate = allSeries(cfg).some(({ series }) => METRICS[series.key]?.unitClass === "rate");
  const leftCls = axisClass(cfg, "left");
  const rightCls = axisClass(cfg, "right");

  const addQuery = () => {
    if (!canAdd) return;
    const id = nextQueryId(cfg);
    set({ queries: [...cfg.queries, newQuery(id, { kind: "wan" }, [])] });
  };
  /** Kopia zapytania przesunięta o dzień – „ten sam ruch wczoraj” jednym kliknięciem. */
  const compare = (q: ChartQuery) => {
    if (!canAdd) return;
    const id = nextQueryId(cfg);
    let next = cfg;
    const series = q.series.map((s) => {
      const copy = { ...s, color: freeColor(next), label: null };
      next = { ...next, queries: [...next.queries, { id: "_", source: q.source, series: [copy] }] };
      return copy;
    });
    set({ queries: [...cfg.queries, { id, source: q.source, series, offset_min: 1440 }] });
  };

  const submit = () => {
    setErrors(composed.errors);
    if (Object.keys(composed.errors).length === 0) onSave(composed.config);
  };

  const axisFields = (axis: Axis, cls: UnitClass | null) => (
    <div className="grid gap-3 sm:grid-cols-3">
      <Field
        id={`ce-${axis}-min`}
        label={t("ce.axis.min")}
        inputMode="decimal"
        value={drafts.axes[axis].min}
        error={errors[`${axis}-min`]}
        hint={t("ce.axis.hint", { unit: unitHint(cls, cfg.unit) })}
        onChange={(e) => setDrafts((d) => ({ ...d, axes: { ...d.axes, [axis]: { ...d.axes[axis], min: e.target.value } } }))}
      />
      <Field
        id={`ce-${axis}-max`}
        label={t("ce.axis.max")}
        inputMode="decimal"
        value={drafts.axes[axis].max}
        error={errors[`${axis}-max`]}
        onChange={(e) => setDrafts((d) => ({ ...d, axes: { ...d.axes, [axis]: { ...d.axes[axis], max: e.target.value } } }))}
      />
      <Field
        id={`ce-${axis}-label`}
        label={t("ce.axis.label")}
        maxLength={40}
        value={cfg.axes?.[axis]?.label ?? ""}
        onChange={(e) => set({ axes: { ...cfg.axes, [axis]: { ...cfg.axes?.[axis], label: e.target.value } } })}
      />
    </div>
  );

  return (
    <Dialog
      size="xl"
      title={t(isNew ? "ce.title.new" : "ce.title.edit")}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button variant="primary" onClick={submit}>
            {t("common.save")}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <section aria-label={t("ce.preview")}>
          <h3 className="mb-2 text-sm font-medium">{t("ce.preview")}</h3>
          {previewOk ? <ChartWidget config={composed.config} /> : <p className="text-xs text-text-2">{t("ce.preview.invalid")}</p>}
        </section>

        <div className="grid gap-4 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
          <div className="flex flex-col gap-3">
            <h3 className="text-sm font-medium">{t("ce.section.data")}</h3>
            {cfg.queries.map((q) => (
              <QueryCard
                key={q.id}
                cfg={cfg}
                query={q}
                error={errors[`q-${q.id}`]}
                onChange={setCfg}
                canAdd={canAdd}
                onRemove={cfg.queries.length > 1 ? () => set({ queries: cfg.queries.filter((x) => x.id !== q.id) }) : null}
                onCompare={() => compare(q)}
              />
            ))}
            {errors.series && <p className="text-xs text-danger">{errors.series}</p>}
            <div className="flex flex-wrap items-center gap-2">
              <Button onClick={addQuery} disabled={!canAdd}>
                <IconPlus size={16} aria-hidden="true" />
                {t("ce.query.add")}
              </Button>
              <span className="text-xs text-text-2">{t("ce.query.limits", { queries: cfg.queries.length, maxQ: MAX_QUERIES, series: totalSeries, maxS: MAX_SERIES })}</span>
            </div>
          </div>

          <div className="flex flex-col gap-3">
            <Section title={t("ce.section.look")}>
              <Field id="ce-title" label={t("ce.field.title")} hint={t("ce.field.title.hint")} value={cfg.title ?? ""} maxLength={80} onChange={(e) => set({ title: e.target.value })} />
              <div className="grid gap-3 sm:grid-cols-2">
                <Select id="ce-kind" label={t("ce.kind")} value={cfg.chart} onChange={(e) => set({ chart: e.target.value as ChartKind })}>
                  {KIND_OPTIONS.map((k) => (
                    <option key={k} value={k}>
                      {t(`ce.kind.${k}` as TextKey)}
                    </option>
                  ))}
                </Select>
                {hasRate && (
                  <Select id="ce-unit" label={t("ce.unit")} value={cfg.unit} onChange={(e) => set({ unit: e.target.value as ChartUnit })}>
                    <option value="bits">{t("ce.unit.bits")}</option>
                    <option value="bytes">{t("ce.unit.bytes")}</option>
                  </Select>
                )}
              </div>
              <Checkbox id="ce-stack" label={t("ce.stack")} checked={cfg.stack ?? false} onChange={(v) => set({ stack: v })} />
              <Checkbox id="ce-smooth" label={t("ce.smooth")} checked={cfg.smooth} onChange={(v) => set({ smooth: v })} />
              <Checkbox id="ce-wan-backup" label={t("ce.wanBackup")} checked={cfg.wan_backup ?? false} onChange={(v) => set({ wan_backup: v })} />
            </Section>

            <Section title={t("ce.section.legend")}>
              <div className="grid gap-3 sm:grid-cols-2">
                <Select id="ce-legend-mode" label={t("ce.legend.mode")} value={legend.mode} onChange={(e) => setLegend({ mode: e.target.value as LegendMode })}>
                  {LEGEND_MODES.map((m) => (
                    <option key={m} value={m}>
                      {t(`ce.legend.mode.${m}` as TextKey)}
                    </option>
                  ))}
                </Select>
                <Select id="ce-legend-placement" label={t("ce.legend.placement")} value={legend.placement} onChange={(e) => setLegend({ placement: e.target.value as "bottom" | "right" })}>
                  <option value="bottom">{t("ce.legend.placement.bottom")}</option>
                  <option value="right">{t("ce.legend.placement.right")}</option>
                </Select>
              </div>
              <div role="group" aria-label={t("ce.legend.values")} className="flex flex-wrap gap-x-4 gap-y-2">
                {LEGEND_VALUES.map((v: LegendValue) => (
                  <Checkbox
                    key={v}
                    id={`ce-legend-${v}`}
                    label={t(`chart.legend.${v}` as TextKey)}
                    checked={legend.values.includes(v)}
                    onChange={(on) => setLegend({ values: on ? LEGEND_VALUES.filter((x) => x === v || legend.values.includes(x)) : legend.values.filter((x) => x !== v) })}
                  />
                ))}
              </div>
            </Section>

            <Section title={t("ce.section.axes")}>
              <p className="text-xs font-medium text-text-2">{t("ce.axis.left")}</p>
              {axisFields("left", leftCls)}
              {rightCls && (
                <>
                  <p className="text-xs font-medium text-text-2">{t("ce.axis.right")}</p>
                  {axisFields("right", rightCls)}
                </>
              )}
            </Section>

            <Section title={t("ce.section.thresholds")}>
              <p className="text-xs text-muted">{t("ce.threshold.hint", { unit: unitHint(leftCls, cfg.unit) })}</p>
              {drafts.thresholds.map((th, i) => (
                <div key={i} className="flex flex-wrap items-end gap-3">
                  <div className="w-32">
                    <Field
                      id={`ce-th-${i}`}
                      label={t("ce.threshold.value", { n: i + 1 })}
                      inputMode="decimal"
                      value={th.value}
                      error={errors[`th-${i}`]}
                      onChange={(e) => setDrafts((d) => ({ ...d, thresholds: d.thresholds.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)) }))}
                    />
                  </div>
                  <ColorPicker
                    label={t("ce.threshold.color", { n: i + 1 })}
                    value={th.color}
                    onChange={(color) => setDrafts((d) => ({ ...d, thresholds: d.thresholds.map((x, j) => (j === i ? { ...x, color } : x)) }))}
                  />
                  <button
                    type="button"
                    aria-label={t("ce.threshold.remove", { n: i + 1 })}
                    onClick={() => setDrafts((d) => ({ ...d, thresholds: d.thresholds.filter((_, j) => j !== i) }))}
                    className="mb-1.5 flex size-8 items-center justify-center rounded-lg text-text-2 hover:bg-surface-2 hover:text-danger"
                  >
                    <IconTrash size={16} aria-hidden="true" />
                  </button>
                </div>
              ))}
              <div className="flex flex-wrap items-end gap-3">
                <Button
                  onClick={() => setDrafts((d) => ({ ...d, thresholds: [...d.thresholds, { value: "", color: d.thresholds.length === 0 ? 4 : 5 }] }))}
                  disabled={drafts.thresholds.length >= MAX_THRESHOLDS}
                >
                  <IconPlus size={16} aria-hidden="true" />
                  {t("ce.threshold.add")}
                </Button>
                {drafts.thresholds.length > 0 && (
                  <div className="w-44">
                    <Select id="ce-th-style" label={t("ce.threshold.style")} value={cfg.threshold_style ?? "line"} onChange={(e) => set({ threshold_style: e.target.value as ThresholdStyle })}>
                      {THRESHOLD_STYLES.map((s) => (
                        <option key={s} value={s}>
                          {t(`ce.threshold.style.${s}` as TextKey)}
                        </option>
                      ))}
                    </Select>
                  </div>
                )}
              </div>
            </Section>

            <Section title={t("ce.section.time")}>
              <div className="grid gap-3 sm:grid-cols-2">
                <Select id="ce-range" label={t("ce.range")} value={cfg.range_min ?? ""} onChange={(e) => set({ range_min: e.target.value ? (Number(e.target.value) as RangeMinutes) : null })}>
                  <option value="">{t("ce.range.global")}</option>
                  {RANGE_OPTIONS.map((m) => (
                    <option key={m} value={m}>
                      {formatRange(m)}
                    </option>
                  ))}
                </Select>
                <Select
                  id="ce-refresh"
                  label={t("ce.refresh")}
                  value={cfg.refresh_s ?? ""}
                  onChange={(e) => set({ refresh_s: e.target.value === "" ? null : (Number(e.target.value) as RefreshSeconds) })}
                >
                  <option value="">{t("ce.refresh.global")}</option>
                  {REFRESH_OPTIONS.map((s) => (
                    <option key={s} value={s}>
                      {refreshLabel(s)}
                    </option>
                  ))}
                </Select>
              </div>
            </Section>
          </div>
        </div>
      </div>
    </Dialog>
  );
}
