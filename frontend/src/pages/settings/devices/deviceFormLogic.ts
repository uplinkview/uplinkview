/**
 * Logika formularza urządzenia: wartości, walidacja i budowanie żądań do API.
 * Czyste funkcje (bez Reacta), żeby łatwo je testować. Reguły odpowiadają walidacji w backendzie
 * (backend/netpulse/api/schemas.py); to on ma ostatnie słowo, panel tylko oszczędza zbędne zapytania.
 */
import { t } from "../../../i18n";
import type {
  AuthProtocol,
  Device,
  DeviceCreatePayload,
  DeviceUpdatePayload,
  DriverName,
  PrivProtocol,
  SnmpTargetPayload,
  SnmpVersion,
} from "../../../lib/api";

export const DRIVERS: DriverName[] = ["auto", "generic", "unifi", "linux", "mikrotik", "omada", "opnsense"];
export const SNMP_VERSIONS: SnmpVersion[] = ["1", "2c", "3"];
export const AUTH_PROTOCOLS: AuthProtocol[] = ["MD5", "SHA", "SHA224", "SHA256", "SHA384", "SHA512"];
export const PRIV_PROTOCOLS: PrivProtocol[] = ["DES", "AES", "AES192", "AES256"];

const MIN_KEY = 8;

export interface DeviceFormValues {
  name: string;
  host: string;
  port: string;
  driver: DriverName;
  snmp_version: SnmpVersion;
  community: string;
  v3_username: string;
  v3_auth_protocol: AuthProtocol | "";
  v3_auth_key: string;
  v3_priv_protocol: PrivProtocol | "";
  v3_priv_key: string;
  v3_context: string;
}

export type FormErrors = Partial<Record<keyof DeviceFormValues, string>>;

export function emptyForm(): DeviceFormValues {
  return {
    name: "",
    host: "",
    port: "161",
    driver: "auto",
    snmp_version: "2c",
    community: "public",
    v3_username: "",
    v3_auth_protocol: "",
    v3_auth_key: "",
    v3_priv_protocol: "",
    v3_priv_key: "",
    v3_context: "",
  };
}

/** Formularz edycji. Sekrety (community, klucze SNMPv3) są puste – API ich nie zwraca; puste = bez zmian. */
export function formFromDevice(d: Device): DeviceFormValues {
  return {
    name: d.name,
    host: d.host,
    port: String(d.port),
    driver: (DRIVERS as string[]).includes(d.driver) ? (d.driver as DriverName) : "auto",
    snmp_version: (SNMP_VERSIONS as string[]).includes(d.snmp_version) ? (d.snmp_version as SnmpVersion) : "2c",
    community: "",
    v3_username: d.v3_username ?? "",
    v3_auth_protocol: (d.v3_auth_protocol as AuthProtocol | null) ?? "",
    v3_auth_key: "",
    v3_priv_protocol: (d.v3_priv_protocol as PrivProtocol | null) ?? "",
    v3_priv_key: "",
    v3_context: d.v3_context ?? "",
  };
}

const IPV4 = /^(25[0-5]|2[0-4]\d|1?\d?\d)(\.(25[0-5]|2[0-4]\d|1?\d?\d)){3}$/;
const HOSTNAME = /^(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$/;

export function isValidHost(host: string): boolean {
  const h = host.trim();
  // IPv6 (dwukropki) sprawdza backend; tu przepuszczamy, żeby nie odrzucić poprawnego adresu
  return IPV4.test(h) || HOSTNAME.test(h) || (h.includes(":") && /^[0-9A-Fa-f:.]+$/.test(h));
}

export function parsePort(port: string): number | null {
  if (!/^\d+$/.test(port.trim())) return null;
  const n = Number(port);
  return n >= 1 && n <= 65535 ? n : null;
}

/**
 * Walidacja formularza. `original` ustawione = edycja: puste sekrety oznaczają „bez zmian”, więc
 * pola, które już mają wartość w bazie (np. community), nie są wymagane ponownie.
 */
export function validate(v: DeviceFormValues, original?: Device): FormErrors {
  const e: FormErrors = {};
  if (!v.name.trim()) e.name = t("devform.err.name");
  if (!v.host.trim()) e.host = t("devform.err.hostRequired");
  else if (!isValidHost(v.host)) e.host = t("devform.err.host");
  if (parsePort(v.port) === null) e.port = t("devform.err.port");

  const wasV3 = original?.snmp_version === "3";
  const wasCommunity = original !== undefined && original.snmp_version !== "3";

  if (v.snmp_version !== "3") {
    // Przy edycji urządzenia, które już jest na v1/v2c, community jest zapisane (puste pole = bez zmian)
    if (!v.community.trim() && !wasCommunity) {
      e.community = t("devform.err.community");
    }
    return e;
  }

  if (!v.v3_username.trim()) e.v3_username = t("devform.err.v3user");
  // Klucz wymagany, gdy wybrano protokół, którego jeszcze nie było w bazie; przy edycji pusty = bez zmian
  const hadAuth = wasV3 && !!original?.v3_auth_protocol && v.v3_auth_protocol === original.v3_auth_protocol;
  const hadPriv = wasV3 && !!original?.v3_priv_protocol && v.v3_priv_protocol === original.v3_priv_protocol;
  if (v.v3_auth_protocol && !v.v3_auth_key && !hadAuth) e.v3_auth_key = t("devform.err.key");
  if (v.v3_priv_protocol && !v.v3_priv_key && !hadPriv) e.v3_priv_key = t("devform.err.key");
  if (v.v3_auth_key && !v.v3_auth_protocol) e.v3_auth_protocol = t("devform.err.protocol");
  if (v.v3_priv_key && !v.v3_priv_protocol) e.v3_priv_protocol = t("devform.err.protocol");
  if (v.v3_priv_protocol && !v.v3_auth_protocol) e.v3_priv_protocol = t("devform.err.privNeedsAuth");
  if (v.v3_auth_key && v.v3_auth_key.length < MIN_KEY) e.v3_auth_key = t("devform.err.keyShort");
  if (v.v3_priv_key && v.v3_priv_key.length < MIN_KEY) e.v3_priv_key = t("devform.err.keyShort");
  return e;
}

/** Dane połączenia (bez nazwy) – do testu SNMP i dodawania. Puste pola są pomijane. */
export function buildTarget(v: DeviceFormValues): SnmpTargetPayload {
  const target: SnmpTargetPayload = {
    host: v.host.trim(),
    port: parsePort(v.port) ?? 161,
    driver: v.driver,
    snmp_version: v.snmp_version,
  };
  if (v.snmp_version !== "3") {
    target.community = v.community.trim();
    return target;
  }
  target.v3_username = v.v3_username.trim();
  if (v.v3_auth_protocol) target.v3_auth_protocol = v.v3_auth_protocol;
  if (v.v3_auth_key) target.v3_auth_key = v.v3_auth_key;
  if (v.v3_priv_protocol) target.v3_priv_protocol = v.v3_priv_protocol;
  if (v.v3_priv_key) target.v3_priv_key = v.v3_priv_key;
  if (v.v3_context.trim()) target.v3_context = v.v3_context.trim();
  return target;
}

export function buildCreate(v: DeviceFormValues): DeviceCreatePayload {
  return { name: v.name.trim(), ...buildTarget(v) };
}

/**
 * PATCH: tylko pola, które się zmieniły. Sekrety trafiają do żądania wyłącznie, gdy użytkownik je wpisał.
 * Wyczyszczenie protokołu SNMPv3 czyści też jego klucz (backend wymaga pary).
 */
export function buildPatch(v: DeviceFormValues, original: Device): DeviceUpdatePayload {
  const patch: DeviceUpdatePayload = {};
  if (v.name.trim() !== original.name) patch.name = v.name.trim();
  if (v.host.trim() !== original.host) patch.host = v.host.trim();
  const port = parsePort(v.port);
  if (port !== null && port !== original.port) patch.port = port;
  if (v.driver !== original.driver) patch.driver = v.driver;
  if (v.snmp_version !== original.snmp_version) patch.snmp_version = v.snmp_version;

  if (v.snmp_version !== "3") {
    if (v.community.trim()) patch.community = v.community.trim();
    return patch;
  }

  if (v.v3_username.trim() !== (original.v3_username ?? "")) patch.v3_username = v.v3_username.trim();
  if (v.v3_context.trim() !== (original.v3_context ?? "")) patch.v3_context = v.v3_context.trim() || null;

  const authBefore = original.v3_auth_protocol ?? "";
  if (v.v3_auth_protocol !== authBefore) {
    patch.v3_auth_protocol = v.v3_auth_protocol || null;
    if (!v.v3_auth_protocol) patch.v3_auth_key = null;
  }
  if (v.v3_auth_key) patch.v3_auth_key = v.v3_auth_key;

  const privBefore = original.v3_priv_protocol ?? "";
  if (v.v3_priv_protocol !== privBefore) {
    patch.v3_priv_protocol = v.v3_priv_protocol || null;
    if (!v.v3_priv_protocol) patch.v3_priv_key = null;
  }
  if (v.v3_priv_key) patch.v3_priv_key = v.v3_priv_key;
  return patch;
}

export function isEmptyPatch(patch: DeviceUpdatePayload): boolean {
  return Object.keys(patch).length === 0;
}
