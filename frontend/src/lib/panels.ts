/** Panele od 0.27.0: kolekcje bieżących wartości, stany w czasie i wspólne funkcje (kolor z progów, liczenie wartości).
 * API: backend/netpulse/api/panels.py. */
import { useQuery } from "@tanstack/react-query";
import type { TextKey } from "../i18n";
import { get } from "./api";
import type { Collection, CollectionKind, ColorIndex, Reduce, StateItemRef, Threshold } from "./layout";
import type { RangeMinutes, RefreshSeconds } from "./refresh";
import { useRefresh } from "./refresh";

/** Wartości w wierszach kolekcji (ta sama lista w layout_schemas.py). */
export const COLLECTION_METRICS: Record<CollectionKind, string[]> = {
  devices: ["up", "cpu_percent", "mem_used_percent", "poll_ms", "uptime_s"],
  ports: ["up", "in_bps", "out_bps", "speed_mbps"],
  disks: ["used_percent", "used_bytes", "free_bytes", "total_bytes"],
  wifi: ["clients", "rx_bps", "tx_bps"],
  containers: ["up", "cpu_percent", "mem_bytes"],
  services: ["up", "mem_bytes", "uptime_s"],
  clients: ["signal_dbm", "rx_rate_kbps", "tx_rate_kbps", "connected_s"],
  checks: ["up", "latency_ms", "loss_percent", "availability_percent", "cert_days"],
};
export const COLLECTION_KINDS: CollectionKind[] = ["devices", "ports", "disks", "wifi", "containers", "services", "clients", "checks"];
export const COLLECTION_LABEL: Record<CollectionKind, TextKey> = {
  devices: "panel.collection.devices",
  ports: "panel.collection.ports",
  disks: "panel.collection.disks",
  wifi: "panel.collection.wifi",
  containers: "panel.collection.containers",
  services: "panel.collection.services",
  clients: "panel.collection.clients",
  checks: "panel.collection.checks",
};
/** Kolekcje jednego urządzenia (wifi: opcjonalnie) */
export const COLLECTION_DEVICE: Record<CollectionKind, "required" | "optional" | "none"> = {
  devices: "none",
  ports: "required",
  disks: "required",
  wifi: "optional",
  containers: "required",
  services: "required",
  clients: "none",
  checks: "none",
};
/** Moduł, bez którego kolekcji nie ma (Ustawienia → Moduły) */
export const COLLECTION_MODULE: Partial<Record<CollectionKind, "agents" | "unifi">> = {
  containers: "agents",
  services: "agents",
  clients: "unifi",
};

export interface CollectionRow {
  key: string;
  label: string;
  device_id: number | null;
  values: Record<string, number | null>;
}

/** Strona szczegółów wiersza kolekcji (null = brak). Klienci mają tylko listę – w wierszu nie ma MAC-a (te same dane widzi pulpit publiczny). */
export function rowLink(kind: CollectionKind, row: CollectionRow): string | null {
  switch (kind) {
    case "devices":
      return `/devices/${row.key}`;
    case "ports":
      return row.device_id ? `/devices/${row.device_id}/ports/${row.key}` : null;
    case "wifi":
      return row.device_id ? `/devices/${row.device_id}` : null;
    case "disks":
    case "containers":
    case "services":
      return row.device_id ? `/devices/${row.device_id}/server` : null;
    case "clients":
      return "/clients";
    case "checks":
      return "/settings/checks";
  }
}

export function collectionPath(c: Collection): string {
  return c.device_id && COLLECTION_DEVICE[c.kind] !== "none" ? `/api/collections/${c.kind}?device_id=${c.device_id}` : `/api/collections/${c.kind}`;
}

export function useCollection(c: Collection, enabled = true) {
  const { refetchInterval } = useRefresh();
  return useQuery({
    queryKey: ["collection", c.kind, c.device_id ?? null],
    queryFn: async () => (await get<{ rows: CollectionRow[] }>(collectionPath(c))).rows,
    refetchInterval,
    enabled: enabled && (COLLECTION_DEVICE[c.kind] !== "required" || !!c.device_id),
    retry: false,
  });
}

// --- stany w czasie ----------------------------------------------------------------------

export interface StateSegment {
  start: string;
  end: string;
  state: "up" | "down" | "unknown";
}
export interface StateItem {
  kind: "device" | "interface";
  id: number;
  label: string;
  segments: StateSegment[];
}
export interface StatesResponse {
  start: string;
  end: string;
  bucket_s: number;
  items: StateItem[];
}

/** Ścieżka stanów; kolejność identyfikatorów jak w konfiguracji (pulpit publiczny porównuje zbiory). */
export function statesPath(items: StateItemRef[], minutes: number): string {
  const ids = (kind: StateItemRef["kind"]) =>
    items
      .filter((i) => i.kind === kind)
      .map((i) => i.id)
      .join(",");
  const params = new URLSearchParams();
  if (ids("device")) params.set("devices", ids("device"));
  if (ids("interface")) params.set("interfaces", ids("interface"));
  if (ids("check")) params.set("checks", ids("check"));
  params.set("minutes", String(minutes));
  return `/api/states?${params.toString().replace(/%2C/g, ",")}`;
}

export function useStates(items: StateItemRef[], rangeMin?: RangeMinutes | null, refreshS?: RefreshSeconds | null) {
  const global = useRefresh();
  const minutes = rangeMin ?? global.rangeMinutes;
  const refetchInterval = refreshS == null ? global.refetchInterval : refreshS > 0 ? refreshS * 1000 : false;
  const query = useQuery({
    queryKey: ["states", items.map((i) => `${i.kind}${i.id}`).join(","), minutes],
    queryFn: () => get<StatesResponse>(statesPath(items, minutes)),
    refetchInterval,
    placeholderData: (previous) => previous,
    retry: false,
  });
  return { ...query, minutes };
}

// --- wspólne -------------------------------------------------------------------------------

/** Kolor wartości: kolor progu, który wartość przekroczyła (najwyższy), inaczej kolor bazowy. */
export function thresholdColor(value: number | null | undefined, thresholds: Threshold[], base: ColorIndex): ColorIndex {
  if (value == null) return base;
  let color = base;
  for (const th of [...thresholds].sort((a, b) => a.value - b.value)) if (value >= th.value) color = th.color;
  return color;
}

/** Jedna liczba z serii: ostatnia, średnia, największa albo najmniejsza (pomija luki). */
/** Zmiana w % względem poprzedniej wartości; null, gdy jej nie ma albo była zerem (z zera nie ma procentów). */
export function percentChange(now: number | null, before: number | null): number | null {
  if (now == null || before == null || before === 0) return null;
  return ((now - before) / Math.abs(before)) * 100;
}

export function reduceValues(values: (number | null | undefined)[], reduce: Reduce): number | null {
  const v = values.filter((x): x is number => x != null && Number.isFinite(x));
  if (v.length === 0) return null;
  switch (reduce) {
    case "last":
      return v[v.length - 1];
    case "avg":
      return v.reduce((a, b) => a + b, 0) / v.length;
    case "max":
      return Math.max(...v);
    case "min":
      return Math.min(...v);
  }
}
