/** Raport miesięczny (od 0.65.0): podgląd i pobranie PDF / CSV. API: backend/netpulse/api/reports.py. */
import { IconFileTypeCsv, IconFileTypePdf } from "@tabler/icons-react";
import { useQuery } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { Card, ErrorNote, PageHeader, Select } from "../components/ui";
import { getLanguage, t, type TextKey } from "../i18n";
import { get } from "../lib/api";
import { formatBytes, formatDateTime } from "../lib/format";
import { numberFormat } from "../lib/intl";

export interface MonthlyReport {
  year: number;
  month: number;
  title: string;
  start: string;
  end: string;
  generated_at: string;
  timezone: string;
  version: string;
  raw_from: string | null;
  devices_percent: number | null;
  checks_percent: number | null;
  devices: { id: number; name: string; host: string; kind: string; percent: number | null; down_s: number; samples: number }[];
  checks: { id: number; name: string; kind: string; target: string; percent: number | null; samples: number; failed: number; avg_latency_ms: number | null; max_latency_ms: number | null }[];
  wan: { name: string; device: string; rx_bytes: number; tx_bytes: number; percent: number | null; down_s: number | null; outages: number | null; longest_outage_s: number | null }[];
  alerts: { id: number; title: string; severity: string; device: string | null; started_at: string; resolved_at: string | null; duration_s: number }[];
  alerts_total: number;
  alerts_by_severity: Record<string, number>;
}

const MAX_ALERTS = 20;

/** Ostatnie 13 miesięcy od bieżącego: wartość „RRRR-MM” i nazwa. */
export function reportMonths(now: Date = new Date()): { value: string; label: string }[] {
  return Array.from({ length: 13 }, (_, i) => {
    const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
    const value = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
    const label = `${t(`month.${d.getMonth() + 1}` as TextKey)} ${d.getFullYear()}${i === 0 ? ` (${t("report.current")})` : ""}`;
    return { value, label };
  });
}

const num = (v: number, digits: number) => numberFormat({ minimumFractionDigits: digits, maximumFractionDigits: digits }).format(v);

/** 99,95% – a przy przerwie, która zaokrągla się do 100,00%, trzy miejsca (jak w PDF). */
export function fmtPercent(v: number | null): string {
  if (v == null) return "–";
  const two = num(v, 2);
  return `${two === num(100, 2) && v < 100 ? num(v, 3) : two}%`;
}

export function fmtDuration(s: number | null): string {
  if (s == null) return "–";
  const sec = Math.round(s);
  if (sec < 60) return `${sec} s`;
  const m = Math.floor(sec / 60);
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  if (h < 48) return m % 60 ? `${h} h ${m % 60} min` : `${h} h`;
  const d = Math.floor(h / 24);
  return h % 24 ? `${d} d ${h % 24} h` : `${d} d`;
}

function Tile({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <Card className="p-4">
      <p className="text-xs text-text-2">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums">{value}</p>
      <p className="mt-1 truncate text-xs text-text-2">{sub}</p>
    </Card>
  );
}

function Section({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section aria-labelledby={id} className="mb-6">
      <h2 id={id} className="mb-2 text-sm font-medium text-text-2">
        {title}
      </h2>
      {children}
    </section>
  );
}

function Table({ head, rows, right, label }: { head: string[]; rows: ReactNode[][]; right: number[]; label: string }) {
  if (rows.length === 0) return <Card className="px-4 py-3 text-sm text-text-2">{t("report.empty")}</Card>;
  return (
    <Card className="overflow-x-auto">
      <table className="w-full min-w-[36rem] text-sm" aria-label={label}>
        <thead>
          <tr className="border-b border-border text-left text-xs text-text-2">
            {head.map((h, i) => (
              <th key={h} scope="col" className={`px-4 py-2 font-medium ${right.includes(i) ? "text-right" : ""}`}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {rows.map((r, i) => (
            <tr key={i}>
              {r.map((v, j) => (
                <td key={j} className={`px-4 py-2 ${right.includes(j) ? "text-right tabular-nums" : ""}`}>
                  {v}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}

const downloadLink =
  "inline-flex items-center gap-1.5 rounded-lg border border-border-strong bg-surface px-3 py-1.5 text-sm hover:bg-surface-2";

export function ReportsPage() {
  const months = reportMonths();
  const [month, setMonth] = useState(months[1].value); // domyślnie poprzedni pełny miesiąc
  const { data, isLoading, isError } = useQuery({
    queryKey: ["reports", "monthly", month],
    queryFn: () => get<MonthlyReport>(`/api/reports/monthly?month=${month}`),
    staleTime: 60_000,
  });
  const crit = data?.alerts_by_severity.critical ?? 0;
  const warn = data?.alerts_by_severity.warning ?? 0;
  const mainWan = data?.wan.find((w) => w.percent != null);
  const longest = [...(data?.alerts ?? [])].sort((a, b) => b.duration_s - a.duration_s).slice(0, MAX_ALERTS);

  return (
    <>
      <PageHeader title={t("report.title")}>
        <div className="flex flex-wrap items-end gap-2">
          <div className="w-56">
            <Select id="report-month" label={t("report.month")} value={month} onChange={(e) => setMonth(e.target.value)}>
              {months.map((m) => (
                <option key={m.value} value={m.value}>
                  {m.label}
                </option>
              ))}
            </Select>
          </div>
          <a className={downloadLink} href={`/api/reports/monthly.pdf?month=${month}&lang=${getLanguage()}`} download>
            <IconFileTypePdf size={16} aria-hidden="true" />
            {t("report.pdf")}
          </a>
          <a className={downloadLink} href={`/api/reports/monthly.csv?month=${month}&lang=${getLanguage()}`} download>
            <IconFileTypeCsv size={16} aria-hidden="true" />
            {t("report.csv")}
          </a>
        </div>
      </PageHeader>
      <p className="mb-4 max-w-prose text-sm text-text-2">{t("report.intro")}</p>

      {isError && <ErrorNote>{t("report.error")}</ErrorNote>}
      {isLoading && <p role="status" className="py-6 text-sm text-text-2">{t("app.loading")}</p>}
      {data && (
        <>
          <p className="mb-3 text-sm text-text-2">
            {t("report.period", { start: formatDateTime(data.start), end: formatDateTime(data.end) })}
          </p>
          <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Tile label={t("report.devices")} value={fmtPercent(data.devices_percent)} sub={t("report.count", { n: data.devices.length })} />
            <Tile label={t("report.checks")} value={fmtPercent(data.checks_percent)} sub={t("report.count", { n: data.checks.length })} />
            <Tile label={t("report.wanTile")} value={fmtPercent(mainWan?.percent ?? null)} sub={mainWan?.name ?? t("report.noData")} />
            <Tile label={t("report.alerts")} value={String(data.alerts_total)} sub={t("report.alertsSub", { crit, warn })} />
          </div>
          {data.raw_from && <p className="mb-4 max-w-prose text-xs text-text-2">{t("report.rawFrom", { time: formatDateTime(data.raw_from) })}</p>}

          <Section id="report-devices" title={t("report.devices")}>
            <Table
              label={t("report.devices")}
              head={[t("report.col.device"), t("report.col.host"), t("report.col.availability"), t("report.col.down")]}
              right={[2, 3]}
              rows={data.devices.map((d) => [d.name, d.host, fmtPercent(d.percent), d.samples ? fmtDuration(d.down_s) : "–"])}
            />
          </Section>
          <Section id="report-checks" title={t("report.checks")}>
            <Table
              label={t("report.checks")}
              head={[t("report.col.check"), t("report.col.target"), t("report.col.availability"), t("report.col.failed"), t("report.col.latency")]}
              right={[2, 3, 4]}
              rows={data.checks.map((c) => [c.name, c.target, fmtPercent(c.percent), c.failed, c.avg_latency_ms != null ? `${num(c.avg_latency_ms, 1)} ms` : "–"])}
            />
          </Section>
          <Section id="report-wan" title={t("report.wan")}>
            <Table
              label={t("report.wan")}
              head={[t("report.col.link"), t("report.col.device"), t("report.col.rx"), t("report.col.tx"), t("report.col.availability"), t("report.col.outages")]}
              right={[2, 3, 4, 5]}
              rows={data.wan.map((w) => [w.name, w.device, formatBytes(w.rx_bytes), formatBytes(w.tx_bytes), fmtPercent(w.percent), w.outages ?? "–"])}
            />
          </Section>
          <Section id="report-alerts" title={t("report.alertsTitle", { n: data.alerts_total })}>
            {data.alerts_total > longest.length && <p className="mb-2 text-xs text-text-2">{t("report.alertsMore", { n: longest.length })}</p>}
            <Table
              label={t("report.alerts")}
              head={[t("report.col.start"), t("report.col.duration"), t("report.col.alert"), t("report.col.device")]}
              right={[1]}
              rows={longest.map((a) => [
                formatDateTime(a.started_at),
                `${fmtDuration(a.duration_s)}${a.resolved_at ? "" : ` (${t("report.ongoing")})`}`,
                a.title,
                a.device ?? "",
              ])}
            />
          </Section>
        </>
      )}
    </>
  );
}
