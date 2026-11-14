import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { t } from "../i18n";
import { newWidget, type Widget } from "../lib/layout";
import { availabilityTone, formatAvailability, formatDuration, type WanHistory, type WanLink, type WanSla, type WanUsage } from "../lib/wan";
import { forecastBytes } from "../components/widgets/WanUsageWidget";
import { mockApi } from "../test/mockApi";
import { customWidgets } from "../test/addWidget";
import { renderApp } from "../test/renderApp";

const minutesAgo = (m: number) => new Date(Date.now() - m * 60_000).toISOString();

const FIBER: WanLink = {
  id: 1,
  name: "Światłowód",
  position: 1,
  device_id: 1,
  device_name: "UCG Ultra",
  interface_id: 8,
  interface_name: "eth4",
  interface_label: "WAN",
  speed_mbps: 1000,
  state: "down",
  state_since: minutesAgo(12),
  source: "traffic",
  in_bps: null,
  out_bps: null,
  sampled_at: minutesAgo(0),
};
const LTE: WanLink = {
  ...FIBER,
  id: 2,
  name: "LTE",
  position: 2,
  interface_id: 15,
  interface_name: "eth3",
  interface_label: "LTE",
  state: "active",
  in_bps: 42_300_000,
  out_bps: 6_500_000,
};

const SWITCH_AT = minutesAgo(12);
const HISTORY: WanHistory = {
  interval_s: 30,
  links: [FIBER, LTE],
  points: [
    { time: minutesAgo(20), values: { in_1: 30e6, out_1: 2e6, in_2: null, out_2: null } },
    { time: minutesAgo(10), values: { in_1: null, out_1: null, in_2: 40e6, out_2: 5e6 } },
  ],
  segments: [
    { link_id: 1, state: "active", start: minutesAgo(60), end: SWITCH_AT },
    { link_id: 1, state: "down", start: SWITCH_AT, end: minutesAgo(0) },
    { link_id: 2, state: "standby", start: minutesAgo(60), end: SWITCH_AT },
    { link_id: 2, state: "active", start: SWITCH_AT, end: minutesAgo(0) },
  ],
  switches: [{ time: SWITCH_AT, from_ids: [1], to_ids: [2] }],
};

const SLA: WanSla = {
  days: 7,
  start: minutesAgo(7 * 1440),
  end: minutesAgo(0),
  links: [
    {
      link: FIBER,
      availability: 99.5,
      up_s: 601_776,
      down_s: 3024,
      active_s: 601_000,
      unknown_s: 0,
      outages: 2,
      longest_outage_s: 2304,
      recent_outages: [
        { start: SWITCH_AT, end: minutesAgo(0), duration_s: 720, ongoing: true },
        { start: minutesAgo(3000), end: minutesAgo(2961.6), duration_s: 2304, ongoing: false },
      ],
    },
    { link: LTE, availability: 100, up_s: 604_800, down_s: 0, active_s: 720, unknown_s: 0, outages: 0, longest_outage_s: 0, recent_outages: [] },
  ],
};

const dashboard = (...widgets: Widget[]) => ({ version: 1 as const, widgets });

describe("formatowanie SLA", () => {
  it("dostępność nie zaokrągla się w górę do 100%", () => {
    expect(formatAvailability(100)).toBe("100%");
    expect(formatAvailability(99.999)).toBe("99,99%");
    expect(formatAvailability(99.5)).toBe("99,50%");
    expect(formatAvailability(null)).toBe("–");
    expect([availabilityTone(99.95), availabilityTone(99.5), availabilityTone(97), availabilityTone(null)]).toEqual(["ok", "warn", "danger", "none"]);
  });

  it("czas trwania przerw", () => {
    expect(formatDuration(45)).toBe("45 s");
    expect(formatDuration(720)).toBe("12 min");
    expect(formatDuration(3 * 3600 + 300)).toBe("3 h 5 min");
    expect(formatDuration(2 * 86400 + 4 * 3600)).toBe("2 d 4 h");
  });
});

describe("widget Aktywny WAN", () => {
  it("pokazuje, którym łączem idzie ruch, a które nie działa", async () => {
    mockApi({ wanStatus: { links: [FIBER, LTE], active_ids: [2] }, layout: dashboard(newWidget("wan_status", "ws")) });
    renderApp();
    expect(await screen.findByText("Teraz: LTE")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "W użyciu – ruch idzie tym łączem" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Nie działa" })).toBeInTheDocument();
    expect(screen.getByText("↓ 42,3 Mb/s")).toBeInTheDocument();
    expect(screen.getByText(/UCG Ultra · LTE/)).toBeInTheDocument();
  });

  it("zapasowe łącze bez ruchu jest nieaktywne, a brak działającego łącza to błąd", async () => {
    mockApi({
      wanStatus: { links: [{ ...FIBER, state: "down" }, { ...LTE, state: "standby" }], active_ids: [] },
      layout: dashboard(newWidget("wan_status", "ws")),
    });
    renderApp();
    expect(await screen.findByText("Żadne łącze WAN nie działa")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Nieaktywne – łącze zapasowe, gotowe" })).toBeInTheDocument();
  });

  it("bez łączy odsyła do ustawień", async () => {
    mockApi({ layout: dashboard(newWidget("wan_status", "ws")) });
    renderApp();
    expect(await screen.findByText("Brak skonfigurowanych łączy WAN.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Ustaw je w Ustawienia → Łącza WAN." })).toHaveAttribute("href", "/settings/wan");
  });

  it("filtruje łącza po routerze", async () => {
    mockApi({ wanStatus: { links: [FIBER, { ...LTE, device_id: 5 }], active_ids: [2] }, layout: dashboard({ ...newWidget("wan_status", "ws"), config: { device_id: 1 } } as Widget) });
    renderApp();
    expect(await screen.findByText("Żadne łącze WAN nie działa")).toBeInTheDocument();
    expect(screen.queryByText("LTE")).not.toBeInTheDocument();
  });
});

describe("widget Aktywne łącze WAN", () => {
  it("rysuje linię każdego łącza, pasy stanu i moment przełączenia", async () => {
    const { calls } = mockApi({ wanHistory: HISTORY, layout: dashboard(newWidget("wan_chart", "wc")) });
    renderApp();
    const chart = await screen.findByTestId("chart");
    expect(chart).toHaveTextContent("Światłowód, LTE");
    expect(chart).toHaveAttribute("data-points", "3"); // 2 punkty z API i luka między nimi (wspólny silnik od 0.36.0)
    expect(screen.getByText("Aktywne łącze WAN – pobieranie")).toBeInTheDocument();
    const band = screen.getByRole("list", { name: "Stan łącza LTE w czasie" });
    const items = within(band).getAllByRole("listitem");
    expect(items.map((i) => i.getAttribute("aria-label")?.split(":")[0])).toEqual(["Nieaktywne – łącze zapasowe, gotowe", "W użyciu – ruch idzie tym łączem"]);
    expect(screen.getByText(/ruch przeszedł z Światłowód na LTE/)).toBeInTheDocument();
    expect(calls.some((c) => c.path === "/api/wan/history?minutes=60")).toBe(true);
    // Wspólny silnik wykresów: legenda z ukrywaniem serii i menu z eksportem
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "LTE" }));
    expect(chart).toHaveTextContent(/^Światłowód$/);
    await user.click(screen.getByRole("button", { name: "Więcej działań" }));
    expect(screen.getAllByRole("menuitem").map((i) => i.textContent)).toEqual(["Pełny ekran", "Pobierz dane (CSV)", "Pobierz obraz (PNG)"]);
  });
});

describe("widget SLA łączy WAN", () => {
  it("pokazuje dostępność, przerwy i trwającą awarię; okres można zmienić", async () => {
    const { calls } = mockApi({ wanSla: SLA, layout: dashboard(newWidget("wan_sla", "sla")) });
    renderApp();
    expect(await screen.findByLabelText("Dostępność Światłowód")).toHaveTextContent("99,50%");
    expect(screen.getByLabelText("Dostępność LTE")).toHaveTextContent("100%");
    expect(screen.getByText(/Przerwa trwa od/)).toBeInTheDocument();
    expect(screen.getByText("38 min")).toBeInTheDocument(); // najdłuższa przerwa
    expect(calls.some((c) => c.path === "/api/wan/sla?days=7")).toBe(true);

    const user = userEvent.setup();
    // „30 dni” jest też w wyborze zakresu wykresów – szukamy w przełączniku okresu SLA
    const period = screen.getByRole("group", { name: t("wan.sla.period") });
    await user.click(within(period).getByRole("button", { name: "30 dni" }));
    await waitFor(() => expect(calls.some((c) => c.path === "/api/wan/sla?days=30")).toBe(true));
    expect(within(period).getByRole("button", { name: "30 dni" })).toHaveAttribute("aria-pressed", "true");
  });
});

const USAGE: WanUsage = {
  timezone: "Europe/Warsaw",
  reset_day: 15,
  today: "2026-11-14",
  period_start: "2026-10-15",
  next_period_start: "2026-11-15",
  total_today: { rx_bytes: 4.2e9, tx_bytes: 0.8e9 },
  total_period: { rx_bytes: 85e9, tx_bytes: 5e9 },
  ports: [
    { interface_id: 8, device_id: 1, device_name: "UCG Ultra", name: "Światłowód", today: { rx_bytes: 4.2e9, tx_bytes: 0.8e9 }, period: { rx_bytes: 80e9, tx_bytes: 4e9 } },
    { interface_id: 15, device_id: 1, device_name: "UCG Ultra", name: "LTE", today: { rx_bytes: 0, tx_bytes: 0 }, period: { rx_bytes: 5e9, tx_bytes: 1e9 } },
  ],
  days: [
    { day: "2026-11-13", rx_bytes: 3e9, tx_bytes: 1e9 },
    { day: "2026-11-14", rx_bytes: 4.2e9, tx_bytes: 0.8e9 },
  ],
};

describe("widget zużycia transferu", () => {
  it("pokazuje licznik dzienny i okresu, pakiet i łącza", async () => {
    const widget = { ...newWidget("wan_usage", "u"), config: { device_id: null, reset_day: 15, limit_gb: 100 } } as Widget;
    const { calls } = mockApi({ wanUsage: USAGE, layout: dashboard(widget) });
    renderApp();
    expect(await screen.findByLabelText("Zużycie – Dziś")).toHaveTextContent("5 GB");
    expect(screen.getByLabelText(/Zużycie – Okres od/)).toHaveTextContent("90 GB");
    expect(screen.getByText("90 GB z 100 GB")).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "Wykorzystanie pakietu" })).toHaveAttribute("aria-valuenow", "90");
    expect(screen.getByText("LTE")).toBeInTheDocument();
    expect(calls.some((c) => c.path === "/api/wan/usage?reset_day=15")).toBe(true);
  });

  it("prognoza na koniec okresu z dotychczasowego tempa", () => {
    const day16 = new Date(2026, 9, 31).getTime(); // 16 z 31 dni okresu 15.10–15.11: 90 GB × 31/16
    expect(forecastBytes(USAGE, day16)! / 1e9).toBeCloseTo(174, 0);
    expect(forecastBytes(USAGE, new Date(2026, 9, 15, 1).getTime())).toBeNull(); // pierwszy dzień – za wcześnie
  });

  it("formularz: dzień startu okresu i pakiet", async () => {
    const { state } = mockApi({ layout: dashboard() });
    renderApp();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Edytuj pulpit" }));
    await user.click(screen.getByRole("button", { name: "Dodaj widget" }));
    const picker = await customWidgets(user);
    await user.click(within(picker).getByRole("button", { name: /Zużycie transferu/ }));
    const form = await screen.findByRole("dialog", { name: "Zużycie transferu" });
    await user.selectOptions(within(form).getByLabelText("Początek okresu"), "15");
    await user.type(within(form).getByLabelText("Pakiet na okres (GB)"), "0");
    expect(within(form).getByRole("button", { name: "Dodaj widget" })).toBeDisabled();
    await user.clear(within(form).getByLabelText("Pakiet na okres (GB)"));
    await user.type(within(form).getByLabelText("Pakiet na okres (GB)"), "50,5");
    await user.click(within(form).getByRole("button", { name: "Dodaj widget" }));
    await user.click(screen.getByRole("button", { name: "Zapisz" }));
    await waitFor(() => expect(state.layout?.widgets.map((w) => [w.type, w.config])).toEqual([["wan_usage", { device_id: null, reset_day: 15, limit_gb: 50.5 }]]));
  });
});

describe("pulpit i ustawienia łączy WAN", () => {
  it("widget WAN można dodać z listy widgetów", async () => {
    const { state } = mockApi({ layout: dashboard() });
    renderApp();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Edytuj pulpit" }));
    await user.click(screen.getByRole("button", { name: "Dodaj widget" }));
    const picker = await customWidgets(user);
    await user.click(within(picker).getByRole("button", { name: /SLA łączy WAN/ }));
    const form = await screen.findByRole("dialog", { name: "SLA łączy WAN" });
    await user.selectOptions(within(form).getByLabelText("Okres"), "30");
    await user.click(within(form).getByRole("button", { name: "Dodaj widget" }));
    await user.click(screen.getByRole("button", { name: "Zapisz" }));
    await waitFor(() => expect(state.layout?.widgets.map((w) => [w.type, w.config])).toEqual([["wan_sla", { device_id: null, days: 30 }]]));
  });

  it("Ustawienia → Łącza WAN: dodanie łącza zapasowego", async () => {
    const { state, calls } = mockApi({ wanLinks: [{ ...FIBER, name: "WAN 1", interface_id: 11 }] });
    renderApp("/settings/wan");
    const user = userEvent.setup();
    expect(await screen.findByDisplayValue("WAN 1")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Dodaj łącze" }));
    await user.click(screen.getByRole("button", { name: "Zapisz" }));
    expect(await screen.findByText("Wybierz port dla każdego łącza.")).toBeInTheDocument();

    const ports = screen.getAllByLabelText("Port");
    await waitFor(() => expect(within(ports[1]).getAllByRole("option")).toHaveLength(3));
    await user.selectOptions(ports[1], "12");
    const names = screen.getAllByLabelText("Nazwa łącza");
    await user.clear(names[1]);
    await user.type(names[1], "LTE");
    await user.click(screen.getByRole("button", { name: "Przesuń WAN 2 wyżej" }));
    await user.click(screen.getByRole("button", { name: "Zapisz" }));
    expect(await screen.findByText(/Zapisano/)).toBeInTheDocument();
    const put = calls.find((c) => c.method === "PUT" && c.path === "/api/wan/links");
    expect(put?.body).toEqual({ links: [{ interface_id: 12, name: "LTE" }, { interface_id: 11, name: "WAN 1" }] });
    expect(state.wanLinks.map((l) => [l.name, l.position])).toEqual([["LTE", 1], ["WAN 1", 2]]);
  });

  it("podpowiedź: łącze WAN zgłoszone przez kontroler, którego nie ma na liście", async () => {
    const hint = { device_id: 1, device_name: "UCG Ultra", interface_id: 12, interface_name: "eth3", interface_label: "LAN 4", slot: 2, up: true, active: false };
    const { calls } = mockApi({ wanLinks: [{ ...FIBER, name: "WAN 1", interface_id: 11 }], wanSuggestions: [hint] });
    renderApp("/settings/wan");
    const user = userEvent.setup();
    expect(await screen.findByText(/Kontroler UniFi zgłasza WAN 2 na porcie LAN 4 \(eth3\) routera UCG Ultra/)).toBeInTheDocument();
    expect(screen.getByText("Łącze działa i czeka jako zapasowe.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Dodaj LAN 4 (eth3)" }));
    expect(screen.queryByText(/Kontroler UniFi zgłasza/)).not.toBeInTheDocument();
    expect(screen.getByDisplayValue("WAN 2")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Zapisz" }));
    expect(await screen.findByText(/Zapisano/)).toBeInTheDocument();
    const put = calls.find((c) => c.method === "PUT" && c.path === "/api/wan/links");
    expect(put?.body).toEqual({ links: [{ interface_id: 11, name: "WAN 1" }, { interface_id: 12, name: "WAN 2" }] });
  });

  it("ten sam port dwa razy to błąd", async () => {
    mockApi({ wanLinks: [{ ...FIBER, name: "WAN 1", interface_id: 11 }] });
    renderApp("/settings/wan");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Dodaj łącze" }));
    const ports = screen.getAllByLabelText("Port");
    await waitFor(() => expect(within(ports[1]).getAllByRole("option")).toHaveLength(3));
    await user.selectOptions(ports[1], "11");
    await user.click(screen.getByRole("button", { name: "Zapisz" }));
    expect(await screen.findByText("Ten sam port nie może być dwoma łączami.")).toBeInTheDocument();
  });
});
