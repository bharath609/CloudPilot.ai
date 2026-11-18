import type { ReactNode } from "react";

import { formatMoney, formatPercent } from "../lib/money";

export const CHART = {
  grid: "#22304a",
  axis: "#8fa2bd",
  accent: "#45c7f5",
  accentSoft: "rgba(69, 199, 245, 0.16)",
  band: "rgba(94, 234, 212, 0.12)",
  lower: "#5eead4",
  upper: "#f8b26a",
  risk: "#f87171",
};

export const axisProps = {
  tick: { fill: CHART.axis, fontSize: 11 },
  tickLine: false,
  axisLine: { stroke: CHART.grid },
} as const;

interface TooltipPayloadRow {
  payload?: {
    label?: string;
    exact?: string;
    lower?: string;
    upper?: string;
    currency?: string;
    detail?: string;
  };
}

/**
 * Exact-value tooltip. Values come from decimal strings held on the data row,
 * never from the plotted float.
 */
export function MoneyTooltip({
  active,
  payload,
  currency,
}: {
  active?: boolean;
  payload?: TooltipPayloadRow[];
  currency?: string | null;
}) {
  if (!active || !payload || payload.length === 0) return null;
  const row = payload[0]?.payload;
  if (!row) return null;
  return (
    <div className="chart-tip">
      {row.label && <strong>{row.label}</strong>}
      {row.exact !== undefined && (
        <span>{formatMoney(row.exact, row.currency ?? currency)}</span>
      )}
      {(row.lower !== undefined || row.upper !== undefined) && (
        <span className="chart-tip-sub">
          Band {formatMoney(row.lower ?? null, row.currency ?? currency)} –{" "}
          {formatMoney(row.upper ?? null, row.currency ?? currency)}
        </span>
      )}
      {row.detail && <span className="chart-tip-sub">{row.detail}</span>}
    </div>
  );
}

export function PercentTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ payload?: { label?: string; exact?: string; detail?: string } }>;
}) {
  if (!active || !payload || payload.length === 0) return null;
  const row = payload[0]?.payload;
  if (!row) return null;
  return (
    <div className="chart-tip">
      {row.label && <strong>{row.label}</strong>}
      {row.exact !== undefined && <span>{formatPercent(row.exact, 2)}</span>}
      {row.detail && <span className="chart-tip-sub">{row.detail}</span>}
    </div>
  );
}

export function ChartLegend({ items }: { items: Array<{ color: string; label: ReactNode }> }) {
  return (
    <div className="chart-legend">
      {items.map((item, index) => (
        <span key={index} className="chart-legend-item">
          <span className="swatch" style={{ background: item.color }} />
          {item.label}
        </span>
      ))}
    </div>
  );
}
