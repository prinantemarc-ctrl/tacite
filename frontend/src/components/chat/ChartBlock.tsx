import { useRef } from "react";
import {
  ResponsiveContainer, BarChart, Bar, LineChart, Line, AreaChart, Area, ScatterChart, Scatter, RadarChart, Radar, PolarGrid, PolarAngleAxis, PolarRadiusAxis,
  PieChart, Pie, Cell, XAxis, YAxis, ZAxis, CartesianGrid, Tooltip, Legend, LabelList, ReferenceLine,
} from "recharts";
import { Download } from "lucide-react";
import { T, CHART_FONT, tooltipStyle, axisTick, SERIES } from "../../theme";
import { useI18n } from "../../i18n/I18nProvider";

export type ChartSpec = {
  type: "bar" | "hbar" | "line" | "area" | "scatter" | "radar" | "axis_strip" | "pie";
  title: string; subtitle?: string; data: any[]; x?: string; y?: string; label?: string; series?: string[]; domain?: [number, number]; unit?: string; note?: string;
};

type TFn = (key: string, vars?: Record<string, string | number>) => string;

function inferSeries(spec: ChartSpec): string[] {
  if (spec.series?.length) return spec.series;
  const xKey = inferX(spec);
  const keys = new Set<string>();
  for (const row of spec.data || []) {
    if (!row || typeof row !== "object") continue;
    for (const [k, v] of Object.entries(row)) {
      if (k === xKey || k === spec.label || k === "axis") continue;
      if (typeof v === "number" || (typeof v === "string" && v.trim() !== "" && !Number.isNaN(Number(v)))) {
        keys.add(k);
      }
    }
  }
  return Array.from(keys).slice(0, 4);
}
function inferX(spec: ChartSpec): string {
  if (spec.x) return spec.x;
  const first = spec.data[0] || {};
  for (const cand of ["name", "outlet", "label", "media", "journalist", "country", "date"]) {
    if (typeof first[cand] === "string") return cand;
  }
  return Object.keys(first).find((k) => k !== "axis" && typeof first[k] === "string") || Object.keys(first)[0];
}
const fmt = (v: any, intl: string) => (typeof v === "number" ? (Math.abs(v) < 10 ? v.toFixed(2).replace(/\.?0+$/, "") : Math.round(v).toLocaleString(intl)) : v);

function axisLabel(t: TFn, k: string) {
  if (!k || k === "undefined") return "Score";
  const v = t(`axis.${k}`);
  return v !== `axis.${k}` ? v : k;
}

export default function ChartBlock({ spec }: { spec: ChartSpec }) {
  const { t, intl, locale } = useI18n();
  const ref = useRef<HTMLDivElement>(null);
  if (!spec || !Array.isArray(spec.data) || spec.data.length === 0) {
    return spec?.title ? <div className="my-3 text-[12px] text-faint">{spec.title}</div> : null;
  }
  const download = () => {
    const svg = ref.current?.querySelector("svg");
    if (!svg) return;
    const s = new XMLSerializer().serializeToString(svg);
    const blob = new Blob([`<?xml version="1.0"?>${s}`], { type: "image/svg+xml" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = `${spec.title.replace(/[^\w\-]+/g, "_")}.svg`; a.click();
  };
  const h = spec.type === "hbar" || spec.type === "axis_strip" ? Math.max(180, Math.min(520, 28 * (spec.type === "axis_strip" ? new Set(spec.data.map((d) => d.axis)).size * 3 : spec.data.length) + 40)) : spec.type === "radar" ? 320 : 260;
  return (
    <div className="my-3 rounded-kit border border-hair bg-paper p-3">
      <div className="mb-2 flex items-start justify-between gap-3">
        <div><div className="label">{spec.title}</div>{spec.subtitle && <div className="text-[11px] text-faint">{spec.subtitle}</div>}</div>
        <button onClick={download} className="text-faint hover:text-ink" title={t("carto.downloadSvg")}><Download size={13} /></button>
      </div>
      <div ref={ref} style={{ height: h, fontFamily: CHART_FONT }}>
        <ResponsiveContainer width="100%" height="100%">{render(spec, t, intl)}</ResponsiveContainer>
      </div>
      {spec.note && <div className="mt-1.5 text-[11px] text-faint">{spec.note}</div>}
    </div>
  );
}

function render(spec: ChartSpec, t: TFn, intl: string) {
  const series = inferSeries(spec);
  const x = inferX(spec);
  const dom = spec.domain as any;
  const common = { margin: { top: 8, right: 16, bottom: 4, left: 4 } };
  const f = (v: any) => fmt(v, intl);
  switch (spec.type) {
    case "bar":
      return (
        <BarChart data={spec.data} {...common}>
          <CartesianGrid vertical={false} stroke={T.hairSoft} />
          <XAxis dataKey={x} tick={axisTick} axisLine={{ stroke: T.hair }} tickLine={false} interval={0} angle={spec.data.length > 8 ? -25 : 0} height={spec.data.length > 8 ? 60 : 30} textAnchor={spec.data.length > 8 ? "end" : "middle"} />
          <YAxis tick={axisTick} axisLine={false} tickLine={false} domain={dom} width={44} tickFormatter={f} />
          <Tooltip contentStyle={tooltipStyle} formatter={(v: any) => f(v)} cursor={{ fill: T.tint }} />
          {series.length > 1 && <Legend wrapperStyle={{ fontSize: 11 }} />}
          {dom && dom[0] < 0 && <ReferenceLine y={0} stroke={T.faint} />}
          {series.map((s, i) => <Bar key={s} dataKey={s} fill={SERIES[(i + 1) % SERIES.length]} radius={[2, 2, 0, 0]} maxBarSize={40} />)}
        </BarChart>
      );
    case "hbar":
      return (
        <BarChart data={spec.data} layout="vertical" {...common} margin={{ top: 4, right: 40, bottom: 4, left: 8 }}>
          <CartesianGrid horizontal={false} stroke={T.hairSoft} />
          <XAxis type="number" tick={axisTick} axisLine={false} tickLine={false} domain={dom} tickFormatter={f} />
          <YAxis type="category" dataKey={x} tick={{ ...axisTick, fill: T.ink }} axisLine={false} tickLine={false} width={150} />
          <Tooltip contentStyle={tooltipStyle} formatter={(v: any) => f(v)} cursor={{ fill: T.tint }} />
          {series.length > 1 && <Legend wrapperStyle={{ fontSize: 11 }} />}
          {dom && dom[0] < 0 && <ReferenceLine x={0} stroke={T.faint} />}
          {series.map((s, i) => (
            <Bar key={s} dataKey={s} fill={SERIES[(i + 1) % SERIES.length]} radius={[0, 2, 2, 0]} maxBarSize={18}>
              {series.length === 1 && spec.data.map((d, j) => <Cell key={j} fill={typeof d[s] === "number" && d[s] < 0 ? T.confidential : SERIES[1]} />)}
              {series.length === 1 && <LabelList dataKey={s} position="right" formatter={f} style={{ fontSize: 10.5, fill: T.muted }} />}
            </Bar>
          ))}
        </BarChart>
      );
    case "line":
    case "area": {
      const C: any = spec.type === "line" ? LineChart : AreaChart;
      return (
        <C data={spec.data} {...common}>
          <CartesianGrid vertical={false} stroke={T.hairSoft} />
          <XAxis dataKey={x} tick={axisTick} axisLine={{ stroke: T.hair }} tickLine={false} minTickGap={24} />
          <YAxis tick={axisTick} axisLine={false} tickLine={false} domain={dom} width={44} tickFormatter={f} />
          <Tooltip contentStyle={tooltipStyle} formatter={(v: any) => f(v)} />
          {series.length > 1 && <Legend wrapperStyle={{ fontSize: 11 }} />}
          {dom && dom[0] < 0 && <ReferenceLine y={0} stroke={T.faint} />}
          {series.map((s, i) => spec.type === "line"
            ? <Line key={s} type="monotone" dataKey={s} stroke={SERIES[(i + 1) % SERIES.length]} strokeWidth={1.75} dot={{ r: 2.5 }} activeDot={{ r: 4 }} />
            : <Area key={s} type="monotone" dataKey={s} stroke={SERIES[(i + 1) % SERIES.length]} fill={SERIES[(i + 1) % SERIES.length]} fillOpacity={0.15} strokeWidth={1.5} />)}
        </C>
      );
    }
    case "scatter": {
      const xk = spec.x || "x", yk = spec.y || "y", lk = spec.label || "name";
      return (
        <ScatterChart {...common} margin={{ top: 8, right: 16, bottom: 8, left: 4 }}>
          <CartesianGrid stroke={T.hairSoft} />
          <XAxis dataKey={xk} type="number" name={xk} tick={axisTick} axisLine={{ stroke: T.hair }} tickLine={false} domain={dom} tickFormatter={f} label={{ value: xk, position: "insideBottomRight", offset: -4, fontSize: 10.5, fill: T.faint }} />
          <YAxis dataKey={yk} type="number" name={yk} tick={axisTick} axisLine={false} tickLine={false} width={44} tickFormatter={f} label={{ value: yk, angle: -90, position: "insideLeft", fontSize: 10.5, fill: T.faint }} />
          <ZAxis range={[40, 40]} />
          <Tooltip contentStyle={tooltipStyle} cursor={{ strokeDasharray: "3 3" }} formatter={(v: any) => f(v)} labelFormatter={() => ""} content={({ payload }) => payload?.length ? <div style={tooltipStyle}><b>{payload[0].payload[lk]}</b><div>{xk} {f(payload[0].payload[xk])} · {yk} {f(payload[0].payload[yk])}</div></div> : null} />
          {dom && dom[0] < 0 && <ReferenceLine x={0} stroke={T.faint} />}
          <Scatter data={spec.data} fill={T.accent}>
            <LabelList dataKey={lk} position="top" style={{ fontSize: 10, fill: T.muted }} />
          </Scatter>
        </ScatterChart>
      );
    }
    case "radar": {
      const data = spec.data.map((d) => ({ ...d, axis: axisLabel(t, d.axis) }));
      return (
        <RadarChart data={data} outerRadius="72%">
          <PolarGrid stroke={T.hair} />
          <PolarAngleAxis dataKey="axis" tick={{ fill: T.muted, fontSize: 10.5, fontFamily: CHART_FONT }} />
          <PolarRadiusAxis domain={dom || [-1, 1]} tick={false} axisLine={false} />
          <Tooltip contentStyle={tooltipStyle} formatter={(v: any) => f(v)} />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          {series.map((s, i) => <Radar key={s} name={s} dataKey={s} stroke={i === 0 ? T.ink : SERIES[i % SERIES.length]} fill={i === 0 ? T.ink : SERIES[i % SERIES.length]} fillOpacity={i === 0 ? 0.04 : 0.18} strokeWidth={1.5} strokeDasharray={i === 0 && series.length > 1 ? "5 3" : undefined} />)}
        </RadarChart>
      );
    }
    case "axis_strip": {
      // Si un seul axe (ou axe omis par le LLM), un hbar horizontal est beaucoup plus lisible : chaque média a sa ligne nommée !
      const rawAxes = Array.from(new Set(spec.data.map((d) => d.axis).filter(Boolean)));
      if (rawAxes.length <= 1) {
        const nameKey = inferX(spec);
        const valKey = spec.y || inferSeries(spec)[0] || "value";
        const barData = spec.data.map((d) => ({
          ...d,
          [nameKey]: d[nameKey] || d.name || d.outlet || d.label || "—",
          [valKey]: Number(d[valKey] ?? d.value ?? d.score ?? 0),
        }));
        return (
          <BarChart data={barData} layout="vertical" {...common} margin={{ top: 4, right: 44, bottom: 4, left: 8 }}>
            <CartesianGrid horizontal={false} stroke={T.hairSoft} />
            <XAxis type="number" tick={axisTick} axisLine={false} tickLine={false} domain={dom || [-1, 1]} tickFormatter={f} />
            <YAxis type="category" dataKey={nameKey} tick={{ ...axisTick, fill: T.ink }} axisLine={false} tickLine={false} width={150} />
            <Tooltip contentStyle={tooltipStyle} formatter={(v: any) => f(v)} cursor={{ fill: T.tint }} />
            <ReferenceLine x={0} stroke={T.faint} />
            <Bar dataKey={valKey} fill={SERIES[1]} radius={[0, 2, 2, 0]} maxBarSize={18}>
              {barData.map((d, j) => <Cell key={j} fill={typeof d[valKey] === "number" && d[valKey] < 0 ? T.confidential : SERIES[1]} />)}
              <LabelList dataKey={valKey} position="right" formatter={f} style={{ fontSize: 10.5, fill: T.muted }} />
            </Bar>
          </BarChart>
        );
      }
      const axes = rawAxes;
      const pts = spec.data.map((d) => ({
        ...d,
        axis: d.axis || axes[0],
        value: Number(d.value ?? d.score ?? 0),
        yi: Math.max(0, axes.indexOf(d.axis || axes[0])),
        label: `${d.name || d.outlet || ""}`,
        s: d.size || 40,
      }));
      return (
        <ScatterChart margin={{ top: 14, right: 24, bottom: 8, left: 8 }}>
          <CartesianGrid horizontal stroke={T.hairSoft} />
          <XAxis type="number" dataKey="value" domain={dom || [-1, 1]} tick={axisTick} axisLine={{ stroke: T.hair }} tickLine={false} tickFormatter={f} />
          <YAxis type="number" dataKey="yi" domain={[-0.5, axes.length - 0.5]} ticks={axes.map((_, i) => i)} tickFormatter={(i) => axisLabel(t, axes[i])} tick={{ ...axisTick, fill: T.ink }} axisLine={false} tickLine={false} width={110} reversed />
          <ZAxis dataKey="s" range={[36, 180]} />
          <ReferenceLine x={0} stroke={T.faint} strokeDasharray="2 2" />
          <Tooltip contentStyle={tooltipStyle} cursor={false} content={({ payload }) => payload?.length ? <div style={tooltipStyle}><b>{payload[0].payload.name || payload[0].payload.outlet}</b><div>{axisLabel(t, payload[0].payload.axis)} : {f(payload[0].payload.value)}{payload[0].payload.declared !== undefined ? t("carto.chartDeclared", { declared: t("series.declared"), v: f(payload[0].payload.declared) }) : ""}</div></div> : null} />
          {pts.some((p) => p.declared !== undefined) && <Scatter data={pts.filter((p) => p.declared !== undefined).map((p) => ({ ...p, value: Number(p.declared) }))} fill={T.paper} stroke={T.faint} shape="circle" />}
          <Scatter data={pts} fill={T.accent} fillOpacity={0.85}>
            <LabelList dataKey="label" position="top" style={{ fontSize: 9.5, fill: T.muted }} />
          </Scatter>
        </ScatterChart>
      );
    }
    case "pie": {
      const v = series[0] || "value";
      return (
        <PieChart>
          <Pie data={spec.data} dataKey={v} nameKey={x} innerRadius="45%" outerRadius="78%" paddingAngle={1} stroke={T.paper}>
            {spec.data.map((_, i) => <Cell key={i} fill={[T.accent, T.ink, T.muted, T.faint, T.accentStrong, T.hair][i % 6]} />)}
            <LabelList dataKey={x} position="outside" style={{ fontSize: 10.5, fill: T.muted }} />
          </Pie>
          <Tooltip contentStyle={tooltipStyle} formatter={(val: any) => f(val)} />
        </PieChart>
      );
    }
    default:
      return <div className="text-[12px] text-faint">{t("carto.unknownChart")}</div>;
  }
}
