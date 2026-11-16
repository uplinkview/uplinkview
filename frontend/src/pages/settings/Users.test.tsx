import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { auditLabel, type AuditEntry } from "../../lib/audit";
import { USER, mockApi } from "../../test/mockApi";
import { renderApp } from "../../test/renderApp";

const entry = (over: Partial<AuditEntry>): AuditEntry => ({
  id: 1,
  time: "2026-11-06T10:00:00Z",
  user_id: 1,
  username: "admin",
  ip: "192.168.1.20",
  action: "login",
  target: null,
  status: null,
  detail: null,
  ...over,
});

describe("role i konta", () => {
  it("dodaje konto z rolą podglądu", async () => {
    const user = userEvent.setup();
    const { calls } = mockApi();
    renderApp("/settings/users");
    await screen.findByRole("heading", { name: "Konta" });
    expect(await screen.findByText("(Ty)")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Dodaj konto" }));
    const dialog = await screen.findByRole("dialog", { name: "Nowe konto" });
    await user.type(within(dialog).getByLabelText("Login"), "jan");
    await user.type(within(dialog).getByLabelText("Hasło"), "krotkie");
    await user.click(within(dialog).getByRole("button", { name: "Zapisz" }));
    expect(within(dialog).getByText("Hasło musi mieć co najmniej 8 znaków.")).toBeInTheDocument();

    await user.clear(within(dialog).getByLabelText("Hasło"));
    await user.type(within(dialog).getByLabelText("Hasło"), "haslo-jana-123");
    expect((within(dialog).getByLabelText("Rola") as HTMLSelectElement).value).toBe("viewer");
    await user.click(within(dialog).getByRole("button", { name: "Zapisz" }));

    const row = (await screen.findByText("jan")).closest("li") as HTMLElement;
    expect(within(row).getByText("Podgląd")).toBeInTheDocument();
    expect(calls.find((c) => c.method === "POST" && c.path === "/api/users")?.body).toEqual({ username: "jan", password: "haslo-jana-123", role: "viewer" });
  });

  it("nie da się usunąć własnego konta", async () => {
    mockApi();
    renderApp("/settings/users");
    expect(await screen.findByRole("button", { name: `Usuń ${USER.username}` })).toBeDisabled();
  });

  it("podgląd nie widzi ustawień administratora ani potwierdzania alertów", async () => {
    mockApi({ admin: false, role: "viewer" });
    renderApp("/settings/account");
    await screen.findByRole("heading", { name: "Konto" });
    expect(screen.getAllByText("Podgląd").length).toBeGreaterThan(0);
    expect(screen.queryByRole("link", { name: "Urządzenia" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Konta" })).toBeNull();
    expect(screen.getByRole("link", { name: "Dashboardy" })).toBeInTheDocument();
  });

  it("operator nie widzi kont ani ustawień administratora", async () => {
    mockApi({ admin: false, role: "operator" });
    renderApp("/settings/account");
    await screen.findByRole("heading", { name: "Konto" });
    expect(screen.getByRole("link", { name: "Dashboardy" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Konta" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Urządzenia" })).toBeNull();
  });
});

describe("dziennik zdarzeń", () => {
  it("opisuje wpisy po polsku i filtruje odrzucone", async () => {
    const user = userEvent.setup();
    mockApi({
      audit: [
        entry({ id: 3, action: "DELETE /api/devices/{device_id}", target: "/api/devices/4", status: 204 }),
        entry({ id: 2, username: "widz", action: "POST /api/devices", target: "/api/devices", status: 403 }),
        entry({ id: 1, action: "login_failed", detail: "nieznany login", username: "x" }),
      ],
    });
    renderApp("/settings/audit");
    await screen.findByRole("heading", { name: "Dziennik zdarzeń" });
    expect(await screen.findByText("Usunięcie: urządzenie")).toBeInTheDocument();
    expect(screen.getByText("Brak uprawnień (403)")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Odrzucone" }));
    expect(await screen.findByText("Nieudane logowanie")).toBeInTheDocument();
    expect(screen.queryByText("Usunięcie: urządzenie")).toBeNull();
  });

  it("auditLabel zna potwierdzenie alertu, testy i nieznane zasoby", () => {
    expect(auditLabel("POST /api/alerts/{alert_id}/ack")).toBe("Potwierdzenie alertu");
    expect(auditLabel("POST /api/devices/{device_id}/probe")).toBe("Test: urządzenie");
    expect(auditLabel("PATCH /api/users/{user_id}")).toBe("Zmiana: konto");
    expect(auditLabel("PUT /api/coś")).toBe("Zmiana: coś");
    expect(auditLabel("logout")).toBe("Wylogowanie");
  });
});
