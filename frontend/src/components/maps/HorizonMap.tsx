import { useEffect, useMemo, useRef, useState } from "react";
import * as d3 from "d3";
import { feature } from "topojson-client";
import { CHART_FONT } from "../../theme";
import { usePalette } from "../../ThemeProvider";
import { countryName, flag } from "../../geo";
import { useI18n } from "../../i18n/I18nProvider";

export type HorizonCountry = {
  code: string;
  numeric?: string;
  centroid?: [number, number] | null;
  mark?: "conflict" | "rapprochement" | "probe" | "signal" | "economy" | "coalition";
  dossiers?: string[];
};

export type HorizonArc = {
  id: string;
  dossier_id?: string;
  source: string;
  target: string;
  kind: "conflict" | "rapprochement" | "probe";
  chance?: string;
  delay?: { fr: string; en: string };
  label?: { fr: string; en: string };
};

export type HorizonChoke = {
  id: string;
  choke_id?: string;
  name: string;
  lat: number;
  lon: number;
  delay?: string;
};

type Props = {
  countries: HorizonCountry[];
  arcs: HorizonArc[];
  chokepoints: HorizonChoke[];
  pulses: string[];
  blocs: { id: string; countries: string[]; label?: string }[];
  layer: "all" | "signals" | "blocs" | "economy";
  reading: "situation" | "forecast";
  mode: "flat" | "globe";
  selected: string | null;
  onSelect: (id: string | null) => void;
};

const TONE_HEX = {
  conflict: "#c45c56",
  rapprochement: "#3d7a62",
  probe: "#c4ae62",
  economy: "#d4a24c",
};

let worldCache: any = null;

function mix(from: string, to: string, t: number) {
  return d3.interpolateRgb(from, to)(Math.max(0, Math.min(1, t)));
}

/** Construit un arc courbe géodésique lisse (multi-segments sur grand cercle). */
function greatCircleCoords(a: [number, number], b: [number, number], steps = 28): [number, number][] {
  const interp = d3.geoInterpolate([a[1], a[0]], [b[1], b[0]]);
  const out: [number, number][] = [];
  for (let i = 0; i <= steps; i += 1) {
    out.push(interp(i / steps));
  }
  return out;
}

export default function HorizonMap({
  countries, arcs, chokepoints, pulses, blocs, layer, reading, mode, selected, onSelect,
}: Props) {
  const { t, locale } = useI18n();
  const palette = usePalette();
  const wrapRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(900);
  const height = Math.max(430, Math.round(width * (mode === "globe" ? 0.64 : 0.52)));
  const [world, setWorld] = useState<any>(worldCache);
  const [rotate, setRotate] = useState({ lambda: -18, phi: -24 });
  const drag = useRef<{ x: number; y: number; lambda: number; phi: number } | null>(null);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const apply = () => setWidth(el.clientWidth || 900);
    apply();
    const obs = new ResizeObserver(apply);
    obs.observe(el);
    return () => obs.disconnect();
  }, []);

  useEffect(() => {
    if (world) return;
    fetch("/geo/countries-110m.json")
      .then((r) => r.json())
      .then((topo) => {
        worldCache = feature(topo, topo.objects.countries);
        setWorld(worldCache);
      })
      .catch(() => undefined);
  }, [world]);

  const byNumeric = useMemo(
    () => Object.fromEntries(countries.filter((c) => c.numeric).map((c) => [String(+c.numeric!), c])),
    [countries],
  );
  const byCode = useMemo(
    () => Object.fromEntries(countries.map((c) => [c.code, c])),
    [countries],
  );

  // Auto-rotation douce du globe vers le théâtre sélectionné
  useEffect(() => {
    if (mode !== "globe" || !selected) return;
    const directCountry = byCode[selected];
    let targetCentroid: [number, number] | null | undefined = directCountry?.centroid;
    if (!targetCentroid) {
      const arc = arcs.find((a) => a.dossier_id === selected || a.id === selected);
      if (arc) {
        const c1 = byCode[arc.source]?.centroid;
        const c2 = byCode[arc.target]?.centroid;
        if (c1 && c2) targetCentroid = [(c1[0] + c2[0]) / 2, (c1[1] + c2[1]) / 2];
        else targetCentroid = c1 || c2;
      }
    }
    if (!targetCentroid) {
      const cp = chokepoints.find((c) => c.id === selected);
      if (cp) targetCentroid = [cp.lat, cp.lon];
    }
    if (targetCentroid) {
      setRotate({
        lambda: -targetCentroid[1],
        phi: Math.max(-72, Math.min(72, -targetCentroid[0] * 0.85)),
      });
    }
  }, [selected, mode, arcs, byCode, chokepoints]);

  const projection = useMemo(() => {
    const sphere = { type: "Sphere" } as any;
    if (mode === "globe") {
      return d3
        .geoOrthographic()
        .rotate([rotate.lambda, rotate.phi])
        .fitExtent([[14, 14], [width - 14, height - 14]], sphere);
    }
    return d3.geoEqualEarth().fitExtent([[8, 8], [width - 8, height - 8]], sphere);
  }, [mode, width, height, rotate]);

  const path = useMemo(() => d3.geoPath(projection), [projection]);
  const pulse = useMemo(() => new Set(pulses), [pulses]);
  const inBloc = useMemo(() => new Set(blocs.flatMap((b) => b.countries)), [blocs]);

  const isCountryInSelected = (c: HorizonCountry | undefined) => {
    if (!selected || !c) return true;
    if (c.code === selected) return true;
    if (c.dossiers?.includes(selected)) return true;
    return false;
  };

  const fillOf = (c: HorizonCountry | undefined) => {
    if (!c?.mark) return palette.surface;
    if (layer === "economy" && c.mark !== "economy") return palette.surface;
    if (layer === "blocs" && !inBloc.has(c.code) && c.mark !== "rapprochement") return palette.surface;
    if (layer === "signals" && !pulse.has(c.code) && c.mark !== "signal") return palette.surface;
    if (c.mark === "conflict") return mix(palette.surface, TONE_HEX.conflict, 0.62);
    if (c.mark === "rapprochement" || c.mark === "coalition") return mix(palette.surface, TONE_HEX.rapprochement, 0.62);
    if (c.mark === "economy") return mix(palette.surface, TONE_HEX.economy, 0.62);
    return mix(palette.surface, TONE_HEX.probe, 0.58);
  };

  const visibleArcs = useMemo(() => {
    return arcs.filter((a) => {
      if (reading === "forecast" && a.chance === "unlikely" && selected !== a.dossier_id) return false;
      if (layer === "blocs") return a.kind === "rapprochement";
      if (layer === "economy") return a.kind === "probe";
      if (layer === "signals") return pulse.has(a.source) || pulse.has(a.target);
      return true;
    });
  }, [arcs, layer, reading, pulse, selected]);

  // Vérifie si un point (lat, lon) est sur la face visible en mode Globe
  const projectVisible = (lat: number, lon: number): [number, number] | null => {
    if (mode === "globe") {
      const centerLon = -rotate.lambda;
      const centerLat = -rotate.phi;
      const angularDist = d3.geoDistance([lon, lat], [centerLon, centerLat]);
      if (angularDist > Math.PI * 0.48) return null;
    }
    return projection([lon, lat]);
  };

  return (
    <div ref={wrapRef} className="relative select-none">
      <svg
        width={width}
        height={height}
        className={mode === "globe" ? "block cursor-grab active:cursor-grabbing" : "block"}
        style={{ fontFamily: CHART_FONT }}
        role="img"
        aria-label={t("horizon.mapName")}
        onClick={() => onSelect(null)}
        onPointerDown={(e) => {
          if (mode !== "globe") return;
          (e.currentTarget as Element).setPointerCapture(e.pointerId);
          drag.current = { x: e.clientX, y: e.clientY, lambda: rotate.lambda, phi: rotate.phi };
        }}
        onPointerMove={(e) => {
          if (!drag.current) return;
          const lambda = drag.current.lambda + (e.clientX - drag.current.x) * 0.38;
          const phi = Math.max(-78, Math.min(78, drag.current.phi + (drag.current.y - e.clientY) * 0.28));
          setRotate({ lambda, phi });
        }}
        onPointerUp={() => { drag.current = null; }}
      >
        <style>{`
          @keyframes hz-dash { to { stroke-dashoffset: -28; } }
          @keyframes hz-pulse { 0% { r: 5px; opacity: 0.85; } 100% { r: 22px; opacity: 0; } }
          .hz-arc-conflict { animation: hz-dash 1.9s linear infinite; }
          .hz-arc-probe { animation: hz-dash 3.2s linear infinite; }
          .hz-pulse-ring { animation: hz-pulse 2.6s ease-out infinite; }
          @media (prefers-reduced-motion: reduce) {
            .hz-arc-conflict, .hz-arc-probe, .hz-pulse-ring { animation: none; }
          }
        `}</style>
        <defs>
          <marker id="hz-arrow-conflict" viewBox="0 0 10 10" refX="7" refY="5" markerWidth="5" markerHeight="5" orient="auto">
            <path d="M 0 1 L 10 5 L 0 9 z" fill={TONE_HEX.conflict} />
          </marker>
          <marker id="hz-arrow-approach" viewBox="0 0 10 10" refX="7" refY="5" markerWidth="5" markerHeight="5" orient="auto">
            <path d="M 0 1 L 10 5 L 0 9 z" fill={TONE_HEX.rapprochement} />
          </marker>
          <marker id="hz-arrow-probe" viewBox="0 0 10 10" refX="7" refY="5" markerWidth="5" markerHeight="5" orient="auto">
            <path d="M 0 1 L 10 5 L 0 9 z" fill={TONE_HEX.probe} />
          </marker>
        </defs>

        {/* Fond océanique & grille */}
        <path d={path({ type: "Sphere" } as any) || ""} fill={palette.paper} stroke={palette.hair} strokeWidth={1} />
        <path d={path(d3.geoGraticule10()) || ""} fill="none" stroke={palette.hairSoft} strokeWidth={0.45} strokeOpacity={0.65} />

        {/* Territoires nationaux */}
        {world?.features?.map((f: any) => {
          const c = byNumeric[String(+f.id)] as HorizonCountry | undefined;
          const highlighted = isCountryInSelected(c);
          return (
            <path
              key={f.id}
              d={path(f) || ""}
              fill={fillOf(c)}
              fillOpacity={selected && !highlighted ? 0.22 : 1}
              stroke={highlighted && selected && c ? palette.ink : palette.paper}
              strokeWidth={highlighted && selected && c ? 1.15 : 0.45}
              className={c ? "cursor-pointer transition-opacity" : undefined}
              onClick={(e) => {
                if (!c) return;
                e.stopPropagation();
                const targetId = c.dossiers?.[0] || c.code;
                onSelect(selected === targetId ? null : targetId);
              }}
            >
              {c && <title>{`${flag(c.code)} ${countryName(c.code)}`}</title>}
            </path>
          );
        })}

        {/* Constellations de coalitions / recompositions diplomatiques */}
        {(layer === "all" || layer === "blocs") && blocs.map((bloc) => {
          const pts = bloc.countries
            .map((code) => byCode[code]?.centroid)
            .filter((c): c is [number, number] => !!c)
            .map(([lat, lon]) => projectVisible(lat, lon))
            .filter((p): p is [number, number] => !!p);
          if (pts.length < 3) return null;
          const hull = d3.polygonHull(pts) || pts;
          const cx = d3.mean(hull, (p) => p[0]) || 0;
          const cy = d3.mean(hull, (p) => p[1]) || 0;
          const expanded = hull.map(([x, y]) => {
            const dx = x - cx;
            const dy = y - cy;
            const len = Math.hypot(dx, dy) || 1;
            return [x + (dx / len) * 16, y + (dy / len) * 16] as [number, number];
          });
          const dim = selected && selected !== bloc.id;
          const lineGen = d3.line().curve(d3.curveCatmullRomClosed.alpha(0.7));
          return (
            <g
              key={bloc.id}
              className="cursor-pointer"
              opacity={dim ? 0.18 : 0.95}
              onClick={(e) => { e.stopPropagation(); onSelect(selected === bloc.id ? null : bloc.id); }}
            >
              <path
                d={lineGen(expanded) || ""}
                fill={TONE_HEX.rapprochement}
                fillOpacity={0.11}
                stroke={TONE_HEX.rapprochement}
                strokeWidth={1.3}
                strokeDasharray="3 3"
              />
            </g>
          );
        })}

        {/* Arcs géopolitiques animés (grands cercles + flèches + délai) */}
        {visibleArcs.map((arc) => {
          const a = byCode[arc.source]?.centroid;
          const b = byCode[arc.target]?.centroid;
          if (!a || !b) return null;
          const coords = greatCircleCoords(a, b);
          const geoLine = { type: "LineString", coordinates: coords } as any;
          const d = path(geoLine);
          if (!d) return null;
          const ownerId = arc.dossier_id || arc.id;
          const isSel = selected === ownerId || selected === arc.source || selected === arc.target;
          const dim = selected && !isSel;
          const stroke = TONE_HEX[arc.kind];
          const marker =
            arc.kind === "conflict"
              ? "url(#hz-arrow-conflict)"
              : arc.kind === "rapprochement"
                ? "url(#hz-arrow-approach)"
                : "url(#hz-arrow-probe)";
          const midCoord = coords[Math.floor(coords.length / 2)];
          const midPx = projectVisible(midCoord[1], midCoord[0]);
          const delayTxt = reading === "forecast" ? (locale === "en" ? arc.delay?.en : arc.delay?.fr) : "";

          return (
            <g
              key={arc.id}
              className="cursor-pointer"
              opacity={dim ? 0.12 : 1}
              onClick={(e) => { e.stopPropagation(); onSelect(selected === ownerId ? null : ownerId); }}
            >
              {/* Halo doux sous l'arc actif */}
              {isSel && (
                <path d={d} fill="none" stroke={stroke} strokeOpacity={0.25} strokeWidth={6} />
              )}
              <path
                d={d}
                fill="none"
                className={arc.kind === "conflict" ? "hz-arc-conflict" : arc.kind === "probe" ? "hz-arc-probe" : undefined}
                stroke={stroke}
                strokeOpacity={0.92}
                strokeWidth={isSel ? 2.6 : arc.chance === "likely" ? 2.2 : 1.65}
                strokeDasharray={arc.kind === "conflict" ? "7 5" : arc.kind === "probe" ? "4 4" : undefined}
                markerEnd={marker}
              >
                <title>{locale === "en" ? arc.label?.en : arc.label?.fr}</title>
              </path>
              {delayTxt && midPx && (isSel || arc.chance === "likely") && (
                <g transform={`translate(${midPx[0]}, ${midPx[1]})`}>
                  <rect x={-18} y={-8} width={36} height={15} rx={3} fill={palette.paper} fillOpacity={0.9} stroke={stroke} strokeWidth={0.9} />
                  <text y={3} textAnchor="middle" fontSize="9.5" fontWeight={600} fill={palette.ink}>{delayTxt}</text>
                </g>
              )}
            </g>
          );
        })}

        {/* Nœuds capitales / États actifs */}
        {countries.map((c) => {
          if (!c.centroid || !c.mark) return null;
          const xy = projectVisible(c.centroid[0], c.centroid[1]);
          if (!xy) return null;
          const highlighted = isCountryInSelected(c);
          if (selected && !highlighted) return null;
          const dotColor =
            c.mark === "conflict"
              ? TONE_HEX.conflict
              : c.mark === "rapprochement" || c.mark === "coalition"
                ? TONE_HEX.rapprochement
                : TONE_HEX.probe;
          return (
            <g
              key={`node-${c.code}`}
              className="cursor-pointer"
              onClick={(e) => {
                e.stopPropagation();
                const targetId = c.dossiers?.[0] || c.code;
                onSelect(selected === targetId ? null : targetId);
              }}
            >
              {pulse.has(c.code) && (
                <circle className="hz-pulse-ring" cx={xy[0]} cy={xy[1]} r={6} fill="none" stroke={TONE_HEX.probe} strokeWidth={1.4} />
              )}
              <circle cx={xy[0]} cy={xy[1]} r={3.4} fill={dotColor} stroke={palette.paper} strokeWidth={1.1} />
              <text
                x={xy[0]}
                y={xy[1] - 6}
                textAnchor="middle"
                fontSize="9"
                fontWeight={700}
                fill={palette.ink}
                style={{ paintOrder: "stroke", stroke: palette.paper, strokeWidth: 2.5 }}
              >
                {c.code}
              </text>
            </g>
          );
        })}

        {/* Détroits & corridors géoéconomiques (losanges) */}
        {(layer === "all" || layer === "economy") && chokepoints.map((p) => {
          const xy = projectVisible(p.lat, p.lon);
          if (!xy) return null;
          const isSel = selected === p.id;
          return (
            <g
              key={`${p.id}-${p.choke_id || p.name}`}
              className="cursor-pointer"
              onClick={(e) => { e.stopPropagation(); onSelect(isSel ? null : p.id); }}
            >
              <circle className="hz-pulse-ring" cx={xy[0]} cy={xy[1]} r={7} fill="none" stroke={TONE_HEX.economy} strokeWidth={1.5} />
              <rect
                x={xy[0] - 5.5}
                y={xy[1] - 5.5}
                width="11"
                height="11"
                transform={`rotate(45 ${xy[0]} ${xy[1]})`}
                fill={TONE_HEX.economy}
                stroke={palette.paper}
                strokeWidth="1.5"
              />
              <text
                x={xy[0]}
                y={xy[1] + 15}
                textAnchor="middle"
                fontSize="9.5"
                fontWeight={600}
                fill={TONE_HEX.economy}
                style={{ paintOrder: "stroke", stroke: palette.paper, strokeWidth: 2.5 }}
              >
                {p.name}
              </text>
            </g>
          );
        })}
      </svg>

      {/* Légende tactique épurée */}
      <div className="mt-2 flex flex-wrap items-center gap-x-5 gap-y-1 text-[11px] text-muted">
        <span className="inline-flex items-center gap-1.5">
          <i className="inline-block h-2 w-4 rounded-sm" style={{ background: TONE_HEX.conflict }} />
          {t("horizon.legConflict")}
        </span>
        <span className="inline-flex items-center gap-1.5">
          <i className="inline-block h-2 w-4 rounded-sm" style={{ background: TONE_HEX.rapprochement }} />
          {t("horizon.legApproach")}
        </span>
        <span className="inline-flex items-center gap-1.5">
          <i className="inline-block h-2 w-4 rounded-sm" style={{ background: TONE_HEX.economy }} />
          {t("horizon.legEconomy")}
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-2.5 rotate-45 border" style={{ borderColor: TONE_HEX.economy, background: TONE_HEX.economy }} />
          {t("horizon.legChokepoint")}
        </span>
        {mode === "globe" && <span className="ml-auto text-[10.5px] text-faint">{t("horizon.dragHint")}</span>}
      </div>
    </div>
  );
}
