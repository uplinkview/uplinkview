/** Dane panelu wykresu w czasie: serie z wielu zapytań, statystyki legendy i obszary progów. Czyste funkcje (bez Reacta). */
import { t } from "../../i18n";
import type { Series } from "../../lib/api";
import { METRICS, allSeries, autoColor, unitClassOf, type Axis, type ChartConfig, type ColorIndex, type OffsetMinutes, type SeriesConfig, type Source, type Threshold, type UnitClass } from "../../lib/layout";
import { toChartRows, type ChartRow } from "./chartData";

export interface PanelLine {
  /** `A.in_bps` – zapytanie i metryka */
  id: string;
  name: string;
  color: ColorIndex;
  axis: Axis;
  rows: ChartRow[];
  /** Seria przesunięta w czasie (porównanie) rysowana jest linią przerywaną */
  dashed: boolean;
}

export interface LineStats {
  last: number | null;
  min: number | null;
  max: number | null;
  avg: number | null;
}

const OFFSET_SUFFIX: Record<Exclude<OffsetMinutes, 0>, Parameters<typeof t>[0]> = {
  60: "chart.offset.60",
  1440: "chart.offset.1440",
  10080: "chart.offset.10080",
};

/** Nazwa serii: własna etykieta, dla WAN „Pobieranie/Wysyłanie” (perspektywa użytkownika), inaczej nazwa metryki.
 * Przy kilku zapytaniach dopisujemy źródło, przy przesunięciu – „(dzień wcześniej)”. */
export function seriesName(source: Source, s: SeriesConfig, offset: OffsetMinutes = 0, sourceLabel?: string): string {
  let name: string;
  if (s.label) name = s.label;
  else if (source.kind === "wan" && s.key === "in_bps") name = t("chart.traffic.in");
  else if (source.kind === "wan" && s.key === "out_bps") name = t("chart.traffic.out");
  else name = METRICS[s.key] ? t(METRICS[s.key].label) : s.key;
  if (!s.label && sourceLabel) name = `${sourceLabel}: ${name}`;
  return offset && !s.label ? `${name} ${t(OFFSET_SUFFIX[offset])}` : name;
}

/** Serie wykresu ze wszystkich zapytań. `sourceLabel` daje nazwę źródła, gdy zapytań o różnych źródłach jest kilka. */
export function buildLines(config: ChartConfig, data: Map<string, Series | undefined>, sourceLabel: (s: Source) => string): PanelLine[] {
  const distinctSources = new Set(config.queries.map((q) => JSON.stringify(q.source))).size > 1;
  return allSeries(config).map(({ query, series }, i) => {
    const d = data.get(query.id);
    const offset = query.offset_min ?? 0;
    return {
      id: `${query.id}.${series.key}`,
      name: seriesName(query.source, series, offset, distinctSources ? sourceLabel(query.source) : undefined),
      color: series.color ?? autoColor(i),
      axis: series.axis ?? "left",
      rows: d ? toChartRows(d.points, series.key, d.interval_s) : [],
      dashed: offset > 0,
    };
  });
}

export function lineStats(rows: ChartRow[]): LineStats {
  const values = rows.map((r) => r[1]).filter((v): v is number => v != null && Number.isFinite(v));
  if (values.length === 0) return { last: null, min: null, max: null, avg: null };
  return {
    last: values[values.length - 1],
    min: Math.min(...values),
    max: Math.max(...values),
    avg: values.reduce((a, b) => a + b, 0) / values.length,
  };
}

/** Najwyższa wartość na lewej osi; przy stosie – najwyższa suma serii w jednej chwili (szczyt stosu). */
export function leftTop(lines: PanelLine[], stack: boolean): number {
  const sums = new Map<number, number>();
  let top = 0;
  for (const line of lines) {
    if (line.axis !== "left") continue;
    for (const [time, value] of line.rows) {
      const v = (stack ? (sums.get(time) ?? 0) : 0) + (value ?? 0);
      if (stack) sums.set(time, v);
      top = Math.max(top, v);
    }
  }
  return top;
}

/** Pasy tła od każdego progu do następnego (ostatni do `top`), w kolorze progu. */
export function thresholdBands(thresholds: Threshold[], top: number): { from: number; to: number; color: ColorIndex }[] {
  const sorted = [...thresholds].sort((a, b) => a.value - b.value);
  return sorted
    .map((th, i) => ({ from: th.value, to: sorted[i + 1]?.value ?? Math.max(top, th.value), color: th.color }))
    .filter((b) => b.to > b.from);
}

/** Jednostka surowych wartości w nagłówku CSV (bez przeliczania – dane do dalszej obróbki). */
const RAW_UNIT: Partial<Record<UnitClass, string>> = {
  rate: "b/s",
  percent: "%",
  ms: "ms",
  temp: "°C",
  size: "B",
  duration: "s",
  dbm: "dBm",
  volt: "V",
  amp: "A",
  watt: "W",
  rpm: t("unit.rpm"),
  linkrate: "kb/s",
  mbps: "Mb/s",
  days: t("unit.daysSuffix"),
  hours: "h",
};

const pad = (n: number) => String(n).padStart(2, "0");
/** Czas lokalny „2026-10-29 12:00:30” – tak go czyta arkusz kalkulacyjny. */
export function csvTime(ms: number): string {
  const d = new Date(ms);
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

/** Serie wykresu jako CSV dla polskiego Excela: średnik, przecinek dziesiętny, BOM (polskie znaki). Wiersz na każdą
 * chwilę z dowolnej serii; brak wartości – puste pole. Wartości surowe (np. bity/s), jednostka w nagłówku. */
export function linesToCsv(lines: PanelLine[], timeLabel: string): string {
  const cell = (s: string) => (/[";\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s);
  const num = (v: number | null | undefined) => (v == null || !Number.isFinite(v) ? "" : String(+v.toFixed(6)).replace(".", ","));
  const head = [
    timeLabel,
    ...lines.map((l) => {
      const unit = RAW_UNIT[unitClassOf(l.id.slice(l.id.indexOf(".") + 1))];
      return unit ? `${l.name} [${unit}]` : l.name;
    }),
  ];
  const values = lines.map((l) => new Map(l.rows.map(([time, v]) => [time, v])));
  const times = [...new Set(lines.flatMap((l) => l.rows.map(([time]) => time)))].sort((a, b) => a - b);
  const rows = times.map((time) => [csvTime(time), ...values.map((m) => num(m.get(time)))].join(";"));
  // BOM na początku – Excel czyta wtedy polskie znaki jako UTF-8
  return String.fromCharCode(0xfeff) + [head.map(cell).join(";"), ...rows].join("\r\n");
}

/** Odcinek czasu `[od, do)` w ms, w którym internet szedł łączem zapasowym. */
export type TimeSpan = [from: number, to: number];

/** Kiedy ruch szedł łączem zapasowym (od 0.55.0): odcinki „aktywne” łączy dalszych niż pierwsze w kolejności (WAN 1),
 * połączone, gdy na siebie zachodzą. Bez łączy albo z jednym łączem – pusta lista. */
export function backupSpans(history: { links: { id: number; position: number }[]; segments: { link_id: number; state: string; start: string; end: string }[] } | undefined): TimeSpan[] {
  if (!history || history.links.length < 2) return [];
  const primary = Math.min(...history.links.map((l) => l.position));
  const backup = new Set(history.links.filter((l) => l.position !== primary).map((l) => l.id));
  const spans = history.segments
    .filter((s) => s.state === "active" && backup.has(s.link_id))
    .map((s): TimeSpan => [new Date(s.start).getTime(), new Date(s.end).getTime()])
    .filter(([a, b]) => b > a)
    .sort((x, y) => x[0] - y[0]);
  const out: TimeSpan[] = [];
  for (const span of spans) {
    const last = out[out.length - 1];
    if (last && span[0] <= last[1]) last[1] = Math.max(last[1], span[1]);
    else out.push([...span]);
  }
  return out;
}

/** Tekst do HTML-a dymka ECharts: nazwy serii pochodzą m.in. z nazw kontenerów, maszyn i etykiet użytkownika (od 0.65.6). */
export function escapeHtml(text: string): string {
  return text.replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch]!);
}

/** HTML dymka wykresu: nagłówek z czasem i wiersz na serię. `marker` to gotowy znacznik koloru z ECharts. */
export function tooltipHtml(head: string, color: string, rows: { marker: string; name: string; value: string }[]): string {
  const body = rows.map((r) => `${r.marker} ${escapeHtml(r.name)}: <b>${escapeHtml(r.value)}</b>`).join("<br/>");
  return `<div style="font-size:12px;color:${color}">${escapeHtml(head)}</div>${body}`;
}
