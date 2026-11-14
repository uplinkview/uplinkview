import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { mockApi } from "../test/mockApi";
import { renderApp } from "../test/renderApp";

describe("kreator pierwszej konfiguracji", () => {
  it("z pustego pulpitu: urządzenie z testem SNMP, integracje i podsumowanie", async () => {
    const { state, calls } = mockApi({ devices: [], modules: { proxmox: false, unifi: false, opnsense: false, agents: false, backups: true } });
    renderApp();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("link", { name: "Uruchom kreator konfiguracji" }));
    expect(await screen.findByRole("heading", { name: "Pierwsza konfiguracja" })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/setup");

    await user.click(screen.getByRole("button", { name: "Zaczynamy" }));
    expect(screen.getByText("Jeszcze nic – dodaj pierwsze urządzenie obok.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Wykryj urządzenia w sieci" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Dodaj urządzenie ręcznie" }));
    await user.type(screen.getByLabelText("Nazwa"), "Router");
    await user.type(screen.getByLabelText("Adres IP lub nazwa hosta"), "192.168.1.1");
    await user.click(screen.getByRole("button", { name: "Testuj połączenie" }));
    expect(await screen.findByText(/Ubiquiti UniFi Switch/)).toBeInTheDocument(); // wynik testu SNMP
    await user.click(screen.getByRole("button", { name: "Zapisz" }));

    expect(await screen.findByText(/Dodano: Router/)).toBeInTheDocument();
    expect(state.devices.map((d) => d.host)).toEqual(["192.168.1.1"]);
    expect(await screen.findByText("Dodane urządzenia (1)")).toBeInTheDocument();
    // Po zapisie formularz chowa się, można dodać następne
    expect(screen.getByRole("button", { name: "Dodaj kolejne urządzenie" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Dalej" }));
    await user.click(await screen.findByRole("switch", { name: "UniFi" }));
    expect(calls.some((c) => c.method === "PUT" && c.path === "/api/modules")).toBe(true);
    await user.click(screen.getByRole("button", { name: "Dalej" }));

    expect(await screen.findByText("Gotowe!")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Dodaj kontroler UniFi/ })).toHaveAttribute("href", "/settings/controllers");
    expect(screen.queryByRole("link", { name: /Proxmox/ })).not.toBeInTheDocument(); // moduł wyłączony
    await user.click(screen.getByRole("button", { name: "Przejdź do pulpitu" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Dashboard" })).toBeInTheDocument();
  });

  it("kroki można pominąć i wrócić", async () => {
    mockApi({ devices: [] });
    renderApp("/setup");
    const user = userEvent.setup();
    const steps = await screen.findByRole("list", { name: "Kroki kreatora" });
    expect(within(steps).getByText("Powitanie").closest("li")).toHaveAttribute("aria-current", "step");
    await user.click(screen.getByRole("button", { name: "Zaczynamy" }));
    await user.click(screen.getByRole("button", { name: "Pomiń, dodam później" }));
    expect(within(steps).getByText("Integracje").closest("li")).toHaveAttribute("aria-current", "step");
    await user.click(screen.getByRole("button", { name: "Wstecz" }));
    expect(screen.getByLabelText("Podsieć")).toBeInTheDocument();
  });
});
