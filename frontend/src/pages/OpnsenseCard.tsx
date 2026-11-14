/** Dane z API OPNsense na stronie urządzenia (od 0.81.0): wersja, bramy, interfejsy, usługi, urządzenia z DHCP i ARP. */
import { useState } from "react";
import { Link } from "react-router";
import { Card, ErrorNote } from "../components/ui";
import { t } from "../i18n";
import { relativeTime } from "../lib/format";
import { formatNumber } from "../lib/intl";
import { useOpnsenseDevice, type OpnsenseGateway } from "../lib/opnsense";

const TH = "px-4 py-2 font-medium";
const TH_NUM = "px-4 py-2 text-right font-medium";
const TD_NUM = "px-4 py-2 text-right tabular-nums";
const HOSTS_SHOWN = 25;

const ms = (v: number | null) => (v == null ? "–" : `${formatNumber(v, { maximumFractionDigits: 1 })} ms`);
const pct = (v: number | null) => (v == null ? "–" : `${formatNumber(v, { maximumFractionDigits: 1 })} %`);

function GatewayState({ g }: { g: OpnsenseGateway }) {
  if (g.up == null) return <span className="text-xs text-muted">{t("opn.gw.noMonitor")}</span>;
  return (
    <span className={`rounded-md px-2 py-0.5 text-xs ${g.up ? "bg-success-soft text-success" : "bg-danger-soft text-danger"}`}>
      {t(g.up ? "opn.gw.up" : "opn.gw.down")}
    </span>
  );
}

export function OpnsenseCard({ deviceId }: { deviceId: number }) {
  const { data } = useOpnsenseDevice(deviceId);
  const [allHosts, setAllHosts] = useState(false);
  if (!data?.configured) return null;

  const stopped = data.services.filter((s) => !s.running);
  const hosts = allHosts ? data.hosts : data.hosts.slice(0, HOSTS_SHOWN);
  const dhcpCount = data.hosts.filter((h) => h.source === "dhcp").length;

  return (
    <div className="flex flex-col gap-3">
      <Card className="p-4">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="mr-auto text-sm font-medium">{t("opn.card.title")}</h2>
          {data.version && <span className="text-sm text-text-2">OPNsense {data.version}</span>}
          {data.update_available && data.latest_version ? (
            <span className="rounded-md bg-warning-soft px-2 py-0.5 text-xs text-warning">{t("opn.update", { version: data.latest_version })}</span>
          ) : (
            data.version && <span className="rounded-md bg-success-soft px-2 py-0.5 text-xs text-success">{t("opn.upToDate")}</span>
          )}
        </div>
        <p className="mt-1 text-xs text-text-2">
          {t("opn.card.read", { when: relativeTime(data.last_ok_at) ?? t("dash.never") })} ·{" "}
          <Link to="/settings/opnsense" className="text-accent-text hover:underline">
            {t("opn.card.settings")}
          </Link>
        </p>
        {data.status === "down" && data.last_error && (
          <div className="mt-3">
            <ErrorNote>{data.last_error}</ErrorNote>
          </div>
        )}
        {data.stale && data.status !== "down" && <p className="mt-3 rounded-lg bg-warning-soft px-3 py-2 text-sm text-warning">{t("opn.card.stale")}</p>}
      </Card>

      <div className="grid gap-3 xl:grid-cols-2">
        {data.gateways.length > 0 && (
          <Card className="overflow-x-auto">
            <h2 className="px-4 pt-4 text-sm font-medium">{t("opn.gw.title")}</h2>
            <table className="mt-2 w-full min-w-[30rem] text-left text-sm">
              <thead className="text-xs text-text-2">
                <tr>
                  <th scope="col" className={TH}>{t("opn.gw.name")}</th>
                  <th scope="col" className={TH}>{t("device.ports.status")}</th>
                  <th scope="col" className={TH_NUM}>{t("opn.gw.delay")}</th>
                  <th scope="col" className={TH_NUM}>{t("opn.gw.loss")}</th>
                  <th scope="col" className={TH_NUM}>{t("opn.gw.jitter")}</th>
                </tr>
              </thead>
              <tbody>
                {data.gateways.map((g) => (
                  <tr key={g.name} className="border-t border-border">
                    <td className="px-4 py-2">
                      <span className="font-medium">{g.name}</span>
                      {g.default && <span className="ml-1.5 rounded bg-accent-soft px-1.5 py-0.5 text-xs text-accent-text">{t("opn.gw.active")}</span>}
                      <span className="block text-xs text-muted">{[g.interface, g.address, g.monitor && t("opn.gw.monitor", { ip: g.monitor })].filter(Boolean).join(" · ")}</span>
                    </td>
                    <td className="px-4 py-2">
                      <GatewayState g={g} />
                    </td>
                    <td className={TD_NUM}>{ms(g.delay_ms)}</td>
                    <td className={`${TD_NUM} ${(g.loss_percent ?? 0) >= 20 ? "text-danger" : ""}`}>{pct(g.loss_percent)}</td>
                    <td className={TD_NUM}>{ms(g.jitter_ms)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {data.gateways.every((g) => g.up == null) && <p className="px-4 pb-4 text-xs text-text-2">{t("opn.probe.noMonitor")}</p>}
          </Card>
        )}

        {data.interfaces.length > 0 && (
          <Card className="overflow-x-auto">
            <h2 className="px-4 pt-4 text-sm font-medium">{t("opn.if.title")}</h2>
            <table className="mt-2 w-full min-w-[26rem] text-left text-sm">
              <thead className="text-xs text-text-2">
                <tr>
                  <th scope="col" className={TH}>{t("opn.if.name")}</th>
                  <th scope="col" className={TH}>{t("opn.if.device")}</th>
                  <th scope="col" className={TH}>{t("opn.if.addr")}</th>
                  <th scope="col" className={TH}>{t("opn.if.type")}</th>
                </tr>
              </thead>
              <tbody>
                {data.interfaces.map((i) => (
                  <tr key={i.device} className="border-t border-border">
                    <td className="px-4 py-2 font-medium">
                      {i.description ?? i.identifier}
                      {i.default_route && <span className="ml-1.5 text-xs text-muted">{t("opn.if.default")}</span>}
                    </td>
                    <td className="px-4 py-2 text-text-2">{i.device}</td>
                    <td className="px-4 py-2 tabular-nums text-text-2">{i.addr4 ?? "–"}</td>
                    <td className="px-4 py-2 text-text-2">{i.link_type ?? "–"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        )}
      </div>

      {data.services.length > 0 && (
        <Card className="p-4">
          <h2 className="mb-2 text-sm font-medium">
            {t("opn.svc.title", { running: data.services.length - stopped.length, total: data.services.length })}
          </h2>
          <ul className="flex flex-wrap gap-1.5">
            {[...stopped, ...data.services.filter((s) => s.running)].map((s) => (
              <li
                key={s.name}
                title={s.name}
                className={`rounded-md px-2 py-0.5 text-xs ${s.running ? "bg-surface-2 text-text-2" : "bg-danger-soft text-danger"}`}
              >
                {s.description}
                {!s.running && ` – ${t("opn.svc.stopped")}`}
              </li>
            ))}
          </ul>
        </Card>
      )}

      {data.hosts.length > 0 && (
        <Card className="overflow-x-auto">
          <h2 className="px-4 pt-4 text-sm font-medium">
            {t("opn.hosts.title", { n: data.hosts.length })}
            <span className="ml-1.5 text-xs font-normal text-text-2">
              {data.dhcp ? t("opn.hosts.dhcp", { n: dhcpCount, server: data.dhcp }) : t("opn.hosts.arpOnly")}
            </span>
          </h2>
          <table className="mt-2 w-full min-w-[40rem] text-left text-sm">
            <thead className="text-xs text-text-2">
              <tr>
                <th scope="col" className={TH}>{t("opn.hosts.ip")}</th>
                <th scope="col" className={TH}>{t("opn.hosts.name")}</th>
                <th scope="col" className={TH}>MAC</th>
                <th scope="col" className={TH}>{t("opn.hosts.vendor")}</th>
                <th scope="col" className={TH}>{t("opn.hosts.iface")}</th>
                <th scope="col" className={TH}>{t("opn.hosts.source")}</th>
              </tr>
            </thead>
            <tbody>
              {hosts.map((h) => (
                <tr key={h.mac} className="border-t border-border">
                  <td className="px-4 py-2 tabular-nums">{h.ip ?? "–"}</td>
                  <td className="max-w-48 truncate px-4 py-2 font-medium">{h.hostname ?? "–"}</td>
                  <td className="px-4 py-2 font-mono text-xs text-text-2">{h.mac}</td>
                  <td className="max-w-48 truncate px-4 py-2 text-text-2">{h.manufacturer ?? "–"}</td>
                  <td className="px-4 py-2 text-text-2">{h.interface ?? "–"}</td>
                  <td className="px-4 py-2 text-text-2">{h.source === "dhcp" ? "DHCP" : "ARP"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {data.hosts.length > HOSTS_SHOWN && (
            <button type="button" className="mx-4 mb-4 mt-2 text-sm text-accent-text hover:underline" onClick={() => setAllHosts((v) => !v)}>
              {allHosts ? t("opn.hosts.less") : t("opn.hosts.all", { n: data.hosts.length })}
            </button>
          )}
        </Card>
      )}
    </div>
  );
}
