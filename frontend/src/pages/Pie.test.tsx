import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import { newWidget, type DashboardLayout, type PieConfig, type Widget } from "../lib/layout";
import type { CollectionRow } from "../lib/panels";
import { parseSample } from "../lib/live";
import { applyLive, pieCollection, pieData, pieMetricsFor } from "../lib/pie";
import { mockApi } from "../test/mockApi";
import { customWidgets } from "../test/addWidget";
import { renderApp } from "../test/renderApp";

const layoutWith = (...widgets: Widget[]): DashboardLayout => ({ version: 1, widgets });
const pie = (config: Partial<PieConfig>): PieConfig => ({ title: null, device_id: null, metric: "devices_state", item: null, limit: 8, ...config });

const DEVICES: CollectionRow[] = [
  { key: "1", label: "UCG Ultra", device_id: 1, values: { up: 1, cpu_percent: 23, mem_used_percent: 75 } },
  { key: "2", label: "USW Lite", device_id: 2, values: { up: 0, cpu_percent: null, mem_used_percent: null } },
  { key: "3", label: "U6+", device_id: 3, values: { up: null, cpu_percent: 5, mem_used_percent: 40 } },
];
const PORTS: CollectionRow[] = [1, 2, 3, 4].map((n) => ({
  key: String(10 + n),
  label: `Port ${n}`,
  device_id: 1,
  values: { up: n < 4 ? 1 : 0, in_bps: n < 4 ? n * 10e6 : null, out_bps: 1e6, speed_mbps: n < 4 ? (n === 3 ? 100 : 1000) : null },
}));

class FakeSocket {
  static instances: FakeSocket[] = [];
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;
  constructor(public url: string) {
    FakeSocket.instances.push(this);
  }
  close() {
    this.closed = true;
  }
}

beforeEach(() => {
  FakeSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeSocket);
});
const DISKS: CollectionRow[] = [
  { key: "/", label: "/", device_id: 5, values: { used_percent: 35, used_bytes: 35e9, free_bytes: 65e9, total_bytes: 100e9 } },
  { key: "/srv", label: "/srv", device_id: 5, values: { used_percent: 92, used_bytes: 920e9, free_bytes: 80e9, total_bytes: 1000e9 } },
];

describe("wykres kołowy – dane", () => {
  it("co można monitorować zależy od urządzenia", () => {
    expect(pieMetricsFor(null)).toEqual(["devices_state", "checks_state", "wifi_clients"]);
    expect(pieMetricsFor({ driver: "auto", kind: "switch" })).toEqual(["cpu", "mem", "port_load", "port_dir", "ports_state"]);
    expect(pieMetricsFor({ driver: "auto", kind: "ap" })).toContain("wifi_clients");
    expect(pieMetricsFor({ driver: "agent", kind: "server" })).toEqual(["cpu", "mem", "disk", "disks_share", "containers_mem", "containers_cpu", "services_state"]);
  });

  it("kolekcja: CPU z listy urządzeń, porty – wybranego urządzenia", () => {
    expect(pieCollection(pie({ device_id: 1, metric: "cpu" }))).toEqual({ kind: "devices", device_id: null });
    expect(pieCollection(pie({ device_id: 2, metric: "ports_in" }))).toEqual({ kind: "ports", device_id: 2 });
    expect(pieCollection(pie({ metric: "checks_state" }))).toEqual({ kind: "checks", device_id: null });
  });

  it("zajętość: CPU urządzenia i wybrany dysk", () => {
    const cpu = pieData(pie({ device_id: 1, metric: "cpu" }), DEVICES)!;
    expect(cpu.center).toBe("23%");
    expect(cpu.slices.map((s) => [s.label, s.value])).toEqual([
      ["Zajęte", 23],
      ["Wolne", 77],
    ]);
    expect(pieData(pie({ device_id: 2, metric: "cpu" }), DEVICES)).toBeNull(); // brak odczytu
    const disk = pieData(pie({ device_id: 5, metric: "disk", item: "/srv" }), DISKS)!;
    expect([disk.center, disk.sub, disk.slices[0].color]).toEqual(["92%", "/srv", "var(--chart-5)"]);
    expect(pieData(pie({ device_id: 5, metric: "disk" }), DISKS)!.sub).toBe("/"); // bez wyboru – pierwszy dysk
  });

  it("udział: od największego, reszta jako „Pozostałe”, zera pominięte", () => {
    const data = pieData(pie({ device_id: 1, metric: "ports_in", limit: 2 }), PORTS)!;
    expect(data.slices.map((s) => s.label)).toEqual(["Port 3", "Pozostałe"]);
    expect(data.slices[1].value).toBe(30e6);
    expect(data.center).toBe("60 Mb/s");
  });

  it("jeden port: obciążenie względem prędkości portu i odbierane / wysyłane", () => {
    const load = pieData(pie({ device_id: 1, metric: "port_load", item: "13" }), PORTS)!;
    expect([load.center, load.sub]).toEqual(["30%", "z 100 Mb/s"]); // 30 Mb/s z 100 Mb/s
    expect(load.slices.map((s) => [s.label, s.text])).toEqual([
      ["Zajęte", "30 Mb/s"],
      ["Wolne", "70 Mb/s"],
    ]);
    const dir = pieData(pie({ device_id: 1, metric: "port_dir", item: "12" }), PORTS)!;
    expect(dir.center).toBe("21 Mb/s");
    expect(dir.slices.map((s) => [s.label, s.text])).toEqual([
      ["Odbierane", "20 Mb/s"],
      ["Wysyłane", "1 Mb/s"],
    ]);
    expect(pieData(pie({ device_id: 1, metric: "port_load", item: "14" }), PORTS)).toBeNull(); // port odłączony
    expect(pieData(pie({ device_id: 1, metric: "port_load", item: "99" }), PORTS)).toBeNull();
  });

  it("dane na żywo: CPU urządzenia, dyski z próbki, prędkość i stan portów; brak wartości – odczyt z bazy", () => {
    const sample = parseSample({
      time: "t",
      ports: [{ id: 12, in_bps: null, out_bps: 9e6, up: 0 }],
      cpu_percent: 64,
      mem_used_percent: null,
      disks: [{ mount: "/", used_percent: 50, used_bytes: 50, free_bytes: 50, total_bytes: 100 }],
    });
    const cpu = applyLive(pie({ device_id: 1, metric: "cpu" }), DEVICES, sample);
    expect(cpu.applied).toBe(true);
    expect(pieData(pie({ device_id: 1, metric: "cpu" }), cpu.rows)!.center).toBe("64%");
    const mem = applyLive(pie({ device_id: 1, metric: "mem" }), DEVICES, sample);
    expect(mem.rows[0].values.mem_used_percent).toBe(75); // próbka bez RAM-u – odczyt z bazy
    const port = applyLive(pie({ device_id: 1, metric: "port_dir", item: "12" }), PORTS, sample).rows.find((r) => r.key === "12")!;
    expect([port.values.in_bps, port.values.out_bps, port.values.up]).toEqual([20e6, 9e6, 0]);
    const disks = applyLive(pie({ device_id: 5, metric: "disk" }), DISKS, sample);
    expect(disks.rows.map((r) => r.key)).toEqual(["/"]);
    expect(applyLive(pie({ device_id: 5, metric: "disk" }), DISKS, parseSample({ time: "t", ports: [] })).applied).toBe(false);
  });

  it("stan: działa, nie działa i brak danych", () => {
    const data = pieData(pie({ metric: "devices_state" }), DEVICES)!;
    expect(data.center).toBe("1 z 3");
    expect(data.slices.map((s) => [s.key, s.value])).toEqual([
      ["up", 1],
      ["down", 1],
      ["unknown", 1],
    ]);
    expect(pieData(pie({ metric: "checks_state" }), [])).toBeNull();
  });
});

describe("wykres kołowy – pulpit", () => {
  it("pokazuje pierścień z liczbą w środku i legendą", async () => {
    const w = newWidget("pie", "p1");
    if (w.type !== "pie") throw new Error();
    w.config = pie({ device_id: 1, metric: "ports_state" });
    mockApi({ layout: layoutWith(w), collections: { ports: PORTS } });
    renderApp();
    expect(await screen.findByRole("img", { name: /Porty: podłączone i odłączone.*Działa 3, Nie działa 1/ })).toBeInTheDocument();
    expect(screen.getByText("3 z 4")).toBeInTheDocument();
    const legend = screen.getByRole("list", { name: "Legenda wykresu" });
    expect(within(legend).getByText("75%")).toBeInTheDocument();
  });

  it("edytor: urządzenie, potem co monitorować; zapis do układu", async () => {
    const { state } = mockApi({ layout: layoutWith(), collections: { devices: DEVICES, ports: PORTS } });
    renderApp();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Edytuj pulpit" }));
    await user.click(screen.getByRole("button", { name: "Dodaj widget" }));
    await user.click(within(await customWidgets(user)).getByRole("button", { name: /Wykres kołowy/ }));
    const form = await screen.findByRole("dialog", { name: "Nowy wykres kołowy" });

    // Bez urządzenia – cała sieć
    const metric = within(form).getByLabelText("Co monitorować");
    expect(within(metric).getAllByRole("option").map((o) => o.textContent)).toContain("Urządzenia: działają i nie");
    await user.selectOptions(within(form).getByLabelText("Urządzenie"), "1");
    expect(within(metric).queryByRole("option", { name: "Urządzenia: działają i nie" })).not.toBeInTheDocument();
    await user.selectOptions(metric, "cpu");
    expect(await within(form).findByRole("img", { name: /Procesor \(CPU\) · UCG Ultra: Zajęte 23%, Wolne 77%/ })).toBeInTheDocument(); // podgląd
    await user.selectOptions(metric, "port_load");
    await user.click(within(form).getByRole("button", { name: "Zapisz" }));
    expect(within(form).getByText("Wybierz port.")).toBeInTheDocument(); // bez portu nie zapisze
    const port = within(form).getByLabelText("Port");
    await waitFor(() => expect(within(port).getAllByRole("option")).toHaveLength(5));
    await user.selectOptions(port, "13");
    expect(await within(form).findByRole("img", { name: /Obciążenie portu · Port 3 · UCG Ultra: Zajęte 30 Mb\/s/ })).toBeInTheDocument();
    await user.selectOptions(metric, "port_dir");
    expect(within(form).getByLabelText("Port")).toHaveValue("13"); // ten sam port po zmianie widoku

    await user.click(within(form).getByRole("button", { name: "Zapisz" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Nowy wykres kołowy" })).not.toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Zapisz" }));
    await waitFor(() => expect(state.layout).not.toBeNull());
    const saved = (state.layout as DashboardLayout).widgets[0];
    expect(saved.type === "pie" && saved.config).toMatchObject({ device_id: 1, metric: "port_dir", item: "13" });
  });

  it("wykres portu pokazuje prędkość na żywo, a po zerwaniu wraca do odczytów kolektora", async () => {
    const w = newWidget("pie", "p1");
    if (w.type !== "pie") throw new Error();
    w.config = pie({ device_id: 1, metric: "port_load", item: "12" });
    mockApi({ layout: layoutWith(w), collections: { ports: PORTS } });
    renderApp();
    expect(await screen.findByRole("img", { name: /Zajęte 20 Mb\/s/ })).toBeInTheDocument(); // odczyt kolektora
    // Wspólny kanał na żywo (0.45.0): jedno połączenie na urządzenie dla całej strony
    await waitFor(() => expect(FakeSocket.instances.length).toBeGreaterThan(0));
    const ws = FakeSocket.instances.at(-1)!;
    expect(ws.url).toMatch(/\/api\/live\/device\?device=1$/);

    act(() => ws.onmessage?.({ data: JSON.stringify({ time: "t", ports: [{ id: 12, in_bps: 450_000_000, out_bps: 5e6 }] }) }));
    expect(await screen.findByRole("img", { name: /Zajęte 450 Mb\/s/ })).toBeInTheDocument();
    expect(screen.getAllByText("45%").length).toBeGreaterThan(0);
    expect(screen.getByTitle("Prędkość portu odświeżana co ok. 1,5 s")).toBeInTheDocument(); // znacznik przy wykresie

    act(() => ws.onclose?.());
    expect(await screen.findByRole("img", { name: /Zajęte 20 Mb\/s/ })).toBeInTheDocument();
    expect(screen.queryByTitle("Prędkość portu odświeżana co ok. 1,5 s")).not.toBeInTheDocument();
  });

  it("CPU na żywo; stany całej sieci i urządzenia z agentem bez połączenia; inne wykresy bez przełącznika", async () => {
    const cpu = newWidget("pie", "p1");
    const state = newWidget("pie", "p2");
    const agent = newWidget("pie", "p3");
    if (cpu.type !== "pie" || state.type !== "pie" || agent.type !== "pie") throw new Error();
    cpu.config = pie({ device_id: 1, metric: "cpu" });
    state.config = pie({ metric: "devices_state" });
    agent.config = pie({ device_id: 5, metric: "mem" });
    const api = mockApi({ layout: layoutWith(cpu, state, agent, newWidget("chart", "c1")), collections: { devices: DEVICES } });
    api.state.devices = [...api.state.devices, { ...api.state.devices[0], id: 5, name: "NAS", kind: "server", driver: "agent" }];
    renderApp();
    expect(await screen.findByRole("img", { name: /Procesor \(CPU\) · UCG Ultra: Zajęte 23%/ })).toBeInTheDocument();
    await waitFor(() => expect(FakeSocket.instances).toHaveLength(1)); // tylko CPU urządzenia SNMP
    const ws = FakeSocket.instances[0];
    expect(ws.url).toMatch(/\/api\/live\/device\?device=1$/);
    act(() => ws.onmessage?.({ data: JSON.stringify({ time: "t", ports: [], cpu_percent: 81, mem_used_percent: 50 }) }));
    expect(await screen.findByRole("img", { name: /Procesor \(CPU\) · UCG Ultra: Zajęte 81%/ })).toBeInTheDocument();
    expect(screen.getAllByTitle("Prędkość portu odświeżana co ok. 1,5 s")).toHaveLength(1);
    // Bez przełączników przy wykresach – jeden wspólny w pasku górnym (0.45.0)
    expect(screen.getAllByRole("button", { name: /Na żywo|Dane na żywo/ })).toHaveLength(1);
  });
});
