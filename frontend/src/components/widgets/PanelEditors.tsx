/** Edytory paneli od 0.27.0: liczba z mini-wykresem, paski, tabela, oś stanów – każdy z podglądem na żywo. */
import { IconPlus, IconTrash } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { t, type TextKey } from "../../i18n";
import { get, type Device } from "../../lib/api";
import { useChecks } from "../../lib/checks";
import { formatRange } from "../../lib/format";
import {
  METRICS,
  SOURCE_METRICS,
  unitClassOf,
  valueFromRaw,
  valueToRaw,
  type BarGaugeConfig,
  type ChartUnit,
  type Collection,
  type CollectionKind,
  type ColorIndex,
  type Reduce,
  type HeatmapConfig,
  type StatConfig,
  type StateItemRef,
  type StateTimelineConfig,
  type TableConfig,
  type Threshold,
  type UnitClass,
} from "../../lib/layout";
import { isOn, useModules } from "../../lib/modules";
import { COLLECTION_DEVICE, COLLECTION_KINDS, COLLECTION_LABEL, COLLECTION_METRICS, COLLECTION_MODULE } from "../../lib/panels";
import { useDevices } from "../../lib/queries";
import { RANGE_OPTIONS, REFRESH_OPTIONS, type RangeMinutes, type RefreshSeconds } from "../../lib/refresh";
import { Dialog } from "../Dialog";
import { refreshLabel } from "../RefreshControl";
import { Button, Field, Select } from "../ui";
import { Checkbox, ColorPicker, SourcePicker, sourceComplete } from "./ChartEditor";
import { HeatmapWidget } from "./HeatmapWidget";
import { BarGaugeWidget, StatWidget, StateTimelineWidget, TableWidget } from "./PanelWidgets";

const metricName = (key: string) => (METRICS[key] ? t(METRICS[key].label) : key);
const REDUCES: Reduce[] = ["last", "avg", "max", "min"];
const MAX_THRESHOLDS = 4;

function unitOf(cls: UnitClass, unit: ChartUnit): string {
  switch (cls) {
    case "rate":
      return unit === "bytes" ? "MB/s" : "Mb/s";
    case "percent":
      return "%";
    case "size":
      return "GB";
    case "temp":
      return "°C";
    case "ms":
      return "ms";
    case "dbm":
      return "dBm";
    case "volt":
      return "V";
    case "amp":
      return "A";
    case "watt":
      return "W";
    case "rpm":
      return "obr/min";
    case "linkrate":
      return "kb/s";
    case "mbps":
      return "Mb/s";
    case "duration":
      return "s";
    default:
      return t("ce.unit.hint.other");
  }
}

const toText = (raw: number | null | undefined, cls: UnitClass, unit: ChartUnit) => (raw == null ? "" : String(+valueFromRaw(raw, cls, unit).toFixed(6)));
const parse = (text: string): number | null | "bad" => {
  if (text.trim() === "") return null;
  const n = Number(text.replace(",", "."));
  return Number.isFinite(n) ? n : "bad";
};

/** Wspólne okno edytora panelu: podgląd na górze, ustawienia pod nim, Zapisz / Anuluj. */
export function EditorDialog({ title, preview, children, onSave, onClose }: { title: string; preview: ReactNode; children: ReactNode; onSave: () => void; onClose: () => void }) {
  return (
    <Dialog
      size="xl"
      title={title}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button variant="primary" onClick={onSave}>
            {t("common.save")}
          </Button>
        </>
      }
    >
      <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
        <section aria-label={t("ce.preview")} className="lg:order-2">
          <h3 className="mb-2 text-sm font-medium">{t("ce.preview")}</h3>
          {preview}
        </section>
        <div className="flex flex-col gap-4 lg:order-1">{children}</div>
      </div>
    </Dialog>
  );
}

function TimeFields({ range, refresh, onChange }: { range?: RangeMinutes | null; refresh?: RefreshSeconds | null; onChange: (patch: { range_min?: RangeMinutes | null; refresh_s?: RefreshSeconds | null }) => void }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <Select id="pe-range" label={t("ce.range")} value={range ?? ""} onChange={(e) => onChange({ range_min: e.target.value ? (Number(e.target.value) as RangeMinutes) : null })}>
        <option value="">{t("ce.range.global")}</option>
        {RANGE_OPTIONS.map((m) => (
          <option key={m} value={m}>
            {formatRange(m)}
          </option>
        ))}
      </Select>
      <Select id="pe-refresh" label={t("ce.refresh")} value={refresh ?? ""} onChange={(e) => onChange({ refresh_s: e.target.value === "" ? null : (Number(e.target.value) as RefreshSeconds) })}>
        <option value="">{t("ce.refresh.global")}</option>
        {REFRESH_OPTIONS.map((s) => (
          <option key={s} value={s}>
            {refreshLabel(s)}
          </option>
        ))}
      </Select>
    </div>
  );
}

// --- progi w jednostce widocznej dla użytkownika ----------------------------------------------------

interface ThresholdDraft {
  value: string;
  color: ColorIndex;
}
const draftsOf = (list: Threshold[], cls: UnitClass, unit: ChartUnit): ThresholdDraft[] => list.map((th) => ({ value: toText(th.value, cls, unit), color: th.color }));

function composeThresholds(drafts: ThresholdDraft[], cls: UnitClass, unit: ChartUnit): { list: Threshold[]; bad: number[] } {
  const bad: number[] = [];
  const list = drafts.flatMap((d, i) => {
    const v = parse(d.value);
    if (typeof v !== "number") {
      bad.push(i);
      return [];
    }
    return [{ value: valueToRaw(v, cls, unit), color: d.color }];
  });
  return { list, bad };
}

function ThresholdList({
  base,
  onBase,
  drafts,
  onChange,
  cls,
  unit,
  bad,
}: {
  base: ColorIndex;
  onBase: (c: ColorIndex) => void;
  drafts: ThresholdDraft[];
  onChange: (d: ThresholdDraft[]) => void;
  cls: UnitClass;
  unit: ChartUnit;
  bad: number[];
}) {
  return (
    <fieldset className="flex flex-col gap-3 rounded-xl border border-border p-3">
      <legend className="px-1 text-sm font-medium">{t("pe.colors")}</legend>
      <div className="flex flex-col gap-1.5">
        <span className="text-sm">{t("pe.color.base")}</span>
        <ColorPicker label={t("pe.color.base")} value={base} onChange={onBase} />
      </div>
      <p className="text-xs text-muted">{t("pe.threshold.hint", { unit: unitOf(cls, unit) })}</p>
      {drafts.map((th, i) => (
        <div key={i} className="flex flex-wrap items-end gap-3">
          <div className="w-32">
            <Field
              id={`pe-th-${i}`}
              label={t("ce.threshold.value", { n: i + 1 })}
              inputMode="decimal"
              value={th.value}
              error={bad.includes(i) ? t("ce.err.number") : undefined}
              onChange={(e) => onChange(drafts.map((x, j) => (j === i ? { ...x, value: e.target.value } : x)))}
            />
          </div>
          <ColorPicker label={t("ce.threshold.color", { n: i + 1 })} value={th.color} onChange={(color) => onChange(drafts.map((x, j) => (j === i ? { ...x, color } : x)))} />
          <button
            type="button"
            aria-label={t("ce.threshold.remove", { n: i + 1 })}
            onClick={() => onChange(drafts.filter((_, j) => j !== i))}
            className="mb-1.5 flex size-8 items-center justify-center rounded-lg text-text-2 hover:bg-surface-2 hover:text-danger"
          >
            <IconTrash size={16} aria-hidden="true" />
          </button>
        </div>
      ))}
      <div>
        <Button onClick={() => onChange([...drafts, { value: "", color: drafts.length === 0 ? 4 : 5 }])} disabled={drafts.length >= MAX_THRESHOLDS}>
          <IconPlus size={16} aria-hidden="true" />
          {t("ce.threshold.add")}
        </Button>
      </div>
    </fieldset>
  );
}

// --- wybór kolekcji ----------------------------------------------------------------------------------

/** Urządzenia, które mają daną kolekcję: dyski – serwery, kontenery – serwery z agentem, WiFi – access pointy. */
const fitsCollection = (kind: CollectionKind, d: Device) =>
  kind === "disks" ? d.kind === "server" : kind === "containers" || kind === "services" ? d.driver === "agent" : kind === "wifi" ? d.kind === "ap" : true;

function CollectionPicker({ value, error, onChange }: { value: Collection; error?: string; onChange: (c: Collection) => void }) {
  const devices = useDevices();
  const mods = useModules().data;
  const needs = COLLECTION_DEVICE[value.kind];
  const options = (devices.data ?? []).filter((d) => fitsCollection(value.kind, d));
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <Select id="pe-collection" label={t("pe.collection")} value={value.kind} onChange={(e) => onChange({ kind: e.target.value as CollectionKind, device_id: null })}>
        {COLLECTION_KINDS.filter((k) => isOn(mods, COLLECTION_MODULE[k] ?? null) || k === value.kind).map((k) => (
          <option key={k} value={k}>
            {t(COLLECTION_LABEL[k])}
          </option>
        ))}
      </Select>
      {needs !== "none" && (
        <Select id="pe-device" label={t("ce.device")} value={value.device_id ?? ""} error={error} onChange={(e) => onChange({ ...value, device_id: e.target.value ? Number(e.target.value) : null })}>
          <option value="">{needs === "optional" ? t("pe.device.all") : t("ce.choose")}</option>
          {options.map((d) => (
            <option key={d.id} value={d.id}>
              {d.name}
            </option>
          ))}
        </Select>
      )}
    </div>
  );
}

const collectionOk = (c: Collection) => COLLECTION_DEVICE[c.kind] !== "required" || !!c.device_id;

// --- liczba z mini-wykresem --------------------------------------------------------------------------

export function StatForm({ initial, isNew, onSave, onClose }: { initial: StatConfig; isNew: boolean; onSave: (c: StatConfig) => void; onClose: () => void }) {
  const [cfg, setCfg] = useState(initial);
  const cls = unitClassOf(cfg.key);
  const [drafts, setDrafts] = useState(() => draftsOf(initial.thresholds, unitClassOf(initial.key), initial.unit));
  const [errors, setErrors] = useState<{ source?: string; max?: string; bad: number[] }>({ bad: [] });
  const [maxText, setMaxText] = useState(() => toText(initial.max, unitClassOf(initial.key), initial.unit));
  const set = (patch: Partial<StatConfig>) => setCfg((c) => ({ ...c, ...patch }));
  const composed = composeThresholds(drafts, cls, cfg.unit);
  const gauge = cfg.display === "gauge";
  const max = parse(maxText);
  const rawMax = gauge && typeof max === "number" && max > 0 ? valueToRaw(max, cls, cfg.unit) : null;
  const preview = { ...cfg, thresholds: composed.list, max: rawMax };
  const ok = sourceComplete(cfg.source) && SOURCE_METRICS[cfg.source.kind].includes(cfg.key);

  const submit = () => {
    const badMax = gauge && (max === "bad" || (typeof max === "number" && max <= 0));
    const next = { source: ok ? undefined : t("ce.err.source"), max: badMax ? t("ce.err.number") : undefined, bad: composed.bad };
    setErrors(next);
    if (!next.source && !next.max && next.bad.length === 0) onSave({ ...preview, title: cfg.title?.trim() || null });
  };
  return (
    <EditorDialog title={t(isNew ? "pe.stat.new" : "pe.stat.edit")} onSave={submit} onClose={onClose} preview={ok ? <StatWidget config={preview} /> : <p className="text-xs text-text-2">{t("ce.preview.invalid")}</p>}>
      <Field id="pe-title" label={t("ce.field.title")} hint={t("ce.field.title.hint")} value={cfg.title ?? ""} maxLength={80} onChange={(e) => set({ title: e.target.value })} />
      <SourcePicker prefix="pe" source={cfg.source} error={errors.source} onChange={(source, reset) => set(reset ? { source, key: SOURCE_METRICS[source.kind][0] } : { source })} />
      <div className="grid gap-3 sm:grid-cols-2">
        <Select id="pe-key" label={t("pe.metric")} value={cfg.key} onChange={(e) => set({ key: e.target.value })}>
          {SOURCE_METRICS[cfg.source.kind].map((k) => (
            <option key={k} value={k}>
              {metricName(k)}
            </option>
          ))}
        </Select>
        <Select id="pe-reduce" label={t("pe.reduce")} value={cfg.reduce} onChange={(e) => set({ reduce: e.target.value as Reduce })}>
          {REDUCES.map((r) => (
            <option key={r} value={r}>
              {t(`pe.reduce.${r}` as TextKey)}
            </option>
          ))}
        </Select>
        {cls === "rate" && (
          <Select id="pe-unit" label={t("ce.unit")} value={cfg.unit} onChange={(e) => set({ unit: e.target.value as ChartUnit })}>
            <option value="bits">{t("ce.unit.bits")}</option>
            <option value="bytes">{t("ce.unit.bytes")}</option>
          </Select>
        )}
        <Select id="pe-display" label={t("pe.display")} value={cfg.display ?? "number"} onChange={(e) => set({ display: e.target.value as StatConfig["display"] })}>
          <option value="number">{t("pe.display.number")}</option>
          <option value="gauge">{t("pe.display.gauge")}</option>
        </Select>
        {gauge && <Field id="pe-max" label={t("pe.gauge.max")} inputMode="decimal" value={maxText} error={errors.max} hint={t("pe.max.hint")} onChange={(e) => setMaxText(e.target.value)} />}
        <Select id="pe-color-mode" label={t("pe.colorMode")} value={cfg.color_mode} onChange={(e) => set({ color_mode: e.target.value as StatConfig["color_mode"] })}>
          <option value="value">{t("pe.colorMode.value")}</option>
          <option value="background">{t("pe.colorMode.background")}</option>
        </Select>
      </div>
      {!gauge && <Checkbox id="pe-sparkline" label={t("pe.sparkline")} checked={cfg.sparkline} onChange={(v) => set({ sparkline: v })} />}
      <Checkbox id="pe-change" label={t("pe.showChange")} checked={!!cfg.show_change} onChange={(v) => set({ show_change: v })} />
      <ThresholdList base={cfg.color} onBase={(color) => set({ color })} drafts={drafts} onChange={setDrafts} cls={cls} unit={cfg.unit} bad={errors.bad} />
      <TimeFields range={cfg.range_min} refresh={cfg.refresh_s} onChange={set} />
    </EditorDialog>
  );
}

// --- paski -------------------------------------------------------------------------------------------

export function BarGaugeForm({ initial, isNew, onSave, onClose }: { initial: BarGaugeConfig; isNew: boolean; onSave: (c: BarGaugeConfig) => void; onClose: () => void }) {
  const [cfg, setCfg] = useState(initial);
  const cls = unitClassOf(cfg.key);
  const [drafts, setDrafts] = useState(() => draftsOf(initial.thresholds, unitClassOf(initial.key), initial.unit));
  const [range, setRange] = useState(() => ({
    min: toText(initial.min, unitClassOf(initial.key), initial.unit),
    max: toText(initial.max, unitClassOf(initial.key), initial.unit),
  }));
  const [errors, setErrors] = useState<{ device?: string; min?: string; max?: string; bad: number[] }>({ bad: [] });
  const set = (patch: Partial<BarGaugeConfig>) => setCfg((c) => ({ ...c, ...patch }));
  const composed = composeThresholds(drafts, cls, cfg.unit);
  const min = parse(range.min);
  const max = parse(range.max);
  const rawMin = typeof min === "number" ? valueToRaw(min, cls, cfg.unit) : 0;
  const rawMax = typeof max === "number" ? valueToRaw(max, cls, cfg.unit) : null;
  const preview: BarGaugeConfig = { ...cfg, thresholds: composed.list, min: rawMin, max: rawMax != null && rawMax > rawMin ? rawMax : null };
  const ok = collectionOk(cfg.collection);

  const submit = () => {
    const next = {
      device: ok ? undefined : t("pe.err.device"),
      min: min === "bad" ? t("ce.err.number") : undefined,
      max: max === "bad" ? t("ce.err.number") : rawMax != null && rawMax <= rawMin ? t("ce.err.axisOrder") : undefined,
      bad: composed.bad,
    };
    setErrors(next);
    if (!next.device && !next.min && !next.max && next.bad.length === 0) onSave({ ...preview, title: cfg.title?.trim() || null });
  };
  return (
    <EditorDialog title={t(isNew ? "pe.bargauge.new" : "pe.bargauge.edit")} onSave={submit} onClose={onClose} preview={ok ? <BarGaugeWidget config={preview} /> : <p className="text-xs text-text-2">{t("ce.preview.invalid")}</p>}>
      <Field id="pe-title" label={t("ce.field.title")} hint={t("ce.field.title.hint")} value={cfg.title ?? ""} maxLength={80} onChange={(e) => set({ title: e.target.value })} />
      <CollectionPicker value={cfg.collection} error={errors.device} onChange={(collection) => set({ collection, key: COLLECTION_METRICS[collection.kind].includes(cfg.key) ? cfg.key : COLLECTION_METRICS[collection.kind][0] })} />
      <div className="grid gap-3 sm:grid-cols-2">
        <Select id="pe-key" label={t("pe.metric")} value={cfg.key} onChange={(e) => set({ key: e.target.value })}>
          {COLLECTION_METRICS[cfg.collection.kind].map((k) => (
            <option key={k} value={k}>
              {metricName(k)}
            </option>
          ))}
        </Select>
        {cls === "rate" && (
          <Select id="pe-unit" label={t("ce.unit")} value={cfg.unit} onChange={(e) => set({ unit: e.target.value as ChartUnit })}>
            <option value="bits">{t("ce.unit.bits")}</option>
            <option value="bytes">{t("ce.unit.bytes")}</option>
          </Select>
        )}
        <Field id="pe-min" label={t("ce.axis.min")} inputMode="decimal" value={range.min} error={errors.min} hint={t("ce.axis.hint", { unit: unitOf(cls, cfg.unit) })} onChange={(e) => setRange((r) => ({ ...r, min: e.target.value }))} />
        <Field id="pe-max" label={t("ce.axis.max")} inputMode="decimal" value={range.max} error={errors.max} hint={t("pe.max.hint")} onChange={(e) => setRange((r) => ({ ...r, max: e.target.value }))} />
        <Select id="pe-orientation" label={t("pe.orientation")} value={cfg.orientation} onChange={(e) => set({ orientation: e.target.value as BarGaugeConfig["orientation"] })}>
          <option value="horizontal">{t("pe.orientation.horizontal")}</option>
          <option value="vertical">{t("pe.orientation.vertical")}</option>
        </Select>
        <Select id="pe-sort" label={t("pe.sort")} value={cfg.sort} onChange={(e) => set({ sort: e.target.value as BarGaugeConfig["sort"] })}>
          <option value="none">{t("pe.sort.none")}</option>
          <option value="desc">{t("pe.sort.desc")}</option>
          <option value="asc">{t("pe.sort.asc")}</option>
        </Select>
        <Field id="pe-limit" label={t("pe.limit")} type="number" min={1} max={50} value={cfg.limit} onChange={(e) => set({ limit: Math.min(50, Math.max(1, Number(e.target.value) || 1)) })} />
      </div>
      <ThresholdList base={cfg.color} onBase={(color) => set({ color })} drafts={drafts} onChange={setDrafts} cls={cls} unit={cfg.unit} bad={errors.bad} />
    </EditorDialog>
  );
}

// --- tabela ------------------------------------------------------------------------------------------

export function TableForm({ initial, isNew, onSave, onClose }: { initial: TableConfig; isNew: boolean; onSave: (c: TableConfig) => void; onClose: () => void }) {
  const [cfg, setCfg] = useState(initial);
  const [errors, setErrors] = useState<{ device?: string; columns?: string }>({});
  const set = (patch: Partial<TableConfig>) => setCfg((c) => ({ ...c, ...patch }));
  const available = COLLECTION_METRICS[cfg.collection.kind];
  const ok = collectionOk(cfg.collection) && cfg.columns.length > 0;
  const hasRate = cfg.columns.some((c) => unitClassOf(c) === "rate");

  const submit = () => {
    const next = { device: collectionOk(cfg.collection) ? undefined : t("pe.err.device"), columns: cfg.columns.length ? undefined : t("pe.err.columns") };
    setErrors(next);
    if (!next.device && !next.columns) onSave({ ...cfg, title: cfg.title?.trim() || null });
  };
  return (
    <EditorDialog title={t(isNew ? "pe.table.new" : "pe.table.edit")} onSave={submit} onClose={onClose} preview={ok ? <TableWidget key={JSON.stringify([cfg.sort_by, cfg.sort_desc])} config={cfg} /> : <p className="text-xs text-text-2">{t("ce.preview.invalid")}</p>}>
      <Field id="pe-title" label={t("ce.field.title")} hint={t("ce.field.title.hint")} value={cfg.title ?? ""} maxLength={80} onChange={(e) => set({ title: e.target.value })} />
      <CollectionPicker
        value={cfg.collection}
        error={errors.device}
        onChange={(collection) => {
          const columns = cfg.columns.filter((c) => COLLECTION_METRICS[collection.kind].includes(c));
          set({ collection, columns: columns.length ? columns : COLLECTION_METRICS[collection.kind].slice(0, 3), sort_by: null });
        }}
      />
      <fieldset className="flex flex-col gap-2">
        <legend className="text-sm font-medium">{t("pe.columns")}</legend>
        <div className="flex flex-wrap gap-x-4 gap-y-2">
          {available.map((k) => (
            <Checkbox
              key={k}
              id={`pe-col-${k}`}
              label={metricName(k)}
              checked={cfg.columns.includes(k)}
              onChange={(on) => {
                const columns = on ? available.filter((c) => c === k || cfg.columns.includes(c)) : cfg.columns.filter((c) => c !== k);
                set({ columns, sort_by: columns.includes(cfg.sort_by ?? "") ? cfg.sort_by : null });
              }}
            />
          ))}
        </div>
        {errors.columns && <p className="text-xs text-danger">{errors.columns}</p>}
      </fieldset>
      <div className="grid gap-3 sm:grid-cols-2">
        <Select id="pe-sort-by" label={t("pe.sortBy")} value={cfg.sort_by ?? ""} onChange={(e) => set({ sort_by: e.target.value || null })}>
          <option value="">{t("panel.table.name")}</option>
          {cfg.columns.map((c) => (
            <option key={c} value={c}>
              {metricName(c)}
            </option>
          ))}
        </Select>
        <Field id="pe-limit" label={t("pe.limit")} type="number" min={1} max={100} value={cfg.limit} onChange={(e) => set({ limit: Math.min(100, Math.max(1, Number(e.target.value) || 1)) })} />
        {hasRate && (
          <Select id="pe-unit" label={t("ce.unit")} value={cfg.unit} onChange={(e) => set({ unit: e.target.value as ChartUnit })}>
            <option value="bits">{t("ce.unit.bits")}</option>
            <option value="bytes">{t("ce.unit.bytes")}</option>
          </Select>
        )}
      </div>
      <Checkbox id="pe-sort-desc" label={t("pe.sortDesc")} checked={cfg.sort_desc} onChange={(v) => set({ sort_desc: v })} />
    </EditorDialog>
  );
}

// --- oś stanów ----------------------------------------------------------------------------------------

interface PortItem {
  id: number;
  label: string;
  alias: string | null;
}

export function StateTimelineForm({ initial, isNew, onSave, onClose }: { initial: StateTimelineConfig; isNew: boolean; onSave: (c: StateTimelineConfig) => void; onClose: () => void }) {
  const [cfg, setCfg] = useState(initial);
  const set = (patch: Partial<StateTimelineConfig>) => setCfg((c) => ({ ...c, ...patch }));
  const devices = useDevices().data ?? [];
  const [portDevice, setPortDevice] = useState<number | null>(null);
  const [portId, setPortId] = useState<number | null>(null);
  const ports = useQuery({
    queryKey: ["device-interfaces", portDevice],
    queryFn: () => get<PortItem[]>(`/api/devices/${portDevice}/interfaces`),
    enabled: portDevice != null,
  });
  const checks = useChecks().data ?? [];
  const has = (kind: StateItemRef["kind"], id: number) => cfg.items.some((i) => i.kind === kind && i.id === id);
  const toggleItem = (kind: "device" | "check", id: number, on: boolean) =>
    set({ items: on ? [...cfg.items, { kind, id }] : cfg.items.filter((i) => !(i.kind === kind && i.id === id)) });
  const toggleDevice = (id: number, on: boolean) => toggleItem("device", id, on);
  const portLabel = (item: StateItemRef) => {
    const device = devices.find((d) => d.id === item.device_id);
    const port = item.device_id === portDevice ? ports.data?.find((p) => p.id === item.id) : undefined;
    return `${device?.name ?? "?"}: ${port?.label ?? `#${item.id}`}`;
  };
  const full = cfg.items.length >= 20;

  return (
    <EditorDialog title={t(isNew ? "pe.states.new" : "pe.states.edit")} onSave={() => onSave({ ...cfg, title: cfg.title?.trim() || null })} onClose={onClose} preview={<StateTimelineWidget config={cfg} />}>
      <Field id="pe-title" label={t("ce.field.title")} hint={t("ce.field.title.hint")} value={cfg.title ?? ""} maxLength={80} onChange={(e) => set({ title: e.target.value })} />
      <fieldset className="flex flex-col gap-2">
        <legend className="text-sm font-medium">{t("pe.states.devices")}</legend>
        <p className="text-xs text-muted">{t("pe.states.hint")}</p>
        <div className="flex flex-wrap gap-x-4 gap-y-2">
          {devices.map((d) => (
            <Checkbox key={d.id} id={`pe-dev-${d.id}`} label={d.name} checked={has("device", d.id)} onChange={(on) => (!on || !full) && toggleDevice(d.id, on)} />
          ))}
        </div>
      </fieldset>
      <fieldset className="flex flex-col gap-2">
        <legend className="text-sm font-medium">{t("pe.states.ports")}</legend>
        <ul className="flex flex-col gap-1 text-sm">
          {cfg.items
            .filter((i) => i.kind === "interface")
            .map((i) => (
              <li key={i.id} className="flex items-center justify-between gap-2">
                <span className="truncate">{portLabel(i)}</span>
                <button
                  type="button"
                  aria-label={t("pe.states.removePort", { name: portLabel(i) })}
                  onClick={() => set({ items: cfg.items.filter((x) => !(x.kind === "interface" && x.id === i.id)) })}
                  className="flex size-8 items-center justify-center rounded-lg text-text-2 hover:bg-surface-2 hover:text-danger"
                >
                  <IconTrash size={16} aria-hidden="true" />
                </button>
              </li>
            ))}
        </ul>
        <div className="grid items-end gap-3 sm:grid-cols-[1fr_1fr_auto]">
          <Select
            id="pe-port-device"
            label={t("ce.device")}
            value={portDevice ?? ""}
            onChange={(e) => {
              setPortDevice(e.target.value ? Number(e.target.value) : null);
              setPortId(null);
            }}
          >
            <option value="">{t("ce.choose")}</option>
            {devices.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </Select>
          <Select id="pe-port" label={t("ce.interface")} value={portId ?? ""} onChange={(e) => setPortId(e.target.value ? Number(e.target.value) : null)}>
            <option value="">{t("ce.choose")}</option>
            {(ports.data ?? []).map((p) => (
              <option key={p.id} value={p.id}>
                {p.alias ? `${p.label} (${p.alias})` : p.label}
              </option>
            ))}
          </Select>
          <Button
            disabled={portId == null || full || (portId != null && has("interface", portId))}
            onClick={() => portId != null && set({ items: [...cfg.items, { kind: "interface", id: portId, device_id: portDevice }] })}
          >
            <IconPlus size={16} aria-hidden="true" />
            {t("pe.states.addPort")}
          </Button>
        </div>
      </fieldset>
      {checks.length > 0 && (
        <fieldset className="flex flex-col gap-2">
          <legend className="text-sm font-medium">{t("pe.states.checks")}</legend>
          <div className="flex flex-wrap gap-x-4 gap-y-2">
            {checks.map((c) => (
              <Checkbox key={c.id} id={`pe-chk-${c.id}`} label={c.name} checked={has("check", c.id)} onChange={(on) => (!on || !full) && toggleItem("check", c.id, on)} />
            ))}
          </div>
        </fieldset>
      )}
      <TimeFields range={cfg.range_min} refresh={cfg.refresh_s} onChange={set} />
    </EditorDialog>
  );
}

// --- mapa cieplna -------------------------------------------------------------------------------------

export function HeatmapForm({ initial, isNew, onSave, onClose }: { initial: HeatmapConfig; isNew: boolean; onSave: (c: HeatmapConfig) => void; onClose: () => void }) {
  const [cfg, setCfg] = useState(initial);
  const [error, setError] = useState<string | undefined>();
  const set = (patch: Partial<HeatmapConfig>) => setCfg((c) => ({ ...c, ...patch }));
  const cls = unitClassOf(cfg.key);
  const ok = sourceComplete(cfg.source) && SOURCE_METRICS[cfg.source.kind].includes(cfg.key);

  const submit = () => {
    setError(ok ? undefined : t("ce.err.source"));
    if (ok) onSave({ ...cfg, title: cfg.title?.trim() || null });
  };
  return (
    <EditorDialog
      title={t(isNew ? "pe.heatmap.new" : "pe.heatmap.edit")}
      onSave={submit}
      onClose={onClose}
      preview={ok ? <HeatmapWidget config={cfg} /> : <p className="text-xs text-text-2">{t("ce.preview.invalid")}</p>}
    >
      <Field id="pe-title" label={t("ce.field.title")} hint={t("ce.field.title.hint")} value={cfg.title ?? ""} maxLength={80} onChange={(e) => set({ title: e.target.value })} />
      <SourcePicker prefix="pe" source={cfg.source} error={error} onChange={(source, reset) => set(reset ? { source, key: SOURCE_METRICS[source.kind][0] } : { source })} />
      <div className="grid gap-3 sm:grid-cols-2">
        <Select id="pe-key" label={t("pe.metric")} value={cfg.key} onChange={(e) => set({ key: e.target.value })}>
          {SOURCE_METRICS[cfg.source.kind].map((k) => (
            <option key={k} value={k}>
              {metricName(k)}
            </option>
          ))}
        </Select>
        <Select id="pe-heat-reduce" label={t("pe.heatmap.reduce")} value={cfg.reduce} onChange={(e) => set({ reduce: e.target.value as HeatmapConfig["reduce"] })}>
          <option value="avg">{t("pe.heatmap.reduce.avg")}</option>
          <option value="max">{t("pe.heatmap.reduce.max")}</option>
        </Select>
        <Select
          id="pe-heat-group"
          label={t("pe.heatmap.group")}
          value={cfg.group}
          // Dzień po dniu – najwyżej 4 tygodnie (28 wierszy)
          onChange={(e) => {
            const group = e.target.value as HeatmapConfig["group"];
            set(group === "date" && cfg.weeks > 4 ? { group, weeks: 4 } : { group });
          }}
        >
          <option value="weekday">{t("pe.heatmap.group.weekday")}</option>
          <option value="date">{t("pe.heatmap.group.date")}</option>
        </Select>
        <Select id="pe-heat-weeks" label={t("pe.heatmap.weeks")} value={cfg.weeks} onChange={(e) => set({ weeks: Number(e.target.value) as HeatmapConfig["weeks"] })}>
          {([1, 4, 12] as const)
            .filter((w) => cfg.group === "weekday" || w <= 4)
            .map((w) => (
              <option key={w} value={w}>
                {t(`pe.heatmap.weeks.${w}`)}
              </option>
            ))}
        </Select>
        {cls === "rate" && (
          <Select id="pe-unit" label={t("ce.unit")} value={cfg.unit} onChange={(e) => set({ unit: e.target.value as ChartUnit })}>
            <option value="bits">{t("ce.unit.bits")}</option>
            <option value="bytes">{t("ce.unit.bytes")}</option>
          </Select>
        )}
      </div>
      <ColorPicker label={t("pe.heatmap.color")} value={cfg.color} onChange={(color) => set({ color })} />
    </EditorDialog>
  );
}

