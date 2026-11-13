/** Klient API UplinkView. Sesja siedzi w ciasteczku HttpOnly, więc wystarczy `same-origin`. */

import { getLanguage } from "../i18n";

/** Nagłówki każdego żądania: język panelu – backend odpowiada komunikatami w tym języku (od 0.75.0). */
export const languageHeaders = (): Record<string, string> => ({ "Accept-Language": getLanguage() });

export class ApiError extends Error {
  readonly status: number;
  /** Kod błędu z `detail.code` (np. `totp_required` przy logowaniu dwuskładnikowym) */
  readonly code?: string;

  constructor(status: number, message: string, code?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

/** FastAPI zwraca `detail` jako tekst (nasze błędy), listę (walidacja Pydantic) albo obiekt `{code, message}`. */
export function messageFromDetail(detail: unknown, fallback: string): string {
  if (typeof detail === "string" && detail) return detail;
  if (detail && typeof detail === "object" && "message" in detail && typeof detail.message === "string") return detail.message;
  if (Array.isArray(detail)) {
    const msgs = detail
      .map((d) => (d && typeof d === "object" && "msg" in d ? String((d as { msg: unknown }).msg).replace(/^Value error, /, "") : ""))
      .filter(Boolean);
    if (msgs.length) return msgs.join(" ");
  }
  return fallback;
}

/** Pulpit publiczny (/p/<token>): widgety pytają o swoje zwykłe ścieżki, a klient kieruje je do API publicznego,
 * które wydaje tylko dane widgetów zapisanych w tym pulpicie (backend/netpulse/api/public.py). */
let publicDashboard: { token: string; access: string | null } | null = null;

export function setPublicDashboard(value: { token: string; access: string | null } | null): void {
  publicDashboard = value;
}

/** Stan logowania (/api/auth/*) zostaje przy zwykłym API – inaczej 401 z pulpitu z PIN-em wywoływałby
 * ponowne sprawdzanie logowania w nieskończoność. */
function routed(method: string, path: string): string {
  if (!publicDashboard || method !== "GET" || !path.startsWith("/api/")) return path;
  if (path.startsWith("/api/public/") || path.startsWith("/api/auth/")) return path;
  return `/api/public/dashboards/${publicDashboard.token}/data?path=${encodeURIComponent(path)}`;
}

export async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(routed(method, path), {
    method,
    credentials: "same-origin",
    headers: {
      Accept: "application/json",
      ...languageHeaders(),
      ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      ...(publicDashboard?.access ? { "X-Dashboard-Access": publicDashboard.access } : {}),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let detail: unknown;
    try {
      detail = (await res.json()).detail;
    } catch {
      /* odpowiedź bez JSON-a */
    }
    const code = detail && typeof detail === "object" && "code" in detail && typeof detail.code === "string" ? detail.code : undefined;
    throw new ApiError(res.status, messageFromDetail(detail, res.statusText || `HTTP ${res.status}`), code);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const get = <T>(path: string) => request<T>("GET", path);
export const post = <T>(path: string, body?: unknown) => request<T>("POST", path, body ?? {});
export const patch = <T>(path: string, body: unknown) => request<T>("PATCH", path, body);
export const put = <T>(path: string, body: unknown) => request<T>("PUT", path, body);
export const del = (path: string) => request<void>("DELETE", path);

// --- typy odpowiedzi (zgodne z backend/netpulse/api/schemas.py) -------------------

export interface User {
  id: number;
  username: string;
  is_admin: boolean;
  /** admin | operator | viewer – od 0.61.0 (starsze API: tylko is_admin) */
  role?: "admin" | "operator" | "viewer";
  /** Logowanie dwuskładnikowe włączone (od 0.63.0) */
  totp_enabled?: boolean;
  created_at: string;
  last_login_at: string | null;
}

export interface AuthStatus {
  setup_required: boolean;
  authenticated: boolean;
  user: User | null;
  version: string | null; // tylko dla zalogowanych (od 0.65.6)
}

export interface Device {
  id: number;
  name: string;
  host: string;
  port: number;
  enabled: boolean;
  driver: string;
  detected_driver: string | null;
  snmp_version: string;
  v3_username: string | null;
  v3_auth_protocol: string | null;
  v3_priv_protocol: string | null;
  v3_context: string | null;
  kind: string;
  vendor: string | null;
  model: string | null;
  firmware: string | null;
  sys_name: string | null;
  uptime_s: number | null;
  /** Status do pokazania: od 0.59.0 „unknown”, gdy kolektor dawno nie wydał werdyktu (wtedy `stale`). */
  status: "up" | "down" | "unknown" | string;
  /** Dane nieaktualne – kolektor nie odświeża urządzenia (od 0.59.0; brak w starszym API) */
  stale?: boolean;
  /** Trwa okno serwisowe obejmujące urządzenie – bez powiadomień (od 0.60.0) */
  maintenance?: boolean;
  /** Dane drivera sprawdzone na prawdziwym sprzęcie: verified | partial | test (od 0.64.0; brak w starszym API) */
  verification?: "verified" | "partial" | "test" | string;
  /** Ostatni zapisany werdykt kolektora, także gdy jest nieaktualny (od 0.59.0) */
  last_status?: string | null;
  last_polled_at: string | null;
  last_ok_at: string | null;
  last_error: string | null;
  created_at: string;
  /** SNMP v1/v2c z fabrycznym community („public”, „private”) – od 0.31.1; brak w starszym API */
  default_community?: boolean;
}

export interface DashboardSummary {
  devices: { total: number; up: number; down: number; unknown: number };
  wan: { in_bps: number | null; out_bps: number | null; interfaces: number };
  wifi_clients: number | null;
  last_poll_at: string | null;
  poll_interval_s: number;
}

export interface SeriesPoint {
  time: string;
  values: Record<string, number | null>;
}

export interface Series {
  interval_s: number;
  points: SeriesPoint[];
}

export type SnmpVersion = "1" | "2c" | "3";
export type DriverName = "auto" | "generic" | "unifi" | "linux" | "mikrotik" | "omada" | "opnsense";
export type AuthProtocol = "MD5" | "SHA" | "SHA224" | "SHA256" | "SHA384" | "SHA512";
export type PrivProtocol = "DES" | "AES" | "AES192" | "AES256";

/** Dane połączenia SNMP wysyłane do POST /api/probe i POST /api/devices (bez pól pustych). */
export interface SnmpTargetPayload {
  host: string;
  port: number;
  driver: DriverName;
  snmp_version: SnmpVersion;
  community?: string;
  v3_username?: string;
  v3_auth_protocol?: AuthProtocol;
  v3_auth_key?: string;
  v3_priv_protocol?: PrivProtocol;
  v3_priv_key?: string;
  v3_context?: string;
}

export interface DeviceCreatePayload extends SnmpTargetPayload {
  name: string;
  enabled?: boolean;
}

/** PATCH /api/devices/{id}: tylko zmienione pola; `null` czyści pole. */
export type DeviceUpdatePayload = Partial<{
  name: string;
  enabled: boolean;
  host: string;
  port: number;
  driver: DriverName;
  snmp_version: SnmpVersion;
  community: string | null;
  v3_username: string | null;
  v3_auth_protocol: AuthProtocol | null;
  v3_auth_key: string | null;
  v3_priv_protocol: PrivProtocol | null;
  v3_priv_key: string | null;
  v3_context: string | null;
}>;

export interface ProbeResult {
  driver: string;
  name: string | null;
  vendor: string | null;
  model: string | null;
  firmware: string | null;
  kind: string;
  uptime_s: number | null;
  interfaces: {
    if_index: number;
    name: string;
    label: string;
    alias: string | null;
    role: string;
    hidden: boolean;
    oper_status: string;
    speed_mbps: number | null;
  }[];
  wifi: { ssid: string; radio: string | null; channel: number | null; clients: number | null; hidden: boolean }[];
}

export interface UpdateVersionInfo {
  version: string | null;
  commit: string | null;
  branch?: string | null;
}

export interface UpdateCheck {
  current: UpdateVersionInfo;
  latest: UpdateVersionInfo;
  behind: number;
  ahead: number;
  diverged: boolean;
  update_available: boolean;
  changes: { sha: string; subject: string }[];
  checked_at: string | null;
}

export type UpdatePhaseStatus = "pending" | "running" | "done" | "failed" | "skipped";
export type UpdateJobState = "idle" | "running" | "ok" | "failed" | "rolled_back";

export interface UpdateJob {
  state: UpdateJobState;
  phase: string | null;
  phases: { id: string; status: UpdatePhaseStatus }[];
  started_at: string | null;
  finished_at: string | null;
  from_version: string | null;
  to_version: string | null;
  from_commit: string | null;
  to_commit: string | null;
  error: string | null;
  note: string | null;
  log: string[];
}

export interface UpdatesResponse {
  installed_version: string;
  updater: { configured: boolean; reachable: boolean; message: string | null };
  current: UpdateVersionInfo | null;
  info: UpdateCheck | null;
  job: UpdateJob | null;
}

/** Ustawienie instalacji: automatyczne sprawdzanie wydań raz w tygodniu (GET/PUT /api/updates/settings). */
export interface UpdateSettings {
  auto_check: boolean;
}
