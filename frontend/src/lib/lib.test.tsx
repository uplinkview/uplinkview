import { act, renderHook } from "@testing-library/react";
import { ApiError, messageFromDetail, request } from "./api";
import { toChartRows } from "../components/charts/chartData";
import { formatBps, formatRange, formatUptime, initials, relativeTime, vendorModel } from "./format";
import { ThemeProvider, readPref, resolveTheme, useTheme } from "./theme";

describe("api", () => {
  it("wyciąga komunikat z tekstu i z listy błędów walidacji", () => {
    expect(messageFromDetail("Nieprawidłowy login", "x")).toBe("Nieprawidłowy login");
    expect(messageFromDetail([{ msg: "za krótkie" }, { msg: "zły format" }], "x")).toBe("za krótkie zły format");
    expect(messageFromDetail(undefined, "awaria")).toBe("awaria");
    expect(messageFromDetail([], "awaria")).toBe("awaria");
    expect(messageFromDetail([{ msg: "Value error, Podaj nazwę okna" }], "x")).toBe("Podaj nazwę okna");
  });

  it("rzuca ApiError z kodem i komunikatem serwera", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ detail: "Wymagane logowanie" }), { status: 401 })),
    );
    await expect(request("GET", "/api/devices")).rejects.toMatchObject({ status: 401, message: "Wymagane logowanie" });
    await expect(request("GET", "/api/devices")).rejects.toBeInstanceOf(ApiError);
  });

  it("obsługuje 204 bez treści", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(null, { status: 204 })));
    await expect(request("POST", "/api/auth/logout", {})).resolves.toBeUndefined();
  });

  it("wysyła ciasteczka z tego samego źródła i JSON", async () => {
    const fetchMock = vi.fn(async () => new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await request("POST", "/api/x", { a: 1 });
    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(init.credentials).toBe("same-origin");
    expect(init.body).toBe('{"a":1}');
    expect((init.headers as Record<string, string>)["Content-Type"]).toBe("application/json");
    // język panelu – backend odpowiada komunikatami w tym języku (0.75.0); testy działają po polsku
    expect((init.headers as Record<string, string>)["Accept-Language"]).toBe("pl");
  });
});

describe("format", () => {
  it("łączy producenta i model bez powtórzeń", () => {
    expect(vendorModel("OPNsense", "OPNsense")).toBe("OPNsense");
    expect(vendorModel("Linux", "Linux 6.8.0-45-generic")).toBe("Linux 6.8.0-45-generic");
    expect(vendorModel("Ubiquiti", "UCG-Ultra")).toBe("Ubiquiti UCG-Ultra");
    expect(vendorModel("MikroTik", "MikroTikRB")).toBe("MikroTik MikroTikRB"); // tylko całe słowo
    expect(vendorModel("Generic", "Printer")).toBe("Printer");
    expect(vendorModel(null, "U6+")).toBe("U6+");
    expect(vendorModel("TP-Link", null)).toBe("TP-Link");
    expect(vendorModel(null, undefined)).toBe("");
  });

  const now = new Date("2026-10-24T20:00:00Z").getTime();

  it("relativeTime", () => {
    expect(relativeTime(null, now)).toBeNull();
    expect(relativeTime("2026-10-24T19:59:58Z", now)).toBe("przed chwilą");
    expect(relativeTime("2026-10-24T19:59:30Z", now)).toMatch(/30 sekund temu/);
    expect(relativeTime("2026-10-24T19:55:00Z", now)).toMatch(/5 minut temu/);
    expect(relativeTime("2026-10-24T17:00:00Z", now)).toMatch(/3 godziny temu/);
  });

  it("formatUptime", () => {
    expect(formatUptime(null)).toBe("-");
    expect(formatUptime(45 * 60)).toBe("45 min");
    expect(formatUptime(3 * 3600 + 120)).toBe("3 h 2 min");
    expect(formatUptime(45 * 86400 + 18 * 3600)).toBe("45 d 18 h");
  });

  it("initials", () => {
    expect(initials("admin")).toBe("AD");
    expect(initials("jan.kowalski")).toBe("JK");
    expect(initials("a")).toBe("A");
  });
});

describe("theme", () => {
  it("domyślnie według systemu i zapamiętuje wybór", () => {
    expect(readPref()).toBe("system");
    const { result } = renderHook(() => useTheme(), { wrapper: ThemeProvider });
    expect(result.current.pref).toBe("system");

    act(() => result.current.cycle());
    expect(result.current.pref).toBe("light");
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(localStorage.getItem("netpulse.theme")).toBe("light");

    act(() => result.current.cycle());
    expect(result.current.pref).toBe("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");

    act(() => result.current.cycle());
    expect(result.current.pref).toBe("system");
  });

  it("system ciemny → motyw ciemny", () => {
    vi.spyOn(window, "matchMedia").mockImplementation(
      (q) => ({ matches: true, media: q, addEventListener() {}, removeEventListener() {} }) as unknown as MediaQueryList,
    );
    expect(resolveTheme("system")).toBe("dark");
    expect(resolveTheme("light")).toBe("light");
  });

  it("ignoruje nieprawidłową zapamiętaną wartość", () => {
    localStorage.setItem("netpulse.theme", "fioletowy");
    expect(readPref()).toBe("system");
  });
});

describe("formatBps i formatRange", () => {
  it("skaluje jednostki i używa polskiego przecinka", () => {
    expect(formatBps(null)).toBe("–");
    expect(formatBps(0)).toBe("0 b/s");
    expect(formatBps(950)).toBe("950 b/s");
    expect(formatBps(42_300_000)).toBe("42,3 Mb/s");
    expect(formatBps(138_000_000)).toBe("138 Mb/s");
    expect(formatBps(6_500_000)).toBe("6,5 Mb/s");
    expect(formatBps(1_250_000_000)).toBe("1,25 Gb/s");
    expect(formatBps(120_000)).toBe("120 kb/s");
  });

  it("opisuje zakresy czasu", () => {
    expect(formatRange(15)).toBe("15 min");
    expect(formatRange(60)).toBe("1 godz.");
    expect(formatRange(360)).toBe("6 godz.");
    expect(formatRange(1440)).toBe("24 godz.");
    expect(formatRange(10080)).toBe("7 dni");
    expect(formatRange(43200)).toBe("30 dni");
    expect(formatRange(525600)).toBe("1 rok");
  });
});

describe("toChartRows", () => {
  const pt = (time: string, v: number | null) => ({ time, values: { x: v } });

  it("zamienia punkty na pary [czas, wartość]", () => {
    const rows = toChartRows([pt("2026-10-24T20:00:00Z", 1), pt("2026-10-24T20:00:30Z", 2)], "x", 30);
    expect(rows).toEqual([
      [Date.parse("2026-10-24T20:00:00Z"), 1],
      [Date.parse("2026-10-24T20:00:30Z"), 2],
    ]);
  });

  it("wstawia pusty punkt, gdy brakuje danych dłużej niż 2,5 odstępu", () => {
    const rows = toChartRows([pt("2026-10-24T20:00:00Z", 1), pt("2026-10-24T20:05:00Z", 2)], "x", 30);
    expect(rows).toHaveLength(3);
    expect(rows[1]).toEqual([Date.parse("2026-10-24T20:00:30Z"), null]);
  });

  it("nie wstawia luki przy drobnym opóźnieniu i zachowuje puste wartości", () => {
    const rows = toChartRows([pt("2026-10-24T20:00:00Z", 1), pt("2026-10-24T20:01:00Z", null)], "x", 30);
    expect(rows).toHaveLength(2);
    expect(rows[1][1]).toBeNull();
  });

  it("brakujący klucz to wartość pusta", () => {
    expect(toChartRows([pt("2026-10-24T20:00:00Z", 1)], "inny", 30)[0][1]).toBeNull();
  });
});
