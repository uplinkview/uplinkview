import { IconCheck, IconSettings } from "@tabler/icons-react";
import { useState } from "react";
import { Link } from "react-router";
import { Button, Card, ErrorNote, PageHeader } from "../components/ui";
import { t, type TextKey } from "../i18n";
import { SEVERITIES, formatDuration, useAckAlert, useAlerts, type Alert, type Severity } from "../lib/alerts";
import { formatDateTime, relativeTime } from "../lib/format";
import { useCan } from "../lib/roles";

type Tab = "firing" | "resolved";
const TABS: Tab[] = ["firing", "resolved"];
const TAB_LABEL: Record<Tab, TextKey> = { firing: "alerts.tab.firing", resolved: "alerts.tab.resolved" };
const SEVERITY_LABEL: Record<Severity, TextKey> = {
  critical: "alerts.severity.critical",
  warning: "alerts.severity.warning",
  info: "alerts.severity.info",
};
const SEVERITY_STYLE: Record<Severity, string> = {
  critical: "bg-danger-soft text-danger",
  warning: "bg-accent-soft text-accent-text",
  info: "bg-surface-2 text-text-2",
};

function AlertRow({ alert, tab }: { alert: Alert; tab: Tab }) {
  const ack = useAckAlert();
  const canAck = useCan("operator");
  const end = alert.resolved_at ? new Date(alert.resolved_at).getTime() : Date.now();
  const lasted = formatDuration((end - new Date(alert.started_at).getTime()) / 1000);
  return (
    <li className="flex flex-wrap items-start justify-between gap-3 px-4 py-3">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className={`rounded-md px-2 py-0.5 text-xs ${SEVERITY_STYLE[alert.severity]}`}>
            {t(SEVERITY_LABEL[alert.severity])}
          </span>
          <h3 className="min-w-0 text-sm font-medium">{alert.title}</h3>
        </div>
        {alert.message && <p className="mt-1 text-xs text-text-2">{alert.message}</p>}
        <p className="mt-1 text-xs text-muted">
          {tab === "firing"
            ? t("alerts.since", { when: relativeTime(alert.started_at) ?? "", lasted })
            : t("alerts.range", { from: formatDateTime(alert.started_at), to: formatDateTime(alert.resolved_at), lasted })}
          {alert.acked_by && ` · ${t("alerts.ackedBy", { user: alert.acked_by })}`}
        </p>
      </div>
      {tab === "firing" && !alert.acked_at && canAck && (
        <Button disabled={ack.isPending} onClick={() => ack.mutate(alert.id)}>
          <IconCheck size={16} aria-hidden="true" />
          {t("alerts.ack")}
        </Button>
      )}
    </li>
  );
}

/** Alerty: aktywne (z potwierdzaniem) i historia zakończonych. */
export function AlertsPage() {
  const [tab, setTab] = useState<Tab>("firing");
  const [severity, setSeverity] = useState<Severity | "all">("all");
  const list = useAlerts(tab);
  const items = (list.data ?? []).filter((a) => severity === "all" || a.severity === severity);

  return (
    <>
      <PageHeader title={t("alerts.title")}>
        <Link
          to="/settings/alert-rules"
          className="inline-flex items-center gap-2 rounded-lg border border-border-strong bg-surface px-3.5 py-2 text-sm font-medium text-text hover:bg-surface-2"
        >
          <IconSettings size={16} aria-hidden="true" />
          {t("alerts.rules")}
        </Link>
      </PageHeader>

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div role="group" aria-label={t("alerts.tabs")} className="inline-flex rounded-lg border border-border bg-surface p-0.5">
          {TABS.map((id) => (
            <button
              key={id}
              type="button"
              aria-pressed={tab === id}
              onClick={() => setTab(id)}
              className={`rounded-md px-3 py-1 text-sm transition-colors ${
                tab === id ? "bg-accent-soft font-medium text-accent-text" : "text-text-2 hover:text-text"
              }`}
            >
              {t(TAB_LABEL[id])}
            </button>
          ))}
        </div>
        <div role="group" aria-label={t("alerts.filter")} className="inline-flex rounded-lg border border-border bg-surface p-0.5">
          {(["all", ...SEVERITIES] as const).map((s) => (
            <button
              key={s}
              type="button"
              aria-pressed={severity === s}
              onClick={() => setSeverity(s)}
              className={`rounded-md px-2.5 py-1 text-xs transition-colors ${
                severity === s ? "bg-accent-soft font-medium text-accent-text" : "text-text-2 hover:text-text"
              }`}
            >
              {s === "all" ? t("alerts.filter.all") : t(SEVERITY_LABEL[s])}
            </button>
          ))}
        </div>
      </div>

      {list.isError && <ErrorNote>{t("alerts.error")}</ErrorNote>}
      {!list.isError && !list.isLoading && items.length === 0 && (
        <Card className="p-6 text-center text-sm text-text-2">{t(tab === "firing" ? "alerts.empty.firing" : "alerts.empty.resolved")}</Card>
      )}
      {items.length > 0 && (
        <Card>
          <ul className="divide-y divide-border">
            {items.map((a) => (
              <AlertRow key={a.id} alert={a} tab={tab} />
            ))}
          </ul>
        </Card>
      )}
    </>
  );
}
