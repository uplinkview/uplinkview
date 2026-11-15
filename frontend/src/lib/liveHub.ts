/**
 * Wspólny kanał na żywo (od 0.45.0): jedno połączenie WebSocket `/api/live/device` na urządzenie dla całej strony,
 * niezależnie od liczby widgetów, które z niego korzystają. Połączenie istnieje, dopóki ktoś ogląda; po zerwaniu
 * wraca samo co kilka sekund. Przełącznik „Na żywo” w pasku górnym (zapamiętany w przeglądarce) wstrzymuje wszystko –
 * widgety pokazują wtedy odczyty kolektora (co 30 s). Na pulpicie publicznym kanału nie ma (wymaga logowania).
 */
import { useQuery } from "@tanstack/react-query";
import { useContext, useEffect, useRef, useSyncExternalStore } from "react";
import { get, type Device } from "./api";
import { liveUrl, parseSample, type LiveSample, type LiveStatus } from "./live";
import { PublicModeContext } from "./publicMode";

const STORAGE_KEY = "netpulse.live";
const RETRY_MS = 5_000;
const CLOSE_GRACE_MS = 2_000;

// --- przełącznik ---------------------------------------------------------------------------------

const toggleListeners = new Set<() => void>();

function readEnabled(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) !== "off";
  } catch {
    return true;
  }
}

let enabled = readEnabled();

export function setLiveEnabled(on: boolean): void {
  enabled = on;
  try {
    localStorage.setItem(STORAGE_KEY, on ? "on" : "off");
  } catch {
    /* bez zapamiętywania */
  }
  toggleListeners.forEach((l) => l());
}

/** Czy dane na żywo są włączone (przełącznik w pasku górnym; na pulpicie publicznym zawsze nie). */
export function useLiveEnabled(): boolean {
  const isPublic = useContext(PublicModeContext);
  const on = useSyncExternalStore(
    (l) => {
      toggleListeners.add(l);
      return () => toggleListeners.delete(l);
    },
    () => enabled,
  );
  return on && !isPublic;
}

// --- połączenia ------------------------------------------------------------------------------------

export interface LiveState {
  status: LiveStatus;
  sample: LiveSample | null;
}

/** Stan dowolnego kanału na żywo (urządzenie, od 0.72.0 też VPN). */
export interface ChannelState<T> {
  status: LiveStatus;
  sample: T | null;
}

interface Entry {
  refs: number;
  state: ChannelState<unknown>;
  path: string;
  parse: (raw: unknown) => unknown;
  ws: WebSocket | null;
  listeners: Set<() => void>;
  retry: ReturnType<typeof setTimeout> | null;
  closing: ReturnType<typeof setTimeout> | null;
}

const IDLE: ChannelState<never> = { status: "connecting", sample: null };
const entries = new Map<string, Entry>();

function entry(key: string, path: string, parse: (raw: unknown) => unknown): Entry {
  let e = entries.get(key);
  if (!e) {
    e = { refs: 0, state: IDLE, path, parse, ws: null, listeners: new Set(), retry: null, closing: null };
    entries.set(key, e);
  }
  return e;
}

function emit(e: Entry, state: ChannelState<unknown>) {
  e.state = state;
  e.listeners.forEach((l) => l());
}

function connect(key: string, e: Entry) {
  if (e.ws || typeof WebSocket === "undefined") return;
  const ws = new WebSocket(liveUrl(window.location, e.path));
  e.ws = ws;
  ws.onmessage = (msg) => {
    try {
      emit(e, { status: "live", sample: e.parse(JSON.parse(String(msg.data))) });
    } catch {
      /* uszkodzona wiadomość – pomijamy */
    }
  };
  const lost = () => {
    if (e.ws !== ws) return;
    e.ws = null;
    emit(e, { status: "lost", sample: null });
    if (e.refs > 0 && !e.retry) {
      e.retry = setTimeout(() => {
        e.retry = null;
        if (e.refs > 0) connect(key, e);
      }, RETRY_MS);
    }
  };
  ws.onclose = lost;
  ws.onerror = lost;
}

function release(key: string, e: Entry) {
  e.refs -= 1;
  if (e.refs > 0) return;
  // Chwila zwłoki: przy przełączaniu stron i przerysowaniu widgetów połączenie nie jest zamykane i otwierane od nowa
  e.closing = setTimeout(() => {
    e.closing = null;
    if (e.refs > 0) return;
    if (e.retry) clearTimeout(e.retry);
    e.retry = null;
    const ws = e.ws;
    e.ws = null;
    ws?.close();
    e.state = IDLE;
    entries.delete(key);
  }, CLOSE_GRACE_MS);
}

/**
 * Najnowsza próbka urządzenia z kanału na żywo albo `null` (wyłączone, pulpit publiczny, brak połączenia,
 * urządzenie bez SNMP). Wiele widgetów tego samego urządzenia dzieli jedno połączenie.
 */
export function useLiveSample(deviceId: number | null | undefined, want = true): LiveState | null {
  return useLiveChannel(deviceId != null ? `d:${deviceId}` : null, `/api/live/device?device=${deviceId}`, parseSample as (raw: unknown) => LiveSample, want);
}

/** Wspólny kanał `key` (jedno połączenie na stronę) – `null`, gdy wyłączony albo niepotrzebny. */
function useLiveChannel<T>(key: string | null, path: string, parse: (raw: unknown) => T, want: boolean): ChannelState<T> | null {
  const on = useLiveEnabled();
  const id = on && want && key != null ? key : null;
  useEffect(() => {
    if (id == null) return;
    const e = entry(id, path, parse);
    if (e.closing) clearTimeout(e.closing);
    e.closing = null;
    e.refs += 1;
    connect(id, e);
    return () => release(id, e);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- ścieżka i parser są stałe dla klucza
  }, [id]);
  const state = useSyncExternalStore(
    (l) => {
      if (id == null) return () => {};
      const e = entry(id, path, parse);
      e.listeners.add(l);
      return () => e.listeners.delete(l);
    },
    () => (id == null ? null : ((entries.get(id)?.state ?? IDLE) as ChannelState<T>)),
  );
  return state;
}

// --- VPN (od 0.72.0) --------------------------------------------------------------------------------

export interface LiveVpnUser {
  name: string;
  since: string | null;
  remote_ip: string | null;
  tunnel_ip: string | null;
  down_bps: number | null;
  up_bps: number | null;
  down_bytes: number | null;
  up_bytes: number | null;
}

export interface LiveVpn {
  time: string;
  /** Czy któryś kontroler odpowiedział – bez tego lista połączeń nic nie znaczy */
  ok: boolean;
  users: LiveVpnUser[];
}

const num = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);
const str = (v: unknown): string | null => (typeof v === "string" ? v : null);

export function parseVpn(raw: unknown): LiveVpn {
  const r = (raw ?? {}) as { time?: unknown; ok?: unknown; users?: unknown };
  const users = Array.isArray(r.users) ? r.users : [];
  return {
    time: str(r.time) ?? "",
    ok: r.ok === true,
    users: users
      .filter((u): u is Record<string, unknown> => !!u && typeof u === "object" && typeof (u as { name?: unknown }).name === "string")
      .map((u) => ({
        name: u.name as string,
        since: str(u.since),
        remote_ip: str(u.remote_ip),
        tunnel_ip: str(u.tunnel_ip),
        down_bps: num(u.down_bps),
        up_bps: num(u.up_bps),
        down_bytes: num(u.down_bytes),
        up_bytes: num(u.up_bytes),
      })),
  };
}

/** Trwające połączenia VPN z kontrolerów co ~1,5 s (`null` = wyłączone albo brak świeżej próbki z kontrolera). */
export function useLiveVpn(want = true): LiveVpn | null {
  const state = useLiveChannel("vpn", "/api/live/vpn", parseVpn, want);
  return state?.status === "live" && state.sample?.ok ? state.sample : null;
}

/** Wartość z próbki tylko wtedy, gdy jest świeża („live”) i ją zawiera. */
export function liveValue(state: LiveState | null, pick: (s: LiveSample) => number | null | undefined): number | null {
  if (!state || state.status !== "live" || !state.sample) return null;
  const v = pick(state.sample);
  return v == null || !Number.isFinite(v) ? null : v;
}

/** Urządzenia bez SNMP (agent wysyła co 30 s, urządzenia UniFi z oficjalnego API) – kanał na żywo nic dla nich nie ma. */
const NON_SNMP = new Set(["agent", "unifi_api"]);

/** Jak `useLiveSample`, ale tylko dla działających urządzeń odpytywanych przez SNMP (lista urządzeń z pamięci podręcznej). */
export function useLiveDeviceSample(deviceId: number | null | undefined, want = true): LiveState | null {
  const on = useLiveEnabled();
  const devices = useQuery({ queryKey: ["devices"], queryFn: () => get<Device[]>("/api/devices"), enabled: on && want && deviceId != null });
  const device = devices.data?.find((d) => d.id === deviceId);
  // Tylko urządzenia, które odpowiadają – do wyłączonego nie ma sensu pytać co 1,5 s (wróci po następnym cyklu kolektora)
  return useLiveSample(deviceId, want && !!device && device.enabled && device.status === "up" && !NON_SNMP.has(device.driver));
}

/** Próbki kilku urządzeń naraz (od 0.72.0, np. mapa sieci): urządzenie → stan kanału. Tylko działające urządzenia SNMP. */
export function useLiveDeviceSamples(deviceIds: number[], want = true): Map<number, LiveState> {
  const on = useLiveEnabled();
  const devices = useQuery({ queryKey: ["devices"], queryFn: () => get<Device[]>("/api/devices"), enabled: on && want && deviceIds.length > 0 });
  const usable = new Set((devices.data ?? []).filter((d) => d.enabled && d.status === "up" && !NON_SNMP.has(d.driver)).map((d) => d.id));
  const ids = on && want ? [...new Set(deviceIds)].filter((id) => usable.has(id)).sort((a, b) => a - b) : [];
  const idsKey = ids.join(",");
  useEffect(() => {
    const keys = idsKey ? idsKey.split(",").map(Number) : [];
    const used = keys.map((id) => {
      const key = `d:${id}`;
      const e = entry(key, `/api/live/device?device=${id}`, parseSample as (raw: unknown) => LiveSample);
      if (e.closing) clearTimeout(e.closing);
      e.closing = null;
      e.refs += 1;
      connect(key, e);
      return [key, e] as const;
    });
    return () => used.forEach(([key, e]) => release(key, e));
  }, [idsKey]);
  const cache = useRef<{ states: (ChannelState<unknown> | undefined)[]; map: Map<number, LiveState> }>({ states: [], map: new Map() });
  return useSyncExternalStore(
    (l) => {
      const subs = ids.map((id) => entry(`d:${id}`, `/api/live/device?device=${id}`, parseSample as (raw: unknown) => LiveSample));
      subs.forEach((e) => e.listeners.add(l));
      return () => subs.forEach((e) => e.listeners.delete(l));
    },
    () => {
      const states = ids.map((id) => entries.get(`d:${id}`)?.state);
      const prev = cache.current;
      if (states.length === prev.states.length && states.every((s, i) => s === prev.states[i])) return prev.map;
      const map = new Map<number, LiveState>();
      ids.forEach((id, i) => {
        if (states[i]) map.set(id, states[i] as LiveState);
      });
      cache.current = { states, map };
      return map;
    },
  );
}

/** Testy: zamyka wszystkie połączenia i zapomina stan (moduł żyje między testami). */
export function resetLiveHub(): void {
  for (const e of entries.values()) {
    if (e.retry) clearTimeout(e.retry);
    if (e.closing) clearTimeout(e.closing);
    e.ws?.close();
  }
  entries.clear();
  enabled = readEnabled();
}
