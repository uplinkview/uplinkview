/** Moduły (Ustawienia → Moduły): które integracje są włączone (API: backend/netpulse/api/modules_api.py). */
import { useQuery } from "@tanstack/react-query";
import { get } from "./api";

export type ModuleId = "proxmox" | "unifi" | "opnsense" | "agents" | "backups";
export const MODULE_IDS: ModuleId[] = ["proxmox", "unifi", "opnsense", "agents", "backups"];
export type Modules = Record<ModuleId, boolean>;

export const MODULES_KEY = ["modules"];

export function useModules() {
  return useQuery({ queryKey: MODULES_KEY, queryFn: () => get<Modules>("/api/modules"), staleTime: 60_000 });
}

/** Moduł włączony? Zanim odpowiedź przyjdzie (albo gdy API jej nie zna), traktujemy go jak włączony. */
export function isOn(mods: Modules | undefined, id: ModuleId | undefined | null): boolean {
  return !id || !mods || mods[id] !== false;
}

/** Źródła wykresów i rodzaje reguł należące do modułów – ukrywane, gdy moduł jest wyłączony. */
export function sourceModule(kind: string): ModuleId | null {
  if (kind === "pve_guest") return "proxmox";
  if (kind.startsWith("agent_")) return "agents";
  if (kind === "wan_ping") return "unifi"; // pingi bramy z kontrolera UniFi; wan_latency – UniFi albo OPNsense (od 0.81.0)
  if (kind === "speedtest") return "unifi"; // testy prędkości bramy z kontrolera UniFi (od 0.70.0)
  if (kind === "vpn") return "unifi"; // klienci VPN bramy z kontrolera UniFi (od 0.57.0)
  if (kind === "lan_client") return "opnsense"; // ruch urządzeń w sieci za OPNsense (od 0.83.0)
  return null;
}

export function ruleModule(kind: string, metric?: string | null): ModuleId | null {
  if (kind === "container_stopped" || kind === "service_failed" || kind === "smart_failed") return "agents";
  if (kind === "guest_stopped" || kind === "backup_failed") return "proxmox";
  if (kind === "vpn_connect") return "unifi";
  if (kind === "gateway_down" || kind === "opnsense_service_failed") return "opnsense";
  if (kind === "metric" && metric === "wan_loss_percent") return "opnsense";
  if (kind === "metric" && metric === "smart_reallocated") return "agents"; // temperatura: też czujniki MikroTika (SNMP)
  if (kind === "metric" && metric === "backup_age_h") return "proxmox";
  return null;
}
