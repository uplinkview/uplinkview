/** Wiele pulpitów i udostępnianie publiczne (API: backend/netpulse/api/dashboards.py i public.py). */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { del, get, patch, post, request } from "./api";
import {
  DEFAULT_LAYOUT,
  newChartConfig,
  newId,
  newWidget,
  type ChartHeight,
  type ChartWidgetModel,
  type DashboardLayout,
  type Widget,
} from "./layout";
import { LAYOUT_KEY } from "./layoutApi";
import type { RangeMinutes } from "./refresh";
import type { TextKey } from "../i18n";

export type PublicRefresh = 10 | 30 | 60 | 300;
export const PUBLIC_REFRESH: PublicRefresh[] = [10, 30, 60, 300];

export interface PublicOptions {
  refresh_s: PublicRefresh;
  range_min: RangeMinutes;
  hide_hosts: boolean;
}

export const DEFAULT_PUBLIC_OPTIONS: PublicOptions = { refresh_s: 30, range_min: 60, hide_hosts: true };

export interface PublicInfo {
  token: string;
  expires_at: string | null;
  expired: boolean;
  has_pin: boolean;
  options: PublicOptions;
}

export interface DashboardInfo {
  id: number;
  name: string;
  is_default: boolean;
  widgets: number;
  updated_at: string;
  /** null = pulpit prywatny */
  public: PublicInfo | null;
}

export interface DashboardFull extends DashboardInfo {
  layout: DashboardLayout | null;
}

/** PUT /api/dashboards/{id}/public */
export interface PublicPayload {
  enabled: boolean;
  expires_at?: string | null;
  /** Nowy PIN (same cyfry, 4–12); pominięty = bez zmian */
  pin?: string;
  clear_pin?: boolean;
  options?: PublicOptions;
}

/** Odpowiedź GET /api/public/dashboards/{token} */
export interface PublicDashboard {
  name: string;
  locked: boolean;
  layout: DashboardLayout | null;
  options: PublicOptions;
}

export const DASHBOARDS_KEY = ["dashboards"] as const;

export function useDashboards() {
  return useQuery({ queryKey: DASHBOARDS_KEY, queryFn: () => get<DashboardInfo[]>("/api/dashboards") });
}

/** Wszystkie zmiany pulpitów odświeżają listę i układ pod „/” (mógł się zmienić pulpit domyślny). */
export function useDashboardMutations() {
  const qc = useQueryClient();
  const refresh = () =>
    Promise.all([
      qc.invalidateQueries({ queryKey: DASHBOARDS_KEY }),
      qc.invalidateQueries({ queryKey: LAYOUT_KEY }),
      qc.invalidateQueries({ queryKey: ["dashboard-by-id"] }),
    ]);
  return {
    create: useMutation({
      mutationFn: (body: { name: string; layout: DashboardLayout; make_default?: boolean }) => post<DashboardFull>("/api/dashboards", body),
      onSuccess: refresh,
    }),
    rename: useMutation({
      mutationFn: ({ id, name }: { id: number; name: string }) => patch<DashboardFull>(`/api/dashboards/${id}`, { name }),
      onSuccess: refresh,
    }),
    remove: useMutation({ mutationFn: (id: number) => del(`/api/dashboards/${id}`), onSuccess: refresh }),
    makeDefault: useMutation({ mutationFn: (id: number) => post<DashboardInfo>(`/api/dashboards/${id}/default`), onSuccess: refresh }),
    share: useMutation({
      mutationFn: ({ id, body }: { id: number; body: PublicPayload }) => request<DashboardInfo>("PUT", `/api/dashboards/${id}/public`, body),
      onSuccess: refresh,
    }),
    rotate: useMutation({ mutationFn: (id: number) => post<DashboardInfo>(`/api/dashboards/${id}/public/rotate`), onSuccess: refresh }),
  };
}

export const publicUrl = (token: string, origin = window.location.origin) => `${origin}/p/${token}`;
export const qrUrl = (id: number, origin = window.location.origin) => `/api/dashboards/${id}/public/qr.svg?origin=${encodeURIComponent(origin)}`;

// --- szablony kreatora ---------------------------------------------------------------

export type TemplateId = "full" | "wan" | "devices" | "wall" | "empty";

export const TEMPLATES: { id: TemplateId; label: TextKey; description: TextKey }[] = [
  { id: "full", label: "dashboards.tpl.full", description: "dashboards.tpl.full.desc" },
  { id: "wan", label: "dashboards.tpl.wan", description: "dashboards.tpl.wan.desc" },
  { id: "devices", label: "dashboards.tpl.devices", description: "dashboards.tpl.devices.desc" },
  { id: "wall", label: "dashboards.tpl.wall", description: "dashboards.tpl.wall.desc" },
  { id: "empty", label: "dashboards.tpl.empty", description: "dashboards.tpl.empty.desc" },
];

const sized = (type: Widget["type"], w: Widget["w"]): Widget => ({ ...newWidget(type), w }) as Widget;

function wanChart(w: Widget["w"], height: ChartHeight = "md"): ChartWidgetModel {
  return { id: newId(), type: "chart", w, config: { ...newChartConfig({ kind: "wan" }), height } };
}

/** Widgety szablonu (nowe identyfikatory przy każdym wywołaniu). */
export function templateWidgets(id: TemplateId): Widget[] {
  switch (id) {
    case "full":
      return [
        ...DEFAULT_LAYOUT.widgets.map((w) => ({ ...w, id: newId() })),
        { id: newId(), type: "chart", w: 4, config: newChartConfig({ kind: "wifi_total" }) },
        sized("wan_status", 4),
        sized("server", 4),
      ];
    case "wan":
      return [sized("wan_status", 4), sized("wan_chart", 8), wanChart(12), sized("wan_usage", 4), sized("wan_sla", 8)];
    case "devices":
      return [{ id: newId(), type: "summary", w: 12, config: { tiles: ["devices"] } }, sized("devices", 12), newWidget("poe")];
    case "wall":
      return [newWidget("summary"), wanChart(8, "lg"), sized("wan_status", 4), sized("devices", 12)];
    case "empty":
      return [];
  }
}
