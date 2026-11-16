import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";
import { browserLanguage, getLanguage, setLanguage, t } from ".";
import { formatRange, relativeTime } from "../lib/format";
import { formatNumber } from "../lib/intl";
import { mockApi } from "../test/mockApi";
import { renderApp } from "../test/renderApp";
import { en } from "./en";
import { pl, type TextKey } from "./pl";

const POLISH = /[ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]/;
const placeholders = (s: string) => [...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();

afterEach(() => setLanguage("pl", { reload: false }));

describe("tłumaczenie angielskie (0.74.0)", () => {
  it("ma każdy klucz polskiego pliku, te same zmienne i żadnego polskiego znaku", () => {
    const keys = Object.keys(pl) as TextKey[];
    expect(Object.keys(en).sort()).toEqual([...keys].sort());
    for (const key of keys) {
      expect(en[key], key).toBeTruthy();
      expect(placeholders(en[key]), key).toEqual(placeholders(pl[key]));
      if (key !== "lang.pl") expect(en[key], key).not.toMatch(POLISH);
    }
  });

  it("język z przeglądarki, wybór zapamiętany i formaty liczb, dat i czasu", () => {
    setLanguage("en", { reload: false });
    expect(getLanguage()).toBe("en");
    expect(localStorage.getItem("netpulse.language")).toBe("en");
    expect(document.documentElement.lang).toBe("en");
    expect(t("dash.of", { total: 5 })).toBe("of 5");
    expect(formatNumber(1234.5)).toBe("1,234.5");
    expect(formatRange(1440)).toBe("24 h");
    expect(formatRange(10080)).toBe("7 days");
    expect(relativeTime(new Date().toISOString())).toBe("just now");
    setLanguage("pl", { reload: false });
    expect(formatNumber(1234.5)).toBe("1234,5");
    expect(formatRange(1440)).toBe("24 godz.");
    setLanguage(null, { reload: false }); // według przeglądarki (jsdom: en-US)
    expect(localStorage.getItem("netpulse.language")).toBeNull();
    expect(getLanguage()).toBe(browserLanguage());
  });

  // Strony, które da się przejść po angielsku bez polskiego tekstu z panelu (dane z atrapy API są neutralne).
  // Raporty i Ustawienia → System pokazują teksty z backendu (tytuły alertów, opisy źródeł danych): tłumaczy je API
  // (od 0.75.0, backend/netpulse/i18n.py, testy w backend/tests/test_i18n.py), a atrapa API odpowiada po polsku.
  const PAGES = [
    "/",
    "/alerts",
    "/checks",
    "/settings/account",
    "/settings/devices",
    "/settings/alert-rules",
    "/settings/notifications",
    "/settings/refresh",
    "/settings/modules",
    "/settings/dashboards",
    "/settings/users",
    "/settings/audit",
    "/settings/wan",
    "/topology",
    "/setup",
  ];

  it.each(PAGES)("strona %s po angielsku nie ma polskich tekstów", async (path) => {
    mockApi();
    setLanguage("en", { reload: false });
    renderApp(path);
    await screen.findByRole("navigation", { name: "Main menu" });
    await waitFor(() => expect(document.querySelector("main")?.textContent?.length ?? 0).toBeGreaterThan(20));
    // bez ładowania: daje zapytaniom chwilę na odpowiedź atrapy
    await waitFor(() => expect(screen.queryByText("Loading…")).not.toBeInTheDocument());
    const text = document.body.textContent ?? "";
    const hit = text.match(new RegExp(`.{0,40}${POLISH.source}.{0,40}`));
    expect(hit?.[0] ?? null).toBeNull();
  });

  it("logowanie: wybór języka przełącza panel", async () => {
    mockApi({ authenticated: false });
    setLanguage("en", { reload: false });
    renderApp("/");
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    const select = screen.getByRole("combobox", { name: "Language" });
    const reload = window.location.reload;
    let reloaded = false;
    Object.defineProperty(window, "location", { configurable: true, value: { ...window.location, reload: () => (reloaded = true) } });
    try {
      await userEvent.setup().selectOptions(select, "pl");
    } finally {
      Object.defineProperty(window, "location", { configurable: true, value: { ...window.location, reload } });
    }
    expect(getLanguage()).toBe("pl");
    expect(reloaded).toBe(true);
  });
});
