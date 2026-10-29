import { useEffect, useMemo, useRef, useState } from "react";
import * as d3 from "d3";
import { T, CHART_FONT } from "../../theme";
import { Tip, Tooltip, clusterStyle, useWidth } from "./shared";
import { useI18n } from "../../i18n/I18nProvider";

type Props = {
  data: any;
  showJournalists: boolean;
  showOfficial: boolean;
  showAxes: boolean;
  focusCluster: number | null;
  onSelectOutlet?: (id: number) => void;
  onSelectJournalist?: (id: number) => void;
};

export default function LandscapeMap({ data, showJournalists, showOfficial, showAxes, focusCluster, onSelectOutlet, onSelectJournalist }: Props) {
  const { t, intl, locale } = useI18n();
  const [wrapRef, width] = useWidth<HTMLDivElement>(900);
  const height = Math.max(460, Math.round(width * 0.58));
  const svgRef = useRef<SVGSVGElement>(null);
  const [tip, setTip] = useState<Tip>(null);
  const [transform, setTransform] = useState(d3.zoomIdentity);

  const outlets: any[] = data?.outlets || [];
  const journalists: any[] = data?.journalists || [];
  const clusters: any[] = data?.clusters || [];
  const axes: any[] = data?.axes || [];

  const confLabel = (c: string) => (c === "high" ? t("map.confHigh") : c === "medium" ? t("map.confMid") : t("map.confLow"));

  const { x, y, r, labelMin } = useMemo(() => {
    // Cadre = positions réelles des médias documentés (élargi de 40 %) ; le reste est rabattu au bord.
    const solid = outlets.filter((o) => o.confidence !== "low");
    const base = solid.length >= 3 ? solid : outlets;
    // Étendue robuste : 85e centile des coordonnées absolues, ×1.6 — les quelques
    // médias atypiques sont rabattus au bord plutôt que d'écraser le centre.
    const abs = base.flatMap((o) => [Math.abs(o.x), Math.abs(o.y)]).sort((a, b) => a - b);
    const q = abs[Math.floor(abs.length * 0.85)] ?? 0.15;
    const ext = Math.max(0.12, q) * 1.6;
    const pad = 36;
    const side = Math.min(width, height);
    const x = d3.scaleLinear().domain([-ext, ext]).range([(width - side) / 2 + pad, (width + side) / 2 - pad]).clamp(true);
    const y = d3.scaleLinear().domain([-ext, ext]).range([(height + side) / 2 - pad, (height - side) / 2 + pad]).clamp(true);
    const r = d3.scaleSqrt().domain([0, Math.max(10, ...outlets.map((o) => o.influence))]).range([3, 16]);
    const infl = outlets.map((o) => o.influence).sort((a, b) => b - a);
    const labelMin = infl[Math.min(14, infl.length - 1)] ?? 0;
    return { x, y, r, labelMin };
  }, [outlets, width, height]);
  const [hover, setHover] = useState<number | null>(null);

  useEffect(() => {
    if (!svgRef.current) return;
    const svg = d3.select(svgRef.current);
    const zoom = d3.zoom<SVGSVGElement, unknown>().scaleExtent([0.6, 6]).on("zoom", (e) => setTransform(e.transform));
    svg.call(zoom);
    return () => { svg.on(".zoom", null); };
  }, []);

  const dim = (cluster: number | null | undefined) => focusCluster !== null && cluster !== focusCluster;
  const tx = (v: number) => transform.applyX(x(v));
  const ty = (v: number) => transform.applyY(y(v));

  const axisScale = 0.92 * (x.range()[1] - x.range()[0]) / 2;
  const clipped = (v: number) => Math.abs(v) > x.domain()[1];
  const showLabel = (o: any) => transform.k > 1.6 || o.influence >= labelMin || hover === o.id;

  const poleName = (axis: string, side: "neg" | "pos", fallback: string) => {
    const k = `pole.${axis}_${side}`;
    const v = t(k);
    return v === k ? fallback : v;
  };

  return (
    <div ref={wrapRef} className="relative select-none">
      <svg ref={svgRef} width={width} height={height} className="block cursor-grab active:cursor-grabbing" style={{ fontFamily: CHART_FONT }}
        onMouseLeave={() => setTip(null)}>
        <defs>
          <marker id="arrow-gap" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
            <path d="M 0 0 L 10 5 L 0 10 z" fill={T.faint} />
          </marker>
          <marker id="arrow-axis" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="4" markerHeight="4" orient="auto">
            <path d="M 0 0 L 10 5 L 0 10 z" fill={T.hair} />
          </marker>
        </defs>

        {/* croix centrale */}
        <line x1={tx(0)} x2={tx(0)} y1={0} y2={height} stroke={T.hairSoft} />
        <line y1={ty(0)} y2={ty(0)} x1={0} x2={width} stroke={T.hairSoft} />

        {/* axes de cadrage (loadings) */}
        {showAxes && axes.map((a) => {
          const len = Math.hypot(a.dx, a.dy);
          if (len < 0.12) return null;
          // Direction normalisée : l'étiquette est repoussée au bord du cadre, la ligne est d'autant plus dense que l'axe pèse
          const ex = tx(0) + (a.dx / len) * axisScale * transform.k;
          const ey = ty(0) - (a.dy / len) * axisScale * transform.k;
          return (
            <g key={a.axis} opacity={0.35 + Math.min(0.6, len)}>
              <line x1={tx(0)} y1={ty(0)} x2={ex} y2={ey} stroke={T.hair} strokeWidth={0.8} strokeDasharray="2 4" markerEnd="url(#arrow-axis)" />
              <text x={ex + (a.dx > 0 ? 4 : -4)} y={ey} dy="0.35em" textAnchor={a.dx > 0 ? "start" : "end"} fontSize={9.5} fill={T.faint} letterSpacing="0.08em">
                {poleName(a.axis, "pos", a.poles[1]).toUpperCase()}
              </text>
            </g>
          );
        })}

        {/* enveloppes de blocs */}
        {clusters.map((c) => {
          const pts = outlets.filter((o) => o.cluster === c.id).map((o) => [tx(o.x), ty(o.y)] as [number, number]);
          if (pts.length < 3) return null;
          const hull = d3.polygonHull(pts);
          if (!hull) return null;
          const st = clusterStyle(c.id);
          return (
            <path key={c.id} d={`M${hull.map((p) => p.join(",")).join("L")}Z`} fill={st.stroke} fillOpacity={dim(c.id) ? 0.02 : 0.06}
              stroke={st.stroke} strokeOpacity={dim(c.id) ? 0.15 : 0.35} strokeDasharray="4 3" strokeLinejoin="round" />
          );
        })}

        {/* journalistes */}
        {showJournalists && journalists.map((j) => {
          const parent = outlets.find((o) => o.id === j.outlet_id);
          const faded = dim(parent?.cluster);
          return (
            <circle key={`j${j.id}`} cx={tx(j.x)} cy={ty(j.y)} r={clipped(j.x) || clipped(j.y) ? 1.6 : 2.2} fill={j.deviation > 0.35 ? T.confidential : T.muted} fillOpacity={faded ? 0.15 : clipped(j.x) || clipped(j.y) ? 0.3 : 0.55}
              className="cursor-pointer"
              onMouseMove={(e) => setTip({ x: e.nativeEvent.offsetX, y: e.nativeEvent.offsetY, content: (
                <><b>{j.name}</b><div className="text-muted">{j.outlet_name} · {t("carto.nArt", { n: j.n_articles })}</div><div className="text-faint">{t("carto.jsMeta", { gap: t("map.gapFromOutlet"), d: j.deviation.toFixed(2), access: t("map.accessibility"), a: j.accessibility })}</div></>
              ) })}
              onClick={() => onSelectJournalist?.(j.id)} />
          );
        })}

        {/* flèches déclaré → mesuré */}
        {showOfficial && outlets.map((o) => (
          <g key={`g${o.id}`} opacity={dim(o.cluster) ? 0.15 : 0.7}>
            <line x1={tx(o.x_official)} y1={ty(o.y_official)} x2={tx(o.x)} y2={ty(o.y)} stroke={T.faint} strokeWidth={0.9} markerEnd="url(#arrow-gap)" />
            <circle cx={tx(o.x_official)} cy={ty(o.y_official)} r={3} fill={T.paper} stroke={T.faint} strokeWidth={1} strokeDasharray="2 1.5" />
          </g>
        ))}

        {/* médias */}
        {outlets.map((o) => {
          const st = clusterStyle(o.cluster);
          const faded = dim(o.cluster);
          const rr = r(o.influence);
          return (
            <g key={o.id} opacity={faded ? 0.2 : 1} className="cursor-pointer"
              onMouseEnter={() => setHover(o.id)} onMouseLeave={() => setHover(null)}
              onMouseMove={(e) => setTip({ x: e.nativeEvent.offsetX, y: e.nativeEvent.offsetY, content: (
                <>
                  <b>{o.name}</b> <span className="text-faint">{o.country}</span>
                  <div className="text-muted">{t("carto.outletTip", { inf: o.influence, n: o.n_articles, conf: confLabel(o.confidence) })}</div>
                  <div className="text-faint">{t("carto.gapMeasured", { g: o.gap.toFixed(2) })}{o.cluster !== null ? ` · ${t("carto.blocNamed", { block: t("map.block"), label: clusters.find((c) => c.id === o.cluster)?.label || o.cluster })}` : ""}</div>
                </>
              ) })}
              onClick={() => onSelectOutlet?.(o.id)}>
              <circle cx={tx(o.x)} cy={ty(o.y)} r={rr} fill={st.fill} stroke={st.stroke} strokeWidth={1.25} strokeDasharray={st.dash || undefined}
                fillOpacity={o.confidence === "low" ? 0.5 : 0.9} />
              {showLabel(o) && (
                <text x={tx(o.x) + rr + 3} y={ty(o.y)} dy="0.35em" fontSize={Math.min(11, 9 + rr / 4)} fill={T.ink} fontWeight={o.influence > 60 ? 600 : 400}
                  stroke={T.paper} strokeWidth={3} paintOrder="stroke">
                  {o.name}
                </text>
              )}
            </g>
          );
        })}

        {/* étiquettes de bloc */}
        {clusters.map((c) => (
          <text key={`l${c.id}`} x={tx(c.x)} y={ty(c.y) - 14} textAnchor="middle" fontSize={9.5} fontWeight={700} letterSpacing="0.14em"
            fill={clusterStyle(c.id).stroke} opacity={dim(c.id) ? 0.25 : 0.85}>
            {c.label.toUpperCase()}
          </text>
        ))}

        <text x={12} y={height - 10} fontSize={9.5} fill={T.faint}>
          {t("carto.pcaFooter", { pca: t("map.pca"), vars: data?.explained_variance?.map((v: number) => `${(v * 100).toFixed(0)} %`).join(" / ") })}
        </text>
      </svg>
      <Tooltip tip={tip} />
      {tip === null && outlets.length === 0 && <div className="absolute inset-0 flex items-center justify-center text-[12.5px] italic text-faint">{t("map.noData")}</div>}
    </div>
  );
}
