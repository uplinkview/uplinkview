import { IconAccessPoint, IconDeviceDesktop, IconNetwork, IconRouter, IconServer2 } from "@tabler/icons-react";
import { Link } from "react-router";
import { t, type TextKey } from "../../i18n";
import type { Device } from "../../lib/api";
import { useDevicesAvailability } from "../../lib/details";
import { useDetailLinks } from "../../lib/publicMode";
import { formatAvailability } from "../../lib/wan";
import { formatUptime, relativeTime, vendorModel } from "../../lib/format";
import type { DeviceKind, DevicesDisplay } from "../../lib/layout";
import { useCollection } from "../../lib/panels";
import { useDevices } from "../../lib/queries";
import { Card, EmptyHint } from "../ui";
import { ServerDetails } from "./ServerDetails";

export const KIND_ICON = { gateway: IconRouter, switch: IconNetwork, ap: IconAccessPoint, server: IconServer2 } as const;
export const KIND_LABEL: Record<string, TextKey> = {
  gateway: "dash.kind.gateway",
  switch: "dash.kind.switch",
  ap: "dash.kind.ap",
  server: "dash.kind.server",
  other: "dash.kind.other",
};
export const STATUS_STYLE: Record<string, string> = {
  up: "bg-success-soft text-success",
  down: "bg-danger-soft text-danger",
  unknown: "bg-surface-2 text-text-2",
  stale: "bg-warning-soft text-warning",
};
export const STATUS_LABEL: Record<string, TextKey> = {
  up: "dash.status.up",
  down: "dash.status.down",
  unknown: "dash.status.unknown",
  stale: "dash.status.stale",
};

/** Stan do pokazania: „stale” = kolektor dawno nie wydał werdyktu – brak danych, a nie awaria (od 0.59.0). */
export function deviceState(d: Pick<Device, "status" | "stale">): string {
  if (d.stale) return "stale";
  return d.status in STATUS_LABEL && d.status !== "stale" ? d.status : "unknown";
}

/** Podpowiedź do plakietki nieaktualnego urządzenia: kiedy był ostatni odczyt i co wtedy pokazał. */
export function staleHint(d: Pick<Device, "stale" | "last_polled_at" | "last_status">): string | undefined {
  if (!d.stale) return undefined;
  const last = d.last_status && d.last_status in STATUS_LABEL ? t("dash.status.staleLast", { status: t(STATUS_LABEL[d.last_status]) }) : "";
  return t("dash.status.staleHint", { time: relativeTime(d.last_polled_at) ?? t("dash.never"), last });
}

/** Plakietka „prace serwisowe”, gdy trwa okno serwisowe obejmujące urządzenie (od 0.60.0). */
export function MaintenanceBadge({ device }: { device: Pick<Device, "maintenance"> }) {
  if (!device.maintenance) return null;
  return (
    <span className="shrink-0 rounded-md bg-warning-soft px-2 py-0.5 text-xs text-warning" title={t("dash.maintenance.hint")}>
      {t("dash.maintenance")}
    </span>
  );
}

export function deviceIcon(kind: string) {
  return KIND_ICON[kind as keyof typeof KIND_ICON] ?? IconDeviceDesktop;
}

function DeviceCard({ device, availability }: { device: Device; availability: number | null | undefined }) {
  const Icon = deviceIcon(device.kind);
  const status = deviceState(device);
  const polled = relativeTime(device.last_polled_at);
  const linked = useDetailLinks();
  return (
    <Card className="flex flex-col gap-3 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2.5">
          <Icon size={22} aria-hidden="true" className="shrink-0 text-text-2" />
          <div className="min-w-0">
            <h3 className="truncate text-sm font-medium">
              {linked ? (
                <Link to={`/devices/${device.id}`} className="hover:text-accent-text hover:underline">
                  {device.name}
                </Link>
              ) : (
                device.name
              )}
            </h3>
            <p className="truncate text-xs text-text-2">
              {[device.host, t(KIND_LABEL[device.kind] ?? "dash.kind.other")].filter(Boolean).join(" · ")}
            </p>
          </div>
        </div>
        <div className="flex shrink-0 flex-wrap justify-end gap-1">
          <MaintenanceBadge device={device} />
          <span className={`shrink-0 rounded-md px-2 py-0.5 text-xs ${STATUS_STYLE[status]}`} title={staleHint(device)}>
            {t(STATUS_LABEL[status])}
          </span>
        </div>
      </div>
      <dl className="flex justify-between gap-3 text-xs text-text-2">
        <div className="min-w-0">
          <dt className="sr-only">Model</dt>
          <dd className="truncate">{vendorModel(device.vendor, device.model) || "-"}</dd>
        </div>
        <div className="shrink-0 text-right">
          <dt className="sr-only">{t("dash.polled")}</dt>
          <dd className={device.stale ? "text-warning" : undefined}>{polled ?? t("dash.never")}</dd>
        </div>
      </dl>
      {availability != null && (
        <p className="text-xs text-text-2">
          {t("avail.card", { value: formatAvailability(availability) })}
        </p>
      )}
      {device.kind === "server" && device.status !== "down" && <ServerDetails deviceId={device.id} />}
      {device.status === "down" && device.last_error && (
        <p className="truncate text-xs text-danger" title={device.last_error}>
          {device.last_error}
        </p>
      )}
    </Card>
  );
}

const STATUS_DOT: Record<string, string> = { up: "bg-success", down: "bg-danger", unknown: "bg-border-strong", stale: "bg-warning" };

/** Procent z paskiem (CPU, RAM w tabeli urządzeń). */
function PercentBar({ value }: { value: number | null | undefined }) {
  if (value == null) return <span className="text-muted">–</span>;
  const v = Math.max(0, Math.min(100, value));
  return (
    <span className="flex items-center gap-2">
      <span className="w-10 text-right">{Math.round(v)} %</span>
      <span className="hidden h-1.5 w-10 overflow-hidden rounded-full bg-surface-2 @[560px]:block @[720px]:w-16" aria-hidden="true">
        <span className={`block h-full rounded-full ${v >= 90 ? "bg-danger" : v >= 75 ? "bg-warning" : "bg-accent"}`} style={{ width: `${v}%` }} />
      </span>
    </span>
  );
}

// Kolumny tabeli zależne od szerokości karty (zapytania kontenera): adres od 480 px, czas pracy od 640 px
const HOST_COL = "hidden @[480px]:table-cell";
const UPTIME_COL = "hidden @[640px]:table-cell";
// Nazwa bierze resztę szerokości i skraca się wielokropkiem (max-w-0 + w-full: komórka nie rozpycha tabeli)
const NAME_CELL = "w-full max-w-0 py-3 pl-5 pr-3";

/** Tabela urządzeń (od 0.42.0): stan, adres, CPU i RAM z ostatniego odczytu, czas pracy. */
function DevicesTable({ list }: { list: Device[] }) {
  const linked = useDetailLinks();
  const { data: rows } = useCollection({ kind: "devices" });
  const byId = new Map((rows ?? []).map((r) => [r.key, r.values]));
  const th = "whitespace-nowrap px-3 py-2.5 text-left text-xs font-medium text-muted";
  return (
    <Card className="flex flex-col pt-5">
      <h2 id="devices-heading" className="flex items-baseline gap-2 px-5 pb-2 text-base font-semibold">
        {t("dash.devicesTitle")} <span className="text-sm font-medium text-muted">{list.length}</span>
      </h2>
      {/* Od 0.66.0 bez przewijania w bok: nazwa się skraca, a w wąskiej karcie znikają kolejno paski, czas pracy i adres */}
      <div className="@container">
        <table aria-labelledby="devices-heading" className="w-full border-collapse text-sm">
          <thead>
            <tr className="border-b border-border">
              <th className={`${th} pl-5`}>{t("devTable.name")}</th>
              <th className={`${th} ${HOST_COL}`}>{t("devTable.host")}</th>
              <th className={th}>CPU</th>
              <th className={th}>RAM</th>
              <th className={`${th} ${UPTIME_COL}`}>{t("devTable.uptime")}</th>
              <th className={`${th} pr-5`}>{t("devTable.state")}</th>
            </tr>
          </thead>
          <tbody>
            {[...list.filter((d) => d.enabled), ...list.filter((d) => !d.enabled)].map((d) => {
              const v = byId.get(String(d.id));
              const status = deviceState(d);
              if (!d.enabled) {
                // Wyłączone (bez odpytywania) – na końcu, wyszarzone; pasek stanu ich nie liczy
                return (
                  <tr key={d.id} className="border-b border-border/60 text-muted last:border-b-0">
                    <td className={NAME_CELL}>
                      <p className="truncate font-medium" title={d.name}>
                        {d.name}
                      </p>
                      <p className="truncate text-xs">{t(KIND_LABEL[d.kind] ?? "dash.kind.other")}</p>
                    </td>
                    <td className={`whitespace-nowrap px-3 py-3 ${HOST_COL}`}>{d.host || "–"}</td>
                    <td className="px-3 py-3">–</td>
                    <td className="px-3 py-3">–</td>
                    <td className={`px-3 py-3 ${UPTIME_COL}`}>–</td>
                    <td className="whitespace-nowrap py-3 pl-3 pr-5">
                      <span className="inline-flex items-center gap-1.5 text-[13px]">
                        <span className="size-2 rounded-full border border-border-strong" aria-hidden="true" />
                        {t("devTable.disabled")}
                      </span>
                    </td>
                  </tr>
                );
              }
              return (
                <tr key={d.id} className="border-b border-border/60 last:border-b-0">
                  <td className={NAME_CELL}>
                    <p className="truncate font-medium" title={d.name}>
                      {linked ? (
                        <Link to={`/devices/${d.id}`} className="hover:underline">
                          {d.name}
                        </Link>
                      ) : (
                        d.name
                      )}
                    </p>
                    <p className="truncate text-xs text-muted">{[t(KIND_LABEL[d.kind] ?? "dash.kind.other"), d.model].filter(Boolean).join(" · ")}</p>
                  </td>
                  <td className={`whitespace-nowrap px-3 py-3 text-text-2 ${HOST_COL}`}>{d.host || "–"}</td>
                  <td className="px-3 py-3">
                    <PercentBar value={v?.cpu_percent} />
                  </td>
                  <td className="px-3 py-3">
                    <PercentBar value={v?.mem_used_percent} />
                  </td>
                  <td className={`whitespace-nowrap px-3 py-3 text-text-2 ${UPTIME_COL}`}>{d.status === "up" && d.uptime_s != null ? formatUptime(d.uptime_s) : "–"}</td>
                  <td className="whitespace-nowrap py-3 pl-3 pr-5">
                    <span className="inline-flex items-center gap-1.5 text-[13px] text-text-2" title={status === "down" ? (d.last_error ?? undefined) : staleHint(d)}>
                      <span className={`size-2 rounded-full ${STATUS_DOT[status]}`} aria-hidden="true" />
                      {t(STATUS_LABEL[status])}
                    </span>
                    {d.maintenance && (
                      <span className="ml-2 text-xs text-warning" title={t("dash.maintenance.hint")}>
                        {t("dash.maintenance")}
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

/** Urządzenia (opcjonalnie tylko wybrane typy): karty albo tabela. */
export function DevicesWidget({ kinds, display = "cards" }: { kinds?: DeviceKind[] | null; display?: DevicesDisplay }) {
  const { data } = useDevices();
  const availability = useDevicesAvailability(30, display === "cards");
  const list = (data ?? []).filter((d) => !kinds?.length || kinds.includes((d.kind as DeviceKind) ?? "other"));
  if (!data) return null;
  if (list.length === 0) {
    // Pusty widget z podpowiedzią (od 0.66.0) zamiast znikania: brak urządzeń albo filtr rodzajów nic nie zostawia
    const filtered = data.length > 0;
    return (
      <Card className="flex flex-col p-5">
        <h2 className="text-base font-semibold">{t("dash.devicesTitle")}</h2>
        {filtered ? (
          <EmptyHint text={t("devEmpty.kinds")} hint={t("devEmpty.kinds.hint")} />
        ) : (
          <EmptyHint text={t("devEmpty.none")} hint={t("devEmpty.none.hint")} to="/settings/devices" action={t("devEmpty.add")} />
        )}
      </Card>
    );
  }
  if (display === "table") return <DevicesTable list={list} />;
  return (
    <section aria-labelledby="devices-heading">
      <h2 id="devices-heading" className="mb-3 text-sm font-medium text-text-2">
        {t("dash.devicesTitle")}
      </h2>
      <div className="grid grid-cols-[repeat(auto-fill,minmax(250px,1fr))] gap-3">
        {list.map((d) => (
          <DeviceCard key={d.id} device={d} availability={availability.data?.[d.id]} />
        ))}
      </div>
    </section>
  );
}
