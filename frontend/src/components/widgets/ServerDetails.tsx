import { useQuery } from "@tanstack/react-query";
import { t } from "../../i18n";
import { get } from "../../lib/api";
import { formatBytes, formatUptime } from "../../lib/format";
import { useRefresh } from "../../lib/refresh";
import { UsageBar } from "./ServerWidget";

export interface ServerDisk {
  mount: string;
  total_bytes: number;
  used_bytes: number;
  used_percent: number;
}

/** Zdjęcie stanu z agenta UplinkView (backend: api/servers.py AgentInfo). */
export interface AgentContainer {
  name: string;
  image: string | null;
  state: string;
  status: string | null;
  cpu_percent: number | null;
  mem_bytes: number | null;
}

export interface AgentSmart {
  device: string;
  model: string | null;
  passed: boolean | null;
  temp_c: number | null;
  power_on_hours?: number | null;
  reallocated?: number | null;
}

export interface AgentInfo {
  agent_version: string | null;
  os: string | null;
  kernel: string | null;
  cpu_cores: number | null;
  load: number[];
  mem_total_bytes: number | null;
  /** Bieżący ruch dysków (B/s) i interfejsów (b/s); agenci sprzed 0.24.0 ich nie przysyłają. */
  disk_io?: { device: string; read_bps: number | null; write_bps: number | null }[];
  net?: { iface: string; rx_bps: number | null; tx_bps: number | null }[];
  temps: { sensor: string; celsius: number }[];
  services: {
    running: number;
    failed: number;
    items: { name: string; active: string; sub: string | null; watched?: boolean | null; mem_bytes?: number | null; uptime_s?: number | null }[];
  } | null;
  containers: AgentContainer[] | null;
  smart: AgentSmart[] | null;
  /** Agent starszy niż UplinkView (server_version) – do zaktualizowania na serwerze. */
  outdated?: boolean;
  server_version?: string;
}

export interface ServerStatus {
  sampled_at: string;
  cpu_percent: number | null;
  mem_used_percent: number | null;
  swap_used_percent: number | null;
  load1: number | null;
  uptime_s: number | null;
  processes: number | null;
  disks: ServerDisk[];
  agent?: AgentInfo | null;
}

/** Dyski pokazywane na karcie; kolejne zostają w „…i N więcej”, bo serwer z dużą liczbą woluminów rozdmuchałby pulpit. */
export const MAX_DISKS = 4;

export function useServerStatus(deviceId: number) {
  const { refetchInterval } = useRefresh();
  return useQuery({
    queryKey: ["device-server", deviceId],
    queryFn: () => get<ServerStatus | null>(`/api/devices/${deviceId}/server`),
    refetchInterval,
  });
}

/** Lista nazw do jednej linijki: pierwsze kilka, reszta jako „+N”. */
function names(list: string[], max = 3): string {
  return list.length > max ? `${list.slice(0, max).join(", ")} +${list.length - max}` : list.join(", ");
}

type AgentService = NonNullable<AgentInfo["services"]>["items"][number];

/** Usługa z problemem: z błędem, obserwowana i brakująca albo obserwowana i zatrzymana. Usługa w trakcie zmiany
 * stanu (`activating`, `reloading`, `deactivating`) problemem nie jest – od 0.29.0 agent wysyła wszystkie działające.
 * Starszy agent nie podaje `watched`; wysyłał tylko usługi z błędem i obserwowane, więc jego „inactive” to problem. */
export function serviceProblem(s: AgentService): boolean {
  return s.active === "failed" || s.active === "missing" || (s.active === "inactive" && s.watched !== false);
}

/** Kontenery, usługi, temperatura i SMART – tylko z agenta (SNMP tego nie podaje). Problemy na czerwono. */
function AgentLines({ agent }: { agent: AgentInfo }) {
  const lines: { key: string; text: string; problem?: boolean; warn?: boolean }[] = [];
  if (agent.containers?.length) {
    const running = agent.containers.filter((c) => c.state === "running");
    const stopped = agent.containers.filter((c) => c.state !== "running").map((c) => c.name);
    lines.push({ key: "containers", text: t("agent.containers", { running: running.length, total: agent.containers.length }) });
    if (stopped.length) lines.push({ key: "stopped", text: t("agent.containers.stopped", { names: names(stopped) }), problem: true });
  }
  if (agent.services) {
    const failed = agent.services.items.filter(serviceProblem).map((s) => s.name.replace(/\.service$/, ""));
    lines.push(
      failed.length
        ? { key: "services", text: t("agent.services.failed", { names: names(failed) }), problem: true }
        : { key: "services", text: t("agent.services.ok", { n: agent.services.running }) },
    );
  }
  if (agent.temps.length) {
    const max = Math.max(...agent.temps.map((x) => x.celsius));
    lines.push({ key: "temp", text: `${t("server.temp")}: ${Math.round(max)}°C`, problem: max >= 85 });
  }
  if (agent.smart?.length) {
    const bad = agent.smart.filter((d) => d.passed === false).map((d) => d.device);
    lines.push(
      bad.length
        ? { key: "smart", text: t("agent.smart.bad", { names: names(bad) }), problem: true }
        : { key: "smart", text: t("agent.smart.ok", { n: agent.smart.length }) },
    );
  }
  if (agent.outdated) lines.push({ key: "outdated", text: t("agent.outdated", { version: agent.agent_version ?? "?" }), warn: true });
  if (!lines.length) return null;
  return (
    <ul className="flex flex-col gap-0.5 text-xs" aria-label={t("agent.details")}>
      {lines.map((l) => (
        <li key={l.key} className={l.problem ? "font-medium text-danger" : l.warn ? "text-warning" : "text-text-2"}>
          {l.text}
        </li>
      ))}
    </ul>
  );
}

/** CPU, RAM, swap i dyski serwera Linux (snmpd albo agent) – wnętrze karty urządzenia. */
export function ServerDetails({ deviceId }: { deviceId: number }) {
  const { data } = useServerStatus(deviceId);
  if (!data) return null;
  // Najbardziej zapełnione dyski na górze: o te chodzi użytkownikowi
  const disks = [...data.disks].sort((a, b) => b.used_percent - a.used_percent);
  return (
    <div className="flex flex-col gap-2.5 border-t border-border pt-3">
      <UsageBar label={t("server.cpu")} percent={data.cpu_percent} />
      <UsageBar label={t("server.ram")} percent={data.mem_used_percent} />
      {data.swap_used_percent != null && <UsageBar label={t("server.swap")} percent={data.swap_used_percent} />}
      {disks.slice(0, MAX_DISKS).map((d) => (
        <UsageBar
          key={d.mount}
          label={d.mount}
          percent={d.used_percent}
          note={t("server.free", { free: formatBytes(d.total_bytes - d.used_bytes), total: formatBytes(d.total_bytes) })}
        />
      ))}
      {disks.length > MAX_DISKS && <p className="text-xs text-text-2">{t("topo.more", { n: disks.length - MAX_DISKS })}</p>}
      {data.agent && <AgentLines agent={data.agent} />}
      <p className="text-xs text-text-2">
        {[
          data.uptime_s != null ? `${t("server.uptime")}: ${formatUptime(data.uptime_s)}` : null,
          data.processes != null ? t("server.processes", { n: data.processes }) : null,
        ]
          .filter(Boolean)
          .join(" · ")}
      </p>
    </div>
  );
}
