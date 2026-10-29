import { useMemo, useState } from "react";
import * as d3 from "d3";
import { T, CHART_FONT } from "../../theme";
import { Tip, Tooltip, useWidth } from "./shared";
import { FR_AXIS_ZONE, FR_SPECIFIC_AXES } from "../../geo";
import { useI18n } from "../../i18n/I18nProvider";

/**
 * Positions par axe — petits multiples. Une ligne par axe de cadrage, les médias
 * en points entre les deux pôles (position mesurée), la position déclarée en cercle
 * creux. Aucune projection : ce qu'on lit est ce qui a été mesuré.
 */

type Props = {
  data: any;
  selected: number | null;
  onSelect: (id: number | null) => void;
  showDeclared: boolean;
  showJournalists: boolean;
  countryFilter: string;
};

const ROW_H = 58;
const LEFT = 165;
const RIGHT = 170;

export default function AxisStrips({ data, selected, onSelect, showDeclared, showJournalists, countryFilter }: Props) {
  const { t, intl, locale } = useI18n();
  const [wrapRef, width] = useWidth<HTMLDivElement>(900);
  const [tip, setTip] = useState<Tip>(null);
  const [hover, setHover] = useState<number | null>(null);

  const axes: any[] = data?.axes || [];
  const allOutlets: any[] = data?.outlets || [];
  const outlets = useMemo(() => allOutlets.filter((o) => !countryFilter || o.country === countryFilter), [allOutlets, countryFilter]);
  const journalists: any[] = data?.journalists || [];

  const axisName = (k: string, fallback?: string) => {
    const v = t(`axis.${k}`);
    return v !== `axis.${k}` ? v : (fallback || k);
  };
  const confLabel = (c: string) => (c === "high" ? t("map.confHigh") : c === "medium" ? t("map.confMid") : t("map.confLow"));

  // Étendue commune à toutes les lignes (comparabilité), symétrique, bornée à ±1.
  const ext = useMemo(() => {
    const vals = outlets.flatMap((o) => axes.flatMap((a) => [Math.abs(o.real[a.axis] ?? 0), showDeclared ? Math.abs(o.official[a.axis] ?? 0) : 0]));
    return Math.min(1, Math.max(0.25, (d3.quantile(vals.sort(d3.ascending), 0.97) ?? 0.5) * 1.15));
  }, [outlets, axes, showDeclared]);

  const x = useMemo(() => d3.scaleLinear().domain([-ext, ext]).range([LEFT, width - RIGHT]).clamp(true), [ext, width]);
  const r = useMemo(() => d3.scaleSqrt().domain([0, Math.max(10, ...outlets.map((o) => o.influence))]).range([2.6, 6.5]), [outlets]);

  // Ordre des lignes : axes les plus discriminants (écart-type des positions mesurées) en premier.
  const rows = useMemo(() => {
    return axes.map((a) => {
      const vals = outlets.map((o) => o.real[a.axis] ?? 0);
      return { ...a, spread: d3.deviation(vals) ?? 0, mean: d3.mean(vals) ?? 0 };
    }).sort((a, b) => b.spread - a.spread);
  }, [axes, outlets]);

  // Essaim par ligne : les points qui se chevauchent sont décalés verticalement.
  const swarm = useMemo(() => {
    const out: Record<string, Record<number, number>> = {};
    for (const row of rows) {
      const nodes = outlets.map((o) => ({ id: o.id, x: x(o.real[row.axis] ?? 0), y: 0, r: r(o.influence) + 0.8 }));
      const sim = d3.forceSimulation(nodes as any)
        .force("x", d3.forceX((d: any) => d.x).strength(1))
        .force("y", d3.forceY(0).strength(0.08))
        .force("collide", d3.forceCollide((d: any) => d.r).iterations(3))
        .stop();
      for (let i = 0; i < 80; i++) sim.tick();
      out[row.axis] = Object.fromEntries(nodes.map((n: any) => [n.id, Math.max(-ROW_H / 2 + 8, Math.min(ROW_H / 2 - 8, n.y))]));
    }
    return out;
  }, [rows, outlets, x, r]);

  const height = rows.length * ROW_H + 40 + 26;
  const active = hover ?? selected;
  const activeOutlet = outlets.find((o) => o.id === active) || allOutlets.find((o) => o.id === active);
  const activeJournalists = showJournalists && active !== null ? journalists.filter((j) => j.outlet_id === active && j.real) : [];

  const poleName = (axis: string, side: "neg" | "pos", fallback: string) => {
    const k = `pole.${axis}_${side}`;
    const v = t(k);
    return v === k ? fallback : v;
  };

  return (
    <div ref={wrapRef} className="relative select-none">
      <svg width={width} height={height} className="block" style={{ fontFamily: CHART_FONT }} onMouseLeave={() => { setTip(null); setHover(null); }}>
        {/* règle */}
        <g transform="translate(0,14)">
          {[-ext, -ext / 2, 0, ext / 2, ext].map((v, i) => (
            <text key={i} x={x(v)} y={0} textAnchor="middle" fontSize={9.5} fill={T.faint} className="num">{v > 0 ? "+" : ""}{v.toFixed(2)}</text>
          ))}
        </g>

        {rows.map((row, i) => {
          const cy = 40 + i * ROW_H + ROW_H / 2;
          const [neg, pos] = row.poles;
          const faded = FR_SPECIFIC_AXES.has(row.axis) && countryFilter && !FR_AXIS_ZONE.has(countryFilter);
          const label = axisName(row.axis, row.label);
          return (
            <g key={row.axis} transform={`translate(0,${cy})`} opacity={faded ? 0.28 : 1}>
              {/* bande alternée */}
              {i % 2 === 0 && <rect x={0} y={-ROW_H / 2} width={width} height={ROW_H} fill={T.surface} opacity={0.5} />}
              {/* pôles */}
              <text x={LEFT - 12} y={-7} textAnchor="end" fontSize={10} fontWeight={700} letterSpacing="0.12em" fill={T.accentStrong}>{label.toUpperCase()}</text>
              <text x={LEFT - 12} y={8} textAnchor="end" fontSize={9.5} fill={T.muted}>◂ {poleName(row.axis, "neg", neg)}</text>
              <text x={width - RIGHT + 12} y={1} dy="0.35em" fontSize={9.5} fill={T.muted}>{poleName(row.axis, "pos", pos)} ▸</text>
              {/* piste */}
              <line x1={x(-ext)} x2={x(ext)} y1={0} y2={0} stroke={T.hair} />
              <line x1={x(0)} x2={x(0)} y1={-ROW_H / 2 + 4} y2={ROW_H / 2 - 4} stroke={T.faint} strokeDasharray="2 2" />
              {/* moyenne du paysage */}
              <line x1={x(row.mean)} x2={x(row.mean)} y1={-7} y2={7} stroke={T.accent} strokeWidth={1.5} opacity={0.6} />

              {/* déclaré → mesuré pour le média actif */}
              {activeOutlet && (
                <line x1={x(activeOutlet.official[row.axis] ?? 0)} x2={x(activeOutlet.real[row.axis] ?? 0)} y1={swarm[row.axis]?.[activeOutlet.id] ?? 0} y2={swarm[row.axis]?.[activeOutlet.id] ?? 0}
                  stroke={T.ink} strokeWidth={1} opacity={0.5} />
              )}

              {/* positions déclarées */}
              {showDeclared && outlets.map((o) => {
                const isActive = o.id === active;
                if (active !== null && !isActive) return null;
                return <circle key={`d${o.id}`} cx={x(o.official[row.axis] ?? 0)} cy={swarm[row.axis]?.[o.id] ?? 0} r={3.2} fill={T.paper} stroke={isActive ? T.ink : T.faint} strokeWidth={1} strokeDasharray={isActive ? undefined : "1.5 1.5"} />;
              })}

              {/* journalistes du média actif */}
              {activeJournalists.map((j) => (
                <circle key={`j${j.id}`} cx={x(j.real[row.axis] ?? 0)} cy={(swarm[row.axis]?.[j.outlet_id] ?? 0) + 11} r={2.4}
                  fill={j.deviation > 0.35 ? T.confidential : T.muted} fillOpacity={0.8}
                  onMouseMove={(e) => setTip({ x: e.nativeEvent.offsetX, y: e.nativeEvent.offsetY, content: <><b>{j.name}</b><div className="text-muted">{t("carto.jsAxisTip", { label, v: fmt(j.real[row.axis]), n: j.n_articles })}</div></> })} />
              ))}

              {/* positions mesurées */}
              {outlets.map((o) => {
                const v = o.real[row.axis] ?? 0;
                const isActive = o.id === active;
                const dimmed = active !== null && !isActive;
                const rr = r(o.influence);
                return (
                  <g key={o.id} className="cursor-pointer" opacity={dimmed ? 0.28 : 1}
                    onMouseEnter={() => setHover(o.id)}
                    onMouseMove={(e) => setTip({ x: e.nativeEvent.offsetX, y: e.nativeEvent.offsetY, content: (
                      <><b>{o.name}</b> <span className="text-faint">{o.country}</span>
                        <div className="text-muted">{t("carto.stripTip", { label, measured: t("series.measured"), m: fmt(v), declared: t("series.declared"), d: fmt(o.official[row.axis] ?? 0) })}</div>
                        <div className="text-faint">{t("carto.nArticlesConf", { n: o.n_articles, conf: confLabel(o.confidence) })}</div></>
                    ) })}
                    onClick={() => onSelect(selected === o.id ? null : o.id)}>
                    <circle cx={x(v)} cy={swarm[row.axis]?.[o.id] ?? 0} r={rr} fill={T.accent} fillOpacity={o.confidence === "low" ? 0.45 : 0.9}
                      stroke={isActive ? T.ink : T.paper} strokeWidth={isActive ? 1.75 : 1} />
                    {isActive && (
                      <text x={x(v)} y={(swarm[row.axis]?.[o.id] ?? 0) - rr - 3} textAnchor="middle" fontSize={10} fontWeight={600} fill={T.ink} stroke={T.paper} strokeWidth={3} paintOrder="stroke">{o.name}</text>
                    )}
                  </g>
                );
              })}
            </g>
          );
        })}

        <text x={LEFT} y={height - 8} fontSize={9.5} fill={T.faint}>
          {t("carto.stripsFooter")}
        </text>
      </svg>
      <Tooltip tip={tip} />
    </div>
  );
}

const fmt = (n: number) => (n > 0 ? "+" : "") + (n ?? 0).toFixed(2);
