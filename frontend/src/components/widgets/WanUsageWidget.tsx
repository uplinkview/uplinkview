import { IconTransfer } from "@tabler/icons-react";
import { t } from "../../i18n";
import { formatBytes } from "../../lib/format";
import { dateFormat, formatNumber } from "../../lib/intl";
import { localDay, useWanUsage, type UsageTotals, type WanUsage } from "../../lib/wan";
import { Card, EmptyHint, ErrorNote } from "../ui";

const dayFmt = dateFormat({ day: "numeric", month: "numeric" });
const sum = (x: UsageTotals) => x.rx_bytes + x.tx_bytes;
const GB = 1e9;

/** Prognoza zużycia na koniec okresu: dotychczasowe tempo × długość okresu (od 2. dnia – wcześniej za mało danych). */
export function forecastBytes(data: WanUsage, now = Date.now()): number | null {
  const start = localDay(data.period_start).getTime();
  const end = localDay(data.next_period_start).getTime();
  const elapsed = (now - start) / (end - start);
  if (elapsed < 1 / 31 || elapsed >= 1) return null;
  return sum(data.total_period) / elapsed;
}

function Tile({ label, totals, sub }: { label: string; totals: UsageTotals; sub?: string }) {
  return (
    <div className="min-w-0 rounded-xl bg-surface-2 px-3 py-2.5">
      <p className="text-xs text-text-2">{label}</p>
      <p aria-label={t("usage.totalOf", { label })} className="np-usage-value whitespace-nowrap font-semibold tabular-nums">
        {formatBytes(sum(totals))}
      </p>
      <p className="flex flex-wrap gap-x-2 text-xs text-text-2 tabular-nums">
        <span className="whitespace-nowrap">↓ {formatBytes(totals.rx_bytes)}</span>
        <span className="whitespace-nowrap">↑ {formatBytes(totals.tx_bytes)}</span>
      </p>
      {sub && <p className="mt-0.5 truncate text-xs text-muted">{sub}</p>}
    </div>
  );
}

function LimitBar({ used, limitGb, forecast }: { used: number; limitGb: number; forecast: number | null }) {
  const limit = limitGb * GB;
  const pct = (used / limit) * 100;
  const tone = pct >= 100 ? "bg-danger" : pct >= 80 ? "bg-warning" : "bg-accent";
  const over = forecast != null && forecast > limit;
  return (
    <div className="mt-3">
      <div className="flex items-baseline justify-between gap-2 text-xs">
        <span>{t("usage.ofLimit", { used: formatBytes(used), limit: formatBytes(limit) })}</span>
        <span className={`font-medium tabular-nums ${pct >= 100 ? "text-danger" : pct >= 80 ? "text-warning" : ""}`}>
          {formatNumber(pct, { maximumFractionDigits: pct < 10 ? 1 : 0 })}%
        </span>
      </div>
      <div
        role="progressbar"
        aria-label={t("usage.limit")}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(Math.min(pct, 100))}
        className="mt-1 h-2 overflow-hidden rounded-full bg-surface-2"
      >
        <div className={`h-full rounded-full ${tone}`} style={{ width: `${Math.min(pct, 100)}%` }} />
      </div>
      {forecast != null && (
        <p className={`mt-1 text-xs ${over ? "text-warning" : "text-text-2"}`}>
          {t(over ? "usage.forecastOver" : "usage.forecast", { value: formatBytes(forecast) })}
        </p>
      )}
    </div>
  );
}

/** Słupki dzień po dniu (pobrane + wysłane) – cały okres, dzisiejszy wyróżniony. */
function DayBars({ data }: { data: WanUsage }) {
  const max = Math.max(...data.days.map(sum), 1);
  return (
    <div className="mt-3">
      <div role="img" aria-label={t("usage.days")} className="flex h-14 items-end gap-px">
        {data.days.map((d) => {
          const total = sum(d);
          const label = `${dayFmt.format(localDay(d.day))}: ${formatBytes(total)} (↓ ${formatBytes(d.rx_bytes)} · ↑ ${formatBytes(d.tx_bytes)})`;
          return (
            <span
              key={d.day}
              title={label}
              className={`min-w-0 flex-1 rounded-t-sm ${d.day === data.today ? "bg-accent" : "bg-accent/40"}`}
              style={{ height: `${Math.max((total / max) * 100, total > 0 ? 3 : 1)}%` }}
            />
          );
        })}
      </div>
      <div className="mt-0.5 flex justify-between text-[11px] text-muted">
        <span>{dayFmt.format(localDay(data.period_start))}</span>
        <span>{t("usage.resetOn", { date: dayFmt.format(localDay(data.next_period_start)) })}</span>
      </div>
    </div>
  );
}

/** Licznik zużycia transferu WAN: dziś i w bieżącym miesiącu (albo okresie od dnia `resetDay`), opcjonalnie z pakietem. */
export function WanUsageWidget({ deviceId, resetDay, limitGb }: { deviceId?: number | null; resetDay: number; limitGb?: number | null }) {
  const { data, isLoading, isError } = useWanUsage(resetDay, deviceId);
  const manyRouters = new Set(data?.ports.map((p) => p.device_id)).size > 1;
  const periodLabel =resetDay === 1 ? t("usage.month") : t("usage.since", { date: data ? dayFmt.format(localDay(data.period_start)) : "" });
  return (
    <Card className="flex h-full flex-col p-4">
      <h3 className="mb-2 flex items-center gap-2 text-sm font-medium">
        <IconTransfer size={18} aria-hidden="true" className="shrink-0 text-accent-text" />
        {t("widget.type.wan_usage")}
      </h3>
      {isError ? (
        <ErrorNote>{t("wan.error")}</ErrorNote>
      ) : data && data.ports.length === 0 ? (
        <EmptyHint text={t("wan.none")} to="/settings/wan" action={t("wan.none.link")} />
      ) : data ? (
        <>
          <div className="grid grid-cols-2 gap-2">
            <Tile label={t("usage.today")} totals={data.total_today} />
            <Tile label={periodLabel} totals={data.total_period} />
          </div>
          {limitGb ? (
            <LimitBar used={sum(data.total_period)} limitGb={limitGb} forecast={forecastBytes(data)} />
          ) : null}
          <DayBars data={data} />
          {data.ports.length > 1 && (
            <ul className="mt-3 divide-y divide-border text-xs">
              {data.ports.map((p) => (
                <li key={p.interface_id} className="flex flex-wrap items-baseline justify-between gap-x-2 py-1.5">
                  <span className="min-w-0 truncate">
                    <span className="font-medium">{p.name}</span>
                    {manyRouters && <span className="ml-1.5 text-text-2">{p.device_name}</span>}
                  </span>
                  <span className="ml-auto whitespace-nowrap tabular-nums text-text-2">
                    {t("usage.portLine", { today: formatBytes(sum(p.today)), period: formatBytes(sum(p.period)) })}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </>
      ) : (
        isLoading && <p className="py-4 text-sm text-text-2">{t("app.loading")}</p>
      )}
    </Card>
  );
}
