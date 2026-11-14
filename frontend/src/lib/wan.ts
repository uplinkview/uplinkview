/** Łącza WAN routera – dual WAN / failover (API: backend/netpulse/api/wan.py). */
import { useQuery } from "@tanstack/react-query";
import { get, type SeriesPoint } from "./api";
import { useRefresh } from "./refresh";
import { numberFormat } from "./intl";

/** active – ruch idzie tym łączem; standby – sprawne, bez ruchu (zapas); down – nie działa; unknown – brak danych. */
export type WanState = "active" | "standby" | "down" | "unknown";

export interface WanLink {
  id: number;
  name: string;
  position: number;
  device_id: number;
  device_name: string;
  interface_id: number;
  interface_name: string;
  interface_label: string;
  speed_mbps: number | null;
  state: WanState;
  state_since: string | null;
  /** priority – zapas, bo działa łącze o wyższym priorytecie na innym routerze */
  source: "controller" | "traffic" | "priority" | null;
  in_bps: number | null;
  out_bps: number | null;
  sampled_at: string | null;
}

export interface WanStatus {
  links: WanLink[];
  active_ids: number[];
}

export interface WanSegment {
  link_id: number;
  state: Exclude<WanState, "unknown">;
  start: string;
  end: string;
}

export interface WanSwitch {
  time: string;
  from_ids: number[];
  to_ids: number[];
}

export interface WanHistory {
  interval_s: number;
  links: WanLink[];
  /** Wartości `in_<id>` / `out_<id>`: ruch łącza tylko wtedy, gdy było aktywne */
  points: SeriesPoint[];
  segments: WanSegment[];
  switches: WanSwitch[];
}

export interface WanOutage {
  start: string;
  end: string;
  duration_s: number;
  ongoing: boolean;
}

export interface WanLinkSla {
  link: WanLink;
  availability: number | null;
  up_s: number;
  down_s: number;
  active_s: number;
  unknown_s: number;
  outages: number;
  longest_outage_s: number;
  recent_outages: WanOutage[];
}

export interface WanSla {
  days: number;
  start: string;
  end: string;
  links: WanLinkSla[];
}

export type SlaDays = 1 | 7 | 30;
export const SLA_DAYS: SlaDays[] = [1, 7, 30];

export const WAN_LINKS_KEY = ["wan", "links"] as const;

export function useWanStatus() {
  const { refetchInterval } = useRefresh();
  return useQuery({ queryKey: ["wan", "status"], queryFn: () => get<WanStatus>("/api/wan/status"), refetchInterval });
}

export function useWanHistory(minutes: number, enabled = true) {
  const { refetchInterval } = useRefresh();
  return useQuery({
    queryKey: ["wan", "history", minutes],
    queryFn: () => get<WanHistory>(`/api/wan/history?minutes=${minutes}`),
    enabled,
    refetchInterval,
    placeholderData: (previous) => previous,
  });
}

export function useWanSla(days: SlaDays) {
  const { refetchInterval } = useRefresh();
  return useQuery({
    queryKey: ["wan", "sla", days],
    queryFn: () => get<WanSla>(`/api/wan/sla?days=${days}`),
    // SLA za dni nie zmienia się co kilka sekund – najwyżej co minutę
    refetchInterval: refetchInterval === false ? false : Math.max(60_000, refetchInterval),
  });
}

/** Zużycie transferu (GET /api/wan/usage, od 0.82.0): bajty dziś i w okresie rozliczeniowym. */
export interface UsageTotals {
  rx_bytes: number;
  tx_bytes: number;
}

export interface WanUsage {
  timezone: string;
  reset_day: number;
  /** Daty lokalne serwera „RRRR-MM-DD” */
  today: string;
  period_start: string;
  next_period_start: string;
  total_today: UsageTotals;
  total_period: UsageTotals;
  ports: { interface_id: number; device_id: number; device_name: string; name: string; today: UsageTotals; period: UsageTotals }[];
  days: ({ day: string } & UsageTotals)[];
}

export function useWanUsage(resetDay: number, deviceId?: number | null) {
  const { refetchInterval } = useRefresh();
  const params = new URLSearchParams({ reset_day: String(resetDay) });
  if (deviceId != null) params.set("device_id", String(deviceId));
  return useQuery({
    queryKey: ["wan", "usage", resetDay, deviceId ?? null],
    queryFn: () => get<WanUsage>(`/api/wan/usage?${params}`),
    // Licznik rośnie co cykl kolektora (30 s) – częściej nie ma sensu
    refetchInterval: refetchInterval === false ? false : Math.max(30_000, refetchInterval),
  });
}

/** Dzień okresu „RRRR-MM-DD” jako data lokalna (bez przesunięcia strefy przeglądarki). */
export const localDay = (iso: string) => {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d);
};

/** Łącze WAN, które zgłasza kontroler UniFi, a nie ma go na liście łączy (podpowiedź w ustawieniach). */
export interface WanSuggestion {
  device_id: number;
  device_name: string;
  interface_id: number;
  interface_name: string;
  interface_label: string;
  /** Numer łącza w UniFi (2 = WAN 2) */
  slot: number | null;
  up: boolean | null;
  active: boolean;
}

export function useWanSuggestions() {
  return useQuery({ queryKey: ["wan", "suggestions"], queryFn: () => get<WanSuggestion[]>("/api/wan/suggestions") });
}

export function useWanLinks() {
  return useQuery({ queryKey: WAN_LINKS_KEY, queryFn: () => get<WanLink[]>("/api/wan/links") });
}

/** Łącza wybranego routera (puste = wszystkie). */
export const forDevice = <T extends { device_id: number }>(items: T[], deviceId?: number | null): T[] =>
  deviceId == null ? items : items.filter((x) => x.device_id === deviceId);

/** Czas trwania: „45 s”, „12 min”, „3 h 5 min”, „2 d 4 h”. */
export function formatDuration(seconds: number): string {
  const s = Math.round(seconds);
  if (s < 60) return `${s} s`;
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (d > 0) return h > 0 ? `${d} d ${h} h` : `${d} d`;
  if (h > 0) return m > 0 ? `${h} h ${m} min` : `${h} h`;
  return `${m} min`;
}

/** Dostępność w %: „99,95%”; 100 bez miejsc po przecinku, brak danych → „–”. */
export function formatAvailability(pct: number | null): string {
  if (pct == null) return "–";
  if (pct >= 100) return "100%";
  // Nie zaokrąglamy w górę do 100% – to by ukryło przerwę
  const floored = Math.floor(pct * 100) / 100;
  return `${numberFormat({ minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(floored)}%`;
}

/** Ocena dostępności: od 99,9% dobra, od 99% słabsza, poniżej – zła. */
export function availabilityTone(pct: number | null): "ok" | "warn" | "danger" | "none" {
  if (pct == null) return "none";
  if (pct >= 99.9) return "ok";
  if (pct >= 99) return "warn";
  return "danger";
}
