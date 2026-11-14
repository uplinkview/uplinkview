import { IconPencil, IconPlugConnected, IconPlus, IconTrash } from "@tabler/icons-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";
import { Dialog } from "../../components/Dialog";
import { Button, Card, ErrorNote, Field, PageHeader, Select, SuccessNote, Toggle } from "../../components/ui";
import { t, type TextKey } from "../../i18n";
import { ApiError, del, patch, post } from "../../lib/api";
import { relativeTime } from "../../lib/format";
import { OPNSENSE_KEYS_KEY, isOpnsense, useOpnsenseKeys, type OpnsenseApiKey, type OpnsenseProbe } from "../../lib/opnsense";
import { useDevices } from "../../lib/queries";

const STATUS_STYLE: Record<string, string> = {
  up: "bg-success-soft text-success",
  down: "bg-danger-soft text-danger",
  unknown: "bg-surface-2 text-text-2",
};
const STATUS_LABEL: Record<string, TextKey> = { up: "dash.status.up", down: "dash.status.down", unknown: "dash.status.unknown" };
const KEY_RE = /^\S{8,255}$/;
const errorMessage = (err: unknown) => (err instanceof ApiError ? err.message : t("auth.error.generic"));
const iconButton = "flex size-9 items-center justify-center rounded-lg text-text-2 hover:bg-surface-2 hover:text-text disabled:opacity-50";

interface FormValues {
  device_id: string;
  port: string;
  api_key: string;
  api_secret: string;
  verify_tls: boolean;
}

function ProbeOk({ probe }: { probe: OpnsenseProbe }) {
  return (
    <SuccessNote>
      {t("opn.probe.ok", { version: probe.version ?? "?", gateways: probe.gateways, monitored: probe.monitored, services: probe.services, hosts: probe.hosts })}
      {probe.gateways > 0 && probe.monitored === 0 && <span className="mt-1 block">{t("opn.probe.noMonitor")}</span>}
    </SuccessNote>
  );
}

function KeyForm({ item, taken, onClose }: { item?: OpnsenseApiKey; taken: Set<number>; onClose: () => void }) {
  const qc = useQueryClient();
  const editing = item !== undefined;
  const devices = useDevices().data ?? [];
  // Najpierw urządzenia rozpoznane jako OPNsense; inne też można wybrać (np. driver ustawiony ręcznie na ogólny)
  const choices = devices
    .filter((d) => !taken.has(d.id) || d.id === item?.device_id)
    .sort((a, b) => Number(isOpnsense(b)) - Number(isOpnsense(a)) || a.name.localeCompare(b.name));
  const [values, setValues] = useState<FormValues>({
    device_id: item ? String(item.device_id) : "",
    port: String(item?.port ?? 443),
    api_key: "",
    api_secret: "",
    verify_tls: item?.verify_tls ?? false,
  });
  const [errors, setErrors] = useState<Partial<Record<keyof FormValues, string>>>({});
  const set = <K extends keyof FormValues>(key: K, value: FormValues[K]) => {
    setValues((v) => ({ ...v, [key]: value }));
    setErrors((e) => ({ ...e, [key]: undefined }));
  };
  // Bez wyboru: pierwsze urządzenie OPNsense (lista urządzeń może przyjść po otwarciu okna)
  const deviceId = values.device_id || String(choices.find(isOpnsense)?.id ?? "");
  const target = () => ({
    device_id: Number(deviceId),
    port: Number(values.port),
    api_key: values.api_key.trim(),
    api_secret: values.api_secret.trim(),
    verify_tls: values.verify_tls,
  });

  function validate(): boolean {
    const found: typeof errors = {};
    const port = Number(values.port);
    if (!editing && !deviceId) found.device_id = t("opn.err.device");
    if (!Number.isInteger(port) || port < 1 || port > 65535) found.port = t("ctrl.err.port");
    for (const k of ["api_key", "api_secret"] as const) {
      const v = values[k].trim();
      if ((!editing || v !== "") && !KEY_RE.test(v)) found[k] = t("opn.err.key");
    }
    setErrors(found);
    return Object.keys(found).length === 0;
  }

  const probe = useMutation({ mutationFn: () => post<OpnsenseProbe>("/api/opnsense/probe", target()) });
  const save = useMutation({
    mutationFn: () => {
      const { device_id, api_key, api_secret, ...rest } = target();
      if (item) {
        return patch<OpnsenseApiKey>(`/api/opnsense/apis/${item.id}`, { ...rest, ...(api_key ? { api_key } : {}), ...(api_secret ? { api_secret } : {}) });
      }
      return post<OpnsenseApiKey>("/api/opnsense/apis", { device_id, api_key, api_secret, ...rest });
    },
    onSuccess: async () => {
      await Promise.all([qc.invalidateQueries({ queryKey: OPNSENSE_KEYS_KEY }), qc.invalidateQueries({ queryKey: ["opnsense", "device"] })]);
      onClose();
    },
  });
  const busy = probe.isPending || save.isPending;

  return (
    <Dialog
      title={editing ? t("ctrl.form.edit", { name: item.device_name }) : t("opn.form.add")}
      onClose={onClose}
      footer={
        <>
          {!editing && (
            <Button className="mr-auto" disabled={busy} onClick={() => validate() && probe.mutate()}>
              {probe.isPending ? t("devices.testing") : t("devform.test")}
            </Button>
          )}
          <Button onClick={onClose}>{t("common.cancel")}</Button>
          <Button variant="primary" disabled={busy} onClick={() => validate() && save.mutate()}>
            {save.isPending ? t("common.saving") : t("common.save")}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <div className="grid gap-4 sm:grid-cols-[1fr_8rem]">
          <Select id="opn-device" label={t("opn.device")} value={deviceId} error={errors.device_id} disabled={editing} onChange={(e) => set("device_id", e.target.value)}>
            {!editing && <option value="">{t("opn.device.choose")}</option>}
            {choices.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name} ({d.host})
              </option>
            ))}
          </Select>
          <Field id="opn-port" label={t("devform.port")} inputMode="numeric" value={values.port} error={errors.port} onChange={(e) => set("port", e.target.value)} />
        </div>
        {!editing && choices.length === 0 && <p className="text-xs text-text-2">{t("opn.device.none")}</p>}
        <Field
          id="opn-key"
          label={t("opn.key")}
          autoComplete="off"
          autoCapitalize="none"
          spellCheck={false}
          value={values.api_key}
          error={errors.api_key}
          hint={editing ? t("opn.key.keep", { hint: item.key_hint }) : t("opn.key.hint")}
          onChange={(e) => set("api_key", e.target.value)}
        />
        <Field
          id="opn-secret"
          label={t("opn.secret")}
          type="password"
          autoComplete="off"
          value={values.api_secret}
          error={errors.api_secret}
          hint={editing ? t("pve.secret.keep") : t("opn.secret.hint")}
          onChange={(e) => set("api_secret", e.target.value)}
        />
        <label htmlFor="opn-tls" className="flex items-start gap-2 text-sm">
          <input id="opn-tls" type="checkbox" checked={values.verify_tls} onChange={(e) => set("verify_tls", e.target.checked)} className="mt-0.5 size-4 accent-accent" />
          <span>
            {t("ctrl.tls")}
            <span className="block text-xs text-muted">{t("opn.tls.hint")}</span>
          </span>
        </label>
        {probe.isSuccess && <ProbeOk probe={probe.data} />}
        {probe.isError && <ErrorNote>{errorMessage(probe.error)}</ErrorNote>}
        {save.isError && <ErrorNote>{errorMessage(save.error)}</ErrorNote>}
      </div>
    </Dialog>
  );
}

function KeyRow({ item, onEdit, onDelete }: { item: OpnsenseApiKey; onEdit: () => void; onDelete: () => void }) {
  const qc = useQueryClient();
  const toggle = useMutation({
    mutationFn: (enabled: boolean) => patch<OpnsenseApiKey>(`/api/opnsense/apis/${item.id}`, { enabled }),
    onSuccess: () => qc.invalidateQueries({ queryKey: OPNSENSE_KEYS_KEY }),
  });
  const test = useMutation({ mutationFn: () => post<OpnsenseProbe>(`/api/opnsense/apis/${item.id}/probe`) });
  const status = item.status in STATUS_STYLE ? item.status : "unknown";
  const details = [
    `${item.host}${item.port !== 443 ? `:${item.port}` : ""}`,
    item.version ? `OPNsense ${item.version}` : null,
    t("opn.keyHint", { hint: item.key_hint }),
  ].filter(Boolean);

  return (
    <li className={`flex flex-col gap-2 px-4 py-3 ${item.enabled ? "" : "opacity-70"}`}>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <div className="min-w-0 flex-1 basis-56">
          <Link to={`/devices/${item.device_id}`} className="truncate text-sm font-medium hover:text-accent-text hover:underline">
            {item.device_name}
          </Link>
          <p className="truncate text-xs text-text-2">{details.join(" · ")}</p>
        </div>
        {item.update_available && item.latest_version && (
          <span className="rounded-md bg-warning-soft px-2 py-0.5 text-xs text-warning">{t("opn.update", { version: item.latest_version })}</span>
        )}
        {item.enabled ? (
          <span className={`rounded-md px-2 py-0.5 text-xs ${STATUS_STYLE[status]}`} title={relativeTime(item.last_polled_at) ?? undefined}>
            {t(STATUS_LABEL[status])}
          </span>
        ) : (
          <span className="rounded-md bg-surface-2 px-2 py-0.5 text-xs text-text-2">{t("devices.disabled")}</span>
        )}
        <div className="flex items-center gap-1">
          <Toggle checked={item.enabled} disabled={toggle.isPending} label={`${t("devices.enabled")}: ${item.device_name}`} onChange={(v) => toggle.mutate(v)} />
          <button type="button" className={iconButton} aria-label={`${t("devices.test")} ${item.device_name}`} title={t("devices.test")} disabled={test.isPending} onClick={() => test.mutate()}>
            <IconPlugConnected size={18} aria-hidden="true" />
          </button>
          <button type="button" className={iconButton} aria-label={`${t("common.edit")} ${item.device_name}`} title={t("common.edit")} onClick={onEdit}>
            <IconPencil size={18} aria-hidden="true" />
          </button>
          <button type="button" className={iconButton} aria-label={`${t("common.delete")} ${item.device_name}`} title={t("common.delete")} onClick={onDelete}>
            <IconTrash size={18} aria-hidden="true" />
          </button>
        </div>
      </div>
      {item.enabled && item.status === "down" && item.last_error && <ErrorNote>{item.last_error}</ErrorNote>}
      {test.isSuccess && <ProbeOk probe={test.data} />}
      {test.isError && <ErrorNote>{errorMessage(test.error)}</ErrorNote>}
    </li>
  );
}

/** Ustawienia → OPNsense: klucz API przy urządzeniu OPNsense (bramy, usługi, DHCP/ARP, wersja). */
export function OpnsenseSettingsPage() {
  const qc = useQueryClient();
  const { data, isLoading, isError } = useOpnsenseKeys();
  const [form, setForm] = useState<{ item?: OpnsenseApiKey } | null>(null);
  const [toDelete, setToDelete] = useState<OpnsenseApiKey | null>(null);
  const remove = useMutation({
    mutationFn: (id: number) => del(`/api/opnsense/apis/${id}`),
    onSuccess: async () => {
      setToDelete(null);
      await Promise.all([qc.invalidateQueries({ queryKey: OPNSENSE_KEYS_KEY }), qc.invalidateQueries({ queryKey: ["opnsense", "device"] })]);
    },
  });
  const list = data ?? [];
  const taken = new Set(list.map((k) => k.device_id));

  return (
    <>
      <PageHeader title={t("settings.opnsense.title")}>
        <Button variant="primary" onClick={() => setForm({})}>
          <IconPlus size={18} aria-hidden="true" />
          {t("opn.add")}
        </Button>
      </PageHeader>
      <p className="mb-2 max-w-prose text-sm text-text-2">{t("opn.intro")}</p>
      <ol className="mb-4 max-w-prose list-decimal pl-5 text-xs text-text-2">
        <li>{t("opn.howto.1")}</li>
        <li>{t("opn.howto.2")}</li>
        <li>{t("opn.howto.3")}</li>
        <li>{t("opn.howto.4")}</li>
      </ol>

      {isError && !data && <ErrorNote>{t("opn.loadError")}</ErrorNote>}
      {!isLoading && !isError && list.length === 0 && (
        <Card className="p-6">
          <h2 className="text-base font-medium">{t("opn.empty.title")}</h2>
          <p className="mt-1 max-w-prose text-sm text-text-2">{t("opn.empty.body")}</p>
        </Card>
      )}
      {list.length > 0 && (
        <Card>
          <ul className="divide-y divide-border">
            {list.map((k) => (
              <KeyRow
                key={k.id}
                item={k}
                onEdit={() => setForm({ item: k })}
                onDelete={() => {
                  remove.reset();
                  setToDelete(k);
                }}
              />
            ))}
          </ul>
        </Card>
      )}

      {form && <KeyForm item={form.item} taken={taken} onClose={() => setForm(null)} />}
      {toDelete && (
        <Dialog
          size="sm"
          title={t("opn.delete.title")}
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
          <p className="text-sm">{t("opn.delete.body", { name: toDelete.device_name })}</p>
          {remove.isError && (
            <div className="mt-3">
              <ErrorNote>{errorMessage(remove.error)}</ErrorNote>
            </div>
          )}
        </Dialog>
      )}
    </>
  );
}
