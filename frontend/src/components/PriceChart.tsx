import { useEffect, useRef } from "react";
import {
  CandlestickSeries,
  ColorType,
  createChart,
  HistogramSeries,
  LineSeries,
  LineStyle,
  type IChartApi,
  type ISeriesApi,
  type SeriesType,
  type Time,
} from "lightweight-charts";

import type { Candle } from "../types/api.ts";

export interface ChartLevel {
  price: number;
  title: string;
  color: string;
}

interface PriceChartProps {
  candles: Candle[];
  levels: ChartLevel[];
  showRsi: boolean;
  showMacd: boolean;
  rangeBars: number | null;
}

export function PriceChart({ candles, levels, showRsi, showMacd, rangeBars }: PriceChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const savedRange = useRef<{ from: number; to: number } | null>(null);
  const lastPreset = useRef(rangeBars);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || candles.length === 0) return;

    const chart: IChartApi = createChart(container, {
      width: container.clientWidth,
      height: container.clientHeight,
      layout: {
        background: { type: ColorType.Solid, color: "#ffffff" },
        textColor: "#4d5d6d",
        fontFamily: "IBM Plex Sans, sans-serif",
      },
      grid: {
        vertLines: { color: "#e6edf2" },
        horzLines: { color: "#e6edf2" },
      },
      rightPriceScale: { borderColor: "#b7c4d0" },
      timeScale: { borderColor: "#b7c4d0", timeVisible: false },
      crosshair: { mode: 0 },
    });

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: "#0c7a43",
      downColor: "#c4233c",
      borderVisible: false,
      wickUpColor: "#0c7a43",
      wickDownColor: "#c4233c",
    });
    candleSeries.setData(
      candles.flatMap((candle) => {
        if (candle.open === null || candle.high === null || candle.low === null || candle.close === null) return [];
        return [{ time: candle.time as Time, open: candle.open, high: candle.high, low: candle.low, close: candle.close }];
      }),
    );

    const volume = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
    });
    chart.priceScale("volume").applyOptions({ scaleMargins: { top: 0.78, bottom: 0 } });
    volume.setData(
      candles.flatMap((candle, index) => {
        if (candle.volume === null) return [];
        const previous = index > 0 ? candles[index - 1].close : candle.open;
        const rising = candle.close !== null && previous !== null ? candle.close >= previous : true;
        return [{ time: candle.time as Time, value: candle.volume, color: rising ? "#1f6b4a" : "#7a3140" }];
      }),
    );

    addLine(chart, candles, "sma20", "#1a56a8");
    addLine(chart, candles, "sma50", "#8a5a00");
    addLine(chart, candles, "sma200", "#6b4c9a");

    for (const level of levels) {
      candleSeries.createPriceLine({
        price: level.price,
        color: level.color,
        lineWidth: 1,
        lineStyle: LineStyle.Dashed,
        axisLabelVisible: true,
        title: level.title,
      });
    }

    let pane = 1;
    if (showRsi) {
      const rsi = chart.addSeries(LineSeries, { color: "#1a56a8", lineWidth: 1, priceScaleId: "right" }, pane);
      rsi.setData(linePoints(candles, "rsi"));
      pane += 1;
    }
    if (showMacd) {
      const macd = chart.addSeries(LineSeries, { color: "#8a5a00", lineWidth: 1, priceScaleId: "right" }, pane);
      const signal = chart.addSeries(LineSeries, { color: "#4d5d6d", lineWidth: 1, priceScaleId: "right" }, pane);
      const histogram = chart.addSeries(HistogramSeries, { priceScaleId: "right" }, pane);
      macd.setData(linePoints(candles, "macd"));
      signal.setData(linePoints(candles, "macd_signal"));
      histogram.setData(
        candles.flatMap((candle) => {
          if (candle.macd_histogram === null) return [];
          return [{
            time: candle.time as Time,
            value: candle.macd_histogram,
            color: candle.macd_histogram >= 0 ? "#1f6b4a" : "#7a3140",
          }];
        }),
      );
    }

    const presetChanged = lastPreset.current !== rangeBars;
    lastPreset.current = rangeBars;
    if (!presetChanged && savedRange.current) {
      chart.timeScale().setVisibleLogicalRange(savedRange.current);
    } else if (rangeBars && candles.length > rangeBars) {
      chart.timeScale().setVisibleLogicalRange({ from: candles.length - rangeBars, to: candles.length });
    } else {
      chart.timeScale().fitContent();
    }
    chart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
      if (range) savedRange.current = { from: range.from, to: range.to };
    });
    const observer = new ResizeObserver(() => {
      chart.applyOptions({ width: container.clientWidth, height: container.clientHeight });
    });
    observer.observe(container);
    return () => {
      observer.disconnect();
      chart.remove();
    };
  }, [candles, levels, rangeBars, showMacd, showRsi]);

  return <div ref={containerRef} className="h-80 w-full lg:h-[460px]" />;
}

function linePoints(candles: Candle[], key: "sma20" | "sma50" | "sma200" | "rsi" | "macd" | "macd_signal") {
  return candles.flatMap((candle) => {
    const value = candle[key];
    if (typeof value !== "number") return [];
    return [{ time: candle.time as Time, value }];
  });
}

function addLine(chart: IChartApi, candles: Candle[], key: "sma20" | "sma50" | "sma200", color: string) {
  const data = linePoints(candles, key);
  if (data.length === 0) return;
  const series: ISeriesApi<SeriesType> = chart.addSeries(LineSeries, { color, lineWidth: 1 });
  series.setData(data);
}
