import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DEVICE, TLS, mockApi } from "../../test/mockApi";
import { renderApp } from "../../test/renderApp";

describe("Ustawienia → System", () => {
  it("pokazuje stan usług z opisami", async () => {
    mockApi();
    renderApp("/settings/system");
    await screen.findByText("API i panel"); // lista usług doczytana
    const list = screen.getByRole("region", { name: "Usługi" });
    expect(within(list).getByText("API i panel")).toBeInTheDocument();
    expect(within(list).getByText("wersja 0.8.2")).toBeInTheDocument();
    expect(within(list).getByText("PostgreSQL z TimescaleDB")).toBeInTheDocument();
    expect(within(list).getByText("Kontrolery UniFi")).toBeInTheDocument();
    expect(within(list).getByText("nieskonfigurowane")).toBeInTheDocument(); // UniFi bez kontrolera
  });

  it("ostrzega przed fabrycznym community SNMP i prowadzi do urządzeń", async () => {
    mockApi({
      devices: [
        { ...DEVICE, default_community: true },
        { ...DEVICE, id: 2, name: "USW Lite 8 PoE", host: "192.168.1.2", default_community: true },
        { ...DEVICE, id: 3, name: "Stary AP", host: "192.168.1.9", default_community: true, enabled: false }, // wyłączony – pomijamy
        { ...DEVICE, id: 4, name: "U6+", host: "192.168.1.3", default_community: false },
      ],
    });
    renderApp("/settings/system");
    const note = (await screen.findByText("Fabryczne community SNMP: 2")).closest("[role=status]") as HTMLElement;
    expect(within(note).getByText("UCG Ultra, USW Lite 8 PoE")).toBeInTheDocument();
    expect(within(note).getByRole("link", { name: "Przejdź do urządzeń" })).toHaveAttribute("href", "/settings/devices");
  });

  it("bez fabrycznego community nie ma ostrzeżenia", async () => {
    mockApi();
    renderApp("/settings/system");
    await screen.findByText("API i panel");
    expect(screen.queryByText(/Fabryczne community SNMP/)).not.toBeInTheDocument();
  });

  it("nazywa usługę, która nie działa, i podaje komunikat", async () => {
    mockApi({
      services: [
        { id: "api", state: "ok", detail: "0.8.2" },
        { id: "database", state: "ok", detail: "postgres" },
        { id: "collector", state: "down", detail: "stale" },
        { id: "unifi", state: "down", detail: "Kontroler odrzucił klucz API" },
        { id: "updater", state: "down", detail: "unreachable" },
      ],
    });
    renderApp("/settings/system");
    await screen.findByText("API i panel"); // lista usług doczytana
    const list = screen.getByRole("region", { name: "Usługi" });
    expect(within(list).getAllByText("nie działa")).toHaveLength(3);
    expect(within(list).getByText(/dawno nie zapisywał danych/)).toBeInTheDocument();
    expect(within(list).getByText("Kontroler odrzucił klucz API")).toBeInTheDocument();
    expect(within(list).getByText("brak połączenia")).toBeInTheDocument();
  });

  it("pokazuje bieżący stan serwera i wykresy", async () => {
    mockApi({
      system: {
        sampled_at: "2026-10-25T10:00:00Z",
        cpu_percent: 12,
        load1: 0.1,
        load5: 0.1,
        load15: 0.1,
        mem_used_percent: 40,
        mem_total_bytes: 8_000_000_000,
        swap_used_percent: null,
        disk_used_percent: 50,
        disk_free_bytes: 100_000_000_000,
        disk_total_bytes: 200_000_000_000,
        uptime_s: 3600,
        temp_c: null,
        db_size_bytes: 1_000_000,
        poll_interval_s: 30,
      },
    });
    renderApp("/settings/system");
    expect(await screen.findByRole("meter", { name: "CPU" })).toHaveAttribute("aria-valuenow", "12");
    await waitFor(() => expect(screen.getAllByTestId("chart")).toHaveLength(4));
    expect(screen.getAllByTestId("chart")[0]).toHaveAccessibleName(/Zajętość: CPU, RAM, dysk/);
  });

  it("pokazuje błąd, gdy nie da się pobrać usług", async () => {
    mockApi({ overrides: { "GET /api/system/services": { status: 500, body: { detail: "awaria" } } } });
    renderApp("/settings/system");
    expect(await screen.findByText("Nie udało się pobrać stanu usług.")).toBeInTheDocument();
  });

  it("pokazuje, które źródła danych potwierdzono na prawdziwym sprzęcie", async () => {
    mockApi();
    renderApp("/settings/system");
    const list = await screen.findByRole("list", { name: "Potwierdzenie danych" });
    const row = (await within(list).findByText("TP-Link Omada przez SNMP")).closest("li") as HTMLElement;
    expect(within(row).getByText("dane testowe")).toBeInTheDocument();
    expect(within(row).getByText(/czeka na prawdziwy sprzęt/)).toBeInTheDocument();
    expect(within(within(list).getByText("MikroTik przez SNMP").closest("li") as HTMLElement).getByText("częściowo")).toBeInTheDocument();
    expect(within(within(list).getByText("SNMP: porty, ruch, błędy").closest("li") as HTMLElement).getByText("potwierdzone")).toBeInTheDocument();
  });

  it("jest w menu Ustawień", async () => {
    mockApi();
    renderApp("/settings/system");
    expect((await screen.findAllByRole("link", { name: "System" })).length).toBeGreaterThan(0);
  });
});

describe("Ustawienia → System → HTTPS", () => {
  it("pokazuje certyfikat, link do HTTPS i pobranie CA", async () => {
    mockApi();
    renderApp("/settings/system");
    const https = await screen.findByRole("region", { name: "HTTPS" });
    expect(await within(https).findByText("Połączenie bez szyfrowania (HTTP)")).toBeInTheDocument();
    expect(within(https).getByRole("link", { name: "Otwórz przez HTTPS (port 8443)" })).toHaveAttribute("href", "https://localhost:8443/settings/system");
    expect(within(https).getByRole("link", { name: "Pobierz certyfikat CA" })).toHaveAttribute("href", "/api/system/tls/ca.pem");
    expect(within(https).getByText("192.168.1.34")).toBeInTheDocument();
  });

  it("adres spoza certyfikatu: administrator dopisuje go jednym kliknięciem", async () => {
    const user = userEvent.setup();
    const { calls } = mockApi({ tls: { ...TLS, host: "netpulse.lan", host_covered: false } });
    renderApp("/settings/system");
    const https = await screen.findByRole("region", { name: "HTTPS" });
    expect(await within(https).findByText(/Adresu netpulse.lan nie ma w certyfikacie/)).toBeInTheDocument();
    await user.click(within(https).getByRole("button", { name: "Dodaj ten adres" }));
    await waitFor(() => expect(calls.find((c) => c.method === "PUT" && c.path === "/api/system/tls/names")?.body).toEqual({ names: ["netpulse.lan"] }));
    expect(await within(https).findByText("Nowy certyfikat powstaje – zwykle w ciągu 30 sekund.")).toBeInTheDocument();
    expect(within(https).getByRole("button", { name: "Usuń adres netpulse.lan" })).toBeInTheDocument();
  });

  it("podgląd nie zmienia adresów", async () => {
    mockApi({ admin: false, role: "viewer", tls: { ...TLS, host: "netpulse.lan", host_covered: false } });
    renderApp("/settings/system");
    const https = await screen.findByRole("region", { name: "HTTPS" });
    await within(https).findByText(/Adresu netpulse.lan nie ma w certyfikacie/);
    expect(within(https).queryByRole("button", { name: "Dodaj ten adres" })).toBeNull();
    expect(within(https).queryByText("Dodatkowe adresy w certyfikacie")).toBeNull();
  });

  it("bez kontenera proxy podpowiada aktualizację", async () => {
    mockApi({ tls: { ...TLS, available: false } });
    renderApp("/settings/system");
    expect(await screen.findByText(/HTTPS nie jest jeszcze włączone/)).toBeInTheDocument();
  });
});
