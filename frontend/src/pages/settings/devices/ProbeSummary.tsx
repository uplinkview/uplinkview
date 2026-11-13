import { IconCircleCheck } from "@tabler/icons-react";
import { t, type TextKey } from "../../../i18n";
import type { ProbeResult } from "../../../lib/api";
import { formatUptime, vendorModel } from "../../../lib/format";

const KIND_LABEL: Record<string, TextKey> = {
  gateway: "dash.kind.gateway",
  switch: "dash.kind.switch",
  ap: "dash.kind.ap",
  other: "dash.kind.other",
};

/** Wynik udanego testu SNMP: co wykryto (typ, model, sterownik) i ile jest portów i sieci WiFi. */
export function ProbeSummary({ result }: { result: ProbeResult }) {
  const model = vendorModel(result.vendor, result.model) || result.name || "-";
  const kind = t(KIND_LABEL[result.kind] ?? "dash.kind.other").toLowerCase();
  const ports = result.interfaces.filter((i) => !i.hidden).length;
  const wifi = result.wifi.filter((w) => !w.hidden).length;
  const details = [
    t("probe.driver", { driver: result.driver }),
    t("probe.ports", { count: ports }),
    ...(wifi > 0 ? [t("probe.wifi", { count: wifi })] : []),
    ...(result.uptime_s != null ? [t("probe.uptime", { uptime: formatUptime(result.uptime_s) })] : []),
    ...(result.firmware ? [t("probe.firmware", { firmware: result.firmware })] : []),
  ];
  return (
    <div role="status" className="flex items-start gap-2.5 rounded-lg bg-success-soft px-3 py-2.5 text-sm text-success">
      <IconCircleCheck size={20} aria-hidden="true" className="mt-0.5 shrink-0" />
      <div className="min-w-0">
        <p className="font-medium">{t("probe.ok")}</p>
        <p>{t("probe.detected", { what: `${model} (${kind})` })}</p>
        <p className="text-xs opacity-90">{details.join(" · ")}</p>
      </div>
    </div>
  );
}
