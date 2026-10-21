"use client";

import React from "react";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  LineChart,
  Line,
  AreaChart,
  Area,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from "recharts";
import { ChartConfig, QueryDataRow } from "../../types/chat";

interface DataChartProps {
  config: ChartConfig;
  data: QueryDataRow[];
}

const PRIMARY_YELLOW = "#FEC50B";

// DataPilot Vibrant Color Palette for multi-slice donuts
const DONUT_COLORS = [
  "#FEC50B", // Primary Gold
  "#38BDF8", // Cyan
  "#818CF8", // Indigo
  "#34D399", // Emerald
  "#FB7185", // Rose
  "#FB923C", // Amber
  "#C084FC", // Purple
  "#2DD4BF", // Teal
];

// Helper to format values for currency vs regular numbers
const formatValue = (val: unknown, keyName: string = ""): string => {
  if (typeof val !== "number") return String(val ?? "");

  const k = keyName.toLowerCase();
  const isCurrency =
    k.includes("revenue") ||
    k.includes("spend") ||
    k.includes("price") ||
    k.includes("amount") ||
    k.includes("cost") ||
    k.includes("refund") ||
    k.includes("discount");

  if (!isCurrency) {
    return val.toLocaleString("en-IN");
  }

  if (Math.abs(val) >= 10000000) {
    return `₹${(val / 10000000).toFixed(2)} Cr`;
  }
  if (Math.abs(val) >= 100000) {
    return `₹${(val / 100000).toFixed(2)} L`;
  }
  return `₹${val.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
};

// Compact Axis Label Formatter
const formatAxisValue = (val: unknown): string => {
  if (typeof val !== "number") {
    const s = String(val ?? "");
    return s.length > 14 ? `${s.slice(0, 12)}...` : s;
  }
  if (Math.abs(val) >= 10000000) return `₹${(val / 10000000).toFixed(1)}Cr`;
  if (Math.abs(val) >= 100000) return `₹${(val / 100000).toFixed(0)}L`;
  if (Math.abs(val) >= 1000) return `₹${(val / 1000).toFixed(0)}k`;
  return String(val);
};

interface TooltipProps {
  active?: boolean;
  payload?: Array<{
    value?: unknown;
    name?: string;
    color?: string;
    dataKey?: string;
    payload?: { name?: string; [key: string]: unknown };
  }>;
  label?: string;
  yKey?: string;
}

// Custom Dark Tooltip
const CustomTooltip = ({ active, payload, label, yKey }: TooltipProps) => {
  if (active && payload && payload.length) {
    const item = payload[0];
    const rawVal = item.value;
    const name = label || item.name || item.payload?.name || "";

    return (
      <div className="bg-[#1E222B] border border-[#323849] rounded-xl px-3.5 py-2.5 shadow-xl text-xs backdrop-blur-md">
        <div className="text-[#94A3B8] font-medium mb-1 truncate max-w-[220px]">
          {name}
        </div>
        <div className="text-white font-semibold font-mono text-[13px] flex items-center gap-1.5">
          <span
            className="w-2 h-2 rounded-full inline-block"
            style={{ backgroundColor: PRIMARY_YELLOW }}
          />
          <span>{formatValue(rawVal, yKey || item.dataKey)}</span>
        </div>
      </div>
    );
  }
  return null;
};

export const DataChart: React.FC<DataChartProps> = ({ config, data }) => {
  if (!data || data.length === 0) return null;

  const type = config.type || "bar";
  const xKey = config.x_key || Object.keys(data[0])[0];
  const yKey =
    config.y_key ||
    Object.keys(data[0]).find(
      (k) => typeof data[0][k] === "number" && k !== xKey
    ) ||
    Object.keys(data[0])[1];

  const chartData = data.map((d) => ({
    ...d,
    // Preserve missing values as gaps; decimal strings become plotting numbers.
    [yKey]: d[yKey] === null || d[yKey] === undefined || d[yKey] === ""
      ? null
      : Number.isFinite(Number(d[yKey])) ? Number(d[yKey]) : null,
  }));

  const cleanTitle =
    config.title ||
    `${yKey.replace(/_/g, " ").toUpperCase()} by ${xKey
      .replace(/_/g, " ")
      .toUpperCase()}`;

  return (
    <div className="w-full bg-[#181A20] border border-[#2E3444] rounded-xl p-4 mt-2 max-w-full">
      <div className="flex items-center justify-between mb-3 px-1">
        <h4 className="text-xs font-semibold text-[#CBD5E1] uppercase tracking-wider font-mono">
          {cleanTitle}
        </h4>
        <span className="text-[10px] text-[#94A3B8] font-mono uppercase bg-[#1E222B] border border-[#2E3444] px-2 py-0.5 rounded">
          {type.toUpperCase()} CHART
        </span>
      </div>

      <div className="h-64 w-full">
        <ResponsiveContainer width="100%" height="100%">
          {type === "line" ? (
            <LineChart
              data={chartData}
              margin={{ top: 10, right: 20, left: 0, bottom: 25 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#2E3444" opacity={0.6} />
              <XAxis
                dataKey={xKey}
                stroke="#64748B"
                fontSize={11}
                tickLine={false}
                dy={10}
                tickFormatter={(val) => {
                  const s = String(val ?? "");
                  return s.length > 12 ? `${s.slice(0, 10)}...` : s;
                }}
              />
              <YAxis
                stroke="#64748B"
                fontSize={11}
                tickLine={false}
                tickFormatter={formatAxisValue}
                width={50}
              />
              <Tooltip
                content={<CustomTooltip yKey={yKey} />}
                cursor={{ stroke: "#3E4557", strokeWidth: 1, strokeDasharray: "4 4" }}
              />
              <Line
                type="monotone"
                dataKey={yKey}
                stroke={PRIMARY_YELLOW}
                strokeWidth={2.5}
                dot={{ fill: "#181A20", stroke: PRIMARY_YELLOW, strokeWidth: 2, r: 4 }}
                activeDot={{ r: 6, fill: PRIMARY_YELLOW }}
              />
            </LineChart>
          ) : type === "area" ? (
            <AreaChart
              data={chartData}
              margin={{ top: 10, right: 20, left: 0, bottom: 25 }}
            >
              <defs>
                <linearGradient id="areaGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor={PRIMARY_YELLOW} stopOpacity={0.4} />
                  <stop offset="95%" stopColor={PRIMARY_YELLOW} stopOpacity={0.0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#2E3444" opacity={0.6} />
              <XAxis
                dataKey={xKey}
                stroke="#64748B"
                fontSize={11}
                tickLine={false}
                dy={10}
                tickFormatter={(val) => {
                  const s = String(val ?? "");
                  return s.length > 12 ? `${s.slice(0, 10)}...` : s;
                }}
              />
              <YAxis
                stroke="#64748B"
                fontSize={11}
                tickLine={false}
                tickFormatter={formatAxisValue}
                width={50}
              />
              <Tooltip
                content={<CustomTooltip yKey={yKey} />}
                cursor={{ stroke: "#3E4557", strokeWidth: 1, strokeDasharray: "4 4" }}
              />
              <Area
                type="monotone"
                dataKey={yKey}
                stroke={PRIMARY_YELLOW}
                strokeWidth={2}
                fillOpacity={1}
                fill="url(#areaGradient)"
              />
            </AreaChart>
          ) : type === "donut" ? (
            <PieChart>
              <Tooltip content={<CustomTooltip yKey={yKey} />} />
              <Legend
                formatter={(value) => (
                  <span className="text-xs text-[#CBD5E1] ml-1">{value}</span>
                )}
              />
              <Pie
                data={chartData}
                dataKey={yKey}
                nameKey={xKey}
                cx="50%"
                cy="50%"
                innerRadius={50}
                outerRadius={80}
                paddingAngle={4}
              >
                {chartData.map((_, index) => (
                  <Cell
                    key={`cell-${index}`}
                    fill={DONUT_COLORS[index % DONUT_COLORS.length]}
                    stroke="#181A20"
                    strokeWidth={2}
                  />
                ))}
              </Pie>
            </PieChart>
          ) : (
            // Default: Bar Chart in unified signature yellow
            <BarChart
              data={chartData}
              margin={{ top: 10, right: 20, left: 0, bottom: 25 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#2E3444" opacity={0.6} />
              <XAxis
                dataKey={xKey}
                stroke="#64748B"
                fontSize={11}
                tickLine={false}
                dy={10}
                tickFormatter={(val) => {
                  const s = String(val ?? "");
                  return s.length > 12 ? `${s.slice(0, 10)}...` : s;
                }}
              />
              <YAxis
                stroke="#64748B"
                fontSize={11}
                tickLine={false}
                tickFormatter={formatAxisValue}
                width={50}
              />
              <Tooltip content={<CustomTooltip yKey={yKey} />} cursor={false} />
              <Bar dataKey={yKey} fill={PRIMARY_YELLOW} radius={[6, 6, 0, 0]} />
            </BarChart>
          )}
        </ResponsiveContainer>
      </div>
    </div>
  );
};
