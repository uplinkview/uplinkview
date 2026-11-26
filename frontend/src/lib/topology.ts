/** Mapa sieci: dane z `/api/topology` (LLDP), obciążenie kabli i przybliżanie (czyste funkcje). Model i układ pełnej mapy: `netmap.ts`. */
import { useQuery } from "@tanstack/react-query";
import { get } from "./api";
import { useRefresh } from "./refresh";

export interface TopologyNode {
  id: string;
  kind: "device" | "external";
  device_id: number | null;
  name: string;
  device_kind: string | null;
  model: string | null;
  status: string | null;
}

export interface TopologyEdge {
  a: string;
  a_port: number | null;
  b: string;
  b_port: number | null;
  /** Obciążenie kabla (0.35.0): port SNMP jednej ze stron, jego prędkość, ruch (większy kierunek) i wykorzystanie 0–1 */
  interface_id?: number | null;
  device_id?: number | null;
  speed_mbps?: number | null;
  traffic_bps?: number | null;
  utilization?: number | null;
}

export type LoadLevel = "none" | "low" | "mid" | "high";

/** Poziom obciążenia kabla: do 50% niski, do 80% średni, wyżej wysoki; bez danych – „none”. */
export function loadLevel(utilization: number | null | undefined): LoadLevel {
  if (utilization == null) return "none";
  return utilization >= 0.8 ? "high" : utilization >= 0.5 ? "mid" : "low";
}

/**
 * Obciążenie kabli z kanału na żywo (od 0.72.0): ruch = większy kierunek portu z próbki jego urządzenia, wykorzystanie
 * jak w API (`api/topology.py`). Kabel bez świeżej próbki zostaje z odczytem kolektora.
 */
export function withLiveEdges(
  edges: TopologyEdge[],
  portRate: (deviceId: number, interfaceId: number) => { in_bps: number | null; out_bps: number | null } | null | undefined,
): TopologyEdge[] {
  let changed = false;
  const out = edges.map((e) => {
    if (e.device_id == null || e.interface_id == null) return e;
    const p = portRate(e.device_id, e.interface_id);
    const rates = [p?.in_bps, p?.out_bps].filter((v): v is number => v != null && Number.isFinite(v));
    if (!rates.length) return e;
    changed = true;
    const traffic = Math.max(...rates);
    return { ...e, traffic_bps: traffic, utilization: e.speed_mbps ? Math.min(1, traffic / (e.speed_mbps * 1e6)) : e.utilization };
  });
  return changed ? out : edges;
}

/** Prędkość łącza krótko: 1G, 2.5G, 100M. */
export function speedLabel(mbps: number | null | undefined): string | null {
  if (!mbps) return null;
  return mbps >= 1000 ? `${+(mbps / 1000).toFixed(1)}G` : `${mbps}M`;
}

export const MIN_SCALE = 0.3;
export const MAX_SCALE = 2;
export const clampScale = (s: number) => Math.min(MAX_SCALE, Math.max(MIN_SCALE, s));

/** Skala „Dopasuj”: cała mapa w szerokości ramki, bez powiększania ponad 100%. */
export function fitScale(frameWidth: number, contentWidth: number): number {
  return contentWidth > 0 && frameWidth > 0 ? clampScale(Math.min(1, frameWidth / contentWidth)) : 1;
}

/** Zmiana skali względem punktu (np. środka ramki): ten punkt mapy zostaje w tym samym miejscu ekranu. */
export function zoomAt(view: { scale: number; x: number; y: number }, scale: number, px: number, py: number) {
  const next = clampScale(scale);
  const k = next / view.scale;
  return { scale: next, x: px - (px - view.x) * k, y: py - (py - view.y) * k };
}

export interface Topology {
  nodes: TopologyNode[];
  edges: TopologyEdge[];
}

export function useTopology() {
  const { refetchInterval } = useRefresh();
  return useQuery({
    queryKey: ["topology"],
    queryFn: () => get<Topology>("/api/topology"),
    refetchInterval,
  });
}

/** Czy węzeł zewnętrzny to „Internet”: łączy się wyłącznie z bramą (router), więc jest za jej portem WAN. */
export function isInternetNode(node: TopologyNode, nodes: TopologyNode[], edges: TopologyEdge[]): boolean {
  if (node.kind !== "external") return false;
  const links = edges.filter((e) => e.a === node.id || e.b === node.id);
  if (links.length === 0) return false;
  return links.every((e) => {
    const other = nodes.find((n) => n.id === (e.a === node.id ? e.b : e.a));
    return other?.kind === "device" && other.device_kind === "gateway";
  });
}

/** Korzeń drzewa: brama (router), a gdy jej nie ma, pierwsze urządzenie. */
export function pickRoot(nodes: TopologyNode[]): TopologyNode | undefined {
  return nodes.find((n) => n.kind === "device" && n.device_kind === "gateway") ?? nodes.find((n) => n.kind === "device") ?? nodes[0];
}
