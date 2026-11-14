/**
 * Wykres panelu (Apache ECharts): wiele serii z różnych źródeł, dwie osie Y, stos, progi. Ładowany leniwie.
 * Legenda jest poza płótnem (ChartLegend) – działa z klawiatury i czytnikiem ekranu.
 */
import { BarChart, LineChart } from "echarts/charts";
import { GridComponent, MarkAreaComponent, MarkLineComponent, TooltipComponent, VisualMapPiecewiseComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useRef, useState, type RefObject } from "react";
import type { ChartKind, Threshold, ThresholdStyle } from "../../lib/layout";
import { useRefresh } from "../../lib/refresh";
import { useTheme } from "../../lib/theme";
import { linkChart } from "./chartSync";
import { plotSizeClass } from "./legendFit";
import { ZoomLayer } from "./ZoomLayer";
import type { ChartRow } from "./chartData";
import { leftTop, thresholdBands, tooltipHtml, type PanelLine, type TimeSpan } from "./panelData";
import { dateFormat } from "../../lib/intl";

echarts.use([LineChart, BarChart, GridComponent, TooltipComponent, MarkLineComponent, MarkAreaComponent, VisualMapPiecewiseComponent, CanvasRenderer]);

export interface AxisView {
  format: (value: number) => string;
  min?: number | null;
  max?: number | null;
  label?: string | null;
  /** Oś od danych zamiast od zera (np. sygnał w dBm) – tylko gdy `min` nie jest ustawione */
  autoMin?: boolean;
}

export interface PanelChartProps {
  lines: PanelLine[];
  kind: ChartKind;
  stack: boolean;
  smooth: boolean;
  left: AxisView;
  /** Oś prawa – tylko gdy jakaś widoczna seria jest na niej */
  right: AxisView | null;
  thresholds: Threshold[];
  thresholdStyle: ThresholdStyle;
  /** Piksele albo "100%" (komórka siatki pulpitu) */
  height: number | string;
  ariaLabel: string;
  /** Instancja ECharts dla właściciela (eksport do PNG) */
  instanceRef?: RefObject<echarts.ECharts | null>;
  /** Od 0.55.0: odcinki, w których internet szedł łączem zapasowym – serie bieżące (bez porównań) mają tam inny kolor */
  backup?: TimeSpan[];
}


const css = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const timeFmt = dateFormat({ dateStyle: "short", timeStyle: "medium" });

const NO_SPANS: TimeSpan[] = [];

export default function PanelChart({ lines, kind, stack, smooth, left, right, thresholds, thresholdStyle, height, ariaLabel, instanceRef, backup = NO_SPANS }: PanelChartProps) {
  const el = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.ECharts | null>(null);
  const { resolved } = useTheme();
  const { zoom } = useRefresh();
  // Klasa rozmiaru obszaru wykresu (od 0.53.0): po zmianie (rozciągnięcie karty, legenda obok) opcje osi liczone od nowa
  const [sizeClass, setSizeClass] = useState("");

  useEffect(() => {
    if (!el.current) return;
    const node = el.current;
    const instance = echarts.init(node, undefined, { renderer: "canvas" });
    chart.current = instance;
    if (instanceRef) instanceRef.current = instance;
    const observer = new ResizeObserver(() => {
      instance.resize();
      setSizeClass(plotSizeClass(node.clientWidth, node.clientHeight));
    });
    observer.observe(el.current);
    const unlink = linkChart(instance);
    return () => {
      unlink();
      observer.disconnect();
      instance.dispose();
      chart.current = null;
      if (instanceRef) instanceRef.current = null;
    };
  }, [instanceRef]);

  useEffect(() => {
    const instance = chart.current;
    if (!instance) return;
    const text = css("--text-2");
    const grid = css("--border");
    const surface = css("--surface");
    const showLines = thresholdStyle === "line" || thresholdStyle === "line_area";
    const showArea = thresholdStyle === "area" || thresholdStyle === "line_area";
    const activeThresholds = thresholdStyle === "off" ? [] : thresholds;
    const topThreshold = activeThresholds.length ? Math.max(...activeThresholds.map((th) => th.value)) : null;
    const dataTop = leftTop(lines, stack);
    const bandTop = Math.max(left.max ?? 0, dataTop, topThreshold ?? 0) * 1.1 || 1;
    const firstLeft = lines.findIndex((l) => l.axis === "left");
    // Oś Y skalowana do widocznego fragmentu, nie do całego zakresu
    const inZoom = (rows: ChartRow[]) => (zoom ? rows.filter(([time]) => time >= zoom.from && time <= zoom.to) : rows);

    const plotHeight = el.current?.clientHeight ?? 300;
    const plotWidth = el.current?.clientWidth ?? 600;
    // Wąski wykres: mniej opisów czasu i mniejsze czcionki osi
    const narrow = plotWidth < 360;
    const axisFont = narrow ? 10 : 12;
    const axis = (a: AxisView, position: "left" | "right", withThreshold: boolean) => ({
      type: "value",
      position,
      name: a.label ?? undefined,
      nameTextStyle: { color: text },
      min: a.min ?? (position === "left" && !a.autoMin ? 0 : undefined),
      // Próg ponad danymi też ma być widoczny
      max: a.max ?? (withThreshold && topThreshold != null ? (v: { max: number }) => Math.max(v.max, topThreshold * 1.05) : undefined),
      // Niski wykres (np. 5 wierszy siatki): mniej podziałek, a nachodzące na siebie opisy chowane
      splitNumber: plotHeight < 170 ? 2 : plotHeight < 240 ? 3 : 5,
      axisLabel: { color: text, fontSize: axisFont, formatter: (v: number) => a.format(v), hideOverlap: true },
      splitLine: { show: position === "left", lineStyle: { color: grid } },
    });

    // Kolor odcinków przez łącze zapasowe: osobna mapa kolorów (po czasie) dla każdej bieżącej serii
    const colored = (l: PanelLine) => backup.length > 0 && !l.dashed;
    const visualMap = lines.flatMap((l, i) =>
      colored(l)
        ? [
            {
              type: "piecewise",
              show: false,
              seriesIndex: i,
              dimension: 0,
              pieces: backup.map(([from, to]) => ({ gte: from, lt: to, color: css(i === 0 ? "--chart-backup" : "--chart-backup-2") })),
              outOfRange: { color: css(`--chart-${l.color}`) },
            },
          ]
        : [],
    );

    instance.setOption(
      {
        animationDuration: 250,
        visualMap: visualMap.length ? visualMap : undefined,
        textStyle: { color: text },
        grid: { left: 8, right: right ? 8 : 16, top: left.label || right?.label ? 28 : 12, bottom: 8, containLabel: true },
        tooltip: {
          trigger: "axis",
          backgroundColor: surface,
          borderColor: grid,
          textStyle: { color: css("--text") },
          formatter: (params: { axisValue: number; marker: string; seriesName: string; seriesIndex: number; value: [number, number | null] }[]) => {
            const head = timeFmt.format(new Date(params[0].axisValue));
            const rows = params.map((p) => {
              const fmt = lines[p.seriesIndex]?.axis === "right" && right ? right.format : left.format;
              return { marker: p.marker, name: p.seriesName, value: p.value[1] == null ? "–" : fmt(p.value[1]) };
            });
            return tooltipHtml(head, text, rows);
          },
        },
        xAxis: {
          type: "time",
          // Powiększony fragment (zaznaczenie myszą) – ta sama oś na wszystkich wykresach
          min: zoom?.from,
          max: zoom?.to,
          axisLine: { lineStyle: { color: grid } },
          axisLabel: { color: text, fontSize: axisFont, hideOverlap: true },
          splitNumber: narrow ? 2 : plotWidth < 560 ? 3 : 4,
          splitLine: { show: false },
        },
        yAxis: right ? [axis(left, "left", true), axis(right, "right", false)] : [axis(left, "left", true)],
        series: [
          ...lines.map((l, i) => {
            const color = css(`--chart-${l.color}`);
            const yAxisIndex = l.axis === "right" && right ? 1 : 0;
            const marks =
              i === firstLeft && activeThresholds.length
                ? {
                    markLine: showLines
                      ? {
                          silent: true,
                          symbol: "none",
                          label: { show: true, position: "insideEndTop", color: text, formatter: (p: { value: number }) => left.format(p.value) },
                          data: activeThresholds.map((th) => ({ yAxis: th.value, lineStyle: { color: css(`--chart-${th.color}`), type: "dashed", width: 1.5 } })),
                        }
                      : undefined,
                    markArea: showArea
                      ? {
                          silent: true,
                          data: thresholdBands(activeThresholds, bandTop).map((b) => [
                            { yAxis: b.from, itemStyle: { color: css(`--chart-${b.color}`), opacity: 0.08 } },
                            { yAxis: b.to },
                          ]),
                        }
                      : undefined,
                  }
                : {};
            const stackId = stack ? l.axis : undefined;
            // Z mapą kolorów (łącze zapasowe) kolor daje mapa – jawny kolor serii by ją przykrył
            const own = colored(l) ? undefined : color;
            if (kind === "bar") {
              return { name: l.name, type: "bar", yAxisIndex, stack: stackId, barMaxWidth: 14, itemStyle: { color: own }, data: inZoom(l.rows), ...marks };
            }
            return {
              name: l.name,
              type: "line",
              yAxisIndex,
              stack: stackId,
              smooth,
              showSymbol: false,
              symbol: "circle",
              symbolSize: 6,
              lineStyle: { width: 2, color: own, type: l.dashed ? "dashed" : "solid" },
              itemStyle: { color: own },
              areaStyle: kind === "area" ? { color: own, opacity: stack ? 0.35 : 0.1 } : undefined,
              data: inZoom(l.rows),
              ...marks,
            };
          }),
        ],
      },
      true,
    );
  }, [lines, kind, stack, smooth, left, right, thresholds, thresholdStyle, resolved, zoom, sizeClass, backup]);

  return (
    <ZoomLayer chart={chart} height={height}>
      <div ref={el} role="img" aria-label={ariaLabel} className="h-full w-full" />
    </ZoomLayer>
  );
}
