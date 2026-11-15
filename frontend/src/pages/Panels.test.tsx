import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { newWidget, type DashboardLayout, type Widget } from "../lib/layout";
import { collectionPath, percentChange, reduceValues, rowLink, statesPath, thresholdColor, type CollectionRow } from "../lib/panels";
import { mockApi } from "../test/mockApi";
import { customWidgets } from "../test/addWidget";
import { renderApp } from "../test/renderApp";

const layoutWith = (...widgets: Widget[]): DashboardLayout => ({ version: 1, widgets });

const DISKS: CollectionRow[] = [
  { key: "/", label: "/", device_id: 5, values: { used_percent: 35, used_bytes: 35e9, free_bytes: 65e9, total_bytes: 100e9 } },
  { key: "/mnt/data", label: "/mnt/data", device_id: 5, values: { used_percent: 92, used_bytes: 3.68e12, free_bytes: 0.32e12, total_bytes: 4e12 } },
  { key: "/boot", label: "/boot", device_id: 5, values: { used_percent: null, used_bytes: null, free_bytes: null, total_bytes: null } },
];
const DEVICES: CollectionRow[] = [
  { key: "1", label: "UCG Ultra", device_id: 1, values: { up: 1, cpu_percent: 12, mem_used_percent: 40 } },
  { key: "2", label: "USW Lite", device_id: 2, values: { up: 0, cpu_percent: null, mem_used_percent: null } },
  { key: "3", label: "U6+", device_id: 3, values: { up: 1, cpu_percent: 30, mem_used_percent: 55 } },
];

describe("panele – funkcje", () => {
  it("zmiana w procentach", () => {
    expect(percentChange(112, 100)).toBeCloseTo(12);
    expect(percentChange(-5, -10)).toBeCloseTo(50); // z -10 do -5 to wzrost
    expect(percentChange(5, 0)).toBeNull();
    expect(percentChange(null, 3)).toBeNull();
  });

  it("link wiersza kolekcji do strony szczegółów", () => {
    const row = (key: string, device_id: number | null = null) => ({ key, label: key, device_id, values: {} });
    expect(rowLink("devices", row("3"))).toBe("/devices/3");
    expect(rowLink("ports", row("17", 2))).toBe("/devices/2/ports/17");
    expect(rowLink("ports", row("17"))).toBeNull();
    expect(rowLink("disks", row("/", 5))).toBe("/devices/5/server");
    expect(rowLink("checks", row("1"))).toBe("/settings/checks");
    expect(rowLink("clients", row("0"))).toBe("/clients");
  });

  it("kolor z progów, liczba z zakresu i ścieżki API", () => {
    const th = [
      { value: 90, color: 5 as const },
      { value: 70, color: 4 as const },
    ];
    expect([50, 70, 89, 95, null].map((v) => thresholdColor(v, th, 1))).toEqual([1, 4, 4, 5, 1]);
    expect(reduceValues([1, null, 5, 3], "last")).toBe(3);
    expect(reduceValues([1, null, 5, 3], "avg")).toBe(3);
    expect(reduceValues([1, null, 5, 3], "max")).toBe(5);
    expect(reduceValues([null], "min")).toBeNull();
    expect(collectionPath({ kind: "disks", device_id: 5 })).toBe("/api/collections/disks?device_id=5");
    expect(collectionPath({ kind: "devices", device_id: 5 })).toBe("/api/collections/devices");
    expect(statesPath([{ kind: "device", id: 1 }, { kind: "interface", id: 7 }, { kind: "device", id: 2 }], 60)).toBe("/api/states?devices=1,2&interfaces=7&minutes=60");
    expect(statesPath([], 15)).toBe("/api/states?minutes=15");
  });
});

describe("panele na pulpicie", () => {
  it("liczba: ostatnia wartość ruchu WAN w kolorze progu", async () => {
    const stat = newWidget("stat", "s1");
    if (stat.type !== "stat") throw new Error();
    stat.config.thresholds = [{ value: 1.5e6, color: 5 }];
    mockApi({ layout: layoutWith(stat) });
    renderApp();
    const value = await screen.findByLabelText("Ruch WAN: Pobieranie: 2 Mb/s", undefined, { timeout: 5000 });
    expect(value).toHaveStyle({ color: "var(--chart-5)" });
  });

  it("liczba jako wskaźnik ze zmianą względem poprzedniego okresu; pełny ekran", async () => {
    const stat = newWidget("stat", "s1");
    if (stat.type !== "stat") throw new Error();
    stat.config = { ...stat.config, display: "gauge", max: 4e6, show_change: true };
    const { calls } = mockApi({ layout: layoutWith(stat) });
    renderApp();
    const meter = await screen.findByRole("meter", { name: "Ruch WAN: Pobieranie" });
    expect(meter).toHaveAttribute("aria-valuemax", "4000000");
    expect(meter).toHaveAttribute("aria-valuetext", "2 Mb/s");
    // Atrapa zwraca te same dane dla poprzedniego okresu – zmiana 0%
    expect(await within(meter).findByText("0%")).toBeInTheDocument();
    expect(calls.some((c) => c.path === "/api/dashboard/traffic?minutes=60&offset=60")).toBe(true);

    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Pełny ekran" }));
    const dialog = screen.getByRole("dialog", { name: "Ruch WAN: Pobieranie" });
    expect(within(dialog).getByRole("meter")).toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: "Pełny ekran" })).not.toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("paski: zajętość dysków od największej, % do 100", async () => {
    const bars = newWidget("bargauge", "b1");
    if (bars.type !== "bargauge") throw new Error();
    bars.config = { ...bars.config, collection: { kind: "disks", device_id: 5 }, key: "used_percent", sort: "desc" };
    mockApi({ layout: layoutWith(bars), collections: { disks: DISKS } });
    renderApp();
    const list = await screen.findByRole("list", { name: "Dyski serwera: Zajętość" });
    const meters = within(list).getAllByRole("meter");
    expect(meters.map((m) => m.getAttribute("aria-label"))).toEqual(["/mnt/data", "/", "/boot"]); // brak wartości na końcu
    expect(meters[0]).toHaveAttribute("aria-valuemax", "100");
    expect(meters[0]).toHaveAttribute("aria-valuetext", "92%");
    expect(within(list).getByText("92%")).toHaveStyle({ color: "var(--chart-5)" }); // ponad progiem 90
  });

  it("tabela: kolumny, stan jako plakietka, sortowanie kliknięciem nagłówka", async () => {
    mockApi({ layout: layoutWith(newWidget("table", "t1")), collections: { devices: DEVICES } });
    renderApp();
    const table = await screen.findByRole("table", { name: "Urządzenia" });
    const names = () => within(table).getAllByRole("row").slice(1).map((r) => (r as HTMLTableRowElement).cells[0].textContent);
    expect(names()).toEqual(["U6+", "UCG Ultra", "USW Lite"]); // domyślnie po nazwie
    expect(within(table).getAllByText("nie działa")).toHaveLength(1);
    const user = userEvent.setup();
    await user.click(within(table).getByRole("button", { name: "CPU" }));
    expect(names()).toEqual(["U6+", "UCG Ultra", "USW Lite"]); // malejąco: 30, 12, brak
    await user.click(within(table).getByRole("button", { name: "CPU" }));
    expect(names()).toEqual(["UCG Ultra", "U6+", "USW Lite"]); // rosnąco, brak dalej na końcu
    // Nazwa prowadzi do strony szczegółów urządzenia
    expect(within(table).getByRole("link", { name: "UCG Ultra" })).toHaveAttribute("href", `/devices/${DEVICES.find((d) => d.label === "UCG Ultra")!.key}`);
  });

  it("oś stanów: pasy działania z opisem okresów", async () => {
    mockApi({
      layout: layoutWith(newWidget("state_timeline", "o1")),
      states: {
        start: "2026-10-25T11:00:00Z",
        end: "2026-10-25T12:00:00Z",
        bucket_s: 30,
        items: [
          {
            kind: "device",
            id: 2,
            label: "USW Lite",
            segments: [
              { start: "2026-10-25T11:00:00Z", end: "2026-10-25T11:30:00Z", state: "up" },
              { start: "2026-10-25T11:30:00Z", end: "2026-10-25T12:00:00Z", state: "down" },
            ],
          },
        ],
      },
    });
    renderApp();
    const band = await screen.findByRole("list", { name: "Stany: USW Lite" });
    const items = within(band).getAllByRole("listitem");
    expect(items.map((i) => i.getAttribute("aria-label")?.split(":")[0])).toEqual(["działa", "nie działa"]);
    expect(items[1]).toHaveStyle({ left: "50%" });
    // Na telefonie nie ma podpowiedzi – szczegóły odcinka po dotknięciu, pod pasem
    await userEvent.setup().click(within(items[1]).getByRole("button"));
    expect(screen.getByText(items[1].getAttribute("aria-label")!)).toBeInTheDocument();
  });
});

describe("edytory paneli", () => {
  async function addWidget(name: RegExp) {
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Edytuj pulpit" }));
    await user.click(screen.getByRole("button", { name: "Dodaj widget" }));
    await user.click(within(await customWidgets(user)).getByRole("button", { name }));
    return user;
  }

  it("paski: dyski wymagają serwera; próg w % trafia do układu", async () => {
    const server = { id: 5, name: "NAS", kind: "server" };
    const { state } = mockApi({ layout: layoutWith(), collections: { disks: DISKS } });
    state.devices = [...state.devices, { ...state.devices[0], ...server, driver: "agent", host: "nas" }];
    renderApp();
    const user = await addWidget(/Paski/);
    const form = await screen.findByRole("dialog", { name: "Nowe paski" });
    await user.selectOptions(within(form).getByLabelText("Dane"), "disks");
    await user.click(within(form).getByRole("button", { name: "Zapisz" }));
    expect(within(form).getByText("Wybierz urządzenie.")).toBeInTheDocument();
    expect(within(form).getByRole("option", { name: "NAS" })).toBeInTheDocument();
    expect(within(form).queryByRole("option", { name: "UCG Ultra" })).not.toBeInTheDocument(); // tylko serwery
    await user.selectOptions(within(form).getByLabelText("Urządzenie"), "5");
    expect(await within(form).findByRole("list", { name: "Dyski serwera: Zajętość" })).toBeInTheDocument(); // podgląd
    await user.clear(within(form).getByLabelText("Próg 2"));
    await user.type(within(form).getByLabelText("Próg 2"), "85");
    await user.click(within(form).getByRole("button", { name: "Zapisz" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Nowe paski" })).not.toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Zapisz" }));
    await waitFor(() => expect(state.layout).not.toBeNull());
    const w = (state.layout as DashboardLayout).widgets[0];
    expect(w.type === "bargauge" && w.config).toMatchObject({
      collection: { kind: "disks", device_id: 5 },
      key: "used_percent",
      thresholds: [
        { value: 70, color: 4 },
        { value: 85, color: 5 },
      ],
    });
  });

  it("tabela: kolumny i sortowanie", async () => {
    const { state } = mockApi({ layout: layoutWith(), collections: { devices: DEVICES } });
    renderApp();
    const user = await addWidget(/Tabela/);
    const form = await screen.findByRole("dialog", { name: "Nowa tabela" });
    await user.click(within(form).getByLabelText("RAM"));
    await user.click(within(form).getByLabelText("Czas pracy"));
    await user.selectOptions(within(form).getByLabelText("Sortuj według"), "cpu_percent");
    await user.click(within(form).getByLabelText("Malejąco"));
    await user.click(within(form).getByRole("button", { name: "Zapisz" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Nowa tabela" })).not.toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Zapisz" }));
    await waitFor(() => expect(state.layout).not.toBeNull());
    const w = (state.layout as DashboardLayout).widgets[0];
    expect(w.type === "table" && [w.config.columns, w.config.sort_by, w.config.sort_desc]).toEqual([["up", "cpu_percent", "uptime_s"], "cpu_percent", true]);
  });

  it("oś stanów: urządzenia i port", async () => {
    const { state } = mockApi({ layout: layoutWith() });
    renderApp();
    const user = await addWidget(/Oś stanów/);
    const form = await screen.findByRole("dialog", { name: "Nowa oś stanów" });
    await user.click(within(form).getByLabelText("UCG Ultra"));
    await user.selectOptions(within(form).getByLabelText("Urządzenie"), "1");
    await user.selectOptions(await within(form).findByLabelText("Port"), "11");
    await user.click(within(form).getByRole("button", { name: "Dodaj port" }));
    expect(within(form).getByRole("button", { name: /^Usuń UCG Ultra: / })).toBeInTheDocument();
    await user.click(within(form).getByRole("button", { name: "Zapisz" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Nowa oś stanów" })).not.toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Zapisz" }));
    await waitFor(() => expect(state.layout).not.toBeNull());
    const w = (state.layout as DashboardLayout).widgets[0];
    expect(w.type === "state_timeline" && w.config.items).toEqual([
      { kind: "device", id: 1 },
      { kind: "interface", id: 11, device_id: 1 },
    ]);
  });
});
