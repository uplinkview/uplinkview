/** Rejestr widgetów: typ → nazwa, opis, ikona i widok. Nowy typ widgetu = jeden wpis tutaj. */
import {
  IconActivityHeartbeat,
  IconArrowsExchange,
  IconBell,
  IconBolt,
  IconCircleCheck,
  IconChartBar,
  IconChartLine,
  IconChartPie,
  IconGridDots,
  IconHeading,
  IconHistory,
  IconLayoutGrid,
  IconListDetails,
  IconNumber,
  IconServer,
  IconShieldCheck,
  IconShieldLock,
  IconTable,
  IconTimeline,
  IconTransfer,
  IconWorld,
  type Icon,
} from "@tabler/icons-react";
import { t, type TextKey } from "../../i18n";
import type { Widget, WidgetType } from "../../lib/layout";
import { ChartWidget, chartTitle } from "./ChartWidget";
import { DevicesWidget } from "./DevicesWidget";
import { EventsWidget } from "./EventsWidget";
import { VpnWidget } from "./VpnWidget";
import { HeatmapWidget, heatmapTitle } from "./HeatmapWidget";
import { BarGaugeWidget, StatWidget, StateTimelineWidget, TableWidget, collectionTitle, statTitle, stateTimelineTitle } from "./PanelWidgets";
import { SectionHeader } from "../DashboardGrid";
import { AlertsWidget, ChecksWidget, StatusWidget } from "./OverviewWidgets";
import { PieWidget } from "./PieWidget";
import { pieTitle } from "../../lib/pie";
import { PoeWidget } from "./PoeWidget";
import { ServerWidget } from "./ServerWidget";
import { SummaryWidget } from "./SummaryWidget";
import { WanChartWidget } from "./WanChartWidget";
import { WanSlaWidget } from "./WanSlaWidget";
import { WanStatusWidget } from "./WanStatusWidget";
import { WanUsageWidget } from "./WanUsageWidget";

export const WIDGET_TYPES: { type: WidgetType; label: TextKey; description: TextKey; icon: Icon }[] = [
  { type: "status", label: "widget.type.status", description: "widget.type.status.desc", icon: IconCircleCheck },
  { type: "chart", label: "widget.type.chart", description: "widget.type.chart.desc", icon: IconChartLine },
  { type: "stat", label: "widget.type.stat", description: "widget.type.stat.desc", icon: IconNumber },
  { type: "pie", label: "widget.type.pie", description: "widget.type.pie.desc", icon: IconChartPie },
  { type: "bargauge", label: "widget.type.bargauge", description: "widget.type.bargauge.desc", icon: IconChartBar },
  { type: "table", label: "widget.type.table", description: "widget.type.table.desc", icon: IconTable },
  { type: "state_timeline", label: "widget.type.state_timeline", description: "widget.type.state_timeline.desc", icon: IconTimeline },
  { type: "heatmap", label: "widget.type.heatmap", description: "widget.type.heatmap.desc", icon: IconGridDots },
  { type: "section", label: "widget.type.section", description: "widget.type.section.desc", icon: IconHeading },
  { type: "summary", label: "widget.type.summary", description: "widget.type.summary.desc", icon: IconLayoutGrid },
  { type: "devices", label: "widget.type.devices", description: "widget.type.devices.desc", icon: IconListDetails },
  { type: "alerts", label: "widget.type.alerts", description: "widget.type.alerts.desc", icon: IconBell },
  { type: "checks", label: "widget.type.checks", description: "widget.type.checks.desc", icon: IconActivityHeartbeat },
  { type: "events", label: "widget.type.events", description: "widget.type.events.desc", icon: IconHistory },
  { type: "vpn", label: "widget.type.vpn", description: "widget.type.vpn.desc", icon: IconShieldLock },
  { type: "poe", label: "widget.type.poe", description: "widget.type.poe.desc", icon: IconBolt },
  { type: "server", label: "widget.type.server", description: "widget.type.server.desc", icon: IconServer },
  { type: "wan_status", label: "widget.type.wan_status", description: "widget.type.wan_status.desc", icon: IconWorld },
  { type: "wan_chart", label: "widget.type.wan_chart", description: "widget.type.wan_chart.desc", icon: IconArrowsExchange },
  { type: "wan_sla", label: "widget.type.wan_sla", description: "widget.type.wan_sla.desc", icon: IconShieldCheck },
  { type: "wan_usage", label: "widget.type.wan_usage", description: "widget.type.wan_usage.desc", icon: IconTransfer },
];

export function widgetTitle(w: Widget): string {
  switch (w.type) {
    case "chart":
      return chartTitle(w.config);
    case "summary":
      return t("widget.type.summary");
    case "devices":
      return t("widget.type.devices");
    case "poe":
      return t("widget.type.poe");
    case "server":
      return t("widget.type.server");
    case "wan_status":
      return t("widget.type.wan_status");
    case "wan_chart":
      return t("widget.type.wan_chart");
    case "wan_sla":
      return t("widget.type.wan_sla");
    case "wan_usage":
      return t("widget.type.wan_usage");
    case "stat":
      return statTitle(w.config);
    case "bargauge":
      return w.config.title || collectionTitle(w.config.collection.kind, w.config.key);
    case "table":
      return w.config.title || collectionTitle(w.config.collection.kind);
    case "state_timeline":
      return stateTimelineTitle(w.config);
    case "heatmap":
      return heatmapTitle(w.config);
    case "pie":
      return pieTitle(w.config);
    case "section":
      return w.config.title || t("widget.type.section");
    case "status":
      return t("widget.type.status");
    case "alerts":
      return t("widget.type.alerts");
    case "checks":
      return t("widget.type.checks");
    case "events":
      return t("widget.type.events");
    case "vpn":
      return w.config.title || t("widget.type.vpn");
  }
}

/** Widok widgetu w pulpicie. */
export function WidgetView({ widget }: { widget: Widget }) {
  switch (widget.type) {
    case "chart":
      return <ChartWidget config={widget.config} />;
    case "summary":
      return <SummaryWidget tiles={widget.config.tiles} />;
    case "devices":
      return <DevicesWidget kinds={widget.config.kinds} display={widget.config.display} />;
    case "poe":
      return <PoeWidget deviceId={widget.config.device_id} />;
    case "server":
      return <ServerWidget />;
    case "wan_status":
      return <WanStatusWidget deviceId={widget.config.device_id} />;
    case "wan_chart":
      return <WanChartWidget deviceId={widget.config.device_id} metric={widget.config.metric} rangeMin={widget.config.range_min} height={widget.config.height} />;
    case "wan_sla":
      return <WanSlaWidget deviceId={widget.config.device_id} days={widget.config.days} />;
    case "wan_usage":
      return <WanUsageWidget deviceId={widget.config.device_id} resetDay={widget.config.reset_day} limitGb={widget.config.limit_gb} />;
    case "stat":
      return <StatWidget config={widget.config} />;
    case "bargauge":
      return <BarGaugeWidget config={widget.config} />;
    case "table":
      return <TableWidget config={widget.config} />;
    case "state_timeline":
      return <StateTimelineWidget config={widget.config} />;
    case "heatmap":
      return <HeatmapWidget config={widget.config} />;
    case "pie":
      return <PieWidget config={widget.config} />;
    case "section":
      return <SectionHeader title={widget.config.title} />;
    case "status":
      return <StatusWidget />;
    case "alerts":
      return <AlertsWidget limit={widget.config.limit} />;
    case "checks":
      return <ChecksWidget days={widget.config.days} />;
    case "events":
      return <EventsWidget days={widget.config.days} limit={widget.config.limit} />;
    case "vpn":
      return <VpnWidget title={widget.config.title ?? null} showOffline={widget.config.show_offline} />;
  }
}
