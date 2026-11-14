import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { mockApi } from "../../test/mockApi";
import { renderApp } from "../../test/renderApp";

const ALL_OFF = { proxmox: false, unifi: false, opnsense: false, agents: false, backups: false };

describe("Ustawienia → Moduły", () => {
  it("wyłączenie modułu chowa jego pozycje w menu, a włączenie przywraca", async () => {
    const { state } = mockApi({ modules: { proxmox: true, unifi: true, opnsense: true, agents: true, backups: true } });
    renderApp("/settings/modules");
    const user = userEvent.setup();
    const nav = await screen.findByRole("navigation", { name: "Menu główne" });
    // Proxmox jest w menu głównym i w podstronach Ustawień
    expect(await within(nav).findAllByRole("link", { name: "Proxmox" })).toHaveLength(2);
    expect(await screen.findByText("włączone: 5 z 5")).toBeInTheDocument(); // strona ładuje się osobnym plikiem

    await user.click(screen.getByRole("switch", { name: "Proxmox VE" }));
    await waitFor(() => expect(state.modules.proxmox).toBe(false));
    await waitFor(() => expect(within(nav).queryAllByRole("link", { name: "Proxmox" })).toHaveLength(0));
    expect(within(nav).getByRole("link", { name: "Klienci" })).toBeInTheDocument();
    expect(screen.getByText("włączone: 4 z 5")).toBeInTheDocument();

    await user.click(screen.getByRole("switch", { name: "Proxmox VE" }));
    expect(await within(nav).findAllByRole("link", { name: "Proxmox" })).toHaveLength(2);
  });

  it("wyłączone moduły: brak pozycji w menu, adres modułu przekierowuje na pulpit", async () => {
    mockApi({ modules: ALL_OFF });
    renderApp("/proxmox");
    expect(await screen.findByRole("button", { name: "Edytuj pulpit" })).toBeInTheDocument();
    const nav = screen.getByRole("navigation", { name: "Menu główne" });
    for (const name of ["Proxmox", "Klienci", "Topologia"]) {
      expect(within(nav).queryByRole("link", { name })).not.toBeInTheDocument();
    }
  });

  it("edytor wykresu i reguły alertów bez pozycji wyłączonych modułów", async () => {
    mockApi({ modules: ALL_OFF });
    renderApp("/settings/alert-rules");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Dodaj regułę" }));
    const form = await screen.findByRole("dialog", { name: "Nowa reguła" });
    const kinds = within(within(form).getByLabelText("Rodzaj reguły")).getAllByRole("option").map((o) => o.getAttribute("value"));
    expect(kinds).toEqual(["device_offline", "port_down", "metric", "check_down", "default_community", "wan_switch", "device_restart"]); // sprawdzenia dostępności – bez modułu
    const metrics = within(within(form).getByLabelText("Metryka")).getAllByRole("option").map((o) => o.getAttribute("value"));
    expect(metrics).not.toContain("smart_reallocated");
    expect(metrics).toContain("temp_c"); // temperaturę mają też czujniki MikroTika (SNMP), bez modułu agentów
  });

  it("konto bez uprawnień administratora widzi stan, ale nie przełącza", async () => {
    mockApi({ admin: false });
    renderApp("/settings/modules");
    expect(await screen.findByRole("switch", { name: "UniFi" })).toBeDisabled();
    expect(screen.getByText("Moduły może włączać i wyłączać tylko administrator.")).toBeInTheDocument();
  });
});
