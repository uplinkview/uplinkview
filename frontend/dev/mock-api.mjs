// Atrapa API UplinkView do rozwoju panelu bez bazy i urządzeń:
//   npm run mock   (port 8000)   +   npm run dev   (port 5173, proxy /api → 8000)
// Dane są w pamięci i znikają po restarcie. Pierwsze konto zakłada kreator, jak w prawdziwym API.
import { createServer } from "node:http";
import { createHash, randomBytes } from "node:crypto";
import { readFileSync } from "node:fs";

const PORT = Number(process.env.PORT ?? 8000);
// Wersja jak w panelu (package.json) – zrzuty ekranu z atrapy pokazują aktualny numer
const VERSION = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf-8")).version;
// Wersja „dostępnej aktualizacji” w atrapie: następna minor po bieżącej (zamiast 9.9.9 – zrzuty do README)
const NEXT_VERSION = VERSION.replace(/^(\d+)\.(\d+)\.\d+.*$/, (_, a, b) => `${a}.${Number(b) + 1}.0`);
// Kubełek wykresu jak w API (aggregates.bucket_seconds): równa drabinka, 24 h = 5 min
const bucketS = (minutes) => [30, 60, 120, 300, 600, 900, 1800, 3600].find((s) => s >= Math.floor((minutes * 60) / 300)) ?? 3600;
const now = () => new Date().toISOString();
const ago = (s) => new Date(Date.now() - s * 1000).toISOString();

let user = null; // { id, username, password, ... }
let layout = null; // układ pulpitu domyślnego (null = domyślny z panelu)
let layoutAt = null;
const sessions = new Set();

const devices = [
  { id: 1, name: "UCG Ultra", host: "192.168.1.1", kind: "gateway", vendor: "Ubiquiti", model: "UCG-Ultra", status: "up", polled: 12 },
  { id: 2, name: "USW Lite 8 PoE", host: "192.168.1.2", kind: "switch", vendor: "Ubiquiti", model: "UniFi Switch", status: "up", polled: 12, default_community: true },
  { id: 3, name: "U6+", host: "192.168.1.3", kind: "ap", vendor: "Ubiquiti", model: "U6+", status: "up", polled: 12 },
  { id: 5, name: "hEX S", host: "192.168.1.5", kind: "gateway", vendor: "MikroTik", model: "RB760iGS", status: "up", polled: 12, detected_driver: "mikrotik", firmware: "7.25.1" },
  { id: 7, name: "NAS", host: "192.168.1.20", kind: "other", vendor: "Synology", model: "DiskStation", status: "up", polled: 12, detected_driver: "generic", firmware: null },
  { id: 4, name: "Garaż (testowy)", host: "192.168.1.9", kind: "other", vendor: null, model: null, status: "down", polled: 95, error: "192.168.1.9: No SNMP response received before timeout" },
].map((d) => ({
  port: 161, enabled: true, driver: "auto", detected_driver: "unifi", snmp_version: "2c", firmware: null, sys_name: d.name,
  uptime_s: 3_000_000, last_polled_at: ago(d.polled), last_ok_at: ago(d.polled), last_error: d.error ?? null, created_at: ago(86400 * 30), ...d,
}));

// Przebieg ruchu w Mb/s: i – numer próbki wstecz, k – 0 pobieranie, 1 wysyłanie
const wave = (i, k) => Math.max(0.2, (k === 0 ? 38 : 6) * (1 + 0.5 * Math.sin(i / 7 + k) + 0.25 * Math.sin(i / 2.3)));


// --- aktualizacja z panelu (symulacja): sprawdzanie → zmiany → postęp co 2 s → sukces ---------------------------
let installed = VERSION;
let updateInfo = null;
const idleJob = { state: "idle", phase: null, phases: [], started_at: null, finished_at: null, from_version: null, to_version: null, from_commit: null, to_commit: null, error: null, note: null, log: [] };
let job = { ...idleJob };
const PHASES = ["prepare", "backup", "fetch", "build", "start", "verify"];
const updatesView = () => ({
  installed_version: installed,
  updater: { configured: true, reachable: true, message: null },
  current: { version: installed, commit: installed === VERSION ? "abc1234" : "def5678", branch: "main" },
  info: updateInfo,
  job,
});
function startSimulation() {
  let i = 0;
  job = {
    ...idleJob, state: "running", phase: PHASES[0], started_at: now(), from_version: installed, to_version: NEXT_VERSION, from_commit: "abc1234", to_commit: "def5678",
    phases: PHASES.map((id, n) => ({ id, status: n === 0 ? "running" : "pending" })), log: ["== prepare", "Wolne miejsce: 41000 MB (wymagane co najmniej 2000 MB)"],
  };
  const timer = setInterval(() => {
    job.phases[i].status = "done";
    i += 1;
    if (i >= PHASES.length) {
      clearInterval(timer);
      installed = NEXT_VERSION;
      updateInfo = null;
      job = { ...job, state: "ok", phase: null, finished_at: now(), log: [...job.log, "Aktualizacja zakończona"] };
      return;
    }
    job.phases[i].status = "running";
    job.phase = PHASES[i];
    job.log = [...job.log, `== ${PHASES[i]}`];
  }, 2000);
}

const publicUser = () => user && { id: 1, username: user.username, is_admin: true, created_at: user.created, last_login_at: user.lastLogin };
// Dane po angielsku dla Accept-Language: en – jak prawdziwy backend (netpulse/i18n.py); zrzuty do README są po angielsku
const EN = [
  ["Garaż (testowy)", "Garage (test)"],
  ["Garaż (test) nie odpowiada", "Garage (test) is not responding"],
  ["Dysk /mnt/data zajęty w 91 %", "Disk /mnt/data 91% full"],
  ["Ping 8.8.8.8 – utrata 20 %", "Ping 8.8.8.8 – 20% packet loss"],
  ["Kopia vzdump LXC 101 gotowa", "vzdump backup of LXC 101 finished"],
  ["Port 7 przeszedł w stan down", "Port 7 went down"],
  ["Urządzenie nie odpowiada", "Device is not responding"],
  ["Internet – Google DNS", "Internet – Google DNS"],
  ["Proxmox – panel", "Proxmox – web UI"],
  ["Światłowód", "Fiber"],
  ["Aktualizacja zakończona", "Update finished"],
];
const english = (text) => EN.reduce((t, [pl, en]) => t.split(JSON.stringify(pl).slice(1, -1)).join(JSON.stringify(en).slice(1, -1)), text);
const send = (res, code, body, headers = {}) => {
  res.writeHead(code, { "Content-Type": "application/json", ...headers });
  const text = body === undefined ? undefined : JSON.stringify(body);
  res.end(text !== undefined && res.lang === "en" ? english(text) : text);
};
const readBody = (req) => new Promise((resolve) => {
  let data = "";
  req.on("data", (c) => (data += c));
  req.on("end", () => { try { resolve(JSON.parse(data || "{}")); } catch { resolve({}); } });
});
const token = (req) => /netpulse_session=([^;]+)/.exec(req.headers.cookie ?? "")?.[1];
const authed = (req) => sessions.has(token(req));
const startSession = (res) => {
  const t = randomBytes(16).toString("hex");
  sessions.add(t);
  user.lastLogin = now();
  return { "Set-Cookie": `netpulse_session=${t}; HttpOnly; SameSite=Lax; Path=/` };
};

createServer(async (req, res) => {
  res.lang = (req.headers["accept-language"] ?? "").toLowerCase().startsWith("en") ? "en" : "pl";
  const url = new URL(req.url, "http://x");
  const route = `${req.method} ${url.pathname}`;
  const body = ["POST", "PATCH", "PUT"].includes(req.method) ? await readBody(req) : {};

  if (route === "GET /api/health") return send(res, 200, { status: "ok", timescaledb: true });
  if (route === "GET /api/auth/status") {
    return send(res, 200, { setup_required: !user, authenticated: !!user && authed(req), user: user && authed(req) ? publicUser() : null, version: user && authed(req) ? VERSION : null });
  }
  if (route === "POST /api/auth/setup") {
    if (user) return send(res, 409, { detail: "Konto administratora już istnieje – zaloguj się" });
    if ((body.password ?? "").length < 8) return send(res, 422, { detail: "Hasło musi mieć co najmniej 8 znaków" });
    user = { username: body.username, password: body.password, created: now(), lastLogin: null };
    return send(res, 201, publicUser(), startSession(res));
  }
  if (route === "POST /api/auth/login") {
    if (!user || body.username !== user.username || body.password !== user.password) return send(res, 401, { detail: "Nieprawidłowy login lub hasło" });
    return send(res, 200, publicUser(), startSession(res));
  }
  if (route === "POST /api/auth/logout") {
    sessions.delete(token(req));
    return send(res, 204, undefined, { "Set-Cookie": "netpulse_session=; Max-Age=0; Path=/" });
  }
  if (!authed(req)) return send(res, 401, { detail: "Wymagane logowanie" });
  if (route === "GET /api/auth/me") return send(res, 200, publicUser());
  if (route === "POST /api/auth/password") {
    if (body.current_password !== user.password) return send(res, 403, { detail: "Obecne hasło jest nieprawidłowe" });
    user.password = body.new_password;
    return send(res, 204);
  }
  if (route === "GET /api/dashboard/summary") {
    const up = devices.filter((d) => d.status === "up").length;
    return send(res, 200, {
      devices: { total: devices.length, up, down: devices.length - up, unknown: 0 },
      wan: { in_bps: wave(0, 0) * 1e6, out_bps: wave(0, 1) * 1e6, interfaces: 1 },
      wifi_clients: 17,
      last_poll_at: ago(12),
      poll_interval_s: 30,
    });
  }
  // VPN bramy UniFi (0.57.0): jeden klient połączony, drugi rozłączony
  if (route === "GET /api/vpn") {
    return send(res, 200, {
      at: ago(10), stale: false, device_id: 1,
      servers: [{ id: "net-wg", name: "WG-Home", type: "WireGuard", enabled: true, port: 51820, subnet: "192.168.3.1/24" }],
      users: [
        { name: "iPhone", server: "WG-Home", tunnel_ip: "192.168.3.2", connected: true, since: ago(840), last_seen: ago(10), remote_ip: "203.0.113.7",
          down_bytes: 76148892, up_bytes: 11867028, down_bps: wave(0, 2) * 2e6, up_bps: wave(0, 3) * 5e5 },
        { name: "Laptop", server: "WG-Home", tunnel_ip: "192.168.3.3", connected: false, since: null, last_seen: ago(7200), remote_ip: "198.51.100.4",
          down_bytes: 5_400_000, up_bytes: 900_000, down_bps: null, up_bps: null },
      ],
    });
  }
  // Zdarzenia na osi czasu (adnotacje): restart, przełączenie WAN i połączenie VPN – w oknie zapytania
  if (route === "GET /api/events") {
    const minutes = Number(url.searchParams.get("minutes") ?? 60);
    const back = Number(url.searchParams.get("offset") ?? 0) * 60_000;
    const until = Date.now() - back;
    const all = [
      { at: 40, kind: "restart", title: "USW Lite 8 PoE", device_id: 2 },
      { at: 25, kind: "wan_switch", title: "WAN 1 → WAN 2", device_id: 1 },
      { at: 14, kind: "vpn_connect", title: "iPhone", device_id: 1 },
    ];
    const events = all
      .map(({ at, ...e }) => ({ ...e, time: new Date(Date.now() - at * 60_000).toISOString() }))
      .filter((e) => { const t = Date.parse(e.time); return t <= until && t >= until - minutes * 60_000; });
    return send(res, 200, events);
  }
  if (route === "GET /api/dashboard/traffic" || route === "GET /api/dashboard/wifi") {
    const minutes = Number(url.searchParams.get("minutes") ?? 60);
    const back = Number(url.searchParams.get("offset") ?? 0) * 60_000; // okno przesunięte wstecz, jak w API
    const stride = bucketS(minutes);
    const n = Math.floor((minutes * 60) / stride);
    const points = [];
    for (let i = n; i >= 0; i--) {
      if (!back && i > n * 0.55 && i < n * 0.62) continue; // przerwa w danych – urządzenie nie odpowiadało
      const time = new Date(Date.now() - back - i * stride * 1000).toISOString();
      // Szczyt (od 0.70.0): zwykle nieco ponad średnią, a raz w zakresie – test prędkości 455 / 51 Mb/s
      const test = i === Math.round(n * 0.2);
      const values = route.endsWith("traffic")
        ? {
            in_bps: wave(i, 0) * 1e6 + (test ? 9e7 : 0),
            out_bps: wave(i, 1) * 1e6 + (test ? 1.4e7 : 0),
            in_bps_max: minutes > 10080 ? null : test ? 4.55e8 : wave(i, 0) * 1.25e6,
            out_bps_max: minutes > 10080 ? null : test ? 5.1e7 : wave(i, 1) * 1.3e6,
          }
        : { clients: Math.round(12 + 5 * Math.sin(i / 9) + (i % 3)) };
      points.push({ time, values });
    }
    return send(res, 200, { interval_s: stride, points });
  }
  // Wykrywanie urządzeń i raport (0.73.0)
  if (route === "GET /api/discovery/suggest") return send(res, 200, { network: "192.168.1.0/24" });
  if (route === "POST /api/discovery/scan") {
    await new Promise((r) => setTimeout(r, 1200));
    const known = (host) => devices.find((d) => d.host === host)?.id ?? null;
    const f = (host, name, vendor, model, firmware, kind, driver) => ({
      host, name, suggested_name: name, descr: null, object_id: null, vendor, model, firmware, kind, driver, generic: driver === "generic", device_id: known(host),
    });
    return send(res, 200, {
      network: body.network, scanned: 254, took_s: 4.4,
      found: [
        f("192.168.1.1", "UCG-Ultra", "Ubiquiti", "UCG-Ultra", "6.0.17", "gateway", "unifi"),
        f("192.168.1.2", "USW-Switch", "Ubiquiti", "UniFi Switch", null, "switch", "unifi"),
        f("192.168.1.3", "APU6-Plus", "Ubiquiti", "U6+", "6.7.54.15663", "ap", "unifi"),
        f("192.168.1.20", "nas", "Synology", "DiskStation", null, "other", "generic"),
        f("192.168.1.40", "drukarka", "HP", "Printer", null, "other", "generic"),
        f("192.168.1.62", "MikroTik", "MikroTik", "CHR", "7.18.2", "gateway", "mikrotik"),
      ],
    });
  }
  const reportMatch = /^\/api\/devices\/(\d+)\/report$/.exec(url.pathname);
  if (reportMatch && req.method === "POST") {
    await new Promise((r) => setTimeout(r, 1500));
    const hex = (t) => Buffer.from(t).toString("hex");
    const walk = [
      `1.3.6.1.2.1.1.1.0|4x|${hex("DiskStation DS920+ Linux 4.4.302")}`, "1.3.6.1.2.1.1.2.0|6|1.3.6.1.4.1.6574.1", "1.3.6.1.2.1.1.3.0|67|123456",
      `1.3.6.1.2.1.1.4.0|4x|${hex("homelab")}`, `1.3.6.1.2.1.1.5.0|4x|${hex("device")}`,
      ...[1, 2].flatMap((n) => [`1.3.6.1.2.1.2.2.1.2.${n}|4x|${hex(`eth${n - 1}`)}`, `1.3.6.1.2.1.2.2.1.6.${n}|4x|02a1b2c3d4e${n}`, `1.3.6.1.2.1.31.1.1.1.6.${n}|70|${n * 987654321}`]),
      `1.3.6.1.4.1.6574.1.5.1.0|4x|${hex("DS920+")}`, `1.3.6.1.4.1.6574.1.5.2.0|4x|${hex("SERIAL")}`, "1.3.6.1.4.1.6574.2.1.1.6.0|2|38",
    ];
    return send(res, 200, {
      format: "netpulse-device-report", format_version: 1, netpulse: VERSION, created_at: new Date().toISOString(), interval_s: 30,
      device: { sys_object_id: "1.3.6.1.4.1.6574.1", sys_descr: "DiskStation DS920+ Linux 4.4.302", detected_driver: "generic", driver: "auto", uptime_s: 1234 },
      branches: [
        { oid: "1.3.6.1.2.1.1", name: "SNMPv2-MIB::system", records: 5, truncated: false },
        { oid: "1.3.6.1.2.1.2", name: "IF-MIB::interfaces", records: 4, truncated: false },
        { oid: "1.3.6.1.2.1.31.1.1", name: "IF-MIB::ifXTable", records: 2, truncated: false },
        { oid: "1.3.6.1.2.1.105.1", name: "POWER-ETHERNET-MIB", records: 0, truncated: false },
        { oid: "1.3.6.1.4.1.6574", name: "gałąź producenta (1.3.6.1.4.1.6574)", records: 3, truncated: false },
      ],
      records: walk.length, changed: 2, walk: walk.join("\n") + "\n",
      walk2_changes: "1.3.6.1.2.1.31.1.1.1.6.1|70|987700000\n1.3.6.1.2.1.31.1.1.1.6.2|70|1975400000\n", notes: "",
    });
  }
  const idMatch = /^\/api\/devices\/(\d+)(\/probe)?$/.exec(url.pathname);
  if (route === "POST /api/probe" || (idMatch?.[2] && req.method === "POST")) {
    await new Promise((r) => setTimeout(r, 700)); // test SNMP chwilę trwa
    if (body.host === "192.168.1.9" || (idMatch && devices.find((d) => d.id === Number(idMatch[1]))?.status === "down")) {
      return send(res, 422, { detail: `Brak odpowiedzi SNMP z ${body.host ?? "urządzenia"}: No SNMP response received before timeout` });
    }
    return send(res, 200, {
      driver: "unifi", name: "USW-Switch", vendor: "Ubiquiti", model: "UniFi Switch", firmware: null, kind: "switch", uptime_s: 3_950_000,
      interfaces: [1, 2, 3, 4, 5, 6, 7, 8].map((n) => ({ if_index: n, name: `0/${n}`, label: `Port ${n}`, alias: null, role: "port", hidden: false, oper_status: "up", speed_mbps: 1000 })),
      wifi: [],
    });
  }
  if (route === "POST /api/devices") {
    if (devices.some((d) => d.host === body.host)) return send(res, 409, { detail: `Urządzenie ${body.host} już jest dodane` });
    if (url.searchParams.get("probe") !== "false" && body.host === "192.168.1.9") {
      return send(res, 422, { detail: `Brak odpowiedzi SNMP z ${body.host}: No SNMP response received before timeout` });
    }
    const device = {
      id: Math.max(0, ...devices.map((d) => d.id)) + 1, name: body.name, host: body.host, port: body.port ?? 161, enabled: true,
      driver: body.driver ?? "auto", detected_driver: null, snmp_version: body.snmp_version ?? "2c", v3_username: body.v3_username ?? null,
      v3_auth_protocol: body.v3_auth_protocol ?? null, v3_priv_protocol: body.v3_priv_protocol ?? null, v3_context: body.v3_context ?? null,
      kind: "other", vendor: null, model: null, firmware: null, sys_name: null, uptime_s: null, status: "unknown", last_polled_at: null,
      last_ok_at: null, last_error: null, created_at: now(),
    };
    devices.push(device);
    return send(res, 201, device);
  }
  if (idMatch && !idMatch[2] && (req.method === "PATCH" || req.method === "DELETE")) {
    const body2 = body;
    const i = devices.findIndex((d) => d.id === Number(idMatch[1]));
    if (i < 0) return send(res, 404, { detail: "Nie ma takiego urządzenia" });
    if (req.method === "DELETE") { devices.splice(i, 1); return send(res, 204); }
    const { community, v3_auth_key, v3_priv_key, ...fields } = body2;
    Object.assign(devices[i], fields);
    return send(res, 200, devices[i]);
  }
  if (route === "GET /api/updates") return send(res, 200, updatesView());
  if (route === "POST /api/updates/check") {
    await new Promise((r) => setTimeout(r, 900));
    updateInfo = installed === NEXT_VERSION
      ? { current: { version: installed, commit: "def5678" }, latest: { version: installed, commit: "def5678" }, behind: 0, ahead: 0, diverged: false, update_available: false, changes: [], checked_at: now() }
      : {
          current: { version: installed, commit: "abc1234" }, latest: { version: NEXT_VERSION, commit: "def5678" }, behind: 3, ahead: 0, diverged: false, update_available: true, checked_at: now(),
          changes: [
            { sha: "def5678", subject: "Etap 5d: aktualizacja jednym kliknięciem" },
            { sha: "b0c1d2e", subject: "Kontrola miejsca na dysku w install.sh i uplinkview update" },
            { sha: "9a8b7c6", subject: "Etap 5c: ustawienia – zarządzanie urządzeniami z panelu" },
          ],
        };
    return send(res, 200, updatesView());
  }
  if (route === "POST /api/updates/apply") {
    if (job.state === "running") return send(res, 409, { detail: "Aktualizacja już trwa." });
    startSimulation();
    return send(res, 202, updatesView());
  }
  // --- pulpit: układ, moduły i dane paneli (wykresy, kolekcje, stany) ---
  // Mapa sieci z obciążeniem kabli: brama – switch (uplink mocno zajęty) – AP, modem za bramą
  // Dwa łącza WAN: światłowód niesie ruch, 25 minut temu przełączenie na LTE na 10 minut
  if (route === "GET /api/wan/history") {
    const minutes = Number(url.searchParams.get("minutes") ?? 60);
    const stride = bucketS(minutes);
    const link = (id, name, position, iface) => ({
      id, name, position, device_id: 1, device_name: "UCG Ultra", interface_id: iface, interface_name: `eth${iface}`, interface_label: name,
      speed_mbps: 1000, state: id === 1 ? "active" : "standby", state_since: ago(900), source: "traffic", in_bps: null, out_bps: null, sampled_at: ago(10),
    });
    const onLte = (s) => s >= 15 * 60 && s < 25 * 60;
    const points = [];
    for (let i = Math.floor((minutes * 60) / stride); i >= 0; i--) {
      const lte = onLte(i * stride);
      points.push({ time: ago(i * stride), values: { in_1: lte ? null : wave(i, 0) * 1e6, out_1: lte ? null : wave(i, 1) * 1e6, in_2: lte ? wave(i, 0) * 4e5 : null, out_2: lte ? wave(i, 1) * 4e5 : null } });
    }
    return send(res, 200, {
      interval_s: stride,
      links: [link(1, "Światłowód", 1, 4), link(2, "LTE", 2, 3)],
      points,
      segments: [
        { link_id: 1, state: "active", start: ago(minutes * 60), end: ago(1500) }, { link_id: 1, state: "down", start: ago(1500), end: ago(900) }, { link_id: 1, state: "active", start: ago(900), end: now() },
        { link_id: 2, state: "standby", start: ago(minutes * 60), end: ago(1500) }, { link_id: 2, state: "active", start: ago(1500), end: ago(900) }, { link_id: 2, state: "standby", start: ago(900), end: now() },
      ],
      switches: [{ time: ago(1500), from_ids: [1], to_ids: [2] }, { time: ago(900), from_ids: [2], to_ids: [1] }],
    });
  }
  if (route === "GET /api/topology") {
    const node = (id, name, device_kind) => ({ id: `d${id}`, kind: "device", device_id: id, name, device_kind, model: null, status: "up" });
    return send(res, 200, {
      nodes: [node(1, "UCG Ultra", "gateway"), node(2, "USW Lite 8 PoE", "switch"), node(3, "U6+", "ap"),
        { id: "x02:00:ff:33:66:69", kind: "external", device_id: null, name: "02:00:ff:33:66:69", device_kind: null, model: null, status: null }],
      edges: [
        { a: "d1", a_port: 1, b: "d2", b_port: 8, interface_id: 28, device_id: 2, speed_mbps: 1000, traffic_bps: 6.2e8, utilization: 0.62 },
        { a: "d2", a_port: 1, b: "d3", b_port: 1, interface_id: 21, device_id: 2, speed_mbps: 1000, traffic_bps: 4.1e7, utilization: 0.041 },
        { a: "d1", a_port: 5, b: "x02:00:ff:33:66:69", b_port: null, interface_id: 5, device_id: 1, speed_mbps: 1000, traffic_bps: 9.1e8, utilization: 0.91 },
      ],
    });
  }
  if (route === "GET /api/clients") return send(res, 200, []);
  if (route === "GET /api/modules") return send(res, 200, { proxmox: false, unifi: true, agents: false, backups: false });
  if (route === "GET /api/dashboards") return send(res, 200, []);
  if (route === "GET /api/dashboards/default") return send(res, 200, { layout, updated_at: layoutAt });
  if (route === "PUT /api/dashboards/default") {
    layout = body;
    layoutAt = now();
    return send(res, 200, { layout, updated_at: layoutAt });
  }
  if (route === "DELETE /api/dashboards/default") {
    layout = null;
    return send(res, 204);
  }
  const one = /^\/api\/devices\/(\d+)$/.exec(url.pathname);
  if (req.method === "GET" && one) {
    const d = devices.find((x) => x.id === Number(one[1]));
    return d ? send(res, 200, d) : send(res, 404, { detail: "Nie ma takiego urządzenia" });
  }
  // Czujniki, PoE i SFP (MikroTik, od 0.50.0) – tylko hEX S
  const sensors = /^\/api\/devices\/(\d+)\/sensors$/.exec(url.pathname);
  if (req.method === "GET" && sensors) {
    if (Number(sensors[1]) !== 5) return send(res, 200, { sensors: [], poe: [], sfp: [] });
    return send(res, 200, {
      sensors: [
        { key: "cpu-temperature", metric: "temp_c", value: 47 },
        { key: "board-temperature1", metric: "temp_c", value: 39 },
        { key: "voltage", metric: "voltage_v", value: 24.1 },
        { key: "poe-out-consumption", metric: "power_w", value: 3.6 },
      ],
      poe: [{ port: "ether5", state: 3, power_w: 3.6, voltage_v: 23.8 }],
      sfp: [{ port: "sfp1", rx_dbm: -7.34, tx_dbm: -5.87, temp_c: 41, voltage_v: 3.29, rx_loss: false, tx_fault: false }],
    });
  }
  const ifaces = /^\/api\/devices\/(\d+)\/interfaces$/.exec(url.pathname);
  if (req.method === "GET" && ifaces) {
    const dev = Number(ifaces[1]);
    return send(
      res,
      200,
      [1, 2, 3, 4, 5, 6, 7, 8].map((n) => ({
        id: dev * 10 + n, if_index: n, name: `0/${n}`, label: `Port ${n}`, alias: n === 1 ? "UCG Ultra" : null, role: "port", hidden: false, mac: null,
        admin_up: true, oper_status: n <= 6 ? "up" : "down", speed_mbps: n === 6 ? 100 : 1000, in_bps: n <= 6 ? wave(n, 0) * 1e5 : null, out_bps: n <= 6 ? wave(n, 1) * 1e5 : null,
      })),
    );
  }
  // Źródła z tabeli `metrics` na bramie: klienci VPN (0.57.0) – klient połączony w ostatnich 14 minutach
  if (req.method === "GET" && /^\/api\/devices\/\d+\/agent-keys$/.test(url.pathname)) {
    return send(res, 200, { agent_net: [], agent_disk: [], agent_temp: [], agent_container: [], pve_guest: [], snmp_sensor: [], snmp_poe: [], snmp_sfp: [], wan_latency: [], wan_ping: [], speedtest: ["eth4"], vpn: ["iPhone", "Laptop"] });
  }
  if (req.method === "GET" && /^\/api\/devices\/\d+\/agent-metrics$/.test(url.pathname) && url.searchParams.get("source") === "vpn") {
    const minutes = Number(url.searchParams.get("minutes") ?? 60);
    const stride = bucketS(minutes);
    const points = [];
    for (let i = Math.floor((minutes * 60) / stride); i >= 0; i--) {
      const on = url.searchParams.get("key") === "iPhone" && i * stride <= 840;
      points.push({ time: new Date(Date.now() - i * stride * 1000).toISOString(), values: on ? { down_bps: wave(i, 2) * 2e6, up_bps: wave(i, 3) * 5e5, connected: 1 } : { connected: 0 } });
    }
    return send(res, 200, points);
  }
  // Testy prędkości bramy (od 0.70.0): kilka punktów w zakresie, wynik jak z bramy
  if (req.method === "GET" && /^\/api\/devices\/\d+\/agent-metrics$/.test(url.pathname) && url.searchParams.get("source") === "speedtest") {
    const minutes = Number(url.searchParams.get("minutes") ?? 60);
    const results = [[0.9, 448, 50.2, 7], [0.62, 455, 51, 6], [0.35, 431, 49.5, 8], [0.08, 455, 51, 6]];
    return send(res, 200, results.map(([at, down, up, ping]) => ({ time: new Date(Date.now() - at * minutes * 60_000).toISOString(), values: { down_bps: down * 1e6, up_bps: up * 1e6, ping_ms: ping } })));
  }
  const series = /^\/api\/(devices|interfaces|wifi)\/(\d+)\/metrics$/.exec(url.pathname) || url.pathname === "/api/system/metrics";
  if (req.method === "GET" && series) {
    const minutes = Number(url.searchParams.get("minutes") ?? 60);
    const back = Number(url.searchParams.get("offset") ?? 0) * 60_000;
    const stride = bucketS(minutes);
    const points = [];
    for (let i = Math.floor((minutes * 60) / stride); i >= 0; i--) {
      const time = new Date(Date.now() - back - i * stride * 1000).toISOString();
      const cpu = 20 + 15 * Math.sin(i / 11) + (i % 5);
      points.push({ time, values: { cpu_percent: cpu, mem_used_percent: 48 + 4 * Math.sin(i / 23), load1: cpu / 40, poll_ms: 40 + (i % 7) * 3, in_bps: wave(i, 0) * 4e5, out_bps: wave(i, 1) * 4e5, in_bps_max: wave(i, 0) * 5e5, out_bps_max: wave(i, 1) * 5.2e5, clients: 5 + (i % 4), disk_used_percent: 63, temp_c: 52 + (i % 6) } });
    }
    return send(res, 200, points);
  }
  // Sprawdzenia dostępności: ping z utratą pakietów, strona www z błędem i certyfikatem
  if (route === "GET /api/checks") {
    const base = { port: null, timeout_s: 3, enabled: true, expect_status: null, keyword: null, verify_tls: true, status_since: ago(3600), last_checked_at: ago(5), created_at: ago(86400) };
    return send(res, 200, [
      { ...base, id: 1, name: "Internet – Google DNS", kind: "ping", target: "8.8.8.8", interval_s: 30, status: "up", last_ok_at: ago(5), last_error: null, last_latency_ms: 15.2, availability_24h: 99.8, loss_percent: 0, jitter_ms: 0.6, status_code: null, cert_days: null },
      { ...base, id: 2, name: "Brama UCG", kind: "ping", target: "192.168.1.1", interval_s: 30, status: "up", last_ok_at: ago(5), last_error: null, last_latency_ms: 0.9, availability_24h: 100, loss_percent: 0, jitter_ms: 0.1, status_code: null, cert_days: null },
      { ...base, id: 3, name: "Pi-hole", kind: "http", target: "https://pihole.lan/admin", interval_s: 60, timeout_s: 10, verify_tls: false, status: "down", last_ok_at: ago(900), last_error: "Kod HTTP 502 (oczekiwany 200-399)", last_latency_ms: 41, availability_24h: 96.4, loss_percent: null, jitter_ms: null, status_code: 502, cert_days: 61 },
      { ...base, id: 4, name: "Proxmox – panel", kind: "tcp", target: "192.168.1.86", port: 8006, interval_s: 60, status: "up", last_ok_at: ago(20), last_error: null, last_latency_ms: 2.4, availability_24h: 100, loss_percent: null, jitter_ms: null, status_code: null, cert_days: null },
      { ...base, id: 5, name: "DNS – NAS", kind: "dns", target: "nas.lan", dns_type: "A", dns_server: "192.168.1.1", keyword: "192.168.1.34", interval_s: 60, status: "up", last_ok_at: ago(20), last_error: null, last_latency_ms: 3.1, last_answer: "192.168.1.34", availability_24h: 100, loss_percent: null, jitter_ms: null, status_code: null, cert_days: null },
    ]);
  }
  if (route === "GET /api/reports/monthly") {
    const [y, m] = (url.searchParams.get("month") || "2026-10").split("-").map(Number);
    const names = ["styczeń", "luty", "marzec", "kwiecień", "maj", "czerwiec", "lipiec", "sierpień", "wrzesień", "październik", "listopad", "grudzień"];
    return send(res, 200, { ...{
      year: 2026,
      month: 10,
      title: "październik 2026",
      start: "2026-09-30T22:00:00Z",
      end: "2026-10-31T23:00:00Z",
      generated_at: "2026-11-06T08:00:00Z",
      timezone: "Europe/Warsaw",
      version: VERSION,
      raw_from: "2026-10-07T00:00:00Z",
      devices_percent: 99.9975,
      checks_percent: 99.5,
      devices: [
        { id: 1, name: "UCG Ultra", host: "192.168.1.1", kind: "gateway", percent: 99.995, down_s: 120, maintenance_s: 0, samples: 89000 },
        { id: 2, name: "USW Lite 8 PoE", host: "192.168.1.2", kind: "switch", percent: 100, down_s: 0, maintenance_s: 3600, samples: 89000 },
      ],
      checks: [{ id: 1, name: "Internet – Google DNS", kind: "ping", target: "8.8.8.8", percent: 99.5, samples: 2000, failed: 10, avg_latency_ms: 15.24, max_latency_ms: 80 }],
      wan: [{ name: "WAN 1", device: "UCG Ultra", rx_bytes: 512.3e9, tx_bytes: 40.1e9, percent: 99.9, down_s: 2580, outages: 2, longest_outage_s: 1800 }],
      alerts: [
        { id: 1, title: "Port 7 przeszedł w stan down", severity: "warning", device: "USW Lite 8 PoE", started_at: "2026-10-03T10:00:00Z", resolved_at: "2026-10-03T10:30:00Z", duration_s: 1800, maintenance: false },
        { id: 2, title: "Urządzenie nie odpowiada", severity: "critical", device: "UCG Ultra", started_at: "2026-10-20T02:00:00Z", resolved_at: null, duration_s: 3600, maintenance: true },
      ],
      alerts_total: 2,
      alerts_by_severity: { warning: 1, critical: 1 },
    }, year: y, month: m, title: `${names[m - 1]} ${y}` });
  }
  if (route === "GET /api/system/verification") {
    return send(res, 200, [
      { id: "snmp_ifmib", label: "SNMP: porty, ruch, błędy (IF-MIB), CPU i RAM (UCD-SNMP-MIB)", level: "verified", note: "UniFi UCG Ultra, USW Lite 8 PoE, U6+ i MikroTik RouterOS 7.18 (CHR)", drivers: ["generic", "unifi", "mikrotik", "omada", "linux"] },
      { id: "mikrotik_hw", label: "MikroTik: czujniki, PoE, SFP, kilka rdzeni", level: "test", note: "zrzut syntetyczny według oficjalnego MIKROTIK-MIB 7.25.1", drivers: ["mikrotik"] },
      { id: "proxmox", label: "Proxmox VE: węzły, maszyny VM i LXC, magazyny, kopie vzdump", level: "partial", note: "PVE 9.1 / 9.2 z jednym węzłem", drivers: ["proxmox"] },
    ]);
  }
  if (route === "POST /api/checks/test") return send(res, 200, { up: true, latency_ms: 14.8, loss_percent: 0, jitter_ms: 0.5, status_code: null, cert_days: null, error: null });
  if (req.method === "GET" && /^\/api\/checks\/\d+\/metrics$/.test(url.pathname)) {
    const minutes = Number(url.searchParams.get("minutes") ?? 60);
    const back = Number(url.searchParams.get("offset") ?? 0) * 60_000;
    const stride = bucketS(minutes);
    const points = [];
    for (let i = Math.floor((minutes * 60) / stride); i >= 0; i--) {
      const time = new Date(Date.now() - back - i * stride * 1000).toISOString();
      // Krótkie zakresy: pojedyncze zgubione pingi; 30 dni: większość dni czysta, jeden dzień z krótką przerwą
      // i jeden z awarią (różne dni dla każdego sprawdzenia) – paski dostępności kolorują tylko te dni
      const id = Number(url.pathname.split("/")[3]);
      const long = minutes > 1440;
      const outage = long && i >= 100 + id * 20 && i < 103 + id * 20;
      const spike = long ? i === 40 + id * 30 : i % 37 === 0;
      const availability = outage ? 20 : spike ? 80 : long && i % 9 === 0 ? 99.5 : 100;
      points.push({ time, values: { latency_ms: 15 + 3 * Math.sin(i / 7) + (spike ? 40 : 0), jitter_ms: 0.5 + (i % 4) * 0.2, loss_percent: 100 - availability, availability_percent: availability, cert_days: null } });
    }
    return send(res, 200, points);
  }
  // Alerty (pasek stanu i widget „Alerty”, od 0.42.0)
  if (route === "GET /api/alerts/summary") return send(res, 200, { firing: 1, unacked: 1, unacked_critical: 0, critical: 0, warning: 1, info: 0 });
  if (route === "GET /api/alerts") {
    const a = (id, state, severity, title, start, end) => ({ id, rule_id: 1, state, severity, title, message: null, device_id: null, value: null, peak: null, started_at: ago(start), resolved_at: end == null ? null : ago(end), acked_at: null, acked_by: null });
    const all = [
      a(4, "firing", "warning", "Dysk /mnt/data zajęty w 91 %", 720, null),
      a(3, "resolved", "critical", "Garaż (test) nie odpowiada", 11000, 10800),
      a(2, "resolved", "warning", "Ping 8.8.8.8 – utrata 20 %", 30000, 29800),
      a(1, "resolved", "info", "Kopia vzdump LXC 101 gotowa", 50000, 49990),
    ];
    const state = url.searchParams.get("state") ?? "firing";
    return send(res, 200, all.filter((x) => state === "all" || x.state === state).slice(0, Number(url.searchParams.get("limit") ?? 100)));
  }
  if (route === "GET /api/availability") return send(res, 200, devices.map((d) => ({ device_id: d.id, percent: d.status === "up" ? 99.9 : 61.2 })));
  const coll = /^\/api\/collections\/(\w+)$/.exec(url.pathname);
  if (req.method === "GET" && coll && coll[1] === "checks") {
    const rows = [
      ["1", "Internet – Google DNS", 1, 15.2, 99.8],
      ["2", "Brama UCG", 1, 0.9, 100],
      ["3", "Pi-hole", 0, 41, 96.4],
    ].map(([key, label, up, latency_ms, availability_percent]) => ({ key, label, device_id: null, values: { up, latency_ms, loss_percent: 0, availability_percent, cert_days: null } }));
    return send(res, 200, { kind: "checks", rows });
  }
  if (req.method === "GET" && coll) {
    const kind = coll[1];
    const rows =
      kind === "devices"
        ? devices.map((d, i) => ({ key: String(d.id), label: d.name, device_id: d.id, values: { up: d.status === "up" ? 1 : 0, cpu_percent: d.status === "up" ? 15 + i * 22 : null, mem_used_percent: d.status === "up" ? 40 + i * 9 : null, poll_ms: 45, uptime_s: d.uptime_s } }))
        : kind === "ports"
          ? [1, 2, 3, 4, 5, 6, 7, 8].map((n) => ({ key: String(Number(url.searchParams.get("device_id") ?? 2) * 10 + n), label: `Port ${n}`, device_id: Number(url.searchParams.get("device_id") ?? 2), values: { up: n === 6 ? 0 : 1, in_bps: n * 3e6, out_bps: n * 1e6, speed_mbps: n === 7 ? 100 : 1000 } }))
          : [["/", 35], ["/boot", 22], ["/mnt/data", 91], ["/mnt/backup", 74]].map(([m, p]) => ({ key: m, label: m, device_id: 1, values: { used_percent: p, used_bytes: p * 1e10, free_bytes: (100 - p) * 1e10, total_bytes: 1e12 } }));
    return send(res, 200, { kind, rows });
  }
  if (route === "GET /api/states") {
    const minutes = Number(url.searchParams.get("minutes") ?? 60);
    const end = Date.now();
    const start = end - minutes * 60_000;
    const iso = (t) => new Date(t).toISOString();
    const items = devices.map((d, i) => ({
      kind: "device", id: d.id, label: d.name,
      segments: d.status === "down"
        ? [{ start: iso(start), end: iso(start + (end - start) * 0.4), state: "up" }, { start: iso(start + (end - start) * 0.4), end: iso(end), state: "down" }]
        : [{ start: iso(start), end: iso(start + (end - start) * (0.3 + i * 0.1)), state: "up" }, { start: iso(start + (end - start) * (0.3 + i * 0.1)), end: iso(start + (end - start) * (0.33 + i * 0.1)), state: "unknown" }, { start: iso(start + (end - start) * (0.33 + i * 0.1)), end: iso(end), state: "up" }],
    }));
    return send(res, 200, { start: iso(start), end: iso(end), bucket_s: 30, items });
  }
  if (route === "GET /api/devices") {
    // Czas odczytu „odświeża się” z każdym zapytaniem
    return send(res, 200, devices.map((d) => (d.status === "up" ? { ...d, last_polled_at: ago(d.polled) } : d)));
  }
  send(res, 404, { detail: "Not Found" });
})
  // Dane na żywo wykresów kołowych: minimalny WebSocket (tylko ramki tekstowe serwer → przeglądarka), próbka co 1,5 s
  .on("upgrade", (req, socket) => {
    const url = new URL(req.url, "http://x");
    const device = Number(url.searchParams.get("device"));
    if (!(url.pathname === "/api/live/device" && device)) return socket.destroy();
    const accept = createHash("sha1").update(`${req.headers["sec-websocket-key"]}258EAFA5-E914-47DA-95CA-C5AB0DC85B11`).digest("base64");
    socket.write(["HTTP/1.1 101 Switching Protocols", "Upgrade: websocket", "Connection: Upgrade", `Sec-WebSocket-Accept: ${accept}`, "", ""].join("\r\n"));
    const frame = (text) => {
      const data = Buffer.from(text);
      const head = data.length < 126 ? Buffer.from([0x81, data.length]) : Buffer.from([0x81, 126, data.length >> 8, data.length & 255]);
      return Buffer.concat([head, data]);
    };
    let i = 0;
    const tick = () => {
      i += 1;
      const rate = (k, scale) => Math.max(0, wave(i, k) * scale * (0.6 + Math.random() * 0.8));
      const time = new Date().toISOString();
      const ports = Array.from({ length: 8 }, (_, n) => ({ id: device * 10 + n + 1, in_bps: n < 6 ? rate(n % 2, 2e6 * (n + 1)) : null, out_bps: n < 6 ? rate(1, 4e5 * (n + 1)) : null, up: n === 5 ? 0 : 1 }));
      const cpu = Math.min(99, 10 + 25 * Math.abs(Math.sin(i / 5)) + Math.random() * 8);
      const disks = [["/", 35], ["/mnt/data", 91]].map(([mount, p]) => {
        const used = (p + Math.sin(i / 3)) * 1e10;
        return { mount, used_percent: used / 1e10, used_bytes: used, free_bytes: 1e12 - used, total_bytes: 1e12 };
      });
      socket.write(frame(JSON.stringify({ time, ports, cpu_percent: cpu, mem_used_percent: 40 + Math.sin(i / 9) * 5, disks })));
    };
    tick();
    const timer = setInterval(tick, 1500);
    socket.on("data", (buf) => (buf[0] & 0x0f) === 8 && socket.end()); // ramka „close” z przeglądarki
    socket.on("close", () => clearInterval(timer));
    socket.on("error", () => clearInterval(timer));
  })
  .listen(PORT, "127.0.0.1", () => console.log(`Atrapa API UplinkView: http://127.0.0.1:${PORT}`));
