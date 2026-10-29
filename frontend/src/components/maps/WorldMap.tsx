import { useEffect, useMemo, useRef, useState } from "react";
import * as d3 from "d3";
import { feature } from "topojson-client";
import { T, CHART_FONT } from "../../theme";
import { usePalette } from "../../ThemeProvider";
import { Tip, Tooltip, useWidth } from "./shared";
import { countryName, flag } from "../../geo";
import { useI18n } from "../../i18n/I18nProvider";

type Props = {
  data: any;
  metric: "influence_sum" | "outlets" | "articles" | "journalists";
  showFlows: boolean;
  selected: string | null;
  onSelect: (code: string | null) => void;
};

let worldCache: any = null;

export default function WorldMap({ data, metric, showFlows, selected, onSelect }: Props) {
  const { t, intl, locale } = useI18n();
  const [wrapRef, width] = useWidth<HTMLDivElement>(900);
  const height = Math.round(width * 0.52);
  const svgRef = useRef<SVGSVGElement>(null);
  const [world, setWorld] = useState<any>(worldCache);
  const [tip, setTip] = useState<Tip>(null);
  const [transform, setTransform] = useState(d3.zoomIdentity);
  const palette = usePalette();

  useEffect(() => {
    if (world) return;
    fetch("/geo/countries-110m.json").then((r) => r.json()).then((topo) => {
      worldCache = feature(topo, topo.objects.countries);
      setWorld(worldCache);
    });
  }, []);

  useEffect(() => {
    if (!svgRef.current) return;
    const svg = d3.select(svgRef.current);
    const zoom = d3.zoom<SVGSVGElement, unknown>().scaleExtent([1, 8]).translateExtent([[0, 0], [width, height]]).on("zoom", (e) => setTransform(e.transform));
    svg.call(zoom);
    return () => { svg.on(".zoom", null); };
  }, [width, height]);

  const projection = useMemo(() => d3.geoEqualEarth().fitExtent([[8, 8], [width - 8, height - 8]], { type: "Sphere" } as any), [width, height]);
  const path = useMemo(() => d3.geoPath(projection), [projection]);

  const countries: any[] = data?.countries || [];
  const byNumeric = useMemo(() => Object.fromEntries(countries.filter((c) => c.numeric).map((c) => [String(+c.numeric), c])), [countries]);
  const byCode = useMemo(() => Object.fromEntries(countries.map((c) => [c.code, c])), [countries]);
  const maxMetric = d3.max(countries, (c: any) => c[metric] as number) || 1;
  const shade = d3.scaleSqrt<string>().domain([0, maxMetric]).range([palette.tint, palette.accent]);
  const bubble = d3.scaleSqrt().domain([0, maxMetric]).range([2, 22]);
  const flowW = d3.scaleSqrt().domain([1, d3.max(data?.flows || [], (f: any) => f.weight as number) || 1]).range([0.6, 4]);

  const metricLabel = {
    influence_sum: t("map.influenceCumul"),
    outlets: t("common.outlets"),
    articles: t("map.arts30"),
    journalists: t("common.journalists"),
  }[metric];

  return (
    <div ref={wrapRef} className="relative select-none">
      <svg ref={svgRef} width={width} height={height} className="block cursor-grab active:cursor-grabbing" style={{ fontFamily: CHART_FONT }} onMouseLeave={() => setTip(null)}>
        <defs>
          <marker id="arrow-flow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="4" markerHeight="4" orient="auto">
            <path d="M 0 0 L 10 5 L 0 10 z" fill={T.ink} />
          </marker>
        </defs>
        <g transform={transform.toString()}>
          <path d={path({ type: "Sphere" } as any) || ""} fill={T.paper} stroke={T.hair} strokeWidth={0.8 / transform.k} />
          <path d={path(d3.geoGraticule10()) || ""} fill="none" stroke={T.hairSoft} strokeWidth={0.5 / transform.k} />
          {world?.features?.map((f: any) => {
            const c = byNumeric[String(+f.id)];
            const isSel = c && selected === c.code;
            return (
              <path key={f.id} d={path(f) || ""}
                fill={c ? shade(c[metric]) : T.surface}
                stroke={isSel ? T.ink : T.paper} strokeWidth={(isSel ? 1.4 : 0.5) / transform.k}
                className={c ? "cursor-pointer" : undefined}
                onMouseMove={(e) => c && setTip({ x: e.nativeEvent.offsetX, y: e.nativeEvent.offsetY, content: (
                  <><b>{flag(c.code)} {countryName(c.code)}</b> <span className="text-faint">{c.region}</span>
                    <div className="text-muted">{t("carto.worldTip", { o: c.outlets, s: c.outlets > 1 ? "s" : "", j: c.journalists, a: c.articles })}</div>
                    <div className="text-faint">{t("carto.worldTipInfl", { m: c.influence_mean, s: c.influence_sum })}</div>
                    <div className="mt-1 text-faint">{c.top.slice(0, 3).map((top: any) => top.name).join(" · ")}</div></>
                ) })}
                onClick={() => c && onSelect(selected === c.code ? null : c.code)} />
            );
          })}

          {showFlows && (data?.flows || []).map((f: any, i: number) => {
            const a = byCode[f.source]?.centroid, b = byCode[f.target]?.centroid;
            if (!a || !b) return null;
            const d = path({ type: "LineString", coordinates: [[a[1], a[0]], [b[1], b[0]]] } as any);
            const dimmed = selected && f.source !== selected && f.target !== selected;
            return <path key={i} d={d || ""} fill="none" stroke={T.ink} strokeOpacity={dimmed ? 0.06 : 0.45} strokeWidth={flowW(f.weight) / transform.k} markerEnd="url(#arrow-flow)" />;
          })}

          {countries.map((c) => {
            if (!c.centroid) return null;
            const p = projection([c.centroid[1], c.centroid[0]]);
            if (!p) return null;
            const r = bubble(c[metric]) / Math.sqrt(transform.k);
            return (
              <g key={c.code} className="cursor-pointer" onClick={() => onSelect(selected === c.code ? null : c.code)}
                onMouseMove={(e) => setTip({ x: e.nativeEvent.offsetX, y: e.nativeEvent.offsetY, content: (
                  <><b>{flag(c.code)} {countryName(c.code)}</b><div className="text-muted">{t("carto.metricValue", { n: c[metric], label: metricLabel })}</div></>
                ) })}>
                <circle cx={p[0]} cy={p[1]} r={r} fill={T.ink} fillOpacity={0.12} stroke={T.ink} strokeWidth={1 / transform.k} />
                {(c.outlets >= 2 || selected === c.code) && (
                  <text x={p[0]} y={p[1] - r - 3 / transform.k} textAnchor="middle" fontSize={9.5 / Math.sqrt(transform.k)} fill={T.ink} fontWeight={600}>{c.code}</text>
                )}
              </g>
            );
          })}
        </g>
        <text x={12} y={height - 10} fontSize={9.5} fill={T.faint}>
          {t("carto.worldFooter", { metric: metricLabel })}
        </text>
      </svg>
      <Tooltip tip={tip} />
    </div>
  );
}
