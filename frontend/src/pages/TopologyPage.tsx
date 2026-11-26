/**
 * Mapa sieci (od 0.88.0 pełny widok): łącza WAN → brama → switche i access pointy → klienci po kablu, Wi-Fi (według
 * sieci i pasma) i WireGuard. Klik w węzeł pokazuje szczegóły i jego drogę do Internetu. Model i układ: `lib/netmap.ts`.
 */
import {
  IconAccessPoint,
  IconArrowsHorizontal,
  IconArrowsMinimize,
  IconArrowsUpDown,
  IconArrowsVertical,
  IconDeviceDesktop,
  IconDeviceMobile,
  IconMinus,
  IconNetwork,
  IconPlus,
  IconQuestionMark,
  IconRouter,
  IconSearch,
  IconShieldLock,
  IconWifi,
  IconWorld,
  IconX,
} from "@tabler/icons-react";
import { useEffect, useMemo, useRef, useState, type PointerEvent, type ReactNode } from "react";
import { Link } from "react-router";
import { Card, ErrorNote, PageHeader } from "../components/ui";
import { t, type TextKey } from "../i18n";
import { formatBps, formatUptime, relativeTime } from "../lib/format";
import {
  bandLabel,
  buildNetMap,
  isVisible,
  labelPoint,
  layoutNetMap,
  linkPath,
  matchesQuery,
  pathToInternet,
  summarize,
  SSID_HEADER_H,
  SSID_ROW_H,
  type Box,
  type ConnFilter,
  type MapNode,
  type NetMap,
  type Orientation,
} from "../lib/netmap";
import { useLiveDeviceSamples, useLiveVpn } from "../lib/liveHub";
import { useDevices } from "../lib/queries";
import { useRefresh } from "../lib/refresh";
import { fitScale, loadLevel, speedLabel, useTopology, withLiveEdges, zoomAt, type LoadLevel, type TopologyEdge } from "../lib/topology";
import { formatLinkRate, signalQuality, useClients, type NetworkClient } from "../lib/unifi";
import { useVpn, withLiveVpn } from "../lib/vpn";
import { useWanStatus, type WanLink } from "../lib/wan";
import type { Device } from "../lib/api";

const KIND_ICON = { gateway: IconRouter, switch: IconNetwork, ap: IconAccessPoint } as const;
const KIND_LABEL: Record<string, TextKey> = {
  gateway: "dash.kind.gateway",
  switch: "dash.kind.switch",
  ap: "dash.kind.ap",
  other: "dash.kind.other",
};
const STATUS_DOT: Record<string, string> = { up: "bg-success", down: "bg-danger", unknown: "bg-muted" };
const STATUS_LABEL: Record<string, TextKey> = {
  up: "dash.status.up",
  down: "dash.status.down",
  unknown: "dash.status.unknown",
};
const WAN_STATE: Record<string, TextKey> = {
  active: "netmap.wan.active",
  standby: "netmap.wan.standby",
  down: "netmap.wan.down",
  unknown: "netmap.wan.unknown",
};
const SIGNAL_TEXT = { great: "text-success", good: "text-success", fair: "text-warning", weak: "text-danger" } as const;
const SIGNAL_LABEL: Record<string, TextKey> = {
  great: "clients.signal.great",
  good: "clients.signal.good",
  fair: "clients.signal.fair",
  weak: "clients.signal.weak",
};
const FILTERS: { id: ConnFilter; label: TextKey }[] = [
  { id: "all", label: "netmap.filter.all" },
  { id: "cable", label: "netmap.filter.cable" },
  { id: "wifi", label: "netmap.filter.wifi" },
  { id: "vpn", label: "netmap.filter.vpn" },
];
const ORIENTATION_KEY = "netpulse.topology.orientation";

function readOrientation(): Orientation | null {
  try {
    const v = localStorage.getItem(ORIENTATION_KEY);
    return v === "vertical" || v === "horizontal" ? v : null;
  } catch {
    return null;
  }
}

const LOAD_STROKE: Record<LoadLevel, string> = {
  none: "var(--border-strong)",
  low: "var(--success)",
  mid: "var(--warning)",
  high: "var(--danger)",
};
const LOAD_LABEL: Record<Exclude<LoadLevel, "none">, TextKey> = { low: "topo.load.low", mid: "topo.load.mid", high: "topo.load.high" };

interface Stroke {
  stroke: string;
  width: number;
  dash?: string;
}

/** Wygląd linii: kabel w kolorze obciążenia, Wi-Fi kropkami, VPN kreskami, WAN – stanem łącza; droga wybranego – akcentem. */
function linkStroke(n: MapNode, onPath: boolean): Stroke {
  if (n.kind === "wan" || n.kind === "internet") {
    const state = n.wan?.state ?? "active";
    if (state === "down") return { stroke: "var(--danger)", width: 2, dash: "6 6" };
    if (state !== "active") return { stroke: "var(--border-strong)", width: 2, dash: "6 6" };
    return { stroke: "var(--accent)", width: 3 };
  }
  if (!n.online) return { stroke: "var(--border-strong)", width: 2, dash: "3 6" };
  if (n.link === "wifi") return { stroke: onPath ? "var(--accent)" : "var(--state-up)", width: 3, dash: "1 6" };
  if (n.link === "vpn") return { stroke: "var(--chart-2)", width: onPath ? 3 : 2, dash: "6 5" };
  if (onPath) return { stroke: "var(--accent)", width: 3 };
  const level = loadLevel(n.edge?.utilization);
  return { stroke: LOAD_STROKE[level], width: level === "none" ? 2 : 2.5 + 3 * (n.edge?.utilization ?? 0) };
}

function StatusDot({ status }: { status: string }) {
  const s = status in STATUS_DOT ? status : "unknown";
  return <span role="img" aria-label={t(STATUS_LABEL[s])} title={t(STATUS_LABEL[s])} className={`inline-block size-2 shrink-0 rounded-full ${STATUS_DOT[s]}`} />;
}

/** Plakietka w karcie: krótka wartość (ruch, liczba klientów). */
function Chip({ children, title }: { children: ReactNode; title?: string }) {
  return (
    <span title={title} className="inline-flex items-center gap-1 rounded-full bg-surface-2 px-2 py-0.5 text-[11px] font-medium tabular-nums text-text-2">
      {children}
    </span>
  );
}

type Tone = "normal" | "down" | "offline" | "wifi" | "vpn";
const TONE: Record<Tone, string> = {
  normal: "border-border bg-surface",
  down: "border-dashed border-danger bg-danger-soft",
  offline: "border-dashed border-border-strong bg-surface-2 text-muted",
  wifi: "border-dashed border-border-strong bg-accent-soft/50",
  vpn: "border-border bg-surface",
};

/** Karta węzła: cała karta wybiera węzeł (przycisk pod treścią), linki w treści działają osobno. */
function Shell({ box, tone, label, selected, dim, onSelect, children }: { box: Box; tone: Tone; label: string; selected: boolean; dim: boolean; onSelect: () => void; children: ReactNode }) {
  return (
    <div
      className={`absolute rounded-xl border shadow-[var(--shadow-card)] transition-opacity ${TONE[tone]}`}
      style={{
        left: box.x,
        top: box.y,
        width: box.w,
        height: box.h,
        opacity: dim ? 0.35 : 1,
        borderColor: selected ? "var(--accent)" : undefined,
        boxShadow: selected ? "0 0 0 4px var(--ring)" : undefined,
      }}
    >
      <button type="button" aria-label={label} aria-pressed={selected} title={label} onClick={onSelect} className="absolute inset-0 cursor-pointer rounded-xl" />
      <div className="pointer-events-none relative flex h-full min-w-0 gap-2.5 overflow-hidden p-3 text-xs leading-4">{children}</div>
    </div>
  );
}

const ICON = "mt-px shrink-0 text-text-2";

interface Counts {
  wired: number;
  wifi: number;
}

interface CardProps {
  node: MapNode;
  box: Box;
  counts: Map<string, Counts>;
  wanTotals: { in: number | null; out: number | null };
  selected: boolean;
  selectedMac: string | null;
  dim: boolean;
  query: string;
  onSelect: (mac?: string) => void;
}

function NodeCard({ node, box, counts, wanTotals, selected, selectedMac, dim, query, onSelect }: CardProps) {
  const label = t("netmap.select", { name: nodeName(node) });
  const shell = (tone: Tone, children: ReactNode) => (
    <Shell box={box} tone={tone} label={label} selected={selected && selectedMac == null} dim={dim} onSelect={() => onSelect()}>
      {children}
    </Shell>
  );

  if (node.kind === "wan") {
    const l = node.wan!;
    return shell(
      l.state === "down" ? "down" : "normal",
      <>
        <IconWorld size={18} aria-hidden="true" className={l.state === "down" ? "mt-px shrink-0 text-danger" : ICON} />
        <div className="min-w-0">
          <p className="flex items-center gap-1.5 text-sm font-medium">
            <span className="truncate">{l.name}</span>
            <span className={`inline-block size-2 shrink-0 rounded-full ${l.state === "active" ? "bg-success" : l.state === "down" ? "bg-danger" : "bg-muted"}`} />
          </p>
          <p className={`truncate ${l.state === "down" ? "text-danger" : "text-text-2"}`}>
            {t(WAN_STATE[l.state] ?? "netmap.wan.unknown")}
            {l.state_since ? ` · ${relativeTime(l.state_since)}` : ""}
          </p>
          <p className="mt-1">
            {l.state === "down" ? (
              <span className="text-text-2">{[l.interface_label, speedLabel(l.speed_mbps)].filter(Boolean).join(" · ")}</span>
            ) : (
              <Chip title={t("topo.traffic.wan")}>
                ↓ {formatBps(l.in_bps)} ↑ {formatBps(l.out_bps)}
              </Chip>
            )}
          </p>
        </div>
      </>,
    );
  }

  if (node.kind === "internet") {
    return shell(
      "normal",
      <>
        <IconWorld size={18} aria-hidden="true" className={ICON} />
        <div className="min-w-0">
          <p className="text-sm font-medium">{t("topo.internet")}</p>
          {node.edge?.traffic_bps != null && (
            <p className="mt-1">
              <Chip title={t("topo.traffic.wan")}>
                <IconArrowsUpDown size={12} aria-hidden="true" />
                {formatBps(node.edge.traffic_bps)}
              </Chip>
            </p>
          )}
        </div>
      </>,
    );
  }

  if (node.kind === "external") {
    return shell(
      "normal",
      <>
        <IconQuestionMark size={18} aria-hidden="true" className={ICON} />
        <div className="min-w-0">
          <p className="font-medium">{t("topo.external")}</p>
          <p className="truncate font-mono text-text-2">{node.name}</p>
        </div>
      </>,
    );
  }

  if (node.kind === "device") {
    const n = node.topo!;
    const Icon = KIND_ICON[n.device_kind as keyof typeof KIND_ICON] ?? IconDeviceDesktop;
    const c = counts.get(node.id);
    const root = node.parent == null;
    const traffic = node.edge?.traffic_bps ?? null;
    return shell(
      n.status === "down" ? "down" : "normal",
      <>
        <Icon size={20} aria-hidden="true" className={ICON} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <h3 className="min-w-0 truncate text-sm font-medium">
              {n.device_id != null ? (
                <Link to={`/devices/${n.device_id}`} className="pointer-events-auto hover:text-accent-text hover:underline">
                  {n.name}
                </Link>
              ) : (
                n.name
              )}
            </h3>
            <StatusDot status={n.status ?? "unknown"} />
          </div>
          <p className="truncate text-text-2">{[t(KIND_LABEL[n.device_kind ?? "other"] ?? "dash.kind.other"), n.model].filter(Boolean).join(" · ")}</p>
          {node.port != null && node.edge && (
            <p className="truncate text-text-2">{t("netmap.uplink", { port: (node.edge.a === node.id ? node.edge.a_port : node.edge.b_port) ?? "–", parent: node.port })}</p>
          )}
          <div className="mt-1.5 flex flex-wrap gap-1">
            {root && (wanTotals.in != null || wanTotals.out != null) && (
              <Chip title={t("topo.traffic.wan")}>
                ↓ {formatBps(wanTotals.in)} ↑ {formatBps(wanTotals.out)}
              </Chip>
            )}
            {!root && traffic != null && (
              <Chip title={t("topo.traffic")}>
                <IconArrowsUpDown size={12} aria-hidden="true" />
                {formatBps(traffic)}
              </Chip>
            )}
            {c && c.wifi > 0 && (
              <Chip title={t("topo.wifi", { n: c.wifi })}>
                <IconWifi size={12} aria-hidden="true" />
                {c.wifi}
              </Chip>
            )}
            {c && c.wired > 0 && (
              <Chip title={t("topo.wired", { n: c.wired })}>
                <IconDeviceDesktop size={12} aria-hidden="true" />
                {c.wired}
              </Chip>
            )}
          </div>
        </div>
      </>,
    );
  }

  if (node.kind === "client") {
    const c = node.client!;
    return shell(
      "normal",
      <>
        <IconDeviceDesktop size={16} aria-hidden="true" className={ICON} />
        <div className="min-w-0">
          <p className="truncate font-medium">{node.name}</p>
          <p className="truncate text-text-2">{[c.uplink_port != null ? t("clients.port", { n: c.uplink_port }) : t("netmap.conn.cable"), c.ip].filter(Boolean).join(" · ")}</p>
        </div>
      </>,
    );
  }

  if (node.kind === "ssid") {
    const g = node.ssid!;
    const q = query.trim().toLowerCase();
    return (
      <div
        className={`absolute rounded-xl border transition-opacity ${TONE.wifi}`}
        style={{
          left: box.x,
          top: box.y,
          width: box.w,
          height: box.h,
          opacity: dim ? 0.35 : 1,
          borderColor: selected && selectedMac == null ? "var(--accent)" : undefined,
          boxShadow: selected && selectedMac == null ? "0 0 0 4px var(--ring)" : undefined,
        }}
      >
        <button
          type="button"
          aria-label={label}
          aria-pressed={selected && selectedMac == null}
          onClick={() => onSelect()}
          className="flex w-full cursor-pointer items-center gap-1.5 rounded-t-xl px-3 text-left text-[11px] font-semibold text-text-2"
          style={{ height: SSID_HEADER_H }}
        >
          <IconWifi size={14} aria-hidden="true" className="shrink-0" />
          <span className="min-w-0 truncate">{[g.essid || t("netmap.ssid.hidden"), bandLabel(g.radio)].filter(Boolean).join(" · ")}</span>
          <span className="ml-auto tabular-nums">{g.clients.length}</span>
        </button>
        <ul className="flex flex-col gap-1 px-1.5">
          {g.clients.map((c) => {
            const quality = signalQuality(c.signal_dbm);
            const on = selected && selectedMac === c.mac;
            const hit = !!q && [c.name, c.ip, c.mac].some((s) => s?.toLowerCase().includes(q));
            return (
              <li key={c.mac}>
                <button
                  type="button"
                  aria-pressed={on}
                  aria-label={t("netmap.select", { name: c.name ?? c.ip ?? c.mac })}
                  onClick={() => onSelect(c.mac)}
                  className={`flex w-full cursor-pointer items-start gap-1.5 rounded-lg border bg-surface px-2 py-1 text-left text-[11px] leading-4 ${on ? "border-accent" : hit ? "border-accent/60" : "border-border"}`}
                  style={{ height: SSID_ROW_H - 4, boxShadow: on ? "0 0 0 3px var(--ring)" : undefined }}
                >
                  <IconDeviceMobile size={14} aria-hidden="true" className="mt-px shrink-0 text-text-2" />
                  <span className="min-w-0">
                    <span className="block truncate text-xs font-medium">{c.name ?? c.ip ?? c.mac}</span>
                    <span className="block truncate text-text-2">
                      {quality && <span className={`${SIGNAL_TEXT[quality]} mr-1`}>●</span>}
                      {[c.signal_dbm != null ? `${c.signal_dbm} dBm` : null, c.tx_rate_kbps != null ? formatLinkRate(c.tx_rate_kbps) : null].filter(Boolean).join(" · ")}
                    </span>
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      </div>
    );
  }

  if (node.kind === "vpn_server") {
    const s = node.vpnServer!;
    return shell(
      s.enabled ? "vpn" : "offline",
      <>
        <IconShieldLock size={18} aria-hidden="true" className="mt-px shrink-0 text-[var(--chart-2)]" />
        <div className="min-w-0">
          <p className="truncate font-medium">{s.name}</p>
          <p className="truncate text-text-2">{[s.type, s.port != null ? `UDP ${s.port}` : null].filter(Boolean).join(" · ")}</p>
          {s.subnet && <p className="truncate font-mono text-[11px] text-text-2">{s.subnet}</p>}
        </div>
      </>,
    );
  }

  // Klient VPN
  const u = node.vpnUser!;
  return shell(
    u.connected ? "vpn" : "offline",
    <>
      <IconDeviceMobile size={16} aria-hidden="true" className={ICON} />
      <div className="min-w-0">
        <p className="flex items-center gap-1.5 font-medium">
          <span className="truncate">{u.name}</span>
          {u.connected && <span className="inline-block size-2 shrink-0 rounded-full bg-success" />}
        </p>
        <p className="truncate text-text-2">
          {u.connected
            ? [u.tunnel_ip, u.down_bps != null ? `↓ ${formatBps(u.down_bps)} ↑ ${formatBps(u.up_bps)}` : null].filter(Boolean).join(" · ")
            : u.last_seen
              ? t("vpn.lastSeen", { when: relativeTime(u.last_seen) ?? "" })
              : t("vpn.offline")}
        </p>
      </div>
    </>,
  );
}

function nodeName(n: MapNode): string {
  if (n.kind === "internet") return t("topo.internet");
  if (n.kind === "external") return t("topo.external");
  if (n.kind === "ssid") return [n.name || t("netmap.ssid.hidden"), bandLabel(n.ssid?.radio)].filter(Boolean).join(" · ");
  return n.name;
}

/** Opis kabla między urządzeniami: prędkość łącza i ruch; prowadzi do strony portu. */
function CableInfo({ edge, at }: { edge: TopologyEdge; at: { x: number; y: number } }) {
  const speed = speedLabel(edge.speed_mbps);
  if (!speed && edge.traffic_bps == null) return null;
  const text = [speed, edge.traffic_bps != null ? formatBps(edge.traffic_bps) : null].filter(Boolean).join(" · ");
  const level = loadLevel(edge.utilization);
  const title = level === "none" ? text : `${text} – ${t(LOAD_LABEL[level])} (${Math.round((edge.utilization ?? 0) * 100)}%)`;
  const className =
    "absolute z-10 -translate-x-1/2 -translate-y-1/2 whitespace-nowrap rounded-full border border-border bg-surface px-1.5 py-0.5 text-[10px] leading-3 tabular-nums text-text-2";
  const style = { left: at.x, top: at.y };
  return edge.interface_id != null && edge.device_id != null ? (
    <Link to={`/devices/${edge.device_id}/ports/${edge.interface_id}`} title={title} className={`${className} hover:border-accent hover:text-accent-text`} style={style}>
      {text}
    </Link>
  ) : (
    <span title={title} className={className} style={style}>
      {text}
    </span>
  );
}

type View = { scale: number; x: number; y: number };
const MAP_BUTTON = "flex size-8 items-center justify-center rounded-lg border border-border bg-surface text-text-2 hover:text-text";

/** Ramka mapy z przybliżaniem (przyciski, Ctrl + kółko) i przesuwaniem (przeciągnięcie tła). Na starcie i po
 * „Dopasuj” cała mapa mieści się w szerokości – na telefonie bez przewijania w bok. */
function MapViewport({ width, height, toolbar, children }: { width: number; height: number; toolbar?: ReactNode; children: ReactNode }) {
  const frame = useRef<HTMLDivElement>(null);
  const [frameWidth, setFrameWidth] = useState(0);
  const [view, setView] = useState<View | null>(null);
  const drag = useRef<{ x: number; y: number; vx: number; vy: number } | null>(null);
  const fit = fitScale(frameWidth, width);
  const frameHeight = Math.max(240, height * fit);
  const fitted: View = { scale: fit, x: Math.max(0, (frameWidth - width * fit) / 2), y: 0 };
  const current = view ?? fitted;
  const currentRef = useRef(current);
  currentRef.current = current;

  useEffect(() => {
    const el = frame.current;
    if (!el) return;
    const observer = new ResizeObserver(() => setFrameWidth(el.clientWidth));
    observer.observe(el);
    setFrameWidth(el.clientWidth);
    // Ctrl + kółko przybliża w miejscu kursora; samo kółko przewija stronę (nasłuch nie-pasywny – bez zoomu strony)
    const onWheel = (e: WheelEvent) => {
      if (!e.ctrlKey && !e.metaKey) return;
      e.preventDefault();
      const r = el.getBoundingClientRect();
      const base = currentRef.current;
      setView(zoomAt(base, base.scale * (e.deltaY < 0 ? 1.15 : 1 / 1.15), e.clientX - r.left, e.clientY - r.top));
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => {
      observer.disconnect();
      el.removeEventListener("wheel", onWheel);
    };
  }, []);

  const zoomBy = (factor: number) => setView(zoomAt(current, current.scale * factor, frameWidth / 2, frameHeight / 2));
  const onDown = (e: PointerEvent<HTMLDivElement>) => {
    if ((e.target as HTMLElement).closest("a, button")) return;
    drag.current = { x: e.clientX, y: e.clientY, vx: current.x, vy: current.y };
    e.currentTarget.setPointerCapture(e.pointerId);
  };
  const onMove = (e: PointerEvent) => {
    const d = drag.current;
    if (d) setView({ scale: current.scale, x: d.vx + e.clientX - d.x, y: d.vy + e.clientY - d.y });
  };
  const stop = () => {
    drag.current = null;
  };
  return (
    <div
      ref={frame}
      className="relative cursor-grab overflow-hidden rounded-xl border border-border bg-surface-2/40 select-none active:cursor-grabbing"
      // Przybliżona mapa przesuwa się palcem; dopasowana – palec przewija stronę
      style={{ height: frameHeight, touchAction: view && view.scale > fit ? "none" : "pan-y" }}
      onPointerDown={onDown}
      onPointerMove={onMove}
      onPointerUp={stop}
      onPointerCancel={stop}
    >
      <div className="absolute top-0 left-0 origin-top-left" style={{ width, height, transform: `translate(${current.x}px, ${current.y}px) scale(${current.scale})` }}>
        {children}
      </div>
      <div role="group" aria-label={t("topo.zoom")} className="absolute top-2 right-2 flex gap-1">
        {toolbar}
        <button type="button" aria-label={t("topo.zoom.in")} title={t("topo.zoom.in")} className={MAP_BUTTON} onClick={() => zoomBy(1.25)}>
          <IconPlus size={16} aria-hidden="true" />
        </button>
        <button type="button" aria-label={t("topo.zoom.out")} title={t("topo.zoom.out")} className={MAP_BUTTON} onClick={() => zoomBy(1 / 1.25)}>
          <IconMinus size={16} aria-hidden="true" />
        </button>
        <button type="button" aria-label={t("topo.zoom.fit")} title={t("topo.zoom.fit")} className={MAP_BUTTON} onClick={() => setView(null)}>
          <IconArrowsMinimize size={16} aria-hidden="true" />
        </button>
      </div>
    </div>
  );
}

function Tile({ label, value, sub, tone = "normal" }: { label: string; value: string; sub: string; tone?: "normal" | "danger" }) {
  return (
    <div className={`rounded-xl border bg-surface px-4 py-3 ${tone === "danger" ? "border-danger/40" : "border-border"}`}>
      <p className="text-xs text-text-2">{label}</p>
      <p className="mt-0.5 truncate text-[15px] font-semibold tabular-nums">{value}</p>
      <p className={`truncate text-xs ${tone === "danger" ? "text-danger" : "text-text-2"}`}>{sub}</p>
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-text-2">{label}</dt>
      <dd className="truncate text-sm font-medium">{children}</dd>
    </div>
  );
}

interface PanelProps {
  map: NetMap;
  node: MapNode;
  mac: string | null;
  devices: Device[];
  onClose: () => void;
}

/** Szczegóły wybranego elementu i jego droga do Internetu. */
function DetailsPanel({ map, node, mac, devices, onClose }: PanelProps) {
  const byId = new Map(map.nodes.map((n) => [n.id, n]));
  const wifiClient: NetworkClient | undefined = mac ? node.ssid?.clients.find((c) => c.mac === mac) : undefined;
  const client = wifiClient ?? node.client;
  const title = client ? (client.name ?? client.ip ?? client.mac) : nodeName(node);

  // Droga: łącza WAN w użyciu, potem od bramy do węzła
  const chain: string[] = [];
  for (let cur: MapNode | undefined = node; cur; cur = cur.parent ? byId.get(cur.parent) : undefined) chain.unshift(nodeName(cur));
  if (node.kind !== "wan" && node.kind !== "internet") {
    const up = map.nodes.filter((n) => n.kind === "internet" || (n.kind === "wan" && n.wan?.state === "active")).map(nodeName);
    chain.unshift(...up);
  }
  if (wifiClient) chain.push(title);

  let fields: ReactNode = null;
  let link: { to: string; label: TextKey } | null = null;
  if (client) {
    const quality = signalQuality(client.signal_dbm);
    fields = (
      <>
        <Field label={t("netmap.f.conn")}>{client.is_wired ? t("netmap.conn.cable") : t("netmap.conn.wifi")}</Field>
        <Field label={t("netmap.f.via")}>{client.uplink_name ?? "–"}</Field>
        {client.is_wired ? (
          <Field label={t("netmap.f.port")}>{client.uplink_port ?? "–"}</Field>
        ) : (
          <>
            <Field label={t("netmap.f.network")}>{client.essid ?? "–"}</Field>
            <Field label={t("netmap.f.band")}>{bandLabel(client.radio) ?? "–"}</Field>
            <Field label={t("netmap.f.signal")}>
              {client.signal_dbm != null ? `${client.signal_dbm} dBm` : "–"}
              {quality && <span className={`ml-1 text-xs ${SIGNAL_TEXT[quality]}`}>({t(SIGNAL_LABEL[quality]).toLowerCase()})</span>}
            </Field>
            <Field label={t("netmap.f.rateDown")}>{formatLinkRate(client.tx_rate_kbps)}</Field>
            <Field label={t("netmap.f.rateUp")}>{formatLinkRate(client.rx_rate_kbps)}</Field>
          </>
        )}
        <Field label={t("netmap.f.ip")}>
          <span className="font-mono">{client.ip ?? "–"}</span>
        </Field>
        <Field label={t("netmap.f.mac")}>
          <span className="font-mono text-xs">{client.mac}</span>
        </Field>
        <Field label={t("netmap.f.connected")}>{formatUptime(client.connected_s)}</Field>
      </>
    );
    link = { to: `/clients/${client.mac}`, label: "netmap.open.client" };
  } else if (node.kind === "device" && node.topo) {
    const n = node.topo;
    const d = devices.find((x) => x.id === n.device_id);
    fields = (
      <>
        <Field label={t("netmap.f.status")}>{t(STATUS_LABEL[n.status && n.status in STATUS_LABEL ? n.status : "unknown"])}</Field>
        <Field label={t("netmap.f.kind")}>{t(KIND_LABEL[n.device_kind ?? "other"] ?? "dash.kind.other")}</Field>
        <Field label={t("netmap.f.model")}>{n.model ?? d?.model ?? "–"}</Field>
        <Field label={t("netmap.f.ip")}>
          <span className="font-mono">{d?.host ?? "–"}</span>
        </Field>
        {d?.firmware && <Field label={t("netmap.f.firmware")}>{d.firmware}</Field>}
        {d?.uptime_s != null && <Field label={t("netmap.f.uptime")}>{formatUptime(d.uptime_s)}</Field>}
        {node.edge && <Field label={t("netmap.f.speed")}>{speedLabel(node.edge.speed_mbps) ?? "–"}</Field>}
        {node.edge?.traffic_bps != null && <Field label={t("netmap.f.traffic")}>{formatBps(node.edge.traffic_bps)}</Field>}
      </>
    );
    if (n.device_id != null) link = { to: `/devices/${n.device_id}`, label: "netmap.open.device" };
  } else if (node.kind === "wan" && node.wan) {
    const l: WanLink = node.wan;
    fields = (
      <>
        <Field label={t("netmap.f.status")}>{t(WAN_STATE[l.state] ?? "netmap.wan.unknown")}</Field>
        <Field label={t("netmap.f.since")}>{relativeTime(l.state_since) ?? "–"}</Field>
        <Field label={t("netmap.f.interface")}>{[l.interface_label, l.interface_name].filter(Boolean).join(" · ")}</Field>
        <Field label={t("netmap.f.speed")}>{speedLabel(l.speed_mbps) ?? "–"}</Field>
        <Field label={t("netmap.f.down")}>{formatBps(l.in_bps)}</Field>
        <Field label={t("netmap.f.up")}>{formatBps(l.out_bps)}</Field>
      </>
    );
    link = { to: `/devices/${l.device_id}/ports/${l.interface_id}`, label: "netmap.open.port" };
  } else if (node.kind === "ssid" && node.ssid) {
    const parent = node.parent ? byId.get(node.parent) : undefined;
    fields = (
      <>
        <Field label={t("netmap.f.network")}>{node.ssid.essid || t("netmap.ssid.hidden")}</Field>
        <Field label={t("netmap.f.band")}>{bandLabel(node.ssid.radio) ?? "–"}</Field>
        <Field label={t("netmap.f.ap")}>{parent ? nodeName(parent) : "–"}</Field>
        <Field label={t("netmap.f.clients")}>{node.ssid.clients.length}</Field>
      </>
    );
  } else if (node.kind === "vpn_server" && node.vpnServer) {
    const s = node.vpnServer;
    const users = map.nodes.filter((n) => n.parent === node.id);
    fields = (
      <>
        <Field label={t("netmap.f.kind")}>{s.type}</Field>
        <Field label={t("netmap.f.port")}>{s.port != null ? `UDP ${s.port}` : "–"}</Field>
        <Field label={t("netmap.f.subnet")}>
          <span className="font-mono">{s.subnet ?? "–"}</span>
        </Field>
        <Field label={t("netmap.f.clients")}>{t("vpn.online", { n: users.filter((u) => u.online).length, total: users.length })}</Field>
      </>
    );
  } else if (node.kind === "vpn_user" && node.vpnUser) {
    const u = node.vpnUser;
    fields = (
      <>
        <Field label={t("netmap.f.status")}>{u.connected ? t("vpn.connected") : t("vpn.offline")}</Field>
        <Field label={t("netmap.f.server")}>{u.server ?? "–"}</Field>
        <Field label={t("netmap.f.tunnel")}>
          <span className="font-mono">{u.tunnel_ip ?? "–"}</span>
        </Field>
        <Field label={t("netmap.f.remote")}>
          <span className="font-mono">{u.remote_ip ?? "–"}</span>
        </Field>
        <Field label={u.connected ? t("netmap.f.since") : t("netmap.f.lastSeen")}>{relativeTime(u.connected ? u.since : u.last_seen) ?? "–"}</Field>
        {u.connected && <Field label={t("netmap.f.down")}>{formatBps(u.down_bps)}</Field>}
        {u.connected && <Field label={t("netmap.f.up")}>{formatBps(u.up_bps)}</Field>}
      </>
    );
  } else if (node.kind === "external") {
    fields = (
      <Field label={t("netmap.f.mac")}>
        <span className="font-mono text-xs">{node.name}</span>
      </Field>
    );
  }

  return (
    <aside aria-label={t("netmap.panel")} className="flex flex-col gap-4 rounded-xl border border-border bg-surface p-4 xl:w-80 xl:shrink-0">
      <div className="flex items-start gap-2">
        <h2 className="min-w-0 flex-1 truncate text-base font-semibold">{title}</h2>
        <button type="button" aria-label={t("netmap.panel.close")} title={t("netmap.panel.close")} onClick={onClose} className="flex size-7 items-center justify-center rounded-lg text-text-2 hover:bg-surface-2 hover:text-text">
          <IconX size={16} aria-hidden="true" />
        </button>
      </div>
      {fields && <dl className="grid grid-cols-2 gap-x-3 gap-y-2.5">{fields}</dl>}
      {chain.length > 1 && (
        <div>
          <h3 className="mb-1.5 text-xs text-text-2">{t("netmap.path")}</h3>
          <ol className="flex flex-col gap-1 text-sm">
            {chain.map((name, i) => (
              <li key={`${i}-${name}`} className={`flex items-center gap-2 ${i === chain.length - 1 ? "font-medium" : ""}`}>
                <span aria-hidden="true" className="inline-block size-2 shrink-0 rounded-full bg-accent" />
                <span className="truncate">{name}</span>
              </li>
            ))}
          </ol>
        </div>
      )}
      {link && (
        <Link to={link.to} className="rounded-lg bg-accent px-3 py-2 text-center text-sm font-medium text-on-accent hover:bg-accent-hover">
          {t(link.label)}
        </Link>
      )}
    </aside>
  );
}

function Legend() {
  const items: { label: TextKey; stroke: Stroke }[] = [
    { label: "netmap.legend.cable", stroke: { stroke: "var(--success)", width: 2.5 } },
    { label: "netmap.legend.wifi", stroke: { stroke: "var(--state-up)", width: 3, dash: "1 6" } },
    { label: "netmap.legend.vpn", stroke: { stroke: "var(--chart-2)", width: 2, dash: "6 5" } },
    { label: "netmap.legend.down", stroke: { stroke: "var(--danger)", width: 2, dash: "6 6" } },
    { label: "netmap.legend.offline", stroke: { stroke: "var(--border-strong)", width: 2, dash: "3 6" } },
    { label: "netmap.legend.path", stroke: { stroke: "var(--accent)", width: 3 } },
  ];
  return (
    <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-text-2">
      {items.map((i) => (
        <span key={i.label} className="inline-flex items-center gap-1.5">
          <svg width="28" height="8" aria-hidden="true">
            <path d="M3,4 H25" fill="none" stroke={i.stroke.stroke} strokeWidth={i.stroke.width} strokeDasharray={i.stroke.dash} strokeLinecap="round" />
          </svg>
          {t(i.label)}
        </span>
      ))}
      <span>
        {t("topo.load")}: {(["low", "mid", "high"] as const).map((l) => t(LOAD_LABEL[l])).join(" / ")}
      </span>
    </div>
  );
}

/** Mapa sieci: WAN, brama, switche, access pointy i klienci (kabel, Wi-Fi, VPN). */
export function TopologyPage() {
  const { refetchInterval } = useRefresh();
  const topo = useTopology();
  const clients = useClients();
  const wan = useWanStatus();
  const devices = useDevices();
  const vpnQuery = useVpn(refetchInterval);
  const liveVpn = useLiveVpn(!!vpnQuery.data && vpnQuery.data.servers.length > 0);
  const vpn = useMemo(() => (vpnQuery.data ? withLiveVpn(vpnQuery.data, liveVpn) : null), [vpnQuery.data, liveVpn]);

  const nodes = useMemo(() => topo.data?.nodes ?? [], [topo.data]);
  const baseEdges = useMemo(() => topo.data?.edges ?? [], [topo.data]);
  // Obciążenie kabli na żywo (0.72.0): ruch z próbek co ~1,5 s
  const liveDevices = useMemo(() => baseEdges.flatMap((e) => (e.device_id != null && e.interface_id != null ? [e.device_id] : [])), [baseEdges]);
  const live = useLiveDeviceSamples(liveDevices);
  const edges = useMemo(
    () =>
      withLiveEdges(baseEdges, (dev, iface) => {
        const st = live.get(dev);
        return st?.status === "live" ? st.sample?.ports.get(iface) : null;
      }),
    [baseEdges, live],
  );
  const wanLinks = useMemo(() => wan.data?.links ?? [], [wan.data]);
  const map = useMemo(
    () => buildNetMap({ nodes, edges, clients: clients.data ?? [], vpn, wan: wanLinks }),
    [nodes, edges, clients.data, vpn, wanLinks],
  );

  const [filter, setFilter] = useState<ConnFilter>("all");
  const [showOffline, setShowOffline] = useState(true);
  const [showTraffic, setShowTraffic] = useState(true);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<{ id: string; mac: string | null } | null>(null);
  const [chosen, setChosen] = useState<Orientation | null>(readOrientation);
  const [wide] = useState(() => typeof matchMedia === "function" && matchMedia("(min-width: 1024px)").matches);
  const orientation: Orientation = chosen ?? (wide ? "horizontal" : "vertical");
  const horizontal = orientation === "horizontal";
  const turn = () => {
    const next: Orientation = horizontal ? "vertical" : "horizontal";
    setChosen(next);
    try {
      localStorage.setItem(ORIENTATION_KEY, next);
    } catch {
      /* bez zapamiętywania */
    }
  };

  const layout = useMemo(() => layoutNetMap(map, (n) => isVisible(n, filter, showOffline), orientation), [map, filter, showOffline, orientation]);
  const byId = useMemo(() => new Map(map.nodes.map((n) => [n.id, n])), [map]);
  const path = useMemo(() => pathToInternet(map, selected?.id ?? null), [map, selected]);
  const summary = useMemo(() => summarize(map), [map]);
  // Wyszukiwanie: pasujące węzły i ich rodzice zostają wyraźne, reszta przygasa
  const matches = useMemo(() => {
    if (!query.trim()) return null;
    const hit = new Set<string>();
    for (const n of map.nodes) {
      if (!matchesQuery(n, query)) continue;
      for (let cur: MapNode | undefined = n; cur; cur = cur.parent ? byId.get(cur.parent) : undefined) hit.add(cur.id);
    }
    return hit;
  }, [map, byId, query]);
  const counts = useMemo(() => {
    const out = new Map<string, Counts>();
    for (const n of map.nodes) {
      if (!n.parent || (n.kind !== "client" && n.kind !== "ssid")) continue;
      const c = out.get(n.parent) ?? { wired: 0, wifi: 0 };
      if (n.kind === "client") c.wired++;
      else c.wifi += n.ssid?.clients.length ?? 0;
      out.set(n.parent, c);
    }
    return out;
  }, [map]);
  const activeWan = wanLinks.filter((l) => l.state === "active");
  const sum = (pick: (l: WanLink) => number | null) => {
    const vals = activeWan.map(pick).filter((v): v is number => v != null);
    return vals.length ? vals.reduce((s, v) => s + v, 0) : null;
  };
  const wanTotals = { in: sum((l) => l.in_bps), out: sum((l) => l.out_bps) };
  const downWan = wanLinks.filter((l) => l.state === "down");

  const shown = map.nodes.filter((n) => layout.boxes[n.id]);
  const upstream = shown.filter((n) => n.kind === "wan" || n.kind === "internet");
  const selNode = selected ? byId.get(selected.id) : undefined;
  const cables = edges.filter((e) => byId.has(e.a) && byId.has(e.b));
  const name = (id: string) => {
    const n = byId.get(id);
    return n ? nodeName(n) : id;
  };
  const port = (p: number | null) => (p != null ? ` (${t("clients.port", { n: p })})` : "");
  const toggle = "inline-flex items-center gap-2 text-sm text-text-2";

  return (
    <>
      <PageHeader title={t("topo.title")} />
      {topo.isError && <ErrorNote>{t("topo.error")}</ErrorNote>}
      {topo.data && nodes.length === 0 && (
        <Card className="p-6">
          <h2 className="text-base font-medium">{t("topo.empty.title")}</h2>
          <p className="mt-1 text-sm text-text-2">{t("topo.empty.body")}</p>
        </Card>
      )}
      {nodes.length > 0 && (
        <>
          <p className="-mt-2 mb-4 text-sm text-text-2">{t("netmap.subtitle")}</p>
          <section aria-label={t("netmap.summary")} className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
            {wanLinks.length > 0 ? (
              <Tile
                label={t("netmap.sum.internet")}
                value={activeWan.length ? activeWan.map((l) => l.name).join(", ") : t("netmap.wan.down")}
                sub={downWan.length ? t("netmap.sum.down", { names: downWan.map((l) => l.name).join(", ") }) : t("netmap.sum.allUp")}
                tone={downWan.length || !activeWan.length ? "danger" : "normal"}
              />
            ) : (
              <Tile label={t("netmap.sum.internet")} value="–" sub={t("netmap.sum.noWan")} />
            )}
            <Tile label={t("netmap.sum.devices")} value={t("netmap.sum.devicesUp", { up: summary.devicesUp, total: summary.devices })} sub={t("netmap.sum.devicesSub")} tone={summary.devicesUp < summary.devices ? "danger" : "normal"} />
            <Tile
              label={t("netmap.sum.clients")}
              value={t("netmap.sum.clientsN", { n: summary.wired + summary.wifi + summary.vpnOnline })}
              sub={t("netmap.sum.clientsBy", { wired: summary.wired, wifi: summary.wifi, vpn: summary.vpnOnline, total: summary.vpnUsers })}
            />
            <Tile label={t("netmap.sum.traffic")} value={wanTotals.in != null || wanTotals.out != null ? `↓ ${formatBps(wanTotals.in)} · ↑ ${formatBps(wanTotals.out)}` : "–"} sub={t("netmap.sum.trafficSub")} />
          </section>

          <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-2">
            <div role="group" aria-label={t("netmap.filter")} className="inline-flex rounded-lg bg-surface-2 p-0.5">
              {FILTERS.map((f) => (
                <button
                  key={f.id}
                  type="button"
                  aria-pressed={filter === f.id}
                  onClick={() => setFilter(f.id)}
                  className={`rounded-md px-3 py-1 text-sm ${filter === f.id ? "bg-surface font-medium text-text shadow-[var(--shadow-card)]" : "text-text-2 hover:text-text"}`}
                >
                  {t(f.label)}
                </button>
              ))}
            </div>
            <label className={toggle}>
              <input type="checkbox" checked={showOffline} onChange={(e) => setShowOffline(e.target.checked)} className="size-4 accent-[var(--accent)]" />
              {t("netmap.showOffline")}
            </label>
            <label className={toggle}>
              <input type="checkbox" checked={showTraffic} onChange={(e) => setShowTraffic(e.target.checked)} className="size-4 accent-[var(--accent)]" />
              {t("netmap.showTraffic")}
            </label>
            <label className="flex h-9 w-full items-center gap-2 rounded-lg border border-border bg-surface px-3 text-sm text-text-2 sm:ml-auto sm:w-72">
              <IconSearch size={16} aria-hidden="true" className="shrink-0" />
              <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder={t("netmap.search")} aria-label={t("netmap.search")} className="w-full bg-transparent text-text outline-none" />
            </label>
          </div>

          <div className="flex flex-col gap-4 xl:flex-row xl:items-start">
            <div className="min-w-0 flex-1">
              <MapViewport
                key={`${orientation}-${filter}-${showOffline}`}
                width={layout.width}
                height={layout.height}
                toolbar={
                  <button
                    type="button"
                    aria-label={t(horizontal ? "topo.layout.vertical" : "topo.layout.horizontal")}
                    title={t(horizontal ? "topo.layout.vertical" : "topo.layout.horizontal")}
                    className={`${MAP_BUTTON} mr-2`}
                    onClick={turn}
                  >
                    {horizontal ? <IconArrowsVertical size={16} aria-hidden="true" /> : <IconArrowsHorizontal size={16} aria-hidden="true" />}
                  </button>
                }
              >
                <svg aria-hidden="true" width={layout.width} height={layout.height} className="absolute inset-0">
                  {shown.map((n) => {
                    const box = layout.boxes[n.id];
                    let from: Box | undefined;
                    let to: Box | undefined;
                    let slot = 0;
                    let slots = 1;
                    if ((n.kind === "wan" || n.kind === "internet") && map.root) {
                      from = box;
                      to = layout.boxes[map.root];
                      slot = upstream.indexOf(n);
                      slots = upstream.length;
                    } else if (n.parent) {
                      from = layout.boxes[n.parent];
                      to = box;
                    }
                    if (!from || !to) return null;
                    const onPath = path.has(n.id) && (n.parent == null || path.has(n.parent));
                    const s = linkStroke(n, onPath);
                    return (
                      <path
                        key={n.id}
                        d={linkPath(from, to, orientation, slot, slots)}
                        fill="none"
                        stroke={s.stroke}
                        strokeWidth={s.width}
                        strokeDasharray={s.dash}
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        opacity={matches && !matches.has(n.id) ? 0.35 : 1}
                      />
                    );
                  })}
                </svg>
                {shown.map((n) => (
                  <NodeCard
                    key={n.id}
                    node={n}
                    box={layout.boxes[n.id]}
                    counts={counts}
                    wanTotals={wanTotals}
                    selected={selected?.id === n.id}
                    selectedMac={selected?.id === n.id ? selected.mac : null}
                    dim={!!matches && !matches.has(n.id)}
                    query={query}
                    onSelect={(mac) => setSelected({ id: n.id, mac: mac ?? null })}
                  />
                ))}
                {showTraffic &&
                  shown.map((n) =>
                    n.edge && n.parent && layout.boxes[n.parent] ? <CableInfo key={`cable-${n.id}`} edge={n.edge} at={labelPoint(layout.boxes[n.id], orientation)} /> : null,
                  )}
              </MapViewport>
              <Legend />
            </div>
            {selNode ? (
              <DetailsPanel map={map} node={selNode} mac={selected?.mac ?? null} devices={devices.data ?? []} onClose={() => setSelected(null)} />
            ) : (
              <p className="rounded-xl border border-dashed border-border-strong p-4 text-sm text-text-2 xl:w-80 xl:shrink-0">{t("netmap.panel.hint")}</p>
            )}
          </div>

          <section aria-labelledby="topo-links" className="mt-6">
            <h2 id="topo-links" className="mb-2 text-sm font-medium text-text-2">
              {t("topo.links")}
            </h2>
            <ul className="flex flex-col gap-1 text-sm">
              {cables.map((e) => (
                <li key={`${e.a}-${e.b}`}>
                  {`${name(e.a)}${port(e.a_port)} ↔ ${name(e.b)}${port(e.b_port)}`}
                  {(e.speed_mbps || e.traffic_bps != null) && (
                    <span className="text-text-2">
                      {" – "}
                      {[speedLabel(e.speed_mbps), e.traffic_bps != null ? formatBps(e.traffic_bps) : null].filter(Boolean).join(", ")}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </section>
        </>
      )}
    </>
  );
}
