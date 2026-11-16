/** Dostępność w procentach (24 h, 7 dni, 30 dni, rok) i pasek dzień po dniu – strona urządzenia i portu. */
import { t } from "../i18n";
import { AVAILABILITY_PERIODS, useAvailability, type AvailabilityDay, type AvailabilityKind } from "../lib/details";
import { availabilityTone, formatAvailability, formatDuration } from "../lib/wan";
import { Card } from "./ui";
import { dateFormat } from "../lib/intl";

const TONE_TEXT = { ok: "text-success", warn: "text-warning", danger: "text-danger", none: "text-text-2" } as const;
const TONE_BAR = { ok: "bg-success", warn: "bg-warning", danger: "bg-danger", none: "bg-surface-2" } as const;
const BAR_DAYS = 30;

function PeriodTile({ kind, id, days }: { kind: AvailabilityKind; id: number; days: (typeof AVAILABILITY_PERIODS)[number] }) {
  const { data, isLoading } = useAvailability(kind, id, days);
  const pct = data?.percent ?? null;
  return (
    <div className="rounded-lg bg-surface-2 px-3 py-2">
      <dt className="text-xs text-text-2">{t(`avail.period.${days}` as const)}</dt>
      <dd className={`text-lg font-medium ${TONE_TEXT[availabilityTone(pct)]}`}>{isLoading ? "…" : formatAvailability(pct)}</dd>
      {data && data.down_s > 0 && <dd className="text-xs text-muted">{t(kind === "devices" ? "avail.down" : "avail.disconnected", { time: formatDuration(data.down_s) })}</dd>}
    </div>
  );
}

/** Klucz dnia w strefie przeglądarki, taki sam jak dzień z API ("2026-10-25"). */
function dayKey(d: Date): string {
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${mm}-${dd}`;
}

const dayLabel = dateFormat({ day: "numeric", month: "short" });

/** Ostatnie dni od najstarszego do dzisiaj; dzień bez próbek ma `percent: null`. */
export function lastDays(daily: AvailabilityDay[], count: number, today = new Date()): { key: string; label: string; percent: number | null }[] {
  const byDay = new Map(daily.map((d) => [d.day, d.percent]));
  return Array.from({ length: count }, (_, i) => {
    const d = new Date(today.getFullYear(), today.getMonth(), today.getDate() - (count - 1 - i));
    const key = dayKey(d);
    return { key, label: dayLabel.format(d), percent: byDay.get(key) ?? null };
  });
}

function DailyBars({ kind, id }: { kind: AvailabilityKind; id: number }) {
  const { data } = useAvailability(kind, id, BAR_DAYS);
  if (!data) return null;
  const days = lastDays(data.daily, BAR_DAYS);
  return (
    <div className="mt-4">
      <ol aria-label={t("avail.daily", { days: BAR_DAYS })} className="flex h-8 items-stretch gap-0.5">
        {days.map((d) => {
          const text = `${d.label}: ${d.percent == null ? t("avail.noData") : formatAvailability(d.percent)}`;
          return <li key={d.key} title={text} aria-label={text} className={`min-w-0 flex-1 rounded-sm ${TONE_BAR[availabilityTone(d.percent)]}`} />;
        })}
      </ol>
      <div className="mt-1 flex justify-between text-xs text-muted">
        <span>{days[0].label}</span>
        <span>{t("avail.today")}</span>
      </div>
    </div>
  );
}

export function AvailabilityCard({ kind, id, title }: { kind: AvailabilityKind; id: number; title: string }) {
  return (
    <Card className="p-4">
      <h2 className="mb-3 text-sm font-medium">{title}</h2>
      <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {AVAILABILITY_PERIODS.map((days) => (
          <PeriodTile key={days} kind={kind} id={id} days={days} />
        ))}
      </dl>
      <DailyBars kind={kind} id={id} />
    </Card>
  );
}
