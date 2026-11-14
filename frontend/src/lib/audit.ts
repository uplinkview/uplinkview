/** Konta i dziennik zdarzeń (od 0.61.0, backend: api/users.py, audit.py). */
import { useQuery } from "@tanstack/react-query";
import { t, type TextKey } from "../i18n";
import { get, type User } from "./api";

export const USERS_KEY = ["users"] as const;
export const AUDIT_KEY = ["audit"] as const;

export type AuditKind = "all" | "auth" | "changes" | "denied";

export interface AuditEntry {
  id: number;
  time: string;
  user_id: number | null;
  username: string | null;
  ip: string | null;
  action: string;
  target: string | null;
  status: number | null;
  detail: string | null;
}

export interface AuditPage {
  items: AuditEntry[];
  total: number;
}

export const useUsers = () => useQuery({ queryKey: USERS_KEY, queryFn: () => get<User[]>("/api/users") });

export function useAudit(kind: AuditKind, q: string, offset: number, limit = 50) {
  const params = new URLSearchParams({ kind, limit: String(limit), offset: String(offset) });
  if (q.trim()) params.set("q", q.trim());
  return useQuery({
    queryKey: [...AUDIT_KEY, kind, q.trim(), offset, limit],
    queryFn: () => get<AuditPage>(`/api/audit?${params}`),
    placeholderData: (prev) => prev,
  });
}

const AUTH_ACTIONS = ["setup", "login", "login_failed", "logout", "password", "totp_enable", "totp_disable", "totp_recovery"];

/** Zasoby z pierwszego członu ścieżki API (szablon trasy, np. /api/devices/{device_id}) – nazwy w `audit.res.*`. */
const RESOURCES = [
  "devices", "interfaces", "alert-rules", "alerts", "maintenance", "users", "dashboards", "dashboard", "checks", "controllers",
  "notification-channels", "backups", "modules", "updates", "wan", "agents", "proxmox", "opnsense", "preferences", "system", "probe",
];

const VERBS: Record<string, TextKey> = { POST: "audit.verb.add", PUT: "audit.verb.change", PATCH: "audit.verb.change", DELETE: "audit.verb.delete" };

/** Czytelny opis wpisu: „Usunięcie: urządzenie”, „Potwierdzenie alertu”, „Logowanie”. */
export function auditLabel(action: string): string {
  if (AUTH_ACTIONS.includes(action)) return t(`audit.auth.${action}` as TextKey);
  const [method, path = ""] = action.split(" ", 2);
  const parts = path.replace(/^\/api\//, "").split("/").filter(Boolean);
  const resource =
    parts[0] === "system" && parts[1] === "tls"
      ? t("audit.res.tls")
      : RESOURCES.includes(parts[0])
        ? t(`audit.res.${parts[0]}` as TextKey)
        : (parts[0] ?? path);
  const last = parts[parts.length - 1];
  if (last === "ack") return t("audit.ack");
  if (last === "probe" || last === "test") return t("audit.test", { resource });
  const verb = VERBS[method];
  return verb ? `${t(verb)}: ${resource}` : action;
}

/** Odrzucona albo nieudana operacja (pokazujemy na czerwono). */
export const auditFailed = (e: AuditEntry) => e.action === "login_failed" || (e.status != null && e.status >= 400);
