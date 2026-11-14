/** Okna edycji widgetów: wykres (ChartEditor), podsumowanie (kafelki), urządzenia (wygląd, filtr), PoE, łącza WAN, alerty i dostępność. */
import { useState } from "react";
import { PieForm } from "./PieEditor";
import { t, type TextKey } from "../../i18n";
import { type Device } from "../../lib/api";
import {
  ALERTS_LIMITS,
  DEVICE_KINDS,
  EVENTS_DAYS,
  SUMMARY_TILES,
  type AlertsLimit,
  type ChartHeight,
  type ChecksDays,
  type EventsDays,
  type DeviceKind,
  type DevicesDisplay,
  type SummaryTile,
  type WanChartWidgetModel,
  type WanMetric,
  type WanSlaWidgetModel,
  type WanStatusWidgetModel,
  type WanUsageWidgetModel,
  type Widget,
} from "../../lib/layout";
import { SLA_DAYS, type SlaDays } from "../../lib/wan";
import { useDevices } from "../../lib/queries";
import { formatRange } from "../../lib/format";
import { RANGE_OPTIONS, type RangeMinutes } from "../../lib/refresh";
import { Dialog } from "../Dialog";
import { Button, Field, Select } from "../ui";
import { ChartEditor } from "./ChartEditor";
import { BarGaugeForm, HeatmapForm, StatForm, StateTimelineForm, TableForm } from "./PanelEditors";
import { KIND_LABEL } from "./DevicesWidget";

const TILE_LABEL: Record<SummaryTile, TextKey> = {
  devices: "widget.tile.devices",
  wan_down: "widget.tile.wan_down",
  wan_up: "widget.tile.wan_up",
  wifi_clients: "widget.tile.wifi_clients",
};
const HEIGHTS: ChartHeight[] = ["sm", "md", "lg"];

function Checkbox({ id, label, checked, onChange }: { id: string; label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label htmlFor={id} className="flex items-center gap-2 text-sm">
      <input id={id} type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} className="size-4 accent-accent" />
      {label}
    </label>
  );
}

// --- podsumowanie i karty urządzeń -------------------------------------------------------------

function SectionForm({ initial, isNew, onSave, onClose }: { initial: { title: string; collapsed: boolean }; isNew: boolean; onSave: (c: { title: string; collapsed: boolean }) => void; onClose: () => void }) {
  const [title, setTitle] = useState(initial.title);
  const [collapsed, setCollapsed] = useState(initial.collapsed);
  const [error, setError] = useState<string | undefined>();
  const submit = () => {
    if (!title.trim()) return setError(t("section.err.title"));
    onSave({ title: title.trim(), collapsed });
  };
  return (
    <Dialog
      size="sm"
      title={t(isNew ? "section.new" : "section.edit")}
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
        <Field id="section-title" label={t("section.title")} value={title} maxLength={80} error={error} hint={t("section.hint")} onChange={(e) => (setTitle(e.target.value), setError(undefined))} />
        <Checkbox id="section-collapsed" label={t("section.collapsed")} checked={collapsed} onChange={setCollapsed} />
      </div>
    </Dialog>
  );
}

function SummaryForm({ initial, onSave, onClose }: { initial: SummaryTile[]; onSave: (tiles: SummaryTile[]) => void; onClose: () => void }) {
  const [tiles, setTiles] = useState<SummaryTile[]>(initial);
  const [error, setError] = useState(false);
  const toggle = (tile: SummaryTile, on: boolean) =>
    setTiles(SUMMARY_TILES.filter((x) => (x === tile ? on : tiles.includes(x)))); // zachowuje stałą kolejność
  return (
    <Dialog
      title={t("widget.type.summary")}
      size="sm"
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button
            variant="primary"
            onClick={() => (tiles.length === 0 ? setError(true) : onSave(tiles))}
          >
            {t("common.save")}
          </Button>
        </>
      }
    >
      <fieldset className="flex flex-col gap-2">
        <legend className="mb-1 text-sm font-medium">{t("widget.summary.tiles")}</legend>
        {SUMMARY_TILES.map((tile) => (
          <Checkbox key={tile} id={`st-${tile}`} label={t(TILE_LABEL[tile])} checked={tiles.includes(tile)} onChange={(on) => toggle(tile, on)} />
        ))}
        {error && tiles.length === 0 && <p className="text-xs text-danger">{t("widget.summary.err")}</p>}
      </fieldset>
    </Dialog>
  );
}

function DevicesForm({
  initial,
  initialDisplay,
  onSave,
  onClose,
}: {
  initial: DeviceKind[] | null | undefined;
  initialDisplay: DevicesDisplay | undefined;
  onSave: (kinds: DeviceKind[] | null, display: DevicesDisplay) => void;
  onClose: () => void;
}) {
  const [kinds, setKinds] = useState<DeviceKind[]>(initial ?? []);
  const [display, setDisplay] = useState<DevicesDisplay>(initialDisplay ?? "cards");
  const toggle = (k: DeviceKind, on: boolean) => setKinds(DEVICE_KINDS.filter((x) => (x === k ? on : kinds.includes(x))));
  return (
    <Dialog
      title={t("widget.type.devices")}
      size="sm"
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button variant="primary" onClick={() => onSave(kinds.length === 0 ? null : kinds, display)}>
            {t("common.save")}
          </Button>
        </>
      }
    >
      <Select id="dev-display" label={t("widget.devices.display")} value={display} onChange={(e) => setDisplay(e.target.value as DevicesDisplay)}>
        <option value="table">{t("widget.devices.display.table")}</option>
        <option value="cards">{t("widget.devices.display.cards")}</option>
      </Select>
      <fieldset className="mt-4 flex flex-col gap-2">
        <legend className="mb-1 text-sm font-medium">{t("widget.devices.filter")}</legend>
        {DEVICE_KINDS.map((k) => (
          <Checkbox key={k} id={`dk-${k}`} label={t(KIND_LABEL[k])} checked={kinds.includes(k)} onChange={(on) => toggle(k, on)} />
        ))}
      </fieldset>
    </Dialog>
  );
}

function PoeForm({ initial, onSave, onClose }: { initial: number | null | undefined; onSave: (deviceId: number | null) => void; onClose: () => void }) {
  const devices = useDevices();
  const [deviceId, setDeviceId] = useState<number | null>(initial ?? null);
  const switches = (devices.data ?? []).filter((d: Device) => d.kind === "switch");
  return (
    <Dialog
      title={t("widget.type.poe")}
      size="sm"
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button variant="primary" onClick={() => onSave(deviceId)}>
            {t("common.save")}
          </Button>
        </>
      }
    >
      <Select id="poe-device" label={t("widget.poe.device")} value={deviceId ?? ""} onChange={(e) => setDeviceId(e.target.value ? Number(e.target.value) : null)}>
        <option value="">{t("widget.poe.all")}</option>
        {switches.map((d: Device) => (
          <option key={d.id} value={d.id}>
            {d.name}
          </option>
        ))}
      </Select>
    </Dialog>
  );
}

/** Karta serwera nie ma ustawień – okno tylko wyjaśnia, skąd bierze dane. */
function InfoDialog({ title, text, isNew, onSave, onClose }: { title: TextKey; text: TextKey; isNew: boolean; onSave: () => void; onClose: () => void }) {
  return (
    <Dialog
      title={t(title)}
      size="sm"
      onClose={onClose}
      footer={
        isNew ? (
          <>
            <Button variant="ghost" onClick={onClose}>
              {t("common.cancel")}
            </Button>
            <Button variant="primary" onClick={onSave}>
              {t("widget.add.title")}
            </Button>
          </>
        ) : (
          <Button variant="primary" onClick={onClose}>
            {t("common.close")}
          </Button>
        )
      }
    >
      <p className="text-sm text-text-2">{t(text)}</p>
    </Dialog>
  );
}

/** Jedno pole wyboru (alerty: ile pokazać, dostępność: okres). */
function ChoiceForm<V extends number>({
  title,
  label,
  options,
  initial,
  isNew,
  onSave,
  onClose,
}: {
  title: TextKey;
  label: TextKey;
  options: { value: V; label: string }[];
  initial: V;
  isNew: boolean;
  onSave: (value: V) => void;
  onClose: () => void;
}) {
  const [value, setValue] = useState<V>(initial);
  return (
    <Dialog
      title={t(title)}
      size="sm"
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button variant="primary" onClick={() => onSave(value)}>
            {isNew ? t("widget.add.title") : t("common.save")}
          </Button>
        </>
      }
    >
      <Select id="choice" label={t(label)} value={value} onChange={(e) => setValue(Number(e.target.value) as V)}>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </Select>
    </Dialog>
  );
}

const CHECKS_DAYS: ChecksDays[] = [7, 30];

// --- łącza WAN ----------------------------------------------------------------------------------

type WanWidget = WanStatusWidgetModel | WanChartWidgetModel | WanSlaWidgetModel | WanUsageWidgetModel;
const RESET_DAYS = Array.from({ length: 28 }, (_, i) => i + 1);

/** Widgety WAN: router (puste = wszystkie), dla wykresu metryka, zakres i wysokość, dla SLA okres. */
function WanForm({ initial, isNew, onSave, onClose }: { initial: WanWidget; isNew: boolean; onSave: (w: Widget) => void; onClose: () => void }) {
  const devices = useDevices();
  const [widget, setWidget] = useState<WanWidget>(initial);
  const routers = (devices.data ?? []).filter((d: Device) => d.kind === "gateway");
  type WanPatch = Partial<WanChartWidgetModel["config"]> | Partial<WanSlaWidgetModel["config"]> | Partial<WanUsageWidgetModel["config"]>;
  const [limit, setLimit] = useState(widget.type === "wan_usage" && widget.config.limit_gb ? String(widget.config.limit_gb) : "");
  const limitValue = limit.trim() ? Number(limit.replace(",", ".")) : null;
  const limitError = limitValue != null && !(limitValue > 0 && limitValue <= 1_000_000) ? t("usage.cfg.limitError") : undefined;
  const setConfig = (patch: WanPatch) => setWidget((w) => ({ ...w, config: { ...w.config, ...patch } }) as WanWidget);
  return (
    <Dialog
      title={t(`widget.type.${widget.type}` as TextKey)}
      size="sm"
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button
            variant="primary"
            disabled={Boolean(limitError)}
            onClick={() => onSave(widget.type === "wan_usage" ? { ...widget, config: { ...widget.config, limit_gb: limitValue } } : widget)}
          >
            {t(isNew ? "widget.add.title" : "common.save")}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <p className="text-sm text-text-2">{t("widget.wan.info")}</p>
        <Select
          id="wan-device"
          label={t("widget.wan.device")}
          value={widget.config.device_id ?? ""}
          onChange={(e) => setConfig({ device_id: e.target.value ? Number(e.target.value) : null })}
        >
          <option value="">{t("widget.wan.all")}</option>
          {routers.map((d: Device) => (
            <option key={d.id} value={d.id}>
              {d.name}
            </option>
          ))}
        </Select>
        {widget.type === "wan_chart" && (
          <>
            <Select id="wan-metric" label={t("widget.wan.metric")} value={widget.config.metric} onChange={(e) => setConfig({ metric: e.target.value as WanMetric })}>
              <option value="in_bps">{t("chart.traffic.in")}</option>
              <option value="out_bps">{t("chart.traffic.out")}</option>
            </Select>
            <Select
              id="wan-range"
              label={t("ce.range")}
              value={widget.config.range_min ?? ""}
              onChange={(e) => setConfig({ range_min: e.target.value ? (Number(e.target.value) as RangeMinutes) : null })}
            >
              <option value="">{t("ce.range.global")}</option>
              {RANGE_OPTIONS.map((m) => (
                <option key={m} value={m}>
                  {formatRange(m)}
                </option>
              ))}
            </Select>
            <Select id="wan-height" label={t("ce.height")} value={widget.config.height} onChange={(e) => setConfig({ height: e.target.value as ChartHeight })}>
              {HEIGHTS.map((h) => (
                <option key={h} value={h}>
                  {t(`ce.height.${h}` as TextKey)}
                </option>
              ))}
            </Select>
          </>
        )}
        {widget.type === "wan_sla" && (
          <Select id="wan-days" label={t("wan.sla.period")} value={widget.config.days} onChange={(e) => setConfig({ days: Number(e.target.value) as SlaDays })}>
            {SLA_DAYS.map((d) => (
              <option key={d} value={d}>
                {t(`wan.sla.days.${d}` as TextKey)}
              </option>
            ))}
          </Select>
        )}
        {widget.type === "wan_usage" && (
          <>
            <Select
              id="usage-reset"
              label={t("usage.cfg.resetDay")}
              value={widget.config.reset_day}
              onChange={(e) => setConfig({ reset_day: Number(e.target.value) })}
            >
              {RESET_DAYS.map((d) => (
                <option key={d} value={d}>
                  {d === 1 ? t("usage.cfg.calendar") : t("usage.cfg.day", { day: d })}
                </option>
              ))}
            </Select>
            <Field
              id="usage-limit"
              label={t("usage.cfg.limit")}
              inputMode="decimal"
              placeholder={t("usage.cfg.limitNone")}
              hint={t("usage.cfg.limitHint")}
              value={limit}
              error={limitError}
              onChange={(e) => setLimit(e.target.value)}
            />
          </>
        )}
      </div>
    </Dialog>
  );
}

/** Okno edycji odpowiednie dla typu widgetu. `isNew` zmienia tylko tytuł okna wykresu. */
export function WidgetEditDialog({ widget, isNew = false, onSave, onClose }: { widget: Widget; isNew?: boolean; onSave: (w: Widget) => void; onClose: () => void }) {
  switch (widget.type) {
    case "chart":
      return <ChartEditor initial={widget.config} isNew={isNew} onClose={onClose} onSave={(config) => onSave({ ...widget, config })} />;
    case "summary":
      return <SummaryForm initial={widget.config.tiles} onClose={onClose} onSave={(tiles) => onSave({ ...widget, config: { tiles } })} />;
    case "devices":
      return (
        <DevicesForm
          initial={widget.config.kinds}
          initialDisplay={widget.config.display}
          onClose={onClose}
          onSave={(kinds, display) => onSave({ ...widget, config: { kinds, display } })}
        />
      );
    case "server":
      return <InfoDialog title="widget.type.server" text="widget.server.info" isNew={isNew} onClose={onClose} onSave={() => onSave(widget)} />;
    case "status":
      return <InfoDialog title="widget.type.status" text="widget.status.info" isNew={isNew} onClose={onClose} onSave={() => onSave(widget)} />;
    case "alerts":
      return (
        <ChoiceForm<AlertsLimit>
          title="widget.type.alerts"
          label="widget.alerts.limit"
          options={ALERTS_LIMITS.map((n) => ({ value: n, label: String(n) }))}
          initial={widget.config.limit}
          isNew={isNew}
          onClose={onClose}
          onSave={(limit) => onSave({ ...widget, config: { limit } })}
        />
      );
    case "checks":
      return (
        <ChoiceForm<ChecksDays>
          title="widget.type.checks"
          label="widget.checks.days"
          options={CHECKS_DAYS.map((d) => ({ value: d, label: t(`widget.checks.days.${d}`) }))}
          initial={widget.config.days}
          isNew={isNew}
          onClose={onClose}
          onSave={(days) => onSave({ ...widget, config: { days } })}
        />
      );
    case "events":
      return (
        <ChoiceForm<EventsDays>
          title="widget.type.events"
          label="widget.events.days"
          options={EVENTS_DAYS.map((d) => ({ value: d, label: t(`widget.events.days.${d}`) }))}
          initial={widget.config.days}
          isNew={isNew}
          onClose={onClose}
          onSave={(days) => onSave({ ...widget, config: { ...widget.config, days } })}
        />
      );
    case "vpn":
      return (
        <ChoiceForm<0 | 1>
          title="widget.type.vpn"
          label="widget.vpn.show"
          options={[
            { value: 1, label: t("widget.vpn.show.all") },
            { value: 0, label: t("widget.vpn.show.online") },
          ]}
          initial={widget.config.show_offline ? 1 : 0}
          isNew={isNew}
          onClose={onClose}
          onSave={(v) => onSave({ ...widget, config: { ...widget.config, show_offline: v === 1 } })}
        />
      );
    case "poe":
      return <PoeForm initial={widget.config.device_id} onClose={onClose} onSave={(device_id) => onSave({ ...widget, config: { device_id } })} />;
    case "wan_status":
    case "wan_chart":
    case "wan_sla":
    case "wan_usage":
      return <WanForm initial={widget} isNew={isNew} onClose={onClose} onSave={onSave} />;
    case "stat":
      return <StatForm initial={widget.config} isNew={isNew} onClose={onClose} onSave={(config) => onSave({ ...widget, config })} />;
    case "bargauge":
      return <BarGaugeForm initial={widget.config} isNew={isNew} onClose={onClose} onSave={(config) => onSave({ ...widget, config })} />;
    case "table":
      return <TableForm initial={widget.config} isNew={isNew} onClose={onClose} onSave={(config) => onSave({ ...widget, config })} />;
    case "state_timeline":
      return <StateTimelineForm initial={widget.config} isNew={isNew} onClose={onClose} onSave={(config) => onSave({ ...widget, config })} />;
    case "pie":
      return <PieForm initial={widget.config} isNew={isNew} onClose={onClose} onSave={(config) => onSave({ ...widget, config })} />;
    case "heatmap":
      return <HeatmapForm initial={widget.config} isNew={isNew} onClose={onClose} onSave={(config) => onSave({ ...widget, config })} />;
    case "section":
      return <SectionForm initial={widget.config} isNew={isNew} onClose={onClose} onSave={(config) => onSave({ ...widget, config })} />;
  }
}
