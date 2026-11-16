/** Role kont (od 0.61.0, backend: api/security.py ROLE_RULES): administrator – wszystko; operator – podgląd,
 *  potwierdzanie alertów; podgląd – tylko odczyt (plus własne hasło, odświeżanie i pulpity). */
import { useAuth } from "../auth/AuthProvider";
import type { TextKey } from "../i18n";

export type Role = "admin" | "operator" | "viewer";
export const ROLES: Role[] = ["admin", "operator", "viewer"];
const RANK: Record<Role, number> = { viewer: 0, operator: 1, admin: 2 };

export const ROLE_LABEL: Record<Role, TextKey> = { admin: "user.role.admin", operator: "user.role.operator", viewer: "user.role.viewer" };

/** Rola z odpowiedzi API; starsze API (bez `role`) – z `is_admin`. */
export function roleOf(user: { role?: string; is_admin: boolean } | null | undefined): Role {
  if (!user) return "viewer";
  if (user.role === "admin" || user.role === "operator" || user.role === "viewer") return user.role;
  return user.is_admin ? "admin" : "viewer";
}

export function hasRole(role: Role, need: Role): boolean {
  return RANK[role] >= RANK[need];
}

/** Czy zalogowany użytkownik ma co najmniej rolę `need`. */
export function useCan(need: Role): boolean {
  return hasRole(roleOf(useAuth().status?.user), need);
}
