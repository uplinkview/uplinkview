import type { ChartUnit, UnitClass } from "./layout";
import { dateFormat, numberFormat } from "./intl";
import { locale, t } from "../i18n";


/** „12 s temu”, „5 min temu”, „wczoraj”. `now` do testów. */
export function relativeTime(iso: string | null, now: number = Date.now()): string | null {
  if (!iso) return null;
  const diffS = Math.round((new Date(iso).getTime() - now) / 1000);
  const abs = Math.abs(diffS);
  if (abs < 5) return t("time.justNow");
  const rtf = new Intl.RelativeTimeFormat(locale(), { numeric: "auto" });
  if (abs < 60) return rtf.format(diffS, "second");
  if (abs < 3600) return rtf.format(Math.round(diffS / 60), "minute");
  if (abs < 86400) return rtf.format(Math.round(diffS / 3600), "hour");
  return rtf.format(Math.round(diffS / 86400), "day");
}

/** Producent i model w jednym tekście bez powtórzeń: „OPNsense” zamiast „OPNsense OPNsense”, „Linux 6.8” zamiast „Linux Linux 6.8”. */
export function vendorModel(vendor: string | null | undefined, model: string | null | undefined): string {
  const v = vendor?.trim() ?? "";
  const m = model?.trim() ?? "";
  if (!v || v === "Generic") return m;
  if (!m) return v;
  const lower = m.toLowerCase();
  const prefix = v.toLowerCase();
  if (lower === prefix || lower.startsWith(prefix + " ")) return m;
  return `${v} ${m}`;
}

export function formatDateTime(iso: string | null): string {
  if (!iso) return "-";
  return dateFormat({ dateStyle: "medium", timeStyle: "medium" }).format(new Date(iso));
}

export function formatUptime(seconds: number | null): string {
  if (seconds == null) return "-";
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (d > 0) return `${d} d ${h} h`;
  if (h > 0) return `${h} h ${m} min`;
  return `${m} min`;
}

/** Prędkość w bitach na sekundę → „42,3 Mb/s”. `null` → „–”. */
export function formatBps(bps: number | null | undefined): string {
  if (bps == null || !Number.isFinite(bps)) return "–";
  const units = ["b/s", "kb/s", "Mb/s", "Gb/s"];
  let v = Math.abs(bps);
  let i = 0;
  while (v >= 1000 && i < units.length - 1) {
    v /= 1000;
    i++;
  }
  const digits = v >= 100 || i === 0 ? 0 : v >= 10 ? 1 : 2;
  return `${numberFormat({ maximumFractionDigits: digits }).format(v)} ${units[i]}`;
}

/** Prędkość z bitów/s jako bajty/s: „5,3 MB/s”. */
export function formatBytesPerSec(bps: number | null | undefined): string {
  if (bps == null || !Number.isFinite(bps)) return "–";
  const units = ["B/s", "kB/s", "MB/s", "GB/s"];
  let v = Math.abs(bps) / 8;
  let i = 0;
  while (v >= 1000 && i < units.length - 1) {
    v /= 1000;
    i++;
  }
  const digits = v >= 100 || i === 0 ? 0 : v >= 10 ? 1 : 2;
  return `${numberFormat({ maximumFractionDigits: digits }).format(v)} ${units[i]}`;
}

/** Rozmiar w bajtach: „2,4 GB” (dziesiętnie, jak w systemie dysków i bazie). */
export function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null || !Number.isFinite(bytes)) return "–";
  const units = ["B", "kB", "MB", "GB", "TB"];
  let v = Math.abs(bytes);
  let i = 0;
  while (v >= 1000 && i < units.length - 1) {
    v /= 1000;
    i++;
  }
  const digits = v >= 100 || i === 0 ? 0 : v >= 10 ? 1 : 2;
  return `${numberFormat({ maximumFractionDigits: digits }).format(v)} ${units[i]}`;
}

/** Formatowanie wartości osi i podpowiedzi wykresu według klasy jednostki metryki. */
export function metricFormatter(cls: UnitClass, unit: ChartUnit): (value: number) => string {
  const num = (digits: number) => (v: number) => numberFormat({ maximumFractionDigits: digits }).format(v);
  switch (cls) {
    case "rate":
      return unit === "bytes" ? formatBytesPerSec : formatBps;
    case "percent":
      return (v) => `${num(1)(v)}%`;
    case "load":
      return num(2);
    case "ms":
      return (v) => `${num(Math.abs(v) < 10 ? 1 : 0)(v)} ms`;
    case "days":
      return (v) => t("unit.days", { n: num(0)(v) });
    case "hours":
      return (v) => (v >= 48 ? t("unit.days", { n: num(1)(v / 24) }) : `${num(v < 10 ? 1 : 0)(v)} h`);
    case "temp":
      return (v) => `${num(1)(v)} °C`;
    case "size":
      return formatBytes;
    case "state":
      return (v) => (v >= 0.5 ? t("state.works") : t("state.notWorks"));
    case "duration":
      return (v) => formatUptime(v);
    case "dbm":
      return (v) => `${num(1)(v)} dBm`;
    case "linkrate":
      return (v) => (v >= 1_000_000 ? `${num(2)(v / 1_000_000)} Gb/s` : `${num(0)(v / 1000)} Mb/s`);
    case "mbps":
      return (v) => (v >= 1000 ? `${num(1)(v / 1000)} Gb/s` : `${num(0)(v)} Mb/s`);
    case "volt":
      return (v) => `${num(1)(v)} V`;
    case "amp":
      return (v) => `${num(2)(v)} A`;
    case "watt":
      return (v) => `${num(1)(v)} W`;
    case "rpm":
      return (v) => `${num(0)(v)} ${t("unit.rpm")}`;
    default:
      return num(1);
  }
}

/** Etykieta zakresu czasu: 15 → „15 min”, 60 → „1 godz.”, 1440 → „24 godz.”, 10080 → „7 dni”, 525600 → „1 rok”. */
export function formatRange(minutes: number): string {
  if (minutes < 60) return `${minutes} min`;
  if (minutes <= 1440) return t("unit.hours", { n: minutes / 60 });
  if (minutes >= 525600) return t("unit.year1");
  return t("unit.days", { n: minutes / 1440 });
}

export function initials(name: string): string {
  const parts = name.split(/[\s._-]+/).filter(Boolean);
  const letters = parts.length > 1 ? parts[0][0] + parts[1][0] : name.slice(0, 2);
  return letters.toUpperCase();
}
