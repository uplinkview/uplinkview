import type { ReactNode } from "react";
import { useParams } from "react-router";
import { Card, ErrorNote, PageHeader } from "../components/ui";
import { serviceProblem, useServerStatus, type AgentContainer, type AgentInfo, type ServerStatus } from "../components/widgets/ServerDetails";
import { UsageBar } from "../components/widgets/ServerWidget";
import { t, locale } from "../i18n";
import { updateCommand } from "../lib/agents";
import { ApiError } from "../lib/api";
import { useDevice } from "../lib/details";
import { formatBps, formatBytes, formatBytesPerSec, formatUptime } from "../lib/format";
import { BackLink } from "./DevicePage";
import { formatNumber } from "../lib/intl";

const fixed = (v: number | null | undefined) => (v == null ? "–" : formatNumber(v, { minimumFractionDigits: 2, maximumFractionDigits: 2 }));

/** Tabela w karcie z nagłówkiem; kolumny z `right` wyrównane do prawej (liczby). */
function TableCard({
  title,
  note,
  columns,
  minWidth = "min-w-[32rem]",
  children,
}: {
  title: string;
  note?: string;
  columns: { label: string; right?: boolean }[];
  minWidth?: string;
  children: ReactNode;
}) {
  return (
    <Card className="overflow-x-auto">
      <h2 className="px-4 pt-4 text-sm font-medium">{title}</h2>
      {note && <p className="px-4 pt-1 text-xs text-text-2">{note}</p>}
      <table className={`mt-2 w-full ${minWidth} text-left text-sm`}>
        <thead className="text-xs text-text-2">
          <tr>
            {columns.map((c) => (
              <th key={c.label} scope="col" className={`px-4 py-2 font-medium ${c.right ? "text-right" : ""}`}>
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </Card>
  );
}

const cell = "px-4 py-2";
const num = "px-4 py-2 text-right tabular-nums";

function StateBadge({ ok, children }: { ok: boolean; children: ReactNode }) {
  return <span className={`rounded-md px-2 py-0.5 text-xs ${ok ? "bg-success-soft text-success" : "bg-danger-soft text-danger"}`}>{children}</span>;
}

/** Agent starszy niż UplinkView: polecenie aktualizacji do wklejenia na serwerze. */
function OutdatedNote({ agent }: { agent: AgentInfo }) {
  return (
    <div role="status" className="rounded-xl border border-warning/40 bg-warning-soft px-4 py-3 text-sm">
      <p className="font-medium text-warning">
        {t("srv.outdated.title", { version: agent.agent_version ?? "?", server: agent.server_version ?? "?" })}
      </p>
      <p className="mt-1 text-text-2">{t("srv.outdated.body")}</p>
      <code className="mt-2 block select-all break-all rounded-lg bg-surface px-3 py-2 font-mono text-xs text-text">
        {updateCommand(window.location.origin)}
      </code>
    </div>
  );
}

function SystemCard({ data }: { data: ServerStatus }) {
  const agent = data.agent;
  const rows: [string, string][] = [
    [t("srv.os"), agent?.os ?? "–"],
    [t("srv.kernel"), agent?.kernel ?? "–"],
    [t("srv.cores"), agent?.cpu_cores != null ? String(agent.cpu_cores) : "–"],
    [t("srv.memTotal"), formatBytes(agent?.mem_total_bytes)],
    [t("srv.load"), agent?.load.length ? agent.load.map(fixed).join(" / ") : fixed(data.load1)],
    [t("server.uptime"), formatUptime(data.uptime_s)],
    [t("srv.processes"), data.processes != null ? String(data.processes) : "–"],
  ];
  if (agent) rows.push([t("srv.agent"), agent.agent_version ?? "–"]);
  return (
    <Card className="p-4">
      <h2 className="mb-3 text-sm font-medium">{t("srv.system")}</h2>
      <div className="grid gap-4 md:grid-cols-2">
        <dl className="grid grid-cols-[auto_1fr] content-start gap-x-4 gap-y-1.5 text-sm">
          {rows.map(([label, value]) => (
            <div key={label} className="contents">
              <dt className="text-text-2">{label}</dt>
              <dd className="min-w-0 truncate" title={value}>
                {value}
              </dd>
            </div>
          ))}
        </dl>
        <div className="flex flex-col gap-2.5">
          <UsageBar label={t("server.cpu")} percent={data.cpu_percent} />
          <UsageBar label={t("server.ram")} percent={data.mem_used_percent} />
          {data.swap_used_percent != null && <UsageBar label={t("server.swap")} percent={data.swap_used_percent} />}
        </div>
      </div>
    </Card>
  );
}

function FilesystemsCard({ data }: { data: ServerStatus }) {
  if (!data.disks.length) return null;
  const disks = [...data.disks].sort((a, b) => a.mount.localeCompare(b.mount));
  return (
    <TableCard
      title={t("srv.fs.title", { n: disks.length })}
      columns={[{ label: t("srv.fs.mount") }, { label: t("srv.fs.used"), right: true }, { label: t("srv.fs.free"), right: true }, { label: t("srv.fs.total"), right: true }]}
    >
      {disks.map((d) => (
        <tr key={d.mount} className="border-t border-border">
          <td className={`${cell} w-1/2`}>
            <UsageBar label={d.mount} percent={d.used_percent} />
          </td>
          <td className={num}>{formatBytes(d.used_bytes)}</td>
          <td className={num}>{formatBytes(d.total_bytes - d.used_bytes)}</td>
          <td className={num}>{formatBytes(d.total_bytes)}</td>
        </tr>
      ))}
    </TableCard>
  );
}

/** Dyski fizyczne: SMART i bieżący odczyt/zapis, połączone po nazwie urządzenia (sda, nvme0n1). */
function DrivesCard({ agent }: { agent: AgentInfo }) {
  const io = new Map((agent.disk_io ?? []).map((d) => [d.device, d]));
  const smart = new Map((agent.smart ?? []).map((d) => [d.device, d]));
  const names = [...new Set([...smart.keys(), ...io.keys()])].sort();
  if (!names.length) return null;
  return (
    <TableCard
      title={t("srv.drives.title", { n: names.length })}
      minWidth="min-w-[44rem]"
      columns={[
        { label: t("srv.drives.device") },
        { label: t("srv.drives.model") },
        { label: "SMART" },
        { label: t("server.temp"), right: true },
        { label: t("srv.drives.hours"), right: true },
        { label: t("srv.drives.realloc"), right: true },
        { label: t("srv.drives.read"), right: true },
        { label: t("srv.drives.write"), right: true },
      ]}
    >
      {names.map((name) => {
        const s = smart.get(name);
        const rate = io.get(name);
        return (
          <tr key={name} className="border-t border-border">
            <td className={`${cell} font-medium`}>{name}</td>
            <td className={`${cell} max-w-48 truncate text-text-2`}>{s?.model ?? "–"}</td>
            <td className={cell}>
              {s?.passed == null ? "–" : <StateBadge ok={s.passed}>{t(s.passed ? "srv.drives.ok" : "srv.drives.failed")}</StateBadge>}
            </td>
            <td className={num}>{s?.temp_c != null ? `${Math.round(s.temp_c)}°C` : "–"}</td>
            <td className={num}>{s?.power_on_hours != null ? s.power_on_hours.toLocaleString(locale()) : "–"}</td>
            <td className={`${num} ${s?.reallocated ? "font-medium text-danger" : ""}`}>{s?.reallocated ?? "–"}</td>
            <td className={num}>{formatBytesPerSec(rate?.read_bps)}</td>
            <td className={num}>{formatBytesPerSec(rate?.write_bps)}</td>
          </tr>
        );
      })}
    </TableCard>
  );
}

function ContainersCard({ containers }: { containers: AgentContainer[] }) {
  // Zatrzymane na górze: o nie chodzi użytkownikowi
  const sorted = [...containers].sort((a, b) => Number(a.state === "running") - Number(b.state === "running") || a.name.localeCompare(b.name));
  const running = containers.filter((c) => c.state === "running").length;
  return (
    <TableCard
      title={t("srv.containers.title", { running, total: containers.length })}
      minWidth="min-w-[40rem]"
      columns={[
        { label: t("srv.containers.name") },
        { label: t("srv.containers.image") },
        { label: t("srv.state") },
        { label: t("srv.containers.status") },
        { label: "CPU", right: true },
        { label: t("server.ram"), right: true },
      ]}
    >
      {sorted.map((c) => (
        <tr key={c.name} className="border-t border-border">
          <td className={`${cell} font-medium`}>{c.name}</td>
          <td className={`${cell} max-w-56 truncate text-text-2`} title={c.image ?? undefined}>
            {c.image ?? "–"}
          </td>
          <td className={cell}>
            <StateBadge ok={c.state === "running"}>{c.state}</StateBadge>
          </td>
          <td className={`${cell} text-text-2`}>{c.status ?? "–"}</td>
          <td className={num}>{c.cpu_percent != null ? `${formatNumber(c.cpu_percent, { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%` : "–"}</td>
          <td className={num}>{formatBytes(c.mem_bytes)}</td>
        </tr>
      ))}
    </TableCard>
  );
}

function ServicesCard({ services }: { services: NonNullable<AgentInfo["services"]> }) {
  // Najpierw usługi z problemem, potem w trakcie zmiany stanu, na końcu działające
  const rank = (s: (typeof services.items)[number]) => (serviceProblem(s) ? 0 : s.active === "active" ? 2 : 1);
  const items = [...services.items].sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name));
  if (!items.length) {
    return (
      <Card className="p-4">
        <h2 className="text-sm font-medium">{t("srv.services.title")}</h2>
        <p className="mt-1 text-sm text-text-2">{t("srv.services.summary", { running: services.running, failed: services.failed })}</p>
        <p className="mt-1 text-xs text-text-2">{t("srv.services.note")}</p>
      </Card>
    );
  }
  return (
    <TableCard
      title={t("srv.services.title")}
      note={`${t("srv.services.summary", { running: services.running, failed: services.failed })} ${t("srv.services.note")}`}
      minWidth="min-w-[28rem]"
      columns={[
        { label: t("srv.services.name") },
        { label: t("srv.state") },
        { label: t("srv.services.sub") },
        { label: t("srv.services.mem"), right: true },
        { label: t("srv.services.uptime"), right: true },
      ]}
    >
      {items.map((s) => (
        <tr key={s.name} className="border-t border-border">
          <td className={`${cell} font-medium`}>{s.name.replace(/\.service$/, "")}</td>
          <td className={cell}>
            <StateBadge ok={!serviceProblem(s)}>{s.active}</StateBadge>
          </td>
          <td className={`${cell} text-text-2`}>{s.sub ?? "–"}</td>
          <td className={num}>{s.mem_bytes != null ? formatBytes(s.mem_bytes) : "–"}</td>
          <td className={num}>{s.uptime_s != null ? formatUptime(s.uptime_s) : "–"}</td>
        </tr>
      ))}
    </TableCard>
  );
}

function NetworkCard({ net }: { net: NonNullable<AgentInfo["net"]> }) {
  const sorted = [...net].sort((a, b) => a.iface.localeCompare(b.iface));
  return (
    <TableCard
      title={t("srv.net.title", { n: net.length })}
      minWidth="min-w-[20rem]"
      columns={[{ label: t("srv.net.iface") }, { label: t("port.in"), right: true }, { label: t("port.out"), right: true }]}
    >
      {sorted.map((n) => (
        <tr key={n.iface} className="border-t border-border">
          <td className={`${cell} font-medium`}>{n.iface}</td>
          <td className={num}>{formatBps(n.rx_bps)}</td>
          <td className={num}>{formatBps(n.tx_bps)}</td>
        </tr>
      ))}
    </TableCard>
  );
}

function TempsCard({ temps }: { temps: AgentInfo["temps"] }) {
  const sorted = [...temps].sort((a, b) => b.celsius - a.celsius);
  return (
    <TableCard title={t("srv.temps.title", { n: temps.length })} minWidth="min-w-[20rem]" columns={[{ label: t("srv.temps.sensor") }, { label: t("server.temp"), right: true }]}>
      {sorted.map((x) => (
        <tr key={x.sensor} className="border-t border-border">
          <td className={`${cell} text-text-2`}>{x.sensor}</td>
          <td className={`${num} ${x.celsius >= 85 ? "font-medium text-danger" : ""}`}>{Math.round(x.celsius)}°C</td>
        </tr>
      ))}
    </TableCard>
  );
}

/** Wszystko o serwerze Linux w jednym widoku: system, systemy plików, dyski z SMART, kontenery, usługi, sieć, temperatury. */
export function ServerPage() {
  const id = Number(useParams().deviceId);
  const device = useDevice(id);
  const server = useServerStatus(id);

  if (device.isError) {
    const missing = device.error instanceof ApiError && device.error.status === 404;
    return (
      <>
        <BackLink to="/" label={t("nav.dashboard")} />
        <ErrorNote>{t(missing ? "device.missing" : "device.error")}</ErrorNote>
      </>
    );
  }
  const d = device.data;
  if (!d || server.isLoading) return <p role="status" className="py-10 text-center text-sm text-text-2">{t("app.loading")}</p>;

  const data = server.data;
  const agent = data?.agent;
  return (
    <>
      <BackLink to={`/devices/${id}`} label={d.name} />
      <PageHeader title={t("srv.title", { name: d.name })} />
      {!data ? (
        <Card className="p-6">
          <p className="text-sm text-text-2">{t(d.kind === "server" ? "srv.noData" : "srv.notServer")}</p>
        </Card>
      ) : (
        <div className="flex flex-col gap-3">
          {agent?.outdated && <OutdatedNote agent={agent} />}
          <SystemCard data={data} />
          <FilesystemsCard data={data} />
          {agent && <DrivesCard agent={agent} />}
          {agent?.containers && agent.containers.length > 0 && <ContainersCard containers={agent.containers} />}
          {agent?.services && <ServicesCard services={agent.services} />}
          <div className="grid gap-3 lg:grid-cols-2">
            {agent?.net && agent.net.length > 0 && <NetworkCard net={agent.net} />}
            {agent && agent.temps.length > 0 && <TempsCard temps={agent.temps} />}
          </div>
          {!agent && d.driver !== "agent" && <p className="text-xs text-text-2">{t("srv.snmpOnly")}</p>}
        </div>
      )}
    </>
  );
}
