/** OPNsense API (od 0.81.0): klucze przy urządzeniach OPNsense i dane z ostatniego odczytu (API: backend/netpulse/api/opnsense.py). */
import { useQuery } from "@tanstack/react-query";
import { get } from "./api";
import { useRefresh } from "./refresh";

export interface OpnsenseApiKey {
  id: number;
  device_id: number;
  device_name: string;
  host: string;
  port: number;
  /** Końcówka klucza („…ab12”) – sam klucz i sekret nie wracają z API */
  key_hint: string;
  verify_tls: boolean;
  enabled: boolean;
  status: string;
  version: string | null;
  latest_version: string | null;
  update_available: boolean;
  last_polled_at: string | null;
  last_ok_at: string | null;
  last_error: string | null;
  created_at: string;
}

export interface OpnsenseProbe {
  version: string | null;
  latest: string | null;
  update_available: boolean;
  gateways: number;
  /** Bramy z pomiarem (monitorowanie włączone w OPNsense) */
  monitored: number;
  interfaces: number;
  services: number;
  hosts: number;
  dhcp: string | null;
}

export interface OpnsenseGateway {
  name: string;
  address: string | null;
  monitor: string | null;
  status: string;
  /** null = brama bez monitorowania (OPNsense nic nie mierzy) */
  up: boolean | null;
  delay_ms: number | null;
  jitter_ms: number | null;
  loss_percent: number | null;
  interface: string | null;
  default: boolean;
}

export interface OpnsenseIface {
  device: string;
  identifier: string | null;
  description: string | null;
  status: string | null;
  link_type: string | null;
  addr4: string | null;
  gateways: string[];
  default_route: boolean;
}

export interface OpnsenseService {
  name: string;
  description: string;
  running: boolean;
}

export interface OpnsenseHost {
  mac: string;
  ip: string | null;
  hostname: string | null;
  interface: string | null;
  manufacturer: string | null;
  source: "dhcp" | "arp" | string;
  expires: number | null;
}

export interface OpnsenseDeviceData {
  configured: boolean;
  status: string | null;
  stale: boolean;
  version: string | null;
  latest_version: string | null;
  update_available: boolean;
  last_ok_at: string | null;
  last_error: string | null;
  dhcp: string | null;
  gateways: OpnsenseGateway[];
  interfaces: OpnsenseIface[];
  services: OpnsenseService[];
  hosts: OpnsenseHost[];
}

export const OPNSENSE_KEYS_KEY = ["opnsense", "apis"];

export function useOpnsenseKeys() {
  return useQuery({ queryKey: OPNSENSE_KEYS_KEY, queryFn: () => get<OpnsenseApiKey[]>("/api/opnsense/apis") });
}

export function useOpnsenseDevice(deviceId: number | null) {
  const { refetchInterval } = useRefresh();
  return useQuery({
    enabled: deviceId != null,
    queryKey: ["opnsense", "device", deviceId],
    queryFn: () => get<OpnsenseDeviceData>(`/api/opnsense/devices/${deviceId}`),
    refetchInterval,
  });
}

/** Urządzenie OPNsense: driver ustawiony albo wykryty przez kolektor SNMP. */
export const isOpnsense = (d: { driver: string; detected_driver: string | null }) => d.driver === "opnsense" || d.detected_driver === "opnsense";
