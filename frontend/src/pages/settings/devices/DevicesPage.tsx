import { IconAccessPoint, IconDeviceDesktop, IconNetwork, IconPencil, IconPlugConnected, IconPlus, IconRadar, IconRouter, IconServer2, IconTrash, IconX } from "@tabler/icons-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Dialog } from "../../../components/Dialog";
import { Button, Card, ErrorNote, PageHeader, Toggle } from "../../../components/ui";
import { t, type TextKey } from "../../../i18n";
import { ApiError, del, patch, post, type Device, type ProbeResult } from "../../../lib/api";
import { relativeTime } from "../../../lib/format";
import { useDevices } from "../../../lib/queries";
import { DefaultCommunityBadge } from "../../../components/SnmpWarning";
import { STATUS_LABEL, STATUS_STYLE, deviceState, staleHint } from "../../../components/widgets/DevicesWidget";
import { DeviceForm } from "./DeviceForm";
import { DiscoveryPanel } from "./DiscoveryPanel";
import { ProbeSummary } from "./ProbeSummary";

const KIND_ICON = { gateway: IconRouter, switch: IconNetwork, ap: IconAccessPoint, server: IconServer2 } as const;
const KIND_LABEL: Record<string, TextKey> = {
  gateway: "dash.kind.gateway",
  switch: "dash.kind.switch",
  ap: "dash.kind.ap",
  server: "dash.kind.server",
  other: "dash.kind.other",
};

type ProbeState = { status: "loading" } | { status: "ok"; result: ProbeResult } | { status: "error"; message: string };

function snmpLabel(d: Device): string {
  return `SNMP ${d.snmp_version} · ${d.driver === "auto" ? (d.detected_driver ?? "auto") : d.driver}`;
}

function DeviceRow({
  device,
  probe,
  onTest,
  onDismissProbe,
  onEdit,
  onDelete,
}: {
  device: Device;
  probe: ProbeState | undefined;
  onTest: () => void;
  onDismissProbe: () => void;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const qc = useQueryClient();
  const toggle = useMutation({
    mutationFn: (enabled: boolean) => patch<Device>(`/api/devices/${device.id}`, { enabled }),
    onSuccess: () =>
      Promise.all([qc.invalidateQueries({ queryKey: ["devices"] }), qc.invalidateQueries({ queryKey: ["dashboard"] })]),
  });
  const Icon = KIND_ICON[device.kind as keyof typeof KIND_ICON] ?? IconDeviceDesktop;
  const status = deviceState(device);
  const polled = staleHint(device) ?? relativeTime(device.last_polled_at);
  // Serwer z agentem i urządzenie UniFi z oficjalnego API nie mają ustawień SNMP: test i edycja nie mają sensu
  const agent = device.driver === "agent" || device.driver === "unifi_api";
  const iconButton = "flex size-9 items-center justify-center rounded-lg text-text-2 hover:bg-surface-2 hover:text-text disabled:opacity-50";

  return (
    <li className={`flex flex-col gap-2 px-4 py-3 ${device.enabled ? "" : "opacity-70"}`}>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <div className="flex min-w-0 flex-1 basis-56 items-center gap-3">
          <Icon size={22} aria-hidden="true" className="shrink-0 text-text-2" />
          <div className="min-w-0">
            <p className="truncate text-sm font-medium">{device.name}</p>
            <p className="truncate text-xs text-text-2">
              {agent ? device.host : `${device.host}:${device.port}`} · {t(KIND_LABEL[device.kind] ?? "dash.kind.other")} ·{" "}
              {device.driver === "unifi_api" ? t("devices.unifiApiRow") : agent ? t("devices.agentRow") : snmpLabel(device)}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <DefaultCommunityBadge device={device} />
          {!device.enabled && <span className="rounded-md bg-surface-2 px-2 py-0.5 text-xs text-text-2">{t("devices.disabled")}</span>}
          {device.enabled && (
            <span className={`rounded-md px-2 py-0.5 text-xs ${STATUS_STYLE[status]}`} title={polled ?? undefined}>
              {t(STATUS_LABEL[status])}
            </span>
          )}
        </div>
        <div className="flex items-center gap-1">
          <Toggle
            checked={device.enabled}
            disabled={toggle.isPending}
            label={`${t("devices.enabled")}: ${device.name}`}
            onChange={(enabled) => toggle.mutate(enabled)}
          />
          {!agent && (
            <>
              <button
                type="button"
                className={iconButton}
                aria-label={`${t("devices.test")} ${device.name}`}
                title={t("devices.test")}
                disabled={probe?.status === "loading"}
                onClick={onTest}
              >
                <IconPlugConnected size={18} aria-hidden="true" />
              </button>
              <button type="button" className={iconButton} aria-label={`${t("common.edit")} ${device.name}`} title={t("common.edit")} onClick={onEdit}>
                <IconPencil size={18} aria-hidden="true" />
              </button>
            </>
          )}
          <button type="button" className={iconButton} aria-label={`${t("common.delete")} ${device.name}`} title={t("common.delete")} onClick={onDelete}>
            <IconTrash size={18} aria-hidden="true" />
          </button>
        </div>
      </div>

      {toggle.isError && <ErrorNote>{t("devices.toggleError")}</ErrorNote>}
      {probe?.status === "loading" && (
        <p role="status" className="text-xs text-text-2">
          {t("devices.testing")}
        </p>
      )}
      {probe && probe.status !== "loading" && (
        <div className="flex items-start gap-2" aria-label={t("devices.testResult")}>
          <div className="min-w-0 flex-1">
            {probe.status === "ok" ? <ProbeSummary result={probe.result} /> : <ErrorNote>{probe.message}</ErrorNote>}
          </div>
          <button type="button" className={iconButton} aria-label={t("devices.dismiss")} title={t("devices.dismiss")} onClick={onDismissProbe}>
            <IconX size={16} aria-hidden="true" />
          </button>
        </div>
      )}
    </li>
  );
}

/** Ustawienia → Urządzenia: lista, dodawanie, edycja, test SNMP, włączanie i usuwanie. */
export function DevicesPage() {
  const qc = useQueryClient();
  const { data, isLoading, isError } = useDevices();
  const [form, setForm] = useState<{ device?: Device } | null>(null);
  const [toDelete, setToDelete] = useState<Device | null>(null);
  const [probes, setProbes] = useState<Record<number, ProbeState>>({});
  const [discover, setDiscover] = useState(false);

  const remove = useMutation({
    mutationFn: (id: number) => del(`/api/devices/${id}`),
    onSuccess: async () => {
      setToDelete(null);
      await Promise.all([qc.invalidateQueries({ queryKey: ["devices"] }), qc.invalidateQueries({ queryKey: ["dashboard"] })]);
    },
  });

  async function test(device: Device) {
    setProbes((p) => ({ ...p, [device.id]: { status: "loading" } }));
    try {
      const result = await post<ProbeResult>(`/api/devices/${device.id}/probe`);
      setProbes((p) => ({ ...p, [device.id]: { status: "ok", result } }));
    } catch (err) {
      const message = err instanceof ApiError ? err.message : t("auth.error.generic");
      setProbes((p) => ({ ...p, [device.id]: { status: "error", message } }));
    }
  }

  const devices = data ?? [];
  const empty = !isLoading && !isError && devices.length === 0;

  return (
    <>
      <PageHeader title={t("settings.devices.title")}>
        <Button aria-pressed={discover} onClick={() => setDiscover((v) => !v)}>
          <IconRadar size={18} aria-hidden="true" />
          {t("discovery.open")}
        </Button>
        <Button variant="primary" onClick={() => setForm({})}>
          <IconPlus size={18} aria-hidden="true" />
          {t("devices.add")}
        </Button>
      </PageHeader>

      {isError && !data && <ErrorNote>{t("devices.loadError")}</ErrorNote>}

      {(discover || empty) && (
        <div className="mb-4">
          <DiscoveryPanel />
        </div>
      )}

      {empty && (
        <Card className="p-6">
          <h2 className="text-base font-medium">{t("devices.empty.title")}</h2>
          <p className="mt-1 max-w-prose text-sm text-text-2">{t("devices.empty.body")}</p>
        </Card>
      )}

      {devices.length > 0 && (
        <Card>
          <ul className="divide-y divide-border">
            {devices.map((d) => (
              <DeviceRow
                key={d.id}
                device={d}
                probe={probes[d.id]}
                onTest={() => void test(d)}
                onDismissProbe={() =>
                  setProbes((p) => {
                    const { [d.id]: _removed, ...rest } = p;
                    return rest;
                  })
                }
                onEdit={() => setForm({ device: d })}
                onDelete={() => {
                  remove.reset();
                  setToDelete(d);
                }}
              />
            ))}
          </ul>
        </Card>
      )}

      {form && <DeviceForm device={form.device} onClose={() => setForm(null)} />}

      {toDelete && (
        <Dialog
          size="sm"
          title={t("devices.delete.title")}
          onClose={() => setToDelete(null)}
          footer={
            <>
              <Button data-autofocus onClick={() => setToDelete(null)}>
                {t("common.cancel")}
              </Button>
              <Button variant="danger" disabled={remove.isPending} onClick={() => remove.mutate(toDelete.id)}>
                {remove.isPending ? t("devices.delete.busy") : t("common.delete")}
              </Button>
            </>
          }
        >
          <p className="text-sm">{t("devices.delete.body", { name: toDelete.name })}</p>
          {remove.isError && (
            <div className="mt-3">
              <ErrorNote>{remove.error instanceof ApiError ? remove.error.message : t("auth.error.generic")}</ErrorNote>
            </div>
          )}
        </Dialog>
      )}
    </>
  );
}
