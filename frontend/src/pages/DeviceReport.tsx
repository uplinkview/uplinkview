import { IconBrandGithub, IconDownload, IconFileReport } from "@tabler/icons-react";
import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { Button, Card, ErrorNote, Field } from "../components/ui";
import { t } from "../i18n";
import { ApiError, post, type Device } from "../lib/api";
import { issueLink, partiallyKnown, previewLines, readableValue, reportFile, type DeviceReport } from "../lib/discovery";
import { useCan } from "../lib/roles";

/** Drugi odczyt po tylu sekundach – widać, które wartości to liczniki. */
const INTERVAL_S = 30;
const NON_SNMP = new Set(["agent", "unifi_api"]);

function download(name: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: "application/json" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function Preview({ report }: { report: DeviceReport }) {
  const { lines, more } = previewLines(report.walk);
  return (
    <details className="mt-3 rounded-lg border border-border">
      <summary className="cursor-pointer px-3 py-2 text-sm">{t("devreport.preview", { n: report.records, changed: report.changed })}</summary>
      <table className="mx-3 mb-2 text-xs">
        <tbody>
          {report.branches.map((b) => (
            <tr key={b.oid}>
              <td className="pr-3 text-text-2">{b.name}</td>
              <td className="tabular-nums">{b.error ? t("devreport.branch.error") : b.truncated ? t("devreport.branch.truncated", { n: b.records }) : b.records}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <pre aria-label={t("devreport.walk")} className="max-h-80 overflow-auto border-t border-border bg-surface-2 px-3 py-2 font-mono text-[11px] leading-4">
        {lines
          .map((l) => {
            const [oid, tag, value = ""] = l.split("|");
            return `${oid} = ${readableValue(tag, value)}`;
          })
          .join("\n")}
        {more > 0 && `\n… ${t("devreport.more", { n: more })}`}
      </pre>
    </details>
  );
}

/**
 * Raport urządzenia (0.73.0, część B z `docs/24`): zanonimizowany zrzut SNMP do zgłoszenia „Nowe urządzenie”.
 * Widoczny dla administratora; przy urządzeniu znanym tylko ogólnie (driver `generic`) – z zachętą.
 */
export function DeviceReportCard({ device }: { device: Device }) {
  const admin = useCan("admin");
  const [open, setOpen] = useState(false);
  const [model, setModel] = useState("");
  const [notes, setNotes] = useState("");
  const build = useMutation({ mutationFn: () => post<DeviceReport>(`/api/devices/${device.id}/report?interval=${INTERVAL_S}`) });
  if (!admin || NON_SNMP.has(device.driver)) return null;
  const partial = partiallyKnown(device.detected_driver);

  if (!partial && !open) {
    return (
      <button type="button" onClick={() => setOpen(true)} className="self-start text-xs text-text-2 hover:text-accent-text hover:underline">
        {t("devreport.open")}
      </button>
    );
  }
  const report = build.data;
  return (
    <Card className={`p-4 ${partial ? "border-warning" : ""}`}>
      <h2 className="flex items-center gap-2 text-sm font-medium">
        <IconFileReport size={18} aria-hidden="true" className={partial ? "text-warning" : "text-text-2"} />
        {t(partial ? "devreport.partial.title" : "devreport.title")}
      </h2>
      <p className="mt-1 text-sm text-text-2">{t(partial ? "devreport.partial.body" : "devreport.body")}</p>
      <p className="mt-1 text-xs text-text-2">{t("devreport.privacy")}</p>
      {!report && (
        <Button className="mt-3" variant={partial ? "primary" : "secondary"} disabled={build.isPending} onClick={() => build.mutate()}>
          {build.isPending ? t("devreport.building", { s: INTERVAL_S }) : t("devreport.build")}
        </Button>
      )}
      {build.error && <ErrorNote>{build.error instanceof ApiError ? build.error.message : t("auth.error.generic")}</ErrorNote>}
      {report && (
        <>
          <Preview report={report} />
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <Field id="report-model" label={t("devreport.model")} value={model} maxLength={200} placeholder={device.model ?? ""} onChange={(e) => setModel(e.target.value)} />
            <label className="flex flex-col gap-1 text-sm sm:col-span-2" htmlFor="report-notes">
              {t("devreport.notes")}
              <textarea
                id="report-notes"
                rows={3}
                maxLength={1000}
                value={notes}
                placeholder={t("devreport.notes.placeholder")}
                onChange={(e) => setNotes(e.target.value)}
                className="rounded-lg border border-border-strong bg-surface px-3 py-2 text-sm"
              />
            </label>
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button
              variant="primary"
              onClick={() => {
                const f = reportFile(report, notes);
                download(f.name, f.text);
              }}
            >
              <IconDownload size={16} aria-hidden="true" />
              {t("devreport.download")}
            </Button>
            <a
              href={issueLink(report, model || device.model || "", notes)}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1.5 rounded-lg border border-border-strong bg-surface px-3.5 py-2 text-sm hover:bg-surface-2"
            >
              <IconBrandGithub size={16} aria-hidden="true" />
              {t("devreport.issue")}
            </a>
          </div>
          <p className="mt-2 text-xs text-text-2">{t("devreport.issue.hint")}</p>
        </>
      )}
    </Card>
  );
}
