/** Strony szczegółów urządzenia i portu: dane z API (backend/netpulse/api/devices.py, availability.py). */
import { useQuery } from "@tanstack/react-query";
import { get, type Device } from "./api";
import { useRefresh } from "./refresh";
import { numberFormat } from "./intl";

export interface InterfaceItem {
  id: number;
  if_index: number;
  name: string;
  label: string;
  alias: string | null;
  role: string;
  hidden: boolean;
  mac: string | null;
  admin_up: boolean | null;
  oper_status: string;
  speed_mbps: number | null;
  in_bps: number | null;
  out_bps: number | null;
}

export interface InterfaceDetail extends InterfaceItem {
  device_id: number;
  device_name: string;
  device_kind: string;
  last_seen_at: string | null;
  /** Numer portu PoE z kontrolera UniFi; null = port bez PoE */
  poe_port_idx: number | null;
}

export interface WifiItem {
  id: number;
  key: string;
  ssid: string;
  radio: string | null;
  channel: number | null;
  bssid: string | null;
  hidden: boolean;
  clients: number | null;
}

export interface AvailabilityDay {
  day: string;
  percent: number | null;
  samples: number;
}

export interface Availability {
  days: number;
  /** null = brak próbek w okresie */
  percent: number | null;
  samples: number;
  /** Przybliżony czas niedostępności w sekundach */
  down_s: number;
  daily: AvailabilityDay[];
}

export interface DeviceAvailability {
  device_id: number;
  percent: number | null;
  samples: number;
}

export type AvailabilityKind = "devices" | "interfaces";
/** Okresy dostępności pokazywane na stronach szczegółów. */
export const AVAILABILITY_PERIODS = [1, 7, 30, 365] as const;

export function useDevice(id: number) {
  const { refetchInterval } = useRefresh();
  return useQuery({ queryKey: ["device", id], queryFn: () => get<Device>(`/api/devices/${id}`), refetchInterval, retry: false });
}

export function useInterfaces(deviceId: number) {
  const { refetchInterval } = useRefresh();
  return useQuery({
    queryKey: ["device-interfaces", deviceId],
    queryFn: () => get<InterfaceItem[]>(`/api/devices/${deviceId}/interfaces`),
    refetchInterval,
  });
}

export function useWifiNetworks(deviceId: number) {
  const { refetchInterval } = useRefresh();
  return useQuery({ queryKey: ["device-wifi", deviceId], queryFn: () => get<WifiItem[]>(`/api/devices/${deviceId}/wifi`), refetchInterval });
}

/** Czujniki, PoE i SFP urządzenia SNMP (od 0.50.0: MikroTik), ostatnie wartości. */
export interface SensorsData {
  sensors: { key: string; metric: string; value: number }[];
  poe: { port: string; state: number | null; power_w: number | null; voltage_v: number | null }[];
  sfp: {
    port: string;
    rx_dbm: number | null;
    tx_dbm: number | null;
    temp_c: number | null;
    voltage_v: number | null;
    rx_loss: boolean | null;
    tx_fault: boolean | null;
  }[];
}

export function useSensors(deviceId: number) {
  const { refetchInterval } = useRefresh();
  return useQuery({ queryKey: ["device-sensors", deviceId], queryFn: () => get<SensorsData>(`/api/devices/${deviceId}/sensors`), refetchInterval });
}

export function useInterface(id: number) {
  const { refetchInterval } = useRefresh();
  return useQuery({ queryKey: ["interface", id], queryFn: () => get<InterfaceDetail>(`/api/interfaces/${id}`), refetchInterval, retry: false });
}

/** Dostępność urządzenia albo portu za ostatnie `days` dni (odświeżana rzadziej niż wykresy). */
export function useAvailability(kind: AvailabilityKind, id: number, days: number) {
  return useQuery({
    queryKey: ["availability", kind, id, days],
    queryFn: () => get<Availability>(`/api/${kind}/${id}/availability?days=${days}`),
    refetchInterval: 5 * 60_000,
  });
}

/** Dostępność wszystkich urządzeń (karty na pulpicie): {id urządzenia: %}. */
export function useDevicesAvailability(days = 30, enabled = true) {
  return useQuery({
    enabled,
    queryKey: ["availability", "all", days],
    queryFn: () => get<DeviceAvailability[]>(`/api/availability?days=${days}`),
    select: (rows) => Object.fromEntries(rows.map((r) => [r.device_id, r.percent])) as Record<number, number | null>,
    refetchInterval: 5 * 60_000,
  });
}

/** „1000 Mb/s” albo „1 Gb/s”; brak → „–”. */
export function formatSpeed(mbps: number | null): string {
  if (mbps == null || mbps <= 0) return "–";
  return mbps >= 1000 ? `${numberFormat({ maximumFractionDigits: 1 }).format(mbps / 1000)} Gb/s` : `${mbps} Mb/s`;
}
