import { useMemo, useState } from "react";
import * as d3 from "d3";
import { T, CHART_FONT } from "../../theme";
import { usePalette } from "../../ThemeProvider";
import { Tip, Tooltip, useWidth } from "./shared";
import { useI18n } from "../../i18n/I18nProvider";

type Props = { data: any; focusOutlet: number | null; focusTopic: string | null };

export default function CorpusMap({ data, focusOutlet, focusTopic }: Props) {
  const { t, intl, locale } = useI18n();
  const [wrapRef, width] = useWidth<HTMLDivElement>(900);
  const height = Math.max(440, Math.round(width * 0.55));
  const [tip, setTip] = useState<Tip>(null);
  const palette = usePalette();
  const points: any[] = data?.points || [];

  const x = useMemo(() => d3.scaleLinear().domain([-1.05, 1.05]).range([24, width - 24]), [width]);
  const y = useMemo(() => d3.scaleLinear().domain([-1.05, 1.05]).range([height - 24, 24]), [height]);

  const contours = useMemo(() => {
    if (points.length < 20) return [];
    return d3.contourDensity<any>().x((p) => x(p.x)).y((p) => y(p.y)).size([width, height]).bandwidth(18).thresholds(10)(points);
  }, [points, x, y, width, height]);
  const maxDensity = d3.max(contours, (c) => c.value) || 1;
  const densityShade = d3.scaleLinear<string>().domain([0, maxDensity]).range([palette.paper, palette.accent]);

  // Étiquettes des thèmes : centre de masse des 12 thèmes les plus fréquents
  const labels = useMemo(() => {
    const groups = d3.rollups(points.filter((p) => p.topic), (v) => ({ n: v.length, x: d3.mean(v, (p) => p.x)!, y: d3.mean(v, (p) => p.y)!, sd: d3.deviation(v, (p) => Math.hypot(p.x, p.y)) || 0 }), (p) => p.topic);
    return groups.filter(([, g]) => g.n >= 6).sort((a, b) => b[1].n - a[1].n).slice(0, 14);
  }, [points]);

  const isFocused = (p: any) => (focusOutlet === null || p.outlet_id === focusOutlet) && (focusTopic === null || p.topic === focusTopic);
  const anyFocus = focusOutlet !== null || focusTopic !== null;

  const fmtDate = (iso?: string | null) => {
    if (!iso) return "";
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString(intl);
  };

  return (
    <div ref={wrapRef} className="relative select-none">
      <svg width={width} height={height} className="block" style={{ fontFamily: CHART_FONT }} onMouseLeave={() => setTip(null)}>
        {contours.map((c, i) => (
          <path key={i} d={d3.geoPath()(c) || ""} fill={densityShade(c.value)} fillOpacity={0.55} stroke={T.accent} strokeOpacity={0.15} strokeWidth={0.6} />
        ))}
        {points.map((p) => {
          const f = isFocused(p);
          return (
            <circle key={p.id} cx={x(p.x)} cy={y(p.y)} r={anyFocus && f ? 2.6 : 1.7}
              fill={anyFocus && f ? T.confidential : T.ink} fillOpacity={anyFocus ? (f ? 0.9 : 0.08) : 0.45}
              className="cursor-crosshair"
              onMouseMove={(e) => setTip({ x: e.nativeEvent.offsetX, y: e.nativeEvent.offsetY, content: (
                <><b>{p.title}</b><div className="text-muted">{p.outlet} · {fmtDate(p.date)}</div><div className="text-faint">{p.topic}{p.tone ? ` · ${p.tone}` : ""}</div></>
              ) })} />
          );
        })}
        {labels.map(([topic, g]) => (
          <text key={topic} x={x(g.x)} y={y(g.y)} textAnchor="middle" fontSize={10} fontWeight={600} fill={T.accentStrong}
            stroke={T.paper} strokeWidth={3} paintOrder="stroke" opacity={focusTopic && focusTopic !== topic ? 0.25 : 0.95}>
            {topic}
          </text>
        ))}
        <text x={12} y={height - 8} fontSize={9.5} fill={T.faint}>
          {t("carto.corpusFooter", { n: points.length })}
        </text>
      </svg>
      <Tooltip tip={tip} />
    </div>
  );
}
