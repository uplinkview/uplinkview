import { IconRadar } from "@tabler/icons-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Button, Card, ErrorNote, Field, Select } from "../../../components/ui";
import { KIND_LABEL, deviceIcon } from "../../../components/widgets/DevicesWidget";
import { t, locale } from "../../../i18n";
import { ApiError, get, post, type Device } from "../../../lib/api";
import { createFromFound, preselected, sortFound, type FoundDevice, type ScanPayload, type ScanResult } from "../../../lib/discovery";
import { vendorModel } from "../../../lib/format";
import { SnmpCredentialFields } from "./DeviceForm";
import { SNMP_VERSIONS, buildTarget, emptyForm, validate, type DeviceFormValues, type FormErrors } from "./deviceFormLogic";

type RowState = "idle" | "adding" | "added" | "error";

function errorText(err: unknown): string {
  return err instanceof ApiError ? err.message : t("auth.error.generic");
}

/** Dane logowania z formularza (bez adresu i nazwy) – do skanu i do dodania znalezionych urządzeń. */
function credsOf(values: DeviceFormValues): Omit<ScanPayload, "network"> {
  const { host: _host, driver: _driver, ...rest } = buildTarget({ ...values, host: "0.0.0.0" });
  return rest;
}

/**
 * Wykrywanie urządzeń w sieci (0.73.0): skan podsieci przez SNMP, lista znalezionych z rozpoznanym sprzętem,
 * dodanie zaznaczonych jednym kliknięciem. W kreatorze `/setup` i w Ustawienia → Urządzenia.
 */
export function DiscoveryPanel({ onAdded }: { onAdded?: (devices: Device[]) => void }) {
  const qc = useQueryClient();
  const suggest = useQuery({ queryKey: ["discovery-suggest"], queryFn: () => get<{ network: string | null }>("/api/discovery/suggest") });
  const [network, setNetwork] = useState("");
  const [values, setValues] = useState<DeviceFormValues>(emptyForm);
  const [errors, setErrors] = useState<FormErrors>({});
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [names, setNames] = useState<Record<string, string>>({});
  const [rows, setRows] = useState<Record<string, { state: RowState; error?: string }>>({});

  useEffect(() => {
    if (!network && suggest.data?.network) setNetwork(suggest.data.network);
  }, [suggest.data, network]);

  const set = <K extends keyof DeviceFormValues>(key: K, value: DeviceFormValues[K]) => {
    setValues((v) => ({ ...v, [key]: value }));
    setErrors((e) => ({ ...e, [key]: undefined }));
  };

  const scan = useMutation({
    mutationFn: () => post<ScanResult>("/api/discovery/scan", { network: network.trim(), ...credsOf(values) }),
    onSuccess: (result) => {
      setSelected(new Set(result.found.filter(preselected).map((f) => f.host)));
      setNames(Object.fromEntries(result.found.map((f) => [f.host, f.suggested_name])));
      setRows({});
    },
  });

  const add = useMutation({
    mutationFn: async (list: FoundDevice[]) => {
      const added: Device[] = [];
      for (const f of list) {
        setRows((r) => ({ ...r, [f.host]: { state: "adding" } }));
        try {
          const d = await post<Device>("/api/devices", createFromFound(f, names[f.host] ?? "", credsOf(values)));
          added.push(d);
          setRows((r) => ({ ...r, [f.host]: { state: "added" } }));
        } catch (err) {
          setRows((r) => ({ ...r, [f.host]: { state: "error", error: errorText(err) } }));
        }
      }
      return added;
    },
    onSuccess: async (added) => {
      setSelected(new Set());
      await Promise.all([qc.invalidateQueries({ queryKey: ["devices"] }), qc.invalidateQueries({ queryKey: ["dashboard"] })]);
      if (added.length) onAdded?.(added);
    },
  });

  function onScan(e: React.FormEvent) {
    e.preventDefault();
    const all = validate({ ...values, name: "x", host: "192.0.2.1" });
    const credErrors: FormErrors = { community: all.community, v3_username: all.v3_username, v3_auth_key: all.v3_auth_key, v3_priv_key: all.v3_priv_key, v3_auth_protocol: all.v3_auth_protocol, v3_priv_protocol: all.v3_priv_protocol };
    setErrors(credErrors);
    if (!network.trim() || Object.values(credErrors).some(Boolean)) return;
    scan.mutate();
  }

  const found = scan.data ? sortFound(scan.data.found) : [];
  const toAdd = found.filter((f) => selected.has(f.host) && f.device_id == null && rows[f.host]?.state !== "added");
  const toggle = (host: string) =>
    setSelected((s) => {
      const next = new Set(s);
      if (next.has(host)) next.delete(host);
      else next.add(host);
      return next;
    });

  return (
    <Card className="p-4">
      <h2 className="flex items-center gap-2 text-sm font-medium">
        <IconRadar size={18} aria-hidden="true" className="text-accent-text" />
        {t("discovery.title")}
      </h2>
      <p className="mt-1 text-xs text-text-2">{t("discovery.intro")}</p>
      <form onSubmit={onScan} noValidate className="mt-3 flex flex-col gap-3">
        <div className="grid gap-3 sm:grid-cols-[1fr_10rem]">
          <Field
            id="disc-network"
            label={t("discovery.network")}
            value={network}
            placeholder="192.168.1.0/24"
            hint={t("discovery.network.hint")}
            autoCapitalize="none"
            spellCheck={false}
            error={scan.error instanceof ApiError && scan.error.status === 422 && !network.trim() ? t("discovery.network.required") : undefined}
            onChange={(e) => setNetwork(e.target.value)}
          />
          <Select id="disc-version" label={t("devform.version")} value={values.snmp_version} onChange={(e) => set("snmp_version", e.target.value as DeviceFormValues["snmp_version"])}>
            {SNMP_VERSIONS.map((v) => (
              <option key={v} value={v}>
                {t(`devform.version.${v}` as const)}
              </option>
            ))}
          </Select>
        </div>
        <SnmpCredentialFields values={values} errors={errors} set={set} idPrefix="disc" />
        <Button type="submit" variant="primary" className="self-start" disabled={scan.isPending || !network.trim()}>
          {scan.isPending ? t("discovery.scanning") : t("discovery.scan")}
        </Button>
      </form>
      {scan.isPending && <p className="mt-2 text-xs text-text-2">{t("discovery.scanning.hint")}</p>}
      {scan.error && <ErrorNote>{errorText(scan.error)}</ErrorNote>}

      {scan.data && (
        <div className="mt-4">
          <p role="status" className="text-xs text-text-2">
            {t("discovery.summary", { found: scan.data.found.length, scanned: scan.data.scanned, s: scan.data.took_s.toLocaleString(locale()) })}
          </p>
          {found.length === 0 ? (
            <p className="mt-2 text-sm text-text-2">{t("discovery.none")}</p>
          ) : (
            <ul aria-label={t("discovery.results")} className="mt-2 divide-y divide-border rounded-lg border border-border">
              {found.map((f) => {
                const Icon = deviceIcon(f.kind);
                const row = rows[f.host];
                const known = f.device_id != null || row?.state === "added";
                return (
                  <li key={f.host} className="flex flex-wrap items-center gap-3 px-3 py-2.5 text-sm">
                    <input
                      type="checkbox"
                      aria-label={t("discovery.select", { host: f.host })}
                      className="size-4 accent-accent"
                      checked={!known && selected.has(f.host)}
                      disabled={known || add.isPending}
                      onChange={() => toggle(f.host)}
                    />
                    <Icon size={20} aria-hidden="true" className="shrink-0 text-text-2" />
                    <div className="min-w-0 flex-1">
                      {known ? (
                        <span className="font-medium">{names[f.host] || f.suggested_name}</span>
                      ) : (
                        <input
                          aria-label={t("discovery.name", { host: f.host })}
                          className="w-full max-w-xs rounded-md border border-border bg-surface px-2 py-1 text-sm"
                          value={names[f.host] ?? ""}
                          maxLength={128}
                          onChange={(e) => setNames((n) => ({ ...n, [f.host]: e.target.value }))}
                        />
                      )}
                      <p className="mt-0.5 truncate text-xs text-text-2">
                        {[f.host, vendorModel(f.vendor, f.model), t(KIND_LABEL[f.kind] ?? "dash.kind.other"), f.firmware].filter(Boolean).join(" · ")}
                      </p>
                      {row?.state === "error" && <p className="mt-0.5 text-xs text-danger">{row.error}</p>}
                    </div>
                    <span className="flex shrink-0 flex-wrap gap-1.5 text-xs">
                      {f.generic && (
                        <span title={t("discovery.generic.hint")} className="rounded-full bg-warning-soft px-2 py-0.5 text-warning">
                          {t("discovery.generic")}
                        </span>
                      )}
                      {known ? (
                        <span className="rounded-full bg-success-soft px-2 py-0.5 text-success">{row?.state === "added" ? t("discovery.added") : t("discovery.known")}</span>
                      ) : row?.state === "adding" ? (
                        <span className="text-text-2">{t("discovery.adding")}</span>
                      ) : null}
                    </span>
                  </li>
                );
              })}
            </ul>
          )}
          {found.some((f) => f.device_id == null && rows[f.host]?.state !== "added") && (
            <Button variant="primary" className="mt-3" disabled={add.isPending || toAdd.length === 0} onClick={() => add.mutate(toAdd)}>
              {add.isPending ? t("discovery.adding") : t("discovery.add", { n: toAdd.length })}
            </Button>
          )}
        </div>
      )}
    </Card>
  );
}
