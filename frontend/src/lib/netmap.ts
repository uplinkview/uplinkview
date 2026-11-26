/**
 * Pełna mapa sieci (0.88.0): drzewo od łączy WAN przez bramę, switche i access pointy do klientów po kablu, Wi-Fi
 * (pogrupowanych według sieci i pasma) i WireGuard. Czyste funkcje – model, filtry, droga do Internetu i układ.
 * Dane: `/api/topology` (LLDP), `/api/clients`, `/api/vpn`, `/api/wan/status`. Opis: docs/22-wykresy.md („Mapa sieci”).
 */
import { locale } from "../i18n";
import { numberFormat } from "./intl";
import { isInternetNode, pickRoot, type TopologyEdge, type TopologyNode } from "./topology";
import type { NetworkClient } from "./unifi";
import type { VpnServer, VpnStatus, VpnUser } from "./vpn";
import type { WanLink } from "./wan";

export type MapNodeKind = "wan" | "internet" | "device" | "external" | "client" | "ssid" | "vpn_server" | "vpn_user";
/** Rodzaj połączenia węzła z rodzicem (dla WAN – z bramą). */
export type LinkKind = "wan" | "cable" | "wifi" | "vpn";
export type ConnFilter = "all" | "cable" | "wifi" | "vpn";
export type Orientation = "vertical" | "horizontal";

export interface SsidGroup {
  essid: string;
  /** Pasmo z kontrolera: ng = 2,4 GHz, na = 5 GHz, 6e = 6 GHz */
  radio: string | null;
  clients: NetworkClient[];
}

export interface MapNode {
  id: string;
  kind: MapNodeKind;
  name: string;
  /** Rodzic w drzewie; brama (korzeń) i łącza WAN go nie mają – WAN łączy się z bramą (`link = "wan"`) */
  parent: string | null;
  link: LinkKind | null;
  /** Działa / połączony teraz (urządzenie bez danych liczy się jako działające) */
  online: boolean;
  topo?: TopologyNode;
  /** Kabel LLDP do rodzica (prędkość, ruch, port SNMP) */
  edge?: TopologyEdge;
  /** Port rodzica, do którego podłączony jest węzeł */
  port?: number | null;
  client?: NetworkClient;
  ssid?: SsidGroup;
  wan?: WanLink;
  vpnServer?: VpnServer;
  vpnUser?: VpnUser;
}

export interface NetMap {
  /** Id bramy (korzeń drzewa) */
  root: string | null;
  /** Węzły w kolejności rysowania; łącza WAN i Internet na początku */
  nodes: MapNode[];
}

export interface NetMapInput {
  nodes: TopologyNode[];
  edges: TopologyEdge[];
  clients: NetworkClient[];
  vpn?: VpnStatus | null;
  wan?: WanLink[];
}

const BAND_ORDER: Record<string, number> = { "6e": 0, na: 1, ng: 2 };
const byName = (a: { name: string }, b: { name: string }) => a.name.localeCompare(b.name, locale());

/** Model mapy: korzeń = brama, nad nią łącza WAN (albo „Internet” z LLDP, gdy UplinkView nie zna łączy WAN). */
export function buildNetMap({ nodes, edges, clients, vpn, wan = [] }: NetMapInput): NetMap {
  const root = pickRoot(nodes);
  if (!root) return { root: null, nodes: [] };
  const out: MapNode[] = [];

  const wanLinks = wan.filter((l) => root.device_id == null || l.device_id === root.device_id).sort((a, b) => a.position - b.position);
  for (const l of wanLinks) {
    out.push({ id: `wan:${l.id}`, kind: "wan", name: l.name, parent: null, link: "wan", online: l.state !== "down", wan: l });
  }
  const internet = new Set(nodes.filter((n) => isInternetNode(n, nodes, edges)).map((n) => n.id));
  if (!wanLinks.length) {
    for (const id of internet) {
      const edge = edges.find((e) => e.a === id || e.b === id);
      out.push({ id, kind: "internet", name: id, parent: null, link: "wan", online: true, topo: nodes.find((n) => n.id === id), edge });
    }
  }

  // Drzewo urządzeń z kabli LLDP (BFS od bramy); urządzenie bez kabla do bramy wisi pod bramą
  const children = new Map<string, MapNode[]>();
  const add = (n: MapNode) => {
    if (n.parent) children.set(n.parent, [...(children.get(n.parent) ?? []), n]);
  };
  const seen = new Set<string>([root.id, ...internet]);
  const queue = [root.id];
  for (let i = 0; i < queue.length; i++) {
    const id = queue[i];
    for (const e of edges) {
      if (e.a !== id && e.b !== id) continue;
      const other = e.a === id ? e.b : e.a;
      if (seen.has(other)) continue;
      const topo = nodes.find((n) => n.id === other);
      if (!topo) continue;
      seen.add(other);
      queue.push(other);
      add({
        id: other,
        kind: topo.kind === "external" ? "external" : "device",
        name: topo.name,
        parent: id,
        link: "cable",
        online: topo.status !== "down",
        topo,
        edge: e,
        port: e.a === id ? e.a_port : e.b_port,
      });
    }
  }
  for (const topo of nodes) {
    if (seen.has(topo.id)) continue;
    add({ id: topo.id, kind: topo.kind === "external" ? "external" : "device", name: topo.name, parent: root.id, link: "cable", online: topo.status !== "down", topo });
  }

  const deviceNode = (deviceId: number | null) => (deviceId == null ? undefined : nodes.find((n) => n.device_id === deviceId && n.kind === "device"));

  // Klienci po kablu – pod urządzeniem i portem; Wi-Fi – w grupie sieci (SSID + pasmo) pod access pointem
  const groups = new Map<string, MapNode>();
  for (const c of clients) {
    const at = deviceNode(c.uplink_device_id) ?? root;
    if (c.is_wired) {
      add({ id: `c:${c.mac}`, kind: "client", name: c.name ?? c.ip ?? c.mac, parent: at.id, link: "cable", online: true, client: c, port: c.uplink_port });
      continue;
    }
    const essid = c.essid ?? "";
    const key = `ssid:${at.id}:${essid}:${c.radio ?? ""}`;
    let group = groups.get(key);
    if (!group) {
      group = { id: key, kind: "ssid", name: essid, parent: at.id, link: "wifi", online: true, ssid: { essid, radio: c.radio, clients: [] } };
      groups.set(key, group);
      add(group);
    }
    group.ssid!.clients.push(c);
  }
  for (const g of groups.values()) g.ssid!.clients.sort((a, b) => (a.name ?? a.mac).localeCompare(b.name ?? b.mac, locale()));

  // VPN: serwery na bramie, klienci pod swoim serwerem
  if (vpn) {
    const at = deviceNode(vpn.device_id) ?? root;
    for (const s of vpn.servers) {
      add({ id: `vs:${s.name}`, kind: "vpn_server", name: s.name, parent: at.id, link: "vpn", online: s.enabled, vpnServer: s });
    }
    for (const u of vpn.users) {
      const server = vpn.servers.find((s) => s.name === u.server) ?? vpn.servers[0];
      add({ id: `vu:${u.name}`, kind: "vpn_user", name: u.name, parent: server ? `vs:${server.name}` : at.id, link: "vpn", online: u.connected, vpnUser: u });
    }
  }

  // Kolejność rodzeństwa: urządzenia, klienci po kablu (według portu), sieci Wi-Fi, VPN (połączeni najpierw)
  const rank: Record<MapNodeKind, number> = { device: 0, external: 1, client: 2, ssid: 3, vpn_server: 4, vpn_user: 5, wan: 9, internet: 9 };
  const sortKids = (list: MapNode[]) =>
    [...list].sort(
      (a, b) =>
        rank[a.kind] - rank[b.kind] ||
        (a.kind === "client" ? (a.port ?? Infinity) - (b.port ?? Infinity) : 0) ||
        (a.kind === "ssid" ? (BAND_ORDER[a.ssid?.radio ?? ""] ?? 3) - (BAND_ORDER[b.ssid?.radio ?? ""] ?? 3) : 0) ||
        (a.kind === "vpn_user" ? Number(b.online) - Number(a.online) : 0) ||
        byName(a, b),
    );
  const walk = (id: string) => {
    for (const k of sortKids(children.get(id) ?? [])) {
      out.push(k);
      walk(k.id);
    }
  };
  out.push({ id: root.id, kind: "device", name: root.name, parent: null, link: null, online: root.status !== "down", topo: root });
  walk(root.id);
  return { root: root.id, nodes: out };
}

/** Czy węzeł zostaje na mapie przy danym filtrze. Urządzenia sieciowe i WAN – zawsze; VPN offline – tylko z „offline”. */
export function isVisible(n: MapNode, filter: ConnFilter, showOffline: boolean): boolean {
  if (n.kind === "vpn_user" && !n.online && !showOffline) return false;
  if (filter === "all" || n.kind === "device" || n.kind === "external" || n.kind === "wan" || n.kind === "internet") return true;
  if (n.kind === "client") return filter === "cable";
  if (n.kind === "ssid") return filter === "wifi";
  return filter === "vpn"; // serwer i klient VPN
}

/** Ids węzłów na drodze do Internetu: węzeł, jego rodzice aż do bramy i łącza WAN, które teraz niosą ruch. */
export function pathToInternet(map: NetMap, id: string | null): Set<string> {
  const path = new Set<string>();
  if (!id) return path;
  const byId = new Map(map.nodes.map((n) => [n.id, n]));
  let cur = byId.get(id);
  if (cur?.kind === "wan" || cur?.kind === "internet") {
    path.add(cur.id);
    if (map.root) path.add(map.root);
    return path;
  }
  while (cur) {
    path.add(cur.id);
    cur = cur.parent ? byId.get(cur.parent) : undefined;
  }
  for (const n of map.nodes) {
    if (n.kind === "internet" || (n.kind === "wan" && n.wan?.state === "active")) path.add(n.id);
  }
  return path;
}

/** Wyszukiwanie: nazwa, IP, MAC, sieć Wi-Fi (bez wielkości liter). Grupa Wi-Fi pasuje też, gdy pasuje któryś jej klient. */
export function matchesQuery(n: MapNode, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  const texts = [n.name, n.topo?.model, n.client?.ip, n.client?.mac, n.vpnUser?.tunnel_ip, n.wan?.interface_label, n.wan?.interface_name];
  for (const c of n.ssid?.clients ?? []) texts.push(c.name, c.ip, c.mac);
  return texts.some((s) => s != null && s.toLowerCase().includes(q));
}

// Wymiary kart (px); grupa Wi-Fi rośnie z liczbą klientów
export const CARD_W = 200;
export const SSID_HEADER_H = 40;
export const SSID_ROW_H = 44;
const GAP_COL = 88; // między kolumnami (układ poziomy) – miejsce na opis kabla
const GAP_ROW = 96; // między warstwami (układ pionowy)
const GAP_SIB = 14; // między sąsiadami
const PAD = 24;
// Miejsce na przyciski mapy w prawym górnym rogu
const TOP = 48;

export function cardHeight(n: MapNode): number {
  switch (n.kind) {
    case "wan":
    case "internet":
      return 84;
    case "device":
      return n.parent == null ? 132 : 112;
    case "ssid":
      return SSID_HEADER_H + SSID_ROW_H * (n.ssid?.clients.length ?? 0) + 8;
    case "vpn_server":
      return 64;
    default:
      return 56;
  }
}

export interface Box {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface MapLayout {
  boxes: Record<string, Box>;
  width: number;
  height: number;
  orientation: Orientation;
}

/**
 * Układ drzewa: warstwy według odległości od bramy (WAN przed bramą), w warstwie rodzeństwo jedno za drugim, rodzic
 * na środku swoich dzieci. Poziomo: warstwy od lewej do prawej; pionowo: od góry, warstwa tak wysoka jak jej najwyższa karta.
 */
export function layoutNetMap(map: NetMap, visible: (n: MapNode) => boolean, orientation: Orientation = "horizontal"): MapLayout {
  const horizontal = orientation === "horizontal";
  const nodes = map.nodes.filter(visible);
  const boxes: Record<string, Box> = {};
  if (!map.root || !nodes.some((n) => n.id === map.root)) return { boxes, width: 0, height: 0, orientation };

  const kids = new Map<string, MapNode[]>();
  for (const n of nodes) if (n.parent) kids.set(n.parent, [...(kids.get(n.parent) ?? []), n]);
  const upstream = nodes.filter((n) => n.kind === "wan" || n.kind === "internet");
  const firstDepth = upstream.length ? 1 : 0;

  const depth = new Map<string, number>();
  const setDepth = (id: string, d: number) => {
    depth.set(id, d);
    for (const k of kids.get(id) ?? []) setDepth(k.id, d + 1);
  };
  setDepth(map.root, firstDepth);
  for (const u of upstream) depth.set(u.id, 0);
  const placed = nodes.filter((n) => depth.has(n.id));

  // Wymiar „w poprzek” warstwy (poziomo: wysokość karty, pionowo: szerokość) i położenie warstw
  const cross = (n: MapNode) => (horizontal ? cardHeight(n) : CARD_W);
  const maxDepth = Math.max(...placed.map((n) => depth.get(n.id)!));
  const layerStart: number[] = [];
  let at = horizontal ? PAD : TOP;
  for (let d = 0; d <= maxDepth; d++) {
    layerStart.push(at);
    const size = horizontal ? CARD_W : Math.max(0, ...placed.filter((n) => depth.get(n.id) === d).map(cardHeight));
    at += size + (horizontal ? GAP_COL : GAP_ROW);
  }

  const span = new Map<string, number>();
  const measure = (n: MapNode): number => {
    const list = kids.get(n.id) ?? [];
    const sum = list.reduce((s, k) => s + measure(k), 0) + GAP_SIB * Math.max(0, list.length - 1);
    const v = Math.max(cross(n), sum);
    span.set(n.id, v);
    return v;
  };
  const put = (n: MapNode, a: number, c: number) => {
    const w = CARD_W;
    const h = cardHeight(n);
    boxes[n.id] = horizontal ? { x: a, y: c, w, h } : { x: c, y: a, w, h };
  };
  const place = (n: MapNode, start: number) => {
    const total = span.get(n.id)!;
    const list = kids.get(n.id) ?? [];
    const size = cross(n);
    const a = layerStart[depth.get(n.id)!];
    if (!list.length) {
      put(n, a, start + (total - size) / 2);
      return;
    }
    const sum = list.reduce((s, k) => s + span.get(k.id)!, 0) + GAP_SIB * (list.length - 1);
    let c = start + (total - sum) / 2;
    const centers: number[] = [];
    for (const k of list) {
      place(k, c);
      const b = boxes[k.id];
      centers.push(horizontal ? b.y + b.h / 2 : b.x + b.w / 2);
      c += span.get(k.id)! + GAP_SIB;
    }
    const mid = (centers[0] + centers[centers.length - 1]) / 2;
    put(n, a, Math.min(Math.max(mid - size / 2, start), start + total - size));
  };

  const rootNode = nodes.find((n) => n.id === map.root)!;
  measure(rootNode);
  const upSum = upstream.reduce((s, u) => s + cross(u), 0) + GAP_SIB * Math.max(0, upstream.length - 1);
  const total = Math.max(span.get(rootNode.id)!, upSum);
  const origin = horizontal ? TOP : PAD;
  place(rootNode, origin + (total - span.get(rootNode.id)!) / 2);
  // WAN przed bramą, na środku jej karty
  const rb = boxes[rootNode.id];
  const rootMid = horizontal ? rb.y + rb.h / 2 : rb.x + rb.w / 2;
  let c = Math.max(origin, rootMid - upSum / 2);
  for (const u of upstream) {
    put(u, layerStart[0], c);
    c += cross(u) + GAP_SIB;
  }

  const all = Object.values(boxes);
  const width = Math.max(...all.map((b) => b.x + b.w)) + PAD;
  const height = Math.max(...all.map((b) => b.y + b.h)) + PAD;
  return { boxes, width, height, orientation };
}

/** Linia od rodzica do dziecka (łamana pod kątem prostym; poziomo z prawej krawędzi do lewej, pionowo z dołu do góry).
 * WAN łączy się z bramą w punkcie `slot` z `slots` na jej krawędzi. */
export function linkPath(from: Box, to: Box, orientation: Orientation, slot = 0, slots = 1): string {
  if (orientation === "horizontal") {
    const x1 = from.x + from.w;
    const y1 = from.y + from.h / 2;
    const x2 = to.x;
    const y2 = slots > 1 ? to.y + (to.h * (slot + 1)) / (slots + 1) : to.y + to.h / 2;
    const mx = Math.round(x2 - GAP_COL / 2);
    return `M${x1},${y1} H${mx} V${y2} H${x2}`;
  }
  const x1 = from.x + from.w / 2;
  const y1 = from.y + from.h;
  const x2 = slots > 1 ? to.x + (to.w * (slot + 1)) / (slots + 1) : to.x + to.w / 2;
  const y2 = to.y;
  const my = Math.round(y2 - GAP_ROW / 2);
  return `M${x1},${y1} V${my} H${x2} V${y2}`;
}

/** Środek odcinka linii przy dziecku – tam stoi opis kabla (prędkość, ruch). */
export function labelPoint(to: Box, orientation: Orientation): { x: number; y: number } {
  return orientation === "horizontal" ? { x: to.x - GAP_COL / 2, y: to.y + to.h / 2 } : { x: to.x + to.w / 2, y: to.y - GAP_ROW / 2 };
}

export interface MapSummary {
  devicesUp: number;
  devices: number;
  wired: number;
  wifi: number;
  vpnOnline: number;
  vpnUsers: number;
}

/** Liczby do paska nad mapą. */
export function summarize(map: NetMap): MapSummary {
  const s: MapSummary = { devicesUp: 0, devices: 0, wired: 0, wifi: 0, vpnOnline: 0, vpnUsers: 0 };
  for (const n of map.nodes) {
    if (n.kind === "device") {
      s.devices++;
      if (n.online) s.devicesUp++;
    } else if (n.kind === "client") s.wired++;
    else if (n.kind === "ssid") s.wifi += n.ssid?.clients.length ?? 0;
    else if (n.kind === "vpn_user") {
      s.vpnUsers++;
      if (n.online) s.vpnOnline++;
    }
  }
  return s;
}

/** Pasmo Wi-Fi z kodu kontrolera. */
export function bandLabel(radio: string | null | undefined): string | null {
  const ghz = radio === "ng" ? 2.4 : radio === "na" ? 5 : radio === "6e" ? 6 : null;
  return ghz == null ? null : `${numberFormat({ maximumFractionDigits: 1 }).format(ghz)} GHz`;
}
