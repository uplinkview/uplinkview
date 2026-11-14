/** Skąd bierze dane wykres: ścieżki API dla każdego rodzaju źródła i normalizacja odpowiedzi. */
import { useQueries, type UseQueryResult } from "@tanstack/react-query";
import { useCallback } from "react";
import { t } from "../../i18n";
import { get, type Series, type SeriesPoint } from "../../lib/api";
import type { ChartConfig, ChartQuery, Source } from "../../lib/layout";
import { useRefresh } from "../../lib/refresh";

/** Powyżej 7 dni API liczy wykres z agregatów godzinowych: kubełki to pełne godziny (backend/netpulse/aggregates.py). */
const RAW_MAX_MINUTES = 7 * 24 * 60;
const LONG_BUCKETS_H = [1, 2, 3, 6, 12, 24, 48];
const RAW_BUCKETS_S = [30, 60, 120, 300, 600, 900, 1800, 3600];

/** Ten sam rozmiar kubełka co w API: najwyżej ~300 punktów z równej drabinki (od 0.71.0: 24 h = 5 min, 7 dni = 1 h, jak w UniFi). */
export function bucketSeconds(minutes: number): number {
  const raw = Math.floor((minutes * 60) / 300);
  if (minutes <= RAW_MAX_MINUTES) return RAW_BUCKETS_S.find((s) => s >= raw) ?? RAW_BUCKETS_S[RAW_BUCKETS_S.length - 1];
  return (LONG_BUCKETS_H.find((h) => h * 3600 >= raw) ?? LONG_BUCKETS_H[LONG_BUCKETS_H.length - 1]) * 3600;
}

/** Ścieżka API danych źródła; `offset` (minuty) przesuwa okno wstecz – porównanie z wcześniejszym okresem. */
export function sourcePath(source: Source, minutes: number, offset = 0): string {
  const shift = offset > 0 ? `&offset=${offset}` : "";
  switch (source.kind) {
    case "wan":
      return `/api/dashboard/traffic?minutes=${minutes}${shift}`;
    case "wifi_total":
      return `/api/dashboard/wifi?minutes=${minutes}${shift}`;
    case "interface":
      return `/api/interfaces/${source.id}/metrics?minutes=${minutes}${shift}`;
    case "device":
      return `/api/devices/${source.id}/metrics?minutes=${minutes}${shift}`;
    case "wifi_network":
      return `/api/wifi/${source.id}/metrics?minutes=${minutes}${shift}`;
    case "server":
      return `/api/system/metrics?minutes=${minutes}${shift}`;
    case "check":
      return `/api/checks/${source.id}/metrics?minutes=${minutes}${shift}`;
    default:
      return `/api/devices/${source.id}/agent-metrics?source=${source.kind}&key=${encodeURIComponent(source.key)}&minutes=${minutes}${shift}`;
  }
}

const AGENT_TITLE = {
  agent_net: "ce.source.agent_net",
  agent_disk: "ce.source.agent_disk",
  agent_temp: "ce.source.agent_temp",
  agent_container: "ce.source.agent_container",
  pve_guest: "ce.source.pve_guest",
  snmp_sensor: "ce.source.snmp_sensor",
  snmp_poe: "ce.source.snmp_poe",
  snmp_sfp: "ce.source.snmp_sfp",
  wan_latency: "ce.source.wan_latency",
  wan_ping: "ce.source.wan_ping",
  speedtest: "ce.source.speedtest",
  vpn: "ce.source.vpn",
  lan_client: "ce.source.lan_client",
} as const;

/** Endpointy pulpitu zwracają `{interval_s, points}`, pozostałe samą listę punktów.
 * Dane z przesunięciem (porównanie) dostają czas przesunięty do przodu, żeby nałożyły się na bieżące;
 * `back` cofa okno bez przesuwania czasu (powiększony fragment z przeszłości). */
export async function fetchSeries(source: Source, minutes: number, offset = 0, back = 0): Promise<Series> {
  const raw = await get<Series | SeriesPoint[]>(sourcePath(source, minutes, offset + back));
  const series = Array.isArray(raw) ? { interval_s: bucketSeconds(minutes), points: raw } : raw;
  if (!offset) return series;
  const ms = offset * 60_000;
  return { ...series, points: series.points.map((p) => ({ ...p, time: new Date(new Date(p.time).getTime() + ms).toISOString() })) };
}

export function defaultTitle(source: Source): string {
  switch (source.kind) {
    case "wan":
      return t("chart.traffic.title");
    case "wifi_total":
      return t("chart.wifi.title");
    case "interface":
      return t("widget.title.interface", { id: source.id });
    case "device":
      return t("widget.title.device", { id: source.id });
    case "wifi_network":
      return t("widget.title.wifi_network", { id: source.id });
    case "server":
      return t("widget.type.server");
    case "agent_cpu":
      return t("widget.title.agent_cpu");
    case "check":
      return t("widget.title.check", { id: source.id });
    default:
      return `${t(AGENT_TITLE[source.kind])}: ${source.key}`;
  }
}

export interface QueryResult {
  query: ChartQuery;
  data: Series | undefined;
  isError: boolean;
  error: unknown;
}

/** Dane wszystkich zapytań wykresu z własnym zakresem i odświeżaniem widgetu (puste = ustawienia globalne).
 * Powiększony fragment osi czasu ma pierwszeństwo przed zakresem widgetu i wstrzymuje odświeżanie. */
export function useChartQueries(config: ChartConfig) {
  const global = useRefresh();
  const zoom = global.zoom;
  const minutes = zoom?.minutes ?? config.range_min ?? global.rangeMinutes;
  const back = zoom?.offset ?? 0;
  const own = config.refresh_s;
  const refetchInterval = zoom ? false : own == null ? global.refetchInterval : own > 0 ? own * 1000 : false;
  // `combine`: wynik (z `queries`) zostaje tym samym obiektem, dopóki dane się nie zmienią – bez tego każdy render
  // widgetu (np. odczyt „Na żywo” w nagłówku co ~1,5 s) przerysowywał cały wykres (od 0.65.4)
  const combine = useCallback(
    (results: UseQueryResult<Series>[]) => ({
      queries: config.queries.map(
        (query, i): QueryResult => ({ query, data: results[i]?.data, isError: results[i]?.isError ?? false, error: results[i]?.error }),
      ),
      isLoading: results.some((r) => r.isLoading),
      // Błąd wykresu tylko wtedy, gdy żadne zapytanie nie dało danych (jedno brakujące źródło nie gasi reszty)
      isError: results.length > 0 && results.every((r) => r.isError && !r.data),
      error: results.find((r) => r.error)?.error,
    }),
    [config.queries],
  );
  const combined = useQueries({
    queries: config.queries.map((q) => ({
      queryKey: back ? ["chart", q.source, minutes, q.offset_min ?? 0, back] : ["chart", q.source, minutes, q.offset_min ?? 0],
      queryFn: () => fetchSeries(q.source, minutes, q.offset_min ?? 0, back),
      refetchInterval,
      placeholderData: (previous: Series | undefined) => previous, // przy zmianie zakresu stary wykres zostaje do czasu nowych danych
      retry: false,
    })),
    combine,
  });
  return { ...combined, minutes };
}
