/** Alerty i reguły (API: backend/netpulse/api/alerts.py). */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { del, get, post, request } from "./api";
import { formatBps } from "./format";
import { useRefresh } from "./refresh";
import { formatNumber, numberFormat } from "./intl";
import { t } from "../i18n";

export type Severity = "info" | "warning" | "critical";
export const SEVERITIES: Severity[] = ["critical", "warning", "info"];
export type RuleKind =
  | "device_offline"
  | "port_down"
  | "metric"
  | "container_stopped"
  | "service_failed"
  | "smart_failed"
  | "guest_stopped"
  | "backup_failed"
  | "gateway_down"
  | "opnsense_service_failed"
  | "check_down"
  | "default_community"
  | "wan_switch"
  | "device_restart"
  | "vpn_connect";
/** Rodzaje ze stanu w agencie, Proxmoxie i OPNsense: kontener, usługa, SMART, maszyna, kopia, brama (bez progu, z filtrem nazwy). */
export const AGENT_KINDS: RuleKind[] = [
  "container_stopped",
  "service_failed",
  "smart_failed",
  "guest_stopped",
  "backup_failed",
  "gateway_down",
  "opnsense_service_failed",
];
/** Zdarzenia chwilowe (od 0.49.0): alert trwa 10 minut i kończy się sam. */
export const EVENT_KINDS: RuleKind[] = ["wan_switch", "device_restart", "vpn_connect"];
export const RULE_KINDS: RuleKind[] = ["device_offline", "port_down", "metric", ...AGENT_KINDS, "check_down", "default_community", ...EVENT_KINDS];

export interface Alert {
  id: number;
  rule_id: number | null;
  state: "firing" | "resolved";
  severity: Severity;
  title: string;
  message: string | null;
  device_id: number | null;
  value: number | null;
  peak: number | null;
  started_at: string;
  resolved_at: string | null;
  acked_at: string | null;
  acked_by: string | null;
  /** Zaczął się w oknie serwisowym – bez powiadomienia (od 0.60.0) */
  maintenance?: boolean;
}

export interface AlertSummary {
  firing: number;
  unacked: number;
  /** Niepotwierdzone krytyczne – kolor plakietki dzwonka */
  unacked_critical: number;
  critical: number;
  warning: number;
  info: number;
}

export interface AlertRule {
  id: number;
  name: string;
  enabled: boolean;
  kind: RuleKind;
  metric: string | null;
  op: ">" | "<" | null;
  threshold: number | null;
  duration_s: number;
  severity: Severity;
  device_id: number | null;
  /** Filtr nazwy kontenera, usługi, dysku albo czujnika (wzorzec z * i ?) */
  match: string | null;
  created_at: string;
}

export type RulePayload = Omit<AlertRule, "id" | "created_at">;

export interface RuleMetric {
  metric: string;
  label: string;
  unit: string;
  per_device: boolean;
  /** Czy regułę można zawęzić filtrem nazwy (metryki z agenta) */
  matchable?: boolean;
}

export const ALERTS_KEY = ["alerts"] as const;
export const RULES_KEY = ["alert-rules"] as const;

export function useAlertSummary(enabled = true) {
  const { refetchInterval } = useRefresh();
  return useQuery({
    queryKey: [...ALERTS_KEY, "summary"],
    queryFn: () => get<AlertSummary>("/api/alerts/summary"),
    refetchInterval,
    retry: false,
    enabled,
  });
}

export function useAlerts(state: "firing" | "resolved") {
  const { refetchInterval } = useRefresh();
  return useQuery({
    queryKey: [...ALERTS_KEY, "list", state],
    queryFn: () => get<Alert[]>(`/api/alerts?state=${state}&limit=200`),
    refetchInterval,
  });
}

export function useAckAlert() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => post<Alert>(`/api/alerts/${id}/ack`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ALERTS_KEY }),
  });
}

export function useRules() {
  return useQuery({ queryKey: RULES_KEY, queryFn: () => get<AlertRule[]>("/api/alert-rules") });
}

export function useRuleMetrics() {
  return useQuery({
    queryKey: [...RULES_KEY, "metrics"],
    queryFn: () => get<RuleMetric[]>("/api/alert-rules/metrics"),
    staleTime: Infinity,
  });
}

export function useSaveRule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, rule }: { id?: number; rule: RulePayload }) =>
      id === undefined ? post<AlertRule>("/api/alert-rules", rule) : request<AlertRule>("PUT", `/api/alert-rules/${id}`, rule),
    onSuccess: () => qc.invalidateQueries({ queryKey: RULES_KEY }),
  });
}

export function useDeleteRule() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => del(`/api/alert-rules/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: RULES_KEY }),
  });
}

/** Czas trwania w sekundach → „5 min”, „2 godz.”, „45 s”. */
export function formatDuration(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)} s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min`;
  if (seconds < 86400) return t("unit.hours", { n: formatNumber(Math.round((seconds / 3600) * 10) / 10) });
  return t("unit.days", { n: formatNumber(Math.round((seconds / 86400) * 10) / 10) });
}

/** Próg reguły w jednostce widocznej dla użytkownika (WAN: Mb/s zamiast b/s). */
export function thresholdToDisplay(metric: string | null, raw: number | null): number | null {
  if (raw == null) return null;
  return metric?.startsWith("wan_") ? raw / 1_000_000 : raw;
}

export function thresholdFromDisplay(metric: string | null, shown: number): number {
  return metric?.startsWith("wan_") ? shown * 1_000_000 : shown;
}

export function formatThreshold(raw: number | null, unit: string): string {
  if (raw == null) return "";
  if (unit === "b/s") return formatBps(raw);
  return `${numberFormat({ maximumFractionDigits: 2 }).format(raw)}${unit}`;
}
