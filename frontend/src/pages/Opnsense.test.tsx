import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { OpnsenseDeviceData } from "../lib/opnsense";
import { DEVICE, mockApi } from "../test/mockApi";
import { renderApp } from "../test/renderApp";

const OPN = { ...DEVICE, id: 5, name: "OPNsense", host: "192.168.1.135", driver: "auto", detected_driver: "opnsense", kind: "gateway" };

const DATA: OpnsenseDeviceData = {
  configured: true,
  status: "up",
  stale: false,
  version: "26.7.9_1",
  latest_version: "26.7.10",
  update_available: true,
  last_ok_at: new Date().toISOString(),
  last_error: null,
  dhcp: "dnsmasq",
  gateways: [
    { name: "WAN_DHCP", address: "192.168.1.1", monitor: "8.8.8.8", status: "none", up: true, delay_ms: 12.3, jitter_ms: 0.8, loss_percent: 0, interface: "em1", default: true },
    { name: "WAN_DHCP6", address: null, monitor: null, status: "none", up: null, delay_ms: null, jitter_ms: null, loss_percent: null, interface: null, default: false },
  ],
  interfaces: [
    { device: "em0", identifier: "lan", description: "LAN", status: "up", link_type: "static", addr4: "192.168.10.1/24", gateways: [], default_route: false },
    { device: "em1", identifier: "wan", description: "WAN", status: "up", link_type: "dhcp", addr4: "192.168.1.135/24", gateways: ["192.168.1.1"], default_route: true },
  ],
  services: [
    { name: "unbound", description: "Unbound", running: true },
    { name: "suricata", description: "Intrusion Detection", running: false },
  ],
  hosts: [
    { mac: "02:00:00:00:00:02", ip: "192.168.10.126", hostname: "host-1", interface: "LAN", manufacturer: "PCS Systemtechnik GmbH", source: "dhcp", expires: 1794699248 },
    { mac: "02:00:00:00:00:04", ip: "192.168.1.1", hostname: null, interface: "WAN", manufacturer: null, source: "arp", expires: null },
  ],
};

describe("Ustawienia → OPNsense", () => {
  it("dodaje klucz do urządzenia OPNsense: test połączenia, sekret nie wraca", async () => {
    const { state, calls } = mockApi({ devices: [DEVICE, OPN] });
    renderApp("/settings/opnsense");
    const user = userEvent.setup();
    expect(await screen.findByText("Nie dodano jeszcze klucza API OPNsense")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Dodaj klucz API" }));
    const form = await screen.findByRole("dialog", { name: "Nowy klucz API OPNsense" });
    // urządzenie rozpoznane jako OPNsense jest wybrane od razu
    await waitFor(() => expect(within(form).getByLabelText("Urządzenie OPNsense")).toHaveValue("5"));

    await user.type(within(form).getByLabelText("Klucz (key)"), "krotki");
    await user.click(within(form).getByRole("button", { name: "Zapisz" }));
    expect(await within(form).findAllByText(/co najmniej 8 znaków/)).toHaveLength(2);

    await user.type(within(form).getByLabelText("Klucz (key)"), "-klucz-1234");
    await user.type(within(form).getByLabelText("Sekret (secret)"), "sekret-5678");
    await user.click(within(form).getByRole("button", { name: /Testuj/ }));
    expect(await within(form).findByText(/OPNsense 26.7.9_1, bram: 2 \(z pomiarem: 1\)/)).toBeInTheDocument();
    await user.click(within(form).getByRole("button", { name: "Zapisz" }));
    await waitFor(() => expect(state.opnKeys).toHaveLength(1));
    const sent = calls.find((c) => c.method === "POST" && c.path === "/api/opnsense/apis")?.body as Record<string, unknown>;
    expect(sent).toMatchObject({ device_id: 5, port: 443, api_key: "krotki-klucz-1234", api_secret: "sekret-5678", verify_tls: false });
    expect(await screen.findByText(/klucz …1234/)).toBeInTheDocument();
  });

  it("wyłączony moduł: brak pozycji w Ustawieniach", async () => {
    mockApi({ modules: { proxmox: true, unifi: true, opnsense: false, agents: true, backups: true } });
    renderApp("/settings/modules");
    const nav = await screen.findByRole("navigation", { name: "Menu główne" });
    expect(await screen.findByRole("switch", { name: "OPNsense API" })).not.toBeChecked();
    expect(within(nav).queryByRole("link", { name: "OPNsense" })).not.toBeInTheDocument();
  });
});

describe("Strona urządzenia OPNsense", () => {
  it("pokazuje wersję z aktualizacją, bramy, interfejsy, usługi i urządzenia w sieci", async () => {
    mockApi({ devices: [OPN], opnDevice: DATA });
    renderApp("/devices/5");
    expect(await screen.findByText("OPNsense (API)")).toBeInTheDocument();
    expect(screen.getByText("aktualizacja 26.7.10")).toBeInTheDocument();
    const gateways = screen.getByRole("heading", { name: "Bramy" }).closest("div")!;
    expect(within(gateways).getByText("WAN_DHCP")).toBeInTheDocument();
    expect(within(gateways).getByText("aktywna")).toBeInTheDocument();
    expect(within(gateways).getByText("bez monitorowania")).toBeInTheDocument();
    expect(within(gateways).getByText(/12,3 ms/)).toBeInTheDocument();
    expect(screen.getByText("Usługi (1 z 2 działa)")).toBeInTheDocument();
    expect(screen.getByText(/Intrusion Detection – zatrzymana/)).toBeInTheDocument();
    expect(screen.getByText("host-1")).toBeInTheDocument();
    expect(screen.getByText(/z DHCP \(dnsmasq\): 1/)).toBeInTheDocument();
  });

  it("urządzenie bez klucza nie ma sekcji OPNsense", async () => {
    mockApi({ devices: [OPN] });
    renderApp("/devices/5");
    expect(await screen.findByRole("heading", { name: "OPNsense" })).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText("OPNsense (API)")).not.toBeInTheDocument());
  });
});
