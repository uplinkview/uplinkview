/**
 * Rejestr modułów panelu – jedno miejsce, z którego powstaje menu i routing.
 * Nowa sekcja (Alerty, Topologia, Klienci WiFi…) to jeden wpis tutaj.
 */
import { Navigate } from "react-router";
import {
  IconBell,
  IconActivity,
  IconBellRinging,
  IconServerCog,
  IconFlame,
  IconDatabase,
  IconDevicesPc,
  IconDownload,
  IconFileAnalytics,
  IconHeartbeat,
  IconHierarchy2,
  IconLayoutDashboard,
  IconRefresh,
  IconSend,
  IconKey,
  IconPlug,
  IconPuzzle,
  IconServer2,
  IconSettings,
  IconTerminal2,
  IconTool,
  IconUsers,
  IconListDetails,
  IconUserCircle,
  IconWand,
  IconWorld,
  type Icon,
} from "@tabler/icons-react";
import { lazy, type ComponentType, type ReactNode } from "react";
import type { TextKey } from "./i18n";
import { isOn, useModules, type ModuleId, type Modules } from "./lib/modules";
import { hasRole, roleOf, type Role } from "./lib/roles";
import { useAuth } from "./auth/AuthProvider";

/** Strona ładowana dopiero przy pierwszym wejściu (osobny plik JS) – panel otwiera się szybciej. */
function page<K extends string>(load: () => Promise<Record<K, ComponentType>>, name: K) {
  return lazy(() => load().then((m) => ({ default: m[name] })));
}

// Pulpit to pierwszy ekran po zalogowaniu – jego plik pobieramy od razu, równolegle z resztą panelu
const loadDashboard = () => import("./pages/DashboardPage");
void loadDashboard();

const ChecksPage = page(() => import("./pages/ChecksPage"), "ChecksPage");
const AgentsPage = page(() => import("./pages/settings/AgentsPage"), "AgentsPage");
const AlertRulesPage = page(() => import("./pages/settings/AlertRulesPage"), "AlertRulesPage");
const BackupsPage = page(() => import("./pages/settings/BackupsPage"), "BackupsPage");
const ModulesPage = page(() => import("./pages/settings/ModulesPage"), "ModulesPage");
const AlertsPage = page(() => import("./pages/AlertsPage"), "AlertsPage");
const ReportsPage = page(() => import("./pages/ReportsPage"), "ReportsPage");
const AccountPage = page(() => import("./pages/settings/AccountPage"), "AccountPage");
const ClientPage = page(() => import("./pages/ClientPage"), "ClientPage");
const ClientsPage = page(() => import("./pages/ClientsPage"), "ClientsPage");
const ProxmoxPage = page(() => import("./pages/ProxmoxPage"), "ProxmoxPage");
const ProxmoxSettingsPage = page(() => import("./pages/settings/ProxmoxSettingsPage"), "ProxmoxSettingsPage");
const OpnsenseSettingsPage = page(() => import("./pages/settings/OpnsenseSettingsPage"), "OpnsenseSettingsPage");
const TopologyPage = page(() => import("./pages/TopologyPage"), "TopologyPage");
const ControllersPage = page(() => import("./pages/settings/ControllersPage"), "ControllersPage");
const DashboardsPage = page(() => import("./pages/settings/dashboards/DashboardsPage"), "DashboardsPage");
const DevicesPage = page(() => import("./pages/settings/devices/DevicesPage"), "DevicesPage");
const NotificationsPage = page(() => import("./pages/settings/NotificationsPage"), "NotificationsPage");
const RefreshPage = page(() => import("./pages/settings/RefreshPage"), "RefreshPage");
const SystemPage = page(() => import("./pages/settings/SystemPage"), "SystemPage");
const UpdatePage = page(() => import("./pages/settings/UpdatePage"), "UpdatePage");
const WanLinksPage = page(() => import("./pages/settings/WanLinksPage"), "WanLinksPage");
const MaintenancePage = page(() => import("./pages/settings/MaintenancePage"), "MaintenancePage");
const UsersPage = page(() => import("./pages/settings/UsersPage"), "UsersPage");
const AuditPage = page(() => import("./pages/settings/AuditPage"), "AuditPage");
const DashboardPage = page(loadDashboard, "DashboardPage");
const DevicePage = page(() => import("./pages/DevicePage"), "DevicePage");
const PortPage = page(() => import("./pages/PortPage"), "PortPage");
const ServerPage = page(() => import("./pages/ServerPage"), "ServerPage");
const SetupPage = page(() => import("./pages/SetupPage"), "SetupPage");

export interface NavChild {
  /** Ścieżka względem rodzica, np. "account" → /settings/account */
  path: string;
  label: TextKey;
  icon: Icon;
  element: ReactNode;
  /** Podstrona modułu z Ustawienia → Moduły – znika, gdy moduł jest wyłączony */
  module?: ModuleId;
  /** Najniższa rola, która widzi podstronę Ustawień (od 0.61.0); bez niej – tylko administrator */
  role?: Role;
}

export interface NavModule {
  id: string;
  /** Ścieżka bezwzględna, np. "/" albo "/settings" */
  path: string;
  label: TextKey;
  icon: Icon;
  /** Moduł bez podstron renderuje `element`. */
  element?: ReactNode;
  /** Moduł z podstronami; wejście na `path` przekierowuje do pierwszej. */
  children?: NavChild[];
  /** Pozycja należy do modułu z Ustawienia → Moduły – znika, gdy moduł jest wyłączony */
  module?: ModuleId;
  /** Sama trasa bez pozycji w menu (np. szczegóły urządzenia otwierane z karty) */
  hidden?: boolean;
  /** Grupa w menu (od 0.58.1); bez niej – „Monitoring”. Integracja z Ustawienia → Moduły = zwykle "integrations". */
  group?: NavGroup;
}

/** Grupy menu w kolejności wyświetlania. */
export const NAV_GROUPS = ["monitoring", "events", "integrations", "system"] as const;
export type NavGroup = (typeof NAV_GROUPS)[number];

export const modules: NavModule[] = [
  {
    id: "dashboard",
    path: "/",
    label: "nav.dashboard",
    icon: IconLayoutDashboard,
    element: <DashboardPage />,
  },
  {
    id: "dashboard-by-id",
    path: "/dashboards/:dashboardId",
    label: "nav.dashboard",
    icon: IconLayoutDashboard,
    element: <DashboardPage />,
    hidden: true,
  },
  {
    id: "setup",
    path: "/setup",
    label: "nav.setup",
    icon: IconWand,
    element: <SetupPage />,
    hidden: true,
  },
  {
    id: "device",
    path: "/devices/:deviceId",
    label: "nav.device",
    icon: IconServer2,
    element: <DevicePage />,
    hidden: true,
  },
  {
    id: "server",
    path: "/devices/:deviceId/server",
    label: "nav.server",
    icon: IconServer2,
    element: <ServerPage />,
    hidden: true,
  },
  {
    id: "port",
    path: "/devices/:deviceId/ports/:interfaceId",
    label: "nav.port",
    icon: IconPlug,
    element: <PortPage />,
    hidden: true,
  },
  {
    id: "clients",
    path: "/clients",
    label: "nav.clients",
    icon: IconDevicesPc,
    element: <ClientsPage />,
    module: "unifi",
  },
  {
    id: "client",
    path: "/clients/:mac",
    label: "nav.client",
    icon: IconDevicesPc,
    element: <ClientPage />,
    module: "unifi",
    hidden: true,
  },
  {
    id: "proxmox",
    path: "/proxmox",
    label: "nav.proxmox",
    icon: IconServerCog,
    element: <ProxmoxPage />,
    module: "proxmox",
    group: "integrations",
  },
  {
    id: "topology",
    path: "/topology",
    label: "nav.topology",
    icon: IconHierarchy2,
    element: <TopologyPage />,
    module: "unifi",
  },
  {
    // Dostępność to konfiguracja sprawdzeń – od 0.58.3 w Ustawieniach; stary adres przekierowuje
    id: "checks-legacy",
    path: "/checks",
    label: "nav.checks",
    icon: IconActivity,
    element: <Navigate to="/settings/checks" replace />,
    hidden: true,
  },
  {
    id: "alerts",
    path: "/alerts",
    label: "nav.alerts",
    icon: IconBellRinging,
    element: <AlertsPage />,
    group: "events",
  },
  {
    id: "reports",
    path: "/reports",
    label: "nav.reports",
    icon: IconFileAnalytics,
    element: <ReportsPage />,
    group: "events",
  },
  {
    id: "settings",
    path: "/settings",
    label: "nav.settings",
    icon: IconSettings,
    group: "system",
    children: [
      { path: "account", label: "nav.settings.account", icon: IconUserCircle, element: <AccountPage />, role: "viewer" },
      {
        path: "users",
        label: "nav.settings.users",
        icon: IconUsers,
        element: <UsersPage />,
      },
      {
        path: "audit",
        label: "nav.settings.audit",
        icon: IconListDetails,
        element: <AuditPage />,
      },
      {
        path: "devices",
        label: "nav.settings.devices",
        icon: IconServer2,
        element: <DevicesPage />,
      },
      {
        path: "checks",
        label: "nav.checks",
        icon: IconActivity,
        element: <ChecksPage />,
      },
      {
        path: "dashboards",
        label: "nav.settings.dashboards",
        icon: IconLayoutDashboard,
        element: <DashboardsPage />,
        role: "viewer",
      },
      {
        path: "wan",
        label: "nav.settings.wan",
        icon: IconWorld,
        element: <WanLinksPage />,
      },
      {
        path: "agents",
        label: "nav.settings.agents",
        icon: IconTerminal2,
        element: <AgentsPage />,
        module: "agents",
      },
      {
        path: "controllers",
        label: "nav.settings.controllers",
        icon: IconKey,
        element: <ControllersPage />,
        module: "unifi",
      },
      {
        path: "proxmox",
        label: "nav.settings.proxmox",
        icon: IconServerCog,
        element: <ProxmoxSettingsPage />,
        module: "proxmox",
      },
      {
        path: "opnsense",
        label: "nav.settings.opnsense",
        icon: IconFlame,
        element: <OpnsenseSettingsPage />,
        module: "opnsense",
      },
      {
        path: "alert-rules",
        label: "nav.settings.alertRules",
        icon: IconBell,
        element: <AlertRulesPage />,
      },
      {
        path: "maintenance",
        label: "nav.settings.maintenance",
        icon: IconTool,
        element: <MaintenancePage />,
        role: "operator",
      },
      {
        path: "notifications",
        label: "nav.settings.notifications",
        icon: IconSend,
        element: <NotificationsPage />,
      },
      {
        path: "refresh",
        label: "nav.settings.refresh",
        icon: IconRefresh,
        element: <RefreshPage />,
        role: "viewer",
      },
      {
        path: "system",
        label: "nav.settings.system",
        icon: IconHeartbeat,
        element: <SystemPage />,
        role: "viewer",
      },
      {
        path: "backups",
        label: "nav.settings.backups",
        icon: IconDatabase,
        element: <BackupsPage />,
        module: "backups",
      },
      {
        path: "modules",
        label: "nav.settings.modules",
        icon: IconPuzzle,
        element: <ModulesPage />,
        role: "viewer",
      },
      {
        path: "update",
        label: "nav.settings.update",
        icon: IconDownload,
        element: <UpdatePage />,
        role: "viewer",
      },
    ],
  },
];

/** Rejestr bez pozycji wyłączonych modułów i podstron Ustawień niedostępnych dla roli (menu i trasy). */
export function visibleModules(mods: Modules | undefined, role: Role = "admin"): NavModule[] {
  return modules
    .filter((m) => isOn(mods, m.module))
    .map((m) => (m.children ? { ...m, children: m.children.filter((c) => isOn(mods, c.module) && hasRole(role, c.role ?? "admin")) } : m));
}

export function useVisibleModules(): NavModule[] {
  return visibleModules(useModules().data, roleOf(useAuth().status?.user));
}
