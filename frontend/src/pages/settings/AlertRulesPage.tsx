import { IconPencil, IconPlus, IconTrash } from "@tabler/icons-react";
import { useState } from "react";
import { Dialog } from "../../components/Dialog";
import { Button, Card, ErrorNote, Field, PageHeader, Select, Toggle } from "../../components/ui";
import { t, type TextKey } from "../../i18n";
import { ApiError } from "../../lib/api";
import {
  AGENT_KINDS,
  EVENT_KINDS,
  RULE_KINDS,
  SEVERITIES,
  formatDuration,
  formatThreshold,
  thresholdFromDisplay,
  thresholdToDisplay,
  useDeleteRule,
  useRuleMetrics,
  useRules,
  useSaveRule,
  type AlertRule,
  type RuleKind,
  type RuleMetric,
  type RulePayload,
  type Severity,
} from "../../lib/alerts";
import { isOn, ruleModule, useModules } from "../../lib/modules";
import { useDevices } from "../../lib/queries";

const KIND_LABEL: Record<RuleKind, TextKey> = {
  device_offline: "rules.kind.device_offline",
  port_down: "rules.kind.port_down",
  metric: "rules.kind.metric",
  container_stopped: "rules.kind.container_stopped",
  service_failed: "rules.kind.service_failed",
  smart_failed: "rules.kind.smart_failed",
  guest_stopped: "rules.kind.guest_stopped",
  backup_failed: "rules.kind.backup_failed",
  gateway_down: "rules.kind.gateway_down",
  opnsense_service_failed: "rules.kind.opnsense_service_failed",
  check_down: "rules.kind.check_down",
  default_community: "rules.kind.default_community",
  wan_switch: "rules.kind.wan_switch",
  device_restart: "rules.kind.device_restart",
  vpn_connect: "rules.kind.vpn_connect",
};
const MATCH_HINT: Partial<Record<RuleKind, TextKey>> = {
  container_stopped: "rules.match.hint.container",
  service_failed: "rules.match.hint.service",
  smart_failed: "rules.match.hint.smart",
  guest_stopped: "rules.match.hint.guest",
  backup_failed: "rules.match.hint.backup",
  gateway_down: "rules.match.hint.gateway",
  opnsense_service_failed: "rules.match.hint.opnsense_service",
  check_down: "rules.match.hint.check",
};
const SEVERITY_LABEL: Record<Severity, TextKey> = {
  critical: "alerts.severity.critical",
  warning: "alerts.severity.warning",
  info: "alerts.severity.info",
};
const DURATIONS = [0, 60, 120, 300, 600, 1800, 3600];
const durationLabel = (s: number) => (s === 0 ? t("rules.duration.now") : formatDuration(s));
const errorMessage = (err: unknown) => (err instanceof ApiError ? err.message : t("auth.error.generic"));
const iconButton = "flex size-9 items-center justify-center rounded-lg text-text-2 hover:bg-surface-2 hover:text-text disabled:opacity-50";

interface FormValues {
  name: string;
  kind: RuleKind;
  metric: string;
  op: ">" | "<";
  threshold: string;
  duration_s: number;
  severity: Severity;
  device_id: string;
  match: string;
}

function RuleForm({ rule, metrics: allMetrics, onClose }: { rule?: AlertRule; metrics: RuleMetric[]; onClose: () => void }) {
  const devices = useDevices();
  // Rodzaje i metryki wyłączonych modułów znikają z formularza (zostaje to, co ma edytowana reguła)
  const mods = useModules().data;
  const metrics = allMetrics.filter((m) => isOn(mods, ruleModule("metric", m.metric)) || m.metric === rule?.metric);
  const kinds = RULE_KINDS.filter((k) => isOn(mods, ruleModule(k)) || k === rule?.kind);
  const save = useSaveRule();
  const first = metrics[0]?.metric ?? "cpu_percent";
  const [values, setValues] = useState<FormValues>({
    name: rule?.name ?? "",
    kind: rule?.kind ?? "metric",
    metric: rule?.metric ?? first,
    op: rule?.op ?? ">",
    threshold: rule ? String(thresholdToDisplay(rule.metric, rule.threshold) ?? "") : "",
    duration_s: rule?.duration_s ?? 300,
    severity: rule?.severity ?? "warning",
    device_id: rule?.device_id != null ? String(rule.device_id) : "",
    match: rule?.match ?? "",
  });
  const [errors, setErrors] = useState<{ name?: string; threshold?: string }>({});
  const set = <K extends keyof FormValues>(key: K, value: FormValues[K]) => {
    setValues((v) => ({ ...v, [key]: value }));
    setErrors({});
  };
  const meta = metrics.find((m) => m.metric === values.metric);
  const isMetric = values.kind === "metric";
  const checkKind = values.kind === "check_down";
  // Stan bez czasu trwania: port przeszedł w down, fabryczne community (trwa, dopóki się nie zmieni)
  const eventKind = EVENT_KINDS.includes(values.kind);
  const noDuration = values.kind === "port_down" || values.kind === "default_community" || eventKind;
  // WAN to suma po routerach, sprawdzenia dostępności nie są urządzeniami – bez wyboru urządzenia
  const perDevice = !checkKind && values.kind !== "wan_switch" && (!isMetric || meta?.per_device !== false);
  const unitHint = meta ? (meta.unit === "b/s" ? "Mb/s" : meta.unit || "") : "";
  const agentKind = AGENT_KINDS.includes(values.kind);
  const matchable = agentKind || checkKind || (isMetric && meta?.matchable === true);

  function submit() {
    const found: typeof errors = {};
    if (!values.name.trim()) found.name = t("rules.err.name");
    const threshold = Number(values.threshold.replace(",", "."));
    if (isMetric && (values.threshold.trim() === "" || !Number.isFinite(threshold))) found.threshold = t("rules.err.threshold");
    setErrors(found);
    if (Object.keys(found).length > 0) return;
    const payload: RulePayload = {
      name: values.name.trim(),
      enabled: rule?.enabled ?? true,
      kind: values.kind,
      metric: isMetric ? values.metric : null,
      op: isMetric ? values.op : null,
      threshold: isMetric ? thresholdFromDisplay(values.metric, threshold) : null,
      duration_s: noDuration ? 0 : values.duration_s,
      severity: values.severity,
      device_id: perDevice && values.device_id ? Number(values.device_id) : null,
      match: matchable && values.match.trim() ? values.match.trim() : null,
    };
    save.mutate({ id: rule?.id, rule: payload }, { onSuccess: onClose });
  }

  return (
    <Dialog
      title={rule ? t("rules.form.edit", { name: rule.name }) : t("rules.form.add")}
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>{t("common.cancel")}</Button>
          <Button variant="primary" disabled={save.isPending} onClick={submit}>
            {save.isPending ? t("common.saving") : t("common.save")}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <Field id="rule-name" label={t("rules.name")} value={values.name} error={errors.name} maxLength={128} onChange={(e) => set("name", e.target.value)} />
        <Select id="rule-kind" label={t("rules.kind")} value={values.kind} onChange={(e) => set("kind", e.target.value as RuleKind)}>
          {kinds.map((k) => (
            <option key={k} value={k}>
              {t(KIND_LABEL[k])}
            </option>
          ))}
        </Select>

        {isMetric && (
          <>
            <Select id="rule-metric" label={t("rules.metric")} value={values.metric} onChange={(e) => set("metric", e.target.value)}>
              {metrics.map((m) => (
                <option key={m.metric} value={m.metric}>
                  {m.label}
                </option>
              ))}
            </Select>
            <div className="grid gap-4 sm:grid-cols-[10rem_1fr]">
              <Select id="rule-op" label={t("rules.op")} value={values.op} onChange={(e) => set("op", e.target.value as ">" | "<")}>
                <option value=">">{t("rules.op.gt")}</option>
                <option value="<">{t("rules.op.lt")}</option>
              </Select>
              <Field
                id="rule-threshold"
                label={t("rules.threshold", { unit: unitHint })}
                inputMode="decimal"
                value={values.threshold}
                error={errors.threshold}
                onChange={(e) => set("threshold", e.target.value)}
              />
            </div>
          </>
        )}

        {checkKind && <p className="text-xs text-text-2">{t("rules.check.hint")}</p>}
        {agentKind && (
          <p className="text-xs text-text-2">
            {t(
              values.kind === "guest_stopped" || values.kind === "backup_failed"
                ? "rules.proxmox.hint"
                : values.kind === "gateway_down" || values.kind === "opnsense_service_failed"
                  ? "rules.opnsense.hint"
                  : "rules.agent.hint",
            )}
          </p>
        )}
        {matchable && (
          <Field
            id="rule-match"
            label={t("rules.match")}
            value={values.match}
            maxLength={255}
            placeholder={t("rules.match.placeholder")}
            hint={t(MATCH_HINT[values.kind] ?? "rules.match.hint.sensor")}
            autoCapitalize="none"
            spellCheck={false}
            onChange={(e) => set("match", e.target.value)}
          />
        )}

        {!noDuration ? (
          <Select id="rule-duration" label={t("rules.duration")} value={values.duration_s} onChange={(e) => set("duration_s", Number(e.target.value))}>
            {DURATIONS.map((s) => (
              <option key={s} value={s}>
                {durationLabel(s)}
              </option>
            ))}
          </Select>
        ) : (
          <p className="text-xs text-text-2">
            {t(eventKind ? "rules.event.hint" : values.kind === "port_down" ? "rules.portdown.hint" : "rules.community.hint")}
          </p>
        )}

        <div className="grid gap-4 sm:grid-cols-2">
          <Select id="rule-severity" label={t("rules.severity")} value={values.severity} onChange={(e) => set("severity", e.target.value as Severity)}>
            {SEVERITIES.map((s) => (
              <option key={s} value={s}>
                {t(SEVERITY_LABEL[s])}
              </option>
            ))}
          </Select>
          {perDevice && (
            <Select id="rule-device" label={t("rules.device")} value={values.device_id} onChange={(e) => set("device_id", e.target.value)}>
              <option value="">{t("rules.device.all")}</option>
              {(devices.data ?? []).map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name}
                </option>
              ))}
            </Select>
          )}
        </div>
        {save.isError && <ErrorNote>{errorMessage(save.error)}</ErrorNote>}
      </div>
    </Dialog>
  );
}

function describe(rule: AlertRule, metrics: RuleMetric[]): string {
  if (rule.kind === "device_offline") return t("rules.sum.offline", { after: durationLabel(rule.duration_s) });
  if (rule.kind === "port_down") return t("rules.sum.portdown");
  if (rule.kind === "default_community") return t("rules.sum.community");
  if (rule.kind === "wan_switch") return t("rules.sum.wan_switch");
  if (rule.kind === "device_restart") return t("rules.sum.device_restart");
  if (rule.kind === "vpn_connect") return t("rules.sum.vpn_connect");
  const only = rule.match ? ` (${rule.match})` : "";
  if (AGENT_KINDS.includes(rule.kind) || rule.kind === "check_down") return `${t(KIND_LABEL[rule.kind])}${only}, ${durationLabel(rule.duration_s)}`;
  const meta = metrics.find((m) => m.metric === rule.metric);
  return t("rules.sum.metric", {
    metric: meta?.label ?? rule.metric ?? "?",
    op: rule.op === "<" ? "<" : ">",
    value: formatThreshold(rule.threshold, meta?.unit ?? ""),
    duration: durationLabel(rule.duration_s),
  }) + only;
}

/** Ustawienia → Reguły alertów: lista z włączaniem, edycją i usuwaniem. */
export function AlertRulesPage() {
  const rules = useRules();
  const metrics = useRuleMetrics().data ?? [];
  const devices = useDevices().data ?? [];
  const save = useSaveRule();
  const remove = useDeleteRule();
  const [form, setForm] = useState<{ rule?: AlertRule } | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<AlertRule | null>(null);

  const toggle = (rule: AlertRule, enabled: boolean) => {
    const { id, created_at: _created, ...payload } = rule;
    save.mutate({ id, rule: { ...payload, enabled } });
  };

  return (
    <>
      <PageHeader title={t("rules.title")}>
        <Button variant="primary" onClick={() => setForm({})}>
          <IconPlus size={16} aria-hidden="true" />
          {t("rules.add")}
        </Button>
      </PageHeader>
      <p className="mb-4 max-w-2xl text-sm text-text-2">{t("rules.intro")}</p>

      {rules.isError && <ErrorNote>{t("rules.error")}</ErrorNote>}
      {rules.data?.length === 0 && <Card className="p-6 text-center text-sm text-text-2">{t("rules.empty")}</Card>}
      {rules.data && rules.data.length > 0 && (
        <Card>
          <ul className="divide-y divide-border">
            {rules.data.map((r) => {
              const device = devices.find((d) => d.id === r.device_id);
              return (
                <li key={r.id} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
                  <div className="min-w-0 flex-1">
                    <h3 className="text-sm font-medium">{r.name}</h3>
                    <p className="text-xs text-text-2">
                      {describe(r, metrics)} · {t(SEVERITY_LABEL[r.severity])} · {device ? device.name : t("rules.device.all")}
                    </p>
                  </div>
                  <div className="flex items-center gap-1">
                    <Toggle checked={r.enabled} label={t("rules.enabled", { name: r.name })} disabled={save.isPending} onChange={(v) => toggle(r, v)} />
                    <button type="button" className={iconButton} aria-label={t("rules.edit", { name: r.name })} onClick={() => setForm({ rule: r })}>
                      <IconPencil size={18} aria-hidden="true" />
                    </button>
                    <button type="button" className={iconButton} aria-label={t("rules.delete", { name: r.name })} onClick={() => setConfirmDelete(r)}>
                      <IconTrash size={18} aria-hidden="true" />
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
        </Card>
      )}

      {form && <RuleForm rule={form.rule} metrics={metrics} onClose={() => setForm(null)} />}
      {confirmDelete && (
        <Dialog
          title={t("rules.delete.title", { name: confirmDelete.name })}
          size="sm"
          onClose={() => setConfirmDelete(null)}
          footer={
            <>
              <Button onClick={() => setConfirmDelete(null)}>{t("common.cancel")}</Button>
              <Button
                variant="danger"
                disabled={remove.isPending}
                onClick={() => remove.mutate(confirmDelete.id, { onSuccess: () => setConfirmDelete(null) })}
              >
                {t("common.delete")}
              </Button>
            </>
          }
        >
          <p className="text-sm text-text-2">{t("rules.delete.body")}</p>
        </Dialog>
      )}
    </>
  );
}
