import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  bandLabel,
  buildNetMap,
  isVisible,
  layoutNetMap,
  matchesQuery,
  pathToInternet,
  summarize,
  type MapNode,
} from "../lib/netmap";
import { fitScale, isInternetNode, loadLevel, pickRoot, speedLabel, zoomAt, type Topology, type TopologyNode } from "../lib/topology";
import type { NetworkClient } from "../lib/unifi";
import type { VpnStatus } from "../lib/vpn";
import type { WanLink } from "../lib/wan";
import { mockApi } from "../test/mockApi";
import { renderApp } from "../test/renderApp";

const node = (id: string, name: string, device_kind: string | null, kind: "device" | "external" = "device"): TopologyNode => ({
  id,
  kind,
  device_id: kind === "device" ? Number(id.slice(1)) : null,
  name,
  device_kind,
  model: null,
  status: "up",
});

// Brama (d1) – switch (d2) – AP (d3); modem (xaa) za bramą
const TOPO: Topology = {
  nodes: [node("d1", "UCG", "gateway"), node("d2", "USW", "switch"), node("d3", "U6+", "ap"), node("xaa", "02:00:ff:33:66:69", null, "external")],
  edges: [
    { a: "d1", a_port: 1, b: "d2", b_port: 8 },
    { a: "d2", a_port: 1, b: "d3", b_port: 1 },
    { a: "d1", a_port: 5, b: "xaa", b_port: null },
  ],
};

const CLIENT: NetworkClient = {
  mac: "02:00:ca:62:d5:01",
  name: "Telewizor",
  ip: "192.168.1.50",
  is_wired: true,
  is_guest: false,
  essid: null,
  radio: null,
  signal_dbm: null,
  tx_rate_kbps: null,
  rx_rate_kbps: null,
  uplink_device_id: 2,
  uplink_name: "USW",
  uplink_port: 7,
  connected_s: 1000,
  updated_at: "2026-10-25T10:00:00Z",
};

const wifi = (mac: string, name: string, essid: string, radio: string, signal: number): NetworkClient => ({
  ...CLIENT,
  mac,
  name,
  ip: `192.168.1.${mac.slice(-2)}`,
  is_wired: false,
  essid,
  radio,
  signal_dbm: signal,
  tx_rate_kbps: 866000,
  rx_rate_kbps: 400000,
  uplink_device_id: 3,
  uplink_name: "U6+",
  uplink_port: null,
});

const CLIENTS: NetworkClient[] = [
  CLIENT,
  wifi("02:00:00:00:00:21", "Galaxy", "Dom", "na", -71),
  wifi("02:00:00:00:00:22", "Dekoder", "Dom", "ng", -50),
  wifi("02:00:00:00:00:23", "Laptop Wi-Fi", "Dom", "na", -55),
];

const wanLink = (id: number, name: string, state: WanLink["state"], iface: string): WanLink => ({
  id,
  name,
  position: id,
  device_id: 1,
  device_name: "UCG",
  interface_id: 10 + id,
  interface_name: iface,
  interface_label: name,
  speed_mbps: 1000,
  state,
  state_since: "2026-10-25T09:00:00Z",
  source: "controller",
  in_bps: state === "active" ? 62_000 : null,
  out_bps: state === "active" ? 375_000 : null,
  sampled_at: "2026-10-25T10:00:00Z",
});
const WAN = [wanLink(1, "WAN 1", "active", "eth4"), wanLink(2, "GSM", "down", "eth3")];

const VPN: VpnStatus = {
  at: "2026-10-25T10:00:00Z",
  stale: false,
  device_id: 1,
  servers: [{ id: "wg1", name: "WG-Home", type: "WireGuard", enabled: true, port: 51820, subnet: "192.168.3.1/24" }],
  users: [
    { name: "Laptop", server: "WG-Home", tunnel_ip: "192.168.3.3", connected: false, since: null, last_seen: "2026-10-24T10:00:00Z", remote_ip: null, down_bytes: null, up_bytes: null, down_bps: null, up_bps: null },
    { name: "iPhone", server: "WG-Home", tunnel_ip: "192.168.3.2", connected: true, since: "2026-10-25T09:00:00Z", last_seen: null, remote_ip: "203.0.113.7", down_bytes: 1000, up_bytes: 500, down_bps: 2000, up_bps: 1000 },
  ],
};

const full = () => buildNetMap({ nodes: TOPO.nodes, edges: TOPO.edges, clients: CLIENTS, vpn: VPN, wan: WAN });
const ids = (nodes: MapNode[]) => nodes.map((n) => n.id);

describe("model mapy sieci", () => {
  it("wybiera bramę jako korzeń", () => {
    expect(pickRoot(TOPO.nodes)?.id).toBe("d1");
    expect(pickRoot([node("d2", "USW", "switch")])?.id).toBe("d2");
    expect(pickRoot([])).toBeUndefined();
    expect(buildNetMap({ nodes: [], edges: [], clients: [] })).toEqual({ root: null, nodes: [] });
  });

  it("buduje drzewo: WAN, brama, switch, AP, klienci po kablu, sieci Wi-Fi i VPN", () => {
    const map = full();
    const by = new Map(map.nodes.map((n) => [n.id, n]));
    expect(map.root).toBe("d1");
    // Łącza WAN zamiast „Internetu” z LLDP
    expect(ids(map.nodes.filter((n) => n.kind === "wan"))).toEqual(["wan:1", "wan:2"]);
    expect(by.has("xaa")).toBe(false);
    expect(by.get("wan:2")!.online).toBe(false);
    expect(by.get("d2")).toMatchObject({ parent: "d1", link: "cable", port: 1 });
    expect(by.get("d3")).toMatchObject({ parent: "d2", link: "cable", port: 1 });
    expect(by.get(`c:${CLIENT.mac}`)).toMatchObject({ kind: "client", parent: "d2", port: 7 });
    // Wi-Fi według sieci i pasma, 5 GHz przed 2,4 GHz
    const groups = map.nodes.filter((n) => n.kind === "ssid");
    expect(groups.map((g) => [g.parent, g.ssid!.radio, g.ssid!.clients.map((c) => c.name)])).toEqual([
      ["d3", "na", ["Galaxy", "Laptop Wi-Fi"]],
      ["d3", "ng", ["Dekoder"]],
    ]);
    // VPN: serwer na bramie, połączeni przed rozłączonymi
    expect(by.get("vs:WG-Home")).toMatchObject({ parent: "d1", link: "vpn" });
    expect(map.nodes.filter((n) => n.kind === "vpn_user").map((n) => [n.name, n.online])).toEqual([
      ["iPhone", true],
      ["Laptop", false],
    ]);
  });

  it("bez łączy WAN Internet bierze się z LLDP (sąsiad bramy)", () => {
    const map = buildNetMap({ nodes: TOPO.nodes, edges: TOPO.edges, clients: [] });
    const internet = map.nodes.find((n) => n.id === "xaa");
    expect(internet?.kind).toBe("internet");
    expect(internet?.edge).toBe(TOPO.edges[2]);
  });

  it("filtry: urządzenia i WAN zawsze, klienci według rodzaju połączenia, rozłączeni VPN na żądanie", () => {
    const map = full();
    const shown = (filter: "all" | "cable" | "wifi" | "vpn", offline = true) => ids(map.nodes.filter((n) => isVisible(n, filter, offline)));
    expect(shown("cable")).toEqual(expect.arrayContaining(["wan:1", "d1", "d2", "d3", `c:${CLIENT.mac}`]));
    expect(shown("cable").some((id) => id.startsWith("ssid:") || id.startsWith("v"))).toBe(false);
    expect(shown("wifi").filter((id) => id.startsWith("ssid:"))).toHaveLength(2);
    expect(shown("wifi")).not.toContain(`c:${CLIENT.mac}`);
    expect(shown("vpn")).toEqual(expect.arrayContaining(["vs:WG-Home", "vu:iPhone", "vu:Laptop"]));
    expect(shown("all", false)).not.toContain("vu:Laptop");
    expect(shown("all", false)).toContain("vu:iPhone");
  });

  it("droga do Internetu: rodzice aż do bramy i łącze WAN w użyciu", () => {
    const map = full();
    const ssid = map.nodes.find((n) => n.kind === "ssid")!;
    expect([...pathToInternet(map, ssid.id)].sort()).toEqual(["d1", "d2", "d3", ssid.id, "wan:1"].sort());
    expect([...pathToInternet(map, "wan:2")].sort()).toEqual(["d1", "wan:2"]);
    expect(pathToInternet(map, null).size).toBe(0);
  });

  it("wyszukiwanie po nazwie, IP, MAC i klientach w sieci Wi-Fi", () => {
    const map = full();
    const find = (q: string) => ids(map.nodes.filter((n) => matchesQuery(n, q)));
    expect(find("telewiz")).toEqual([`c:${CLIENT.mac}`]);
    expect(find("192.168.1.50")).toEqual([`c:${CLIENT.mac}`]);
    expect(find("galaxy")).toEqual([map.nodes.find((n) => n.kind === "ssid" && n.ssid!.radio === "na")!.id]);
    expect(find("02:00:00:00:00:22")).toHaveLength(1);
    expect(find("")).toHaveLength(map.nodes.length);
  });

  it("podsumowanie i pasmo", () => {
    expect(summarize(full())).toEqual({ devicesUp: 3, devices: 3, wired: 1, wifi: 3, vpnOnline: 1, vpnUsers: 2 });
    expect([bandLabel("ng"), bandLabel("na"), bandLabel("6e"), bandLabel(null)]).toEqual(["2,4 GHz", "5 GHz", "6 GHz", null]);
  });
});

describe("układ mapy sieci", () => {
  const overlaps = (boxes: { x: number; y: number; w: number; h: number }[]) =>
    boxes.some((a, i) => boxes.some((b, j) => i < j && a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h));

  it("poziomo: WAN, brama, switch, AP i klienci od lewej, bez nakładania, wszystko w wymiarach mapy", () => {
    const map = full();
    const { boxes, width, height } = layoutNetMap(map, () => true, "horizontal");
    expect(boxes["wan:1"].x).toBeLessThan(boxes.d1.x);
    expect(boxes.d1.x).toBeLessThan(boxes.d2.x);
    expect(boxes.d2.x).toBeLessThan(boxes.d3.x);
    const ssid = map.nodes.find((n) => n.kind === "ssid")!;
    expect(boxes[ssid.id].x).toBeGreaterThan(boxes.d3.x);
    const all = Object.values(boxes);
    expect(all).toHaveLength(map.nodes.length);
    expect(overlaps(all)).toBe(false);
    for (const b of all) {
      expect(b.x).toBeGreaterThanOrEqual(0);
      expect(b.y).toBeGreaterThanOrEqual(0);
      expect(b.x + b.w).toBeLessThanOrEqual(width);
      expect(b.y + b.h).toBeLessThanOrEqual(height);
    }
  });

  it("pionowo: warstwy od góry; filtr zmniejsza mapę", () => {
    const map = full();
    const { boxes } = layoutNetMap(map, () => true, "vertical");
    expect(boxes["wan:1"].y).toBeLessThan(boxes.d1.y);
    expect(boxes.d1.y + boxes.d1.h).toBeLessThanOrEqual(boxes.d2.y);
    expect(overlaps(Object.values(boxes))).toBe(false);
    const cable = layoutNetMap(map, (n) => isVisible(n, "cable", true), "vertical");
    expect(Object.keys(cable.boxes).some((id) => id.startsWith("ssid:"))).toBe(false);
    expect(cable.width).toBeLessThanOrEqual(layoutNetMap(map, () => true, "vertical").width);
  });

  it("pusta mapa daje pusty układ", () => {
    expect(layoutNetMap({ root: null, nodes: [] }, () => true)).toMatchObject({ boxes: {}, width: 0, height: 0 });
  });
});

describe("strona Mapa sieci", () => {
  it("pokazuje urządzenia, Internet, klientów po kablu i listę połączeń", async () => {
    mockApi({ topology: TOPO, clients: [CLIENT] });
    renderApp("/topology");
    expect(await screen.findByRole("heading", { name: "USW" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "UCG" })).toBeInTheDocument();
    // Nazwa urządzenia prowadzi do jego strony
    expect(screen.getByRole("link", { name: "UCG" })).toHaveAttribute("href", "/devices/1");
    expect(screen.getByText("Internet (WAN)")).toBeInTheDocument();
    expect(screen.queryByText("02:00:ff:33:66:69")).not.toBeInTheDocument(); // bez adresu MAC modemu
    expect(await screen.findByText("Telewizor")).toBeInTheDocument();
    expect(screen.getByText("port 7 · 192.168.1.50")).toBeInTheDocument();

    const links = screen.getByRole("region", { name: "Połączenia" });
    expect(within(links).getByText("UCG (port 1) ↔ USW (port 8)")).toBeInTheDocument();
    expect(within(links).getByText("USW (port 1) ↔ U6+ (port 1)")).toBeInTheDocument();
  });

  it("wyjaśnia, jak uzyskać mapę, gdy nie ma danych", async () => {
    mockApi();
    renderApp("/topology");
    expect(await screen.findByText("Brak danych o połączeniach")).toBeInTheDocument();
  });

  it("pokazuje błąd, gdy API nie odpowiada", async () => {
    mockApi({ overrides: { "GET /api/topology": { status: 500, body: { detail: "awaria" } } } });
    renderApp("/topology");
    expect(await screen.findByText("Nie udało się pobrać mapy sieci.")).toBeInTheDocument();
  });

  it("menu zawiera pozycję Mapa sieci", async () => {
    mockApi();
    renderApp("/topology");
    expect((await screen.findAllByRole("link", { name: "Mapa sieci" })).length).toBeGreaterThan(0);
  });

  it("klient Wi-Fi: sieć z pasmem, sygnał i droga do Internetu w panelu szczegółów", async () => {
    const user = userEvent.setup();
    mockApi({ topology: TOPO, clients: CLIENTS });
    renderApp("/topology");
    expect(await screen.findByRole("button", { name: "Szczegóły: Dom · 5 GHz" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Szczegóły: Dom · 2,4 GHz" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Szczegóły: Galaxy" }));
    const panel = screen.getByRole("complementary", { name: "Szczegóły wybranego elementu" });
    expect(within(panel).getByRole("heading", { name: "Galaxy" })).toBeInTheDocument();
    expect(within(panel).getByText("-71 dBm")).toBeInTheDocument();
    expect(within(panel).getByText("(sygnał przeciętny)")).toBeInTheDocument();
    expect(within(panel).getByRole("list").textContent).toBe(["Internet (WAN)", "UCG", "USW", "U6+", "Dom · 5 GHz", "Galaxy"].join(""));
    expect(within(panel).getByRole("link", { name: "Otwórz stronę klienta" })).toHaveAttribute("href", "/clients/02:00:00:00:00:21");
    await user.click(within(panel).getByRole("button", { name: "Zamknij szczegóły" }));
    expect(screen.queryByRole("complementary", { name: "Szczegóły wybranego elementu" })).not.toBeInTheDocument();
  });

  it("filtr Wi-Fi chowa klientów po kablu, wyszukiwanie przygasza resztę", async () => {
    const user = userEvent.setup();
    mockApi({ topology: TOPO, clients: CLIENTS });
    renderApp("/topology");
    expect(await screen.findByText("Telewizor")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Wi-Fi" }));
    expect(screen.queryByText("Telewizor")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Wi-Fi" })).toHaveAttribute("aria-pressed", "true");
    await user.click(screen.getByRole("button", { name: "Wszystko" }));
    await user.type(screen.getByRole("searchbox", { name: "Znajdź urządzenie, IP albo MAC" }), "telewizor");
    const card = (name: string) => screen.getByRole("button", { name: `Szczegóły: ${name}` }).parentElement!;
    expect(card("Telewizor").style.opacity).toBe("1");
    expect(card("Dom · 5 GHz").style.opacity).toBe("0.35");
    expect(card("USW").style.opacity).toBe("1"); // rodzic znalezionego zostaje wyraźny
  });

  it("łącza WAN ze stanem i VPN z klientami; rozłączonych można schować", async () => {
    const user = userEvent.setup();
    mockApi({ topology: TOPO, clients: [], wanStatus: { links: WAN, active_ids: [1] }, vpn: VPN });
    renderApp("/topology");
    expect(await screen.findByRole("button", { name: "Szczegóły: GSM" })).toBeInTheDocument();
    expect(screen.queryByText("Internet (WAN)")).not.toBeInTheDocument();
    const summary = screen.getByRole("region", { name: "Podsumowanie sieci" });
    expect(within(summary).getByText("nie działa: GSM")).toBeInTheDocument();
    expect(await screen.findByText("WG-Home")).toBeInTheDocument();
    expect(screen.getByText("iPhone")).toBeInTheDocument();
    expect(screen.getByText("Laptop")).toBeInTheDocument();
    await user.click(screen.getByRole("checkbox", { name: "Pokaż rozłączonych" }));
    expect(screen.queryByText("Laptop")).not.toBeInTheDocument();
    expect(screen.getByText("iPhone")).toBeInTheDocument();
  });
});

describe("Internet za bramą", () => {
  it("węzeł zewnętrzny za bramą to Internet, za switchem to nieznane urządzenie", () => {
    const xsw = node("xbb", "02:00:aa:aa:aa:aa", null, "external");
    const edges = [...TOPO.edges, { a: "d2", a_port: 3, b: "xbb", b_port: null }];
    const nodes = [...TOPO.nodes, xsw];
    expect(isInternetNode(nodes.find((n) => n.id === "xaa")!, nodes, edges)).toBe(true);
    expect(isInternetNode(xsw, nodes, edges)).toBe(false);
    expect(isInternetNode(nodes[0], nodes, edges)).toBe(false); // urządzenie UplinkView nigdy
    expect(isInternetNode(node("xzz", "02:00:00:00:00:01", null, "external"), nodes, edges)).toBe(false); // bez kabla
  });
});

describe("obciążenie kabli i powiększenie mapy (0.35.0)", () => {
  it("poziom obciążenia, prędkość, dopasowanie i przybliżanie w punkcie", () => {
    expect([null, 0.1, 0.5, 0.79, 0.8, 1].map(loadLevel)).toEqual(["none", "low", "mid", "mid", "high", "high"]);
    expect([1000, 2500, 100, null].map(speedLabel)).toEqual(["1G", "2.5G", "100M", null]);
    expect(fitScale(400, 800)).toBe(0.5);
    expect(fitScale(1600, 800)).toBe(1); // bez powiększania ponad 100%
    expect(fitScale(100, 1000)).toBe(0.3); // nie mniej niż minimum
    // Punkt pod kursorem (100, 50) zostaje w miejscu
    const v = zoomAt({ scale: 1, x: 0, y: 0 }, 2, 100, 50);
    expect(v).toEqual({ scale: 2, x: -100, y: -50 });
  });

  it("kabel pokazuje prędkość i ruch, opis prowadzi do strony portu", async () => {
    const topo: Topology = {
      ...TOPO,
      edges: [
        { ...TOPO.edges[0], interface_id: 21, device_id: 2, speed_mbps: 1000, traffic_bps: 8.5e8, utilization: 0.85 },
        { ...TOPO.edges[1], speed_mbps: 100 },
        TOPO.edges[2],
      ],
    };
    mockApi({ topology: topo, clients: [] });
    renderApp("/topology");
    const label = await screen.findByRole("link", { name: "1G · 850 Mb/s" });
    expect(label).toHaveAttribute("href", "/devices/2/ports/21");
    expect(label).toHaveAttribute("title", "1G · 850 Mb/s – ponad 80% (85%)");
    expect(screen.getByText("100M")).toBeInTheDocument(); // bez ruchu i bez portu SNMP – sam opis
    expect(screen.getByRole("group", { name: "Powiększenie mapy" })).toBeInTheDocument();
    const links = screen.getByRole("region", { name: "Połączenia" });
    expect(within(links).getByText(/1G, 850 Mb\/s/)).toBeInTheDocument();
  });
});
