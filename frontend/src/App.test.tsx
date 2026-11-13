import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { mockApi } from "./test/mockApi";
import { renderApp } from "./test/renderApp";

describe("kreator pierwszego konta", () => {
  it("pokazuje kreator, gdy nie ma jeszcze kont", async () => {
    mockApi({ setupRequired: true, authenticated: false });
    renderApp();
    expect(await screen.findByRole("heading", { name: "Witaj w UplinkView" })).toBeInTheDocument();
    expect(screen.getByLabelText("Powtórz hasło")).toBeInTheDocument();
  });

  it("linkuje do kodu źródłowego (AGPL-3.0)", async () => {
    mockApi({ setupRequired: true, authenticated: false });
    renderApp();
    const link = await screen.findByRole("link", { name: "AGPL-3.0 · Kod źródłowy" });
    expect(link).toHaveAttribute("href", "https://github.com/uplinkview/uplinkview");
  });

  it("nie wysyła formularza, gdy hasła się różnią albo są za krótkie", async () => {
    const user = userEvent.setup();
    const { calls } = mockApi({ setupRequired: true, authenticated: false });
    renderApp();
    await user.type(await screen.findByLabelText("Login"), "admin");
    await user.type(screen.getByLabelText("Hasło"), "krotkie");
    await user.type(screen.getByLabelText("Powtórz hasło"), "krotkie");
    await user.click(screen.getByRole("button", { name: "Utwórz konto" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("co najmniej 10 znaków");

    await user.clear(screen.getByLabelText("Hasło"));
    await user.type(screen.getByLabelText("Hasło"), "dlugie-haslo-1");
    await user.click(screen.getByRole("button", { name: "Utwórz konto" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Hasła się różnią");
    expect(calls.some((c) => c.path === "/api/auth/setup")).toBe(false);
  });

  it("zakłada konto i od razu otwiera kreator pierwszej konfiguracji", async () => {
    const user = userEvent.setup();
    const { calls } = mockApi({ setupRequired: true, authenticated: false });
    renderApp();
    await user.type(await screen.findByLabelText("Login"), "admin");
    await user.type(screen.getByLabelText("Hasło"), "dlugie-haslo-1");
    await user.type(screen.getByLabelText("Powtórz hasło"), "dlugie-haslo-1");
    await user.click(screen.getByRole("button", { name: "Utwórz konto" }));

    expect(await screen.findByRole("heading", { name: "Pierwsza konfiguracja" })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/setup");
    const setup = calls.find((c) => c.path === "/api/auth/setup");
    expect(setup?.body).toEqual({ username: "admin", password: "dlugie-haslo-1" });
  });
});

describe("logowanie", () => {
  it("pokazuje komunikat serwera przy błędnym haśle", async () => {
    const user = userEvent.setup();
    mockApi({
      authenticated: false,
      overrides: { "POST /api/auth/login": { status: 401, body: { detail: "Nieprawidłowy login lub hasło" } } },
    });
    renderApp();
    await user.type(await screen.findByLabelText("Login"), "admin");
    await user.type(screen.getByLabelText("Hasło"), "zle-haslo");
    await user.click(screen.getByRole("button", { name: "Zaloguj" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Nieprawidłowy login lub hasło");
  });

  it("pokazuje komunikat o zbyt wielu próbach (429)", async () => {
    const user = userEvent.setup();
    mockApi({
      authenticated: false,
      overrides: { "POST /api/auth/login": { status: 429, body: { detail: "Za dużo nieudanych prób. Spróbuj za 15 min." } } },
    });
    renderApp();
    await user.type(await screen.findByLabelText("Login"), "admin");
    await user.type(screen.getByLabelText("Hasło"), "cokolwiek");
    await user.click(screen.getByRole("button", { name: "Zaloguj" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Za dużo nieudanych prób");
  });

  it("po poprawnym logowaniu wchodzi do panelu", async () => {
    const user = userEvent.setup();
    mockApi({ authenticated: false });
    renderApp();
    await user.type(await screen.findByLabelText("Login"), "admin");
    await user.type(screen.getByLabelText("Hasło"), "dlugie-haslo-1");
    await user.click(screen.getByRole("button", { name: "Zaloguj" }));
    expect(await screen.findByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
  });
});

describe("panel po zalogowaniu", () => {
  it("pokazuje użytkownika w pasku górnym i menu z Dashboard i Ustawieniami", async () => {
    mockApi();
    renderApp();
    const nav = await screen.findByRole("navigation", { name: "Menu główne" });
    expect(within(nav).getByRole("link", { name: "Dashboard" })).toBeInTheDocument();
    expect(within(nav).getByRole("link", { name: "Ustawienia" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Menu konta" })).toHaveTextContent("admin");
  });

  it("dzieli menu na grupy: Monitoring, Zdarzenia, Integracje, System", async () => {
    mockApi();
    renderApp();
    const nav = await screen.findByRole("navigation", { name: "Menu główne" });
    expect(within(nav).getByText("Monitoring")).toBeInTheDocument();
    expect(within(nav).getByText("Zdarzenia")).toBeInTheDocument();
    expect(within(nav).getByText("System")).toBeInTheDocument();
    expect(within(nav).getByRole("link", { name: /^Alerty/ })).toBeInTheDocument();
    // Grupy według przeznaczenia, nie źródła danych: Klienci (z UniFi) to monitoring, Proxmox – integracja
    const linksIn = (group: string) =>
      within(within(nav).getByText(group).parentElement as HTMLElement)
        .getAllByRole("link")
        .map((a) => a.textContent);
    expect(linksIn("Monitoring")).toEqual(["Dashboard", "Klienci", "Mapa sieci"]);
    expect(linksIn("Integracje")).toEqual(["Proxmox"]);
  });

  it("pokazuje karty urządzeń i podsumowanie", async () => {
    mockApi();
    renderApp();
    expect(await screen.findByText("UCG Ultra")).toBeInTheDocument();
    expect(screen.getByText("działa")).toBeInTheDocument();
  });

  it("pokazuje, jak dodać pierwsze urządzenie, gdy lista jest pusta", async () => {
    mockApi({ devices: [] });
    renderApp();
    expect(await screen.findByText("Nie dodano jeszcze urządzeń")).toBeInTheDocument();
  });

  it("menu konta ma ustawienia konta i wylogowanie", async () => {
    const user = userEvent.setup();
    const { calls } = mockApi();
    renderApp();
    await user.click(await screen.findByRole("button", { name: "Menu konta" }));
    expect(screen.getByRole("menuitem", { name: "Ustawienia konta" })).toHaveAttribute("href", "/settings/account");

    await user.click(screen.getByRole("menuitem", { name: "Wyloguj" }));
    expect(await screen.findByRole("heading", { name: "Zaloguj się" })).toBeInTheDocument();
    expect(calls.some((c) => c.method === "POST" && c.path === "/api/auth/logout")).toBe(true);
  });

  it("Escape zamyka menu konta", async () => {
    const user = userEvent.setup();
    mockApi();
    renderApp();
    await user.click(await screen.findByRole("button", { name: "Menu konta" }));
    expect(screen.getByRole("menu")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("Ustawienia prowadzą do Konta i pokazują podstrony, w tym Aktualizację", async () => {
    const user = userEvent.setup();
    mockApi();
    renderApp();
    const nav = await screen.findByRole("navigation", { name: "Menu główne" });
    await user.click(within(nav).getByRole("link", { name: "Ustawienia" }));

    expect(await screen.findByRole("heading", { name: "Konto" })).toBeInTheDocument();
    for (const name of ["Konto", "Urządzenia", "Odświeżanie", "Aktualizacja"]) {
      expect(within(nav).getByRole("link", { name })).toBeInTheDocument();
    }
    await user.click(within(nav).getByRole("link", { name: "Aktualizacja" }));
    expect(await screen.findByRole("heading", { name: "Aktualizacja" })).toBeInTheDocument();
    expect(screen.getByText("0.2.0")).toBeInTheDocument();
  });

  it("nieznany adres wraca na Dashboard", async () => {
    mockApi();
    renderApp("/nie-ma-takiej-strony");
    expect(await screen.findByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
  });

  it("wraca do logowania, gdy sesja wygaśnie (401 z API)", async () => {
    const { state } = mockApi();
    const { client } = renderApp();
    expect(await screen.findByText("UCG Ultra")).toBeInTheDocument();
    state.authenticated = false; // serwer unieważnił sesję
    // kolejne odświeżenie listy kończy się 401 → status logowania → ekran logowania
    await client.invalidateQueries({ queryKey: ["devices"] });
    expect(await screen.findByRole("heading", { name: "Zaloguj się" })).toBeInTheDocument();
    expect(screen.queryByText("UCG Ultra")).not.toBeInTheDocument();
  });
});

describe("zmiana hasła", () => {
  it("wysyła obecne i nowe hasło i pokazuje potwierdzenie", async () => {
    const user = userEvent.setup();
    const { calls } = mockApi();
    renderApp("/settings/account");
    await user.type(await screen.findByLabelText("Obecne hasło"), "stare-haslo-1");
    await user.type(screen.getByLabelText("Nowe hasło"), "nowe-haslo-123");
    await user.type(screen.getByLabelText("Powtórz nowe hasło"), "nowe-haslo-123");
    await user.click(screen.getByRole("button", { name: "Zmień hasło" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Hasło zmienione");
    expect(calls.find((c) => c.path === "/api/auth/password")?.body).toEqual({
      current_password: "stare-haslo-1",
      new_password: "nowe-haslo-123",
    });
  });

  it("pokazuje błąd serwera przy złym obecnym haśle", async () => {
    const user = userEvent.setup();
    mockApi({
      overrides: { "POST /api/auth/password": { status: 403, body: { detail: "Obecne hasło jest nieprawidłowe" } } },
    });
    renderApp("/settings/account");
    await user.type(await screen.findByLabelText("Obecne hasło"), "zle");
    await user.type(screen.getByLabelText("Nowe hasło"), "nowe-haslo-123");
    await user.type(screen.getByLabelText("Powtórz nowe hasło"), "nowe-haslo-123");
    await user.click(screen.getByRole("button", { name: "Zmień hasło" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Obecne hasło jest nieprawidłowe");
  });
});

describe("brak połączenia", () => {
  it("pokazuje ekran błędu z ponowieniem", async () => {
    const user = userEvent.setup();
    const { fetchMock } = mockApi();
    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    renderApp();
    expect(await screen.findByRole("heading", { name: "Brak połączenia z serwerem" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Spróbuj ponownie" }));
    expect(await screen.findByRole("heading", { name: "Dashboard" })).toBeInTheDocument();
  });
});
