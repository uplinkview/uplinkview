/**
 * Wykrywanie urządzeń w sieci i raport urządzenia (od 0.73.0, `docs/43-wykrywanie-urzadzen.md`).
 * API: `/api/discovery/suggest`, `/api/discovery/scan`, `/api/devices/{id}/report`. Czyste funkcje bez Reacta.
 */
import type { DeviceCreatePayload, SnmpTargetPayload } from "./api";
import { t } from "../i18n";

export interface FoundDevice {
  host: string;
  name: string | null;
  suggested_name: string;
  descr: string | null;
  object_id: string | null;
  vendor: string | null;
  model: string | null;
  firmware: string | null;
  kind: string;
  driver: string;
  /** Tylko driver ogólny: porty i ruch działają, szczegóły producenta nie */
  generic: boolean;
  /** Już w UplinkView */
  device_id: number | null;
}

export interface ScanResult {
  network: string;
  scanned: number;
  took_s: number;
  found: FoundDevice[];
}

export type ScanPayload = Omit<SnmpTargetPayload, "host" | "driver"> & { network: string };

/** Producenci z własnym driverem – sprzęt sieciowy, który kreator zaznacza od razu (drukarki, NAS-y itp. – na życzenie). */
const NETWORK_DRIVERS = new Set(["unifi", "mikrotik", "omada", "opnsense"]);

/** Czy wynik zaznaczyć od razu: jeszcze nie dodany i rozpoznany jako sprzęt sieciowy. */
export function preselected(f: FoundDevice): boolean {
  return f.device_id == null && (NETWORK_DRIVERS.has(f.driver) || ["gateway", "switch", "ap"].includes(f.kind));
}

/** Kolejność listy: router, switche, AP, serwery, reszta; w grupie według adresu. */
export function sortFound(list: FoundDevice[]): FoundDevice[] {
  const rank: Record<string, number> = { gateway: 0, switch: 1, ap: 2, server: 3 };
  const ip = (h: string) => h.split(".").reduce((a, p) => a * 256 + (Number(p) || 0), 0);
  return [...list].sort((a, b) => (rank[a.kind] ?? 4) - (rank[b.kind] ?? 4) || ip(a.host) - ip(b.host));
}

/** Nowe urządzenie z wyniku skanu: te same dane SNMP co skan, driver wybierany automatycznie (jak w formularzu). */
export function createFromFound(f: FoundDevice, name: string, creds: Omit<ScanPayload, "network">): DeviceCreatePayload {
  return { ...creds, name: name.trim() || f.suggested_name, host: f.host, driver: "auto" };
}

// --- raport urządzenia -------------------------------------------------------------------------------

export interface ReportBranch {
  oid: string;
  name: string;
  records: number;
  truncated: boolean;
  error?: string;
}

export interface DeviceReport {
  format: string;
  format_version: number;
  netpulse: string;
  created_at: string;
  interval_s: number;
  device: { sys_object_id: string | null; sys_descr: string | null; detected_driver: string; driver: string | null; uptime_s: number | null };
  branches: ReportBranch[];
  records: number;
  changed: number;
  walk: string;
  walk2_changes: string;
  notes: string;
}

/** Czy urządzenie warto zgłosić: UplinkView zna je tylko ogólnie (driver `generic`). */
export function partiallyKnown(detectedDriver: string | null | undefined): boolean {
  return detectedDriver === "generic";
}

/** Plik do pobrania: raport z uwagami użytkownika. */
export function reportFile(report: DeviceReport, notes: string): { name: string; text: string } {
  const oid = (report.device.sys_object_id ?? "unknown").replace(/[^\d.]/g, "");
  const day = report.created_at.slice(0, 10);
  return { name: `uplinkview-report-${oid || "unknown"}-${day}.json`, text: JSON.stringify({ ...report, notes: notes.trim() }, null, 1) };
}

export const ISSUE_URL = "https://github.com/uplinkview/uplinkview/issues/new";

/** Link do gotowego zgłoszenia „Nowe urządzenie” (szablon w `.github/ISSUE_TEMPLATE/nowe-urzadzenie.yml`); plik dołącza użytkownik. */
export function issueLink(report: DeviceReport, model: string, notes: string): string {
  const params = new URLSearchParams({
    template: "nowe-urzadzenie.yml",
    title: t("devreport.issueTitle", { model: model || report.device.sys_descr?.slice(0, 60) || report.device.sys_object_id || "?" }),
    model: model.slice(0, 200),
    object_id: report.device.sys_object_id ?? "",
    descr: (report.device.sys_descr ?? "").slice(0, 300),
    driver: report.device.detected_driver,
    version: report.netpulse,
    notes: notes.trim().slice(0, 1000),
  });
  return `${ISSUE_URL}?${params.toString()}`;
}

/** Pierwsze linie zrzutu do podglądu (cały zrzut jest w pliku). */
export function previewLines(walk: string, max = 400): { lines: string[]; more: number } {
  const all = walk.split("\n").filter(Boolean);
  return { lines: all.slice(0, max), more: Math.max(0, all.length - max) };
}

/** Wartość .snmprec do podglądu: tekst, gdy da się go czytać, inaczej szesnastkowo. */
export function readableValue(tag: string, value: string): string {
  if (tag !== "4x") return value;
  const bytes = value.match(/../g)?.map((h) => parseInt(h, 16)) ?? [];
  return bytes.every((b) => b >= 32 && b < 127) ? `"${String.fromCharCode(...bytes)}"` : `0x${value}`;
}
