import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import * as d3 from "d3";
import { CHART_FONT } from "../../theme";
import { usePalette } from "../../ThemeProvider";
import { useWidth } from "./shared";
import { useI18n } from "../../i18n/I18nProvider";

type Props = {
  data: any;
  selected: number | null;
  themeId?: number | null;
  onSelect: (id: number | null) => void;
  onTheme?: (id: number | null) => void;
  compact?: boolean;
};

const PALETTE: [number, number, number][] = [
  [0.42, 0.62, 0.78], [0.32, 0.64, 0.56], [0.72, 0.56, 0.30], [0.64, 0.44, 0.70],
  [0.76, 0.42, 0.34], [0.42, 0.62, 0.46], [0.52, 0.48, 0.74], [0.78, 0.66, 0.38],
  [0.34, 0.52, 0.70], [0.72, 0.48, 0.52], [0.38, 0.66, 0.64], [0.64, 0.46, 0.32],
];
const rgb = (id: number) => PALETTE[Math.abs(id) % PALETTE.length];
const cssRgb = (id: number, a = 1) => {
  const [r, g, b] = rgb(id);
  return `rgba(${Math.round(r * 255)}, ${Math.round(g * 255)}, ${Math.round(b * 255)}, ${a})`;
};

type Bubble = {
  id: number;
  kind: "theme" | "story";
  label: string;
  articles: number;
  outlets: number;
  stories?: number;
  themeId: number;
  heat?: string;
  r: number;
  x: number;
  y: number;
  seedX: number;
  seedY: number;
};

type ThemeLink = {
  source: number;
  target: number;
  source_label: string;
  target_label: string;
  similarity: number;
  weight: number;
  kind: "entity" | "journalist" | "semantic";
  label: string;
  shared_entities?: string[];
  shared_journalists?: string[];
  shared_outlets?: string[];
  shared_outlets_count?: number;
};

function wrapLabel(label: string, maxChars: number): string[] {
  const cap = Math.max(10, maxChars);
  if (label.length <= cap) return [label];
  const words = label.split(/\s+/);
  const lines: string[] = [];
  let cur = "";
  for (const w of words) {
    const next = cur ? `${cur} ${w}` : w;
    if (next.length <= cap) cur = next;
    else {
      if (cur) lines.push(cur);
      cur = w;
      if (lines.length >= 2) break;
    }
  }
  if (cur && lines.length < 3) lines.push(cur);
  const last = lines.length - 1;
  if (last >= 0 && lines[last].length > cap) lines[last] = `${lines[last].slice(0, cap - 1)}…`;
  return lines.slice(0, 3);
}

function layoutBubbles<T extends { id: number }>(
  items: T[],
  width: number,
  height: number,
  seed: (d: T) => [number, number],
  weight: (d: T) => number,
  extra: (d: T) => Omit<Bubble, "id" | "r" | "x" | "y" | "seedX" | "seedY">,
  links: ThemeLink[] = [],
): Bubble[] {
  const n = items.length;
  if (!n || width < 40) return [];
  const pad = 24;
  const seeds = items.map(seed);
  const xs = seeds.map((s) => s[0]);
  const ys = seeds.map((s) => s[1]);
  const x0 = d3.min(xs) ?? 0, x1 = d3.max(xs) ?? 1;
  const y0 = d3.min(ys) ?? 0, y1 = d3.max(ys) ?? 1;
  const dx = (x1 - x0) || 1, dy = (y1 - y0) || 1;

  const minR = n <= 5 ? 46 : n <= 10 ? 36 : 30;
  const maxR = n <= 5 ? 90 : n <= 10 ? 72 : 58;
  const wts = items.map((d) => Math.sqrt(Math.max(1, weight(d))));
  const wMin = d3.min(wts) ?? 1, wMax = d3.max(wts) ?? 1;
  const span = (wMax - wMin) || 1;

  const nodes: Bubble[] = items.map((d, i) => {
    const r = minR + ((wts[i] - wMin) / span) * (maxR - minR);
    const sx = pad + r + ((xs[i] - x0) / dx) * Math.max(1, width - 2 * pad - 2 * r);
    const sy = pad + r + ((ys[i] - y0) / dy) * Math.max(1, height - 2 * pad - 2 * r);
    return { id: d.id, ...extra(d), r, x: sx, y: sy, seedX: sx, seedY: sy };
  });

  const nodeIds = new Set(nodes.map((nd) => nd.id));
  const simLinks = links
    .filter((l) => nodeIds.has(l.source) && nodeIds.has(l.target))
    .map((l) => ({ source: l.source, target: l.target, weight: l.weight || 0.5 }));

  const sim = d3.forceSimulation(nodes as any)
    .force("x", d3.forceX((d: any) => d.seedX).strength(0.14))
    .force("y", d3.forceY((d: any) => d.seedY).strength(0.14))
    .force("collide", d3.forceCollide((d: any) => d.r + 16).iterations(5).strength(1));

  if (simLinks.length > 0) {
    sim.force(
      "link",
      d3.forceLink(simLinks as any)
        .id((d: any) => d.id)
        .distance((l: any) => {
          const s = l.source as Bubble;
          const t = l.target as Bubble;
          return (s.r || 40) + (t.r || 40) + 46;
        })
        .strength((l: any) => Math.min(0.32, (l.weight || 0.5) * 0.28)),
    );
  }
  sim.stop();
  for (let i = 0; i < 220; i++) sim.tick();

  for (const d of nodes) {
    d.x = Math.max(d.r + 10, Math.min(width - d.r - 10, d.x));
    d.y = Math.max(d.r + 10, Math.min(height - d.r - 10, d.y));
  }
  const sim2 = d3.forceSimulation(nodes as any)
    .force("collide", d3.forceCollide((d: any) => d.r + 14).iterations(4).strength(1))
    .force("x", d3.forceX((d: any) => d.x).strength(0.04))
    .force("y", d3.forceY((d: any) => d.y).strength(0.04))
    .stop();
  for (let i = 0; i < 60; i++) sim2.tick();
  for (const d of nodes) {
    d.x = Math.max(d.r + 10, Math.min(width - d.r - 10, d.x));
    d.y = Math.max(d.r + 10, Math.min(height - d.r - 10, d.y));
  }
  return nodes;
}

function placeArticles(members: any[], cx: number, cy: number, r: number, width: number, height: number) {
  const list = members.slice(0, 28);
  const n = list.length;
  if (!n) return [];
  const mx = d3.mean(list, (m) => m.x) ?? 0;
  const my = d3.mean(list, (m) => m.y) ?? 0;
  const ring = r + 18;
  return list.map((m, i) => {
    const a = (i / n) * Math.PI * 2 - Math.PI / 2;
    const jitter = 10 + Math.min(22, n);
    const px = cx + Math.cos(a) * ring + ((m.x ?? 0) - mx) * jitter;
    const py = cy + Math.sin(a) * ring + ((m.y ?? 0) - my) * jitter;
    return {
      ...m,
      ax: Math.max(8, Math.min(width - 8, px)),
      ay: Math.max(8, Math.min(height - 8, py)),
      ar: 3.2 + Math.min(3.2, (Number(m.influence) || 0) * 0.028),
    };
  });
}

export default function TopicsMap({ data, selected, themeId, onSelect, onTheme, compact }: Props) {
  const { t, intl } = useI18n();
  const palette = usePalette();
  const [wrapRef, width] = useWidth<HTMLDivElement>(720);
  const height = compact ? Math.max(220, Math.round(width * 0.42)) : Math.max(520, Math.round(width * 0.78));
  const [hoverArt, setHoverArt] = useState<any>(null);
  const [pickedArt, setPickedArt] = useState<any>(null);
  const [hoverNodeId, setHoverNodeId] = useState<number | null>(null);
  const [hoverLink, setHoverLink] = useState<(ThemeLink & { mx: number; my: number }) | null>(null);

  const clusters: any[] = data?.clusters || [];
  const themes: any[] = data?.themes || [];
  const themeLinks: ThemeLink[] = data?.theme_links || [];
  const points: any[] = data?.points || [];
  const isolated = useMemo(() => points.filter((p: any) => p.cluster_id == null), [points]);
  const clusterById = useMemo(() => Object.fromEntries(clusters.map((c: any) => [c.id, c])), [clusters]);

  useEffect(() => {
    setHoverArt(null);
    setPickedArt(null);
    setHoverNodeId(null);
    setHoverLink(null);
  }, [data]);

  const focusTheme = themes.find((th: any) => th.id === themeId) || null;
  const familyMode = themeId == null;

  const familyNodes = useMemo(() => layoutBubbles(
    themes,
    width, height,
    (th) => [th.x ?? 0, th.y ?? 0],
    (th) => (th.articles || 1) * (1 + Math.log1p(th.outlets || 1)),
    (th) => ({
      kind: "theme" as const,
      label: th.label,
      articles: th.articles,
      outlets: th.outlets,
      stories: th.stories,
      themeId: th.id,
      heat: th.heat,
    }),
    themeLinks,
  ), [themes, width, height, themeLinks]);

  const storyRows = useMemo(() => {
    if (themeId == null) return [];
    const rows = clusters.filter((c: any) => (c.theme_id ?? c.id) === themeId);
    return rows.length ? rows : clusters.filter((c: any) => (focusTheme?.story_ids || []).includes(c.id));
  }, [clusters, themeId, focusTheme]);

  const storyNodes = useMemo(() => layoutBubbles(
    storyRows,
    width, height,
    (s) => [s.x ?? 0, s.y ?? 0],
    (s) => s.articles || 1,
    (s) => ({
      kind: "story" as const,
      label: s.label,
      articles: s.articles,
      outlets: s.outlets,
      themeId: s.theme_id ?? themeId ?? s.id,
      heat: s.heat,
    }),
  ), [storyRows, width, height, themeId]);

  const nodes = familyMode ? familyNodes : storyNodes;
  const nodeById = useMemo(() => new Map(nodes.map((nd) => [nd.id, nd])), [nodes]);
  const selectedNode = !familyMode && selected != null ? storyNodes.find((n) => n.id === selected) : null;

  const connectedToHover = useMemo(() => {
    if (!familyMode || hoverNodeId == null) return null;
    const set = new Set<number>([hoverNodeId]);
    for (const l of themeLinks) {
      if (l.source === hoverNodeId) set.add(l.target);
      else if (l.target === hoverNodeId) set.add(l.source);
    }
    return set;
  }, [familyMode, hoverNodeId, themeLinks]);

  const articles = useMemo(() => {
    if (!selectedNode) return [];
    const cl = clusterById[selectedNode.id];
    const members = (cl?.members?.length ? cl.members : points.filter((p: any) => p.cluster_id === selectedNode.id));
    return placeArticles(members, selectedNode.x, selectedNode.y, selectedNode.r, width, height);
  }, [selectedNode, clusterById, points, width, height]);

  const dust = useMemo(() => {
    if (!familyMode || isolated.length < 8 || width < 40) return [] as d3.ContourMultiPolygon[];
    const xs = [...themes.map((th: any) => th.x ?? 0), ...isolated.map((p: any) => p.x ?? 0)];
    const ys = [...themes.map((th: any) => th.y ?? 0), ...isolated.map((p: any) => p.y ?? 0)];
    const x = d3.scaleLinear().domain([d3.min(xs) ?? -1, d3.max(xs) ?? 1]).range([16, width - 16]);
    const y = d3.scaleLinear().domain([d3.min(ys) ?? -1, d3.max(ys) ?? 1]).range([height - 16, 16]);
    return d3.contourDensity<any>().x((p) => x(p.x)).y((p) => y(p.y)).size([width, height]).bandwidth(22).thresholds(6)(isolated);
  }, [familyMode, isolated, themes, width, height]);
  const maxD = d3.max(dust, (c) => c.value) || 1;

  const openFamily = (id: number) => {
    const rows = clusters.filter((c: any) => (c.theme_id ?? c.id) === id);
    setHoverArt(null);
    setPickedArt(null);
    onTheme?.(id);
    if (rows.length === 1) onSelect(rows[0].id);
    else onSelect(null);
  };

  const back = () => {
    setHoverArt(null);
    setPickedArt(null);
    onTheme?.(null);
    onSelect(null);
  };

  const onBg = () => {
    if (pickedArt) { setPickedArt(null); return; }
    if (selected != null) { onSelect(null); return; }
    if (!familyMode) back();
  };

  const card = pickedArt || hoverArt;

  return (
    <div ref={wrapRef} className="relative overflow-hidden" style={{ height, background: palette.paper, fontFamily: CHART_FONT }}>
      <svg width={width} height={height} className="block cursor-default" onClick={onBg}>
        {dust.map((c, i) => (
          <path key={i} d={d3.geoPath()(c) || ""} fill={palette.accent} fillOpacity={0.04 + 0.08 * (c.value / maxD)} stroke="none" />
        ))}

        {familyMode && themeLinks.map((link, idx) => {
          const s = nodeById.get(link.source);
          const tg = nodeById.get(link.target);
          if (!s || !tg) return null;
          const dx = tg.x - s.x;
          const dy = tg.y - s.y;
          const dist = Math.hypot(dx, dy) || 1;
          const ux = dx / dist;
          const uy = dy / dist;
          const x1 = s.x + ux * (s.r + 2);
          const y1 = s.y + uy * (s.r + 2);
          const x2 = tg.x - ux * (tg.r + 2);
          const y2 = tg.y - uy * (tg.r + 2);
          const mx = (x1 + x2) / 2;
          const my = (y1 + y2) / 2;

          const isHighlighted =
            hoverLink?.source === link.source && hoverLink?.target === link.target
              ? true
              : hoverNodeId != null
              ? link.source === hoverNodeId || link.target === hoverNodeId
              : false;
          const isDimmed = hoverNodeId != null && !isHighlighted;
          const isActorBridge = link.kind === "entity" || link.kind === "journalist";
          const strokeColor = isActorBridge ? palette.accent : palette.muted;
          const strokeOpacity = isDimmed ? 0.12 : isHighlighted ? 0.92 : isActorBridge ? 0.62 : 0.36;
          const strokeWidth = isHighlighted ? 2.2 : isActorBridge ? 1.65 : 1.15;
          const showBadge = !compact && (isHighlighted || isActorBridge || link.similarity >= 0.64);

          return (
            <g
              key={`link-${link.source}-${link.target}-${idx}`}
              className="cursor-pointer"
              onMouseEnter={() => setHoverLink({ ...link, mx, my })}
              onMouseLeave={() => setHoverLink((cur) => (cur && cur.source === link.source && cur.target === link.target ? null : cur))}
              onClick={(e) => {
                e.stopPropagation();
                openFamily(link.source);
              }}
            >
              <line
                x1={x1}
                y1={y1}
                x2={x2}
                y2={y2}
                stroke={strokeColor}
                strokeOpacity={strokeOpacity}
                strokeWidth={strokeWidth}
                strokeDasharray={isActorBridge ? undefined : "4,3"}
              />
              {showBadge && link.label && (
                <g transform={`translate(${mx},${my})`} opacity={isDimmed ? 0.2 : 1}>
                  <rect
                    x={-Math.min(72, link.label.length * 3.2 + 8)}
                    y={-8.5}
                    width={Math.min(144, link.label.length * 6.4 + 16)}
                    height={16}
                    rx={8}
                    fill={palette.paper}
                    fillOpacity={0.92}
                    stroke={strokeColor}
                    strokeOpacity={isHighlighted ? 0.9 : 0.55}
                    strokeWidth={0.9}
                  />
                  <text
                    textAnchor="middle"
                    y={3.2}
                    fill={isActorBridge ? palette.ink : palette.muted}
                    style={{ fontSize: 9.5, fontWeight: isActorBridge ? 600 : 500 }}
                  >
                    {link.label.length > 22 ? `${link.label.slice(0, 21)}…` : link.label}
                  </text>
                </g>
              )}
            </g>
          );
        })}

        {nodes.map((n) => {
          const activeBySelect = familyMode || selected == null || n.id === selected;
          const activeByHover = !connectedToHover || connectedToHover.has(n.id);
          const active = activeBySelect && activeByHover;
          const isHovered = hoverNodeId === n.id;
          const fillA = !active ? 0.06 : isHovered || (n.kind === "story" && n.id === selected) ? 0.34 : 0.18;
          const lines = wrapLabel(n.label, Math.floor(n.r / 3.3));
          const fs = Math.max(9.5, Math.min(12.5, n.r / 5.4));
          const meta = n.kind === "theme" && (n.stories || 0) > 1
            ? `${t("topics.storiesCount", { n: n.stories || 0 })}${t("topics.artsMed", { a: n.articles, o: n.outlets })}`
            : t("topics.artsMed", { a: n.articles, o: n.outlets });
          const titleH = lines.length * (fs + 1);
          const metaH = n.r >= 34 ? 14 : 0;
          const startY = -(titleH + metaH) / 2 + fs * 0.82;
          return (
            <g
              key={`${n.kind}-${n.id}`}
              transform={`translate(${n.x},${n.y})`}
              className="cursor-pointer"
              opacity={active ? 1 : 0.28}
              role="button"
              tabIndex={0}
              aria-label={n.label}
              onMouseEnter={() => setHoverNodeId(n.id)}
              onMouseLeave={() => setHoverNodeId((cur) => (cur === n.id ? null : cur))}
              onClick={(e) => {
                e.stopPropagation();
                setPickedArt(null);
                if (n.kind === "theme") openFamily(n.id);
                else onSelect(selected === n.id ? null : n.id);
              }}
              onKeyDown={(e) => {
                if (e.key !== "Enter" && e.key !== " ") return;
                e.preventDefault();
                e.stopPropagation();
                if (n.kind === "theme") openFamily(n.id);
                else onSelect(selected === n.id ? null : n.id);
              }}
            >
              <title>{n.label}</title>
              <circle
                r={n.r}
                fill={cssRgb(n.themeId, fillA)}
                stroke={cssRgb(n.themeId, active ? 0.95 : 0.35)}
                strokeWidth={isHovered || n.id === selected ? 2.3 : 1.25}
              />
              <text textAnchor="middle" fill={palette.ink} style={{ fontSize: fs, fontWeight: 650 }} y={startY}>
                {lines.map((ln, i) => (
                  <tspan key={i} x={0} dy={i === 0 ? 0 : fs + 1}>{ln}</tspan>
                ))}
              </text>
              {n.r >= 34 && (
                <text textAnchor="middle" y={startY + titleH + 2} fill={palette.muted} style={{ fontSize: 10 }}>
                  {meta}
                </text>
              )}
            </g>
          );
        })}

        {articles.map((a: any) => (
          <circle
            key={a.id}
            cx={a.ax} cy={a.ay} r={a.ar}
            fill={cssRgb(themeId || 0, 0.95)}
            stroke={palette.paper}
            strokeWidth={0.8}
            className="cursor-pointer"
            onClick={(e) => { e.stopPropagation(); setPickedArt(a); }}
            onMouseEnter={() => setHoverArt(a)}
            onMouseLeave={() => setHoverArt((cur: any) => (cur?.id === a.id ? null : cur))}
          />
        ))}
      </svg>

      {hoverLink && !card && (
        <div
          className="pointer-events-none absolute z-20 w-[280px] rounded-sm border border-hair bg-paper p-2.5 shadow-[0_12px_32px_-12px_rgba(0,0,0,.35)]"
          style={{ left: Math.max(12, Math.min(hoverLink.mx + 12, width - 292)), top: Math.max(12, Math.min(hoverLink.my + 12, height - 130)) }}
        >
          <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-accent-strong">
            Lien entre sujets · {Math.round(hoverLink.similarity * 100)} % proximité
          </div>
          <div className="mt-1 text-[12px] font-semibold leading-snug text-ink">
            {hoverLink.source_label} ↔ {hoverLink.target_label}
          </div>
          {hoverLink.shared_entities && hoverLink.shared_entities.length > 0 && (
            <div className="mt-1 text-[11px] text-ink">
              <span className="text-muted">Acteurs communs : </span>
              <span className="font-medium">{hoverLink.shared_entities.join(", ")}</span>
            </div>
          )}
          {hoverLink.shared_journalists && hoverLink.shared_journalists.length > 0 && (
            <div className="mt-0.5 text-[11px] text-ink">
              <span className="text-muted">Journalistes : </span>
              <span className="font-medium">{hoverLink.shared_journalists.join(", ")}</span>
            </div>
          )}
          {hoverLink.shared_outlets && hoverLink.shared_outlets.length > 0 && (
            <div className="mt-0.5 text-[11px] text-faint">
              Médias communs ({hoverLink.shared_outlets_count}) : {hoverLink.shared_outlets.join(", ")}
            </div>
          )}
        </div>
      )}

      {card && (
        <div
          className="absolute z-20 w-[260px] rounded-sm border border-hair bg-paper p-2.5 shadow-[0_12px_32px_-12px_rgba(0,0,0,.3)]"
          style={{ left: Math.min((card.ax ?? 12) + 10, width - 272), top: Math.min((card.ay ?? 12) + 10, height - 110) }}
          onClick={(e) => e.stopPropagation()}
          onMouseEnter={() => setHoverArt(card)}
          onMouseLeave={() => { if (!pickedArt) setHoverArt(null); }}
        >
          <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-faint">
            {card.outlet || t("topics.unknownOutlet")}
            {card.influence ? <span className="num ml-1.5 opacity-70">infl. {card.influence}</span> : null}
          </div>
          <div className="mt-0.5 text-[12.5px] font-semibold leading-snug text-ink">{card.title}</div>
          <div className="mt-1 text-[11px] text-muted">
            {card.journalist ? `${card.journalist} · ` : ""}{card.date || ""}
          </div>
          {card.id && (
            <Link to={`/articles/${card.id}`} className="mt-2 inline-block text-[11px] font-semibold text-accent-strong hover:underline">
              {t("topics.openArticle")}
            </Link>
          )}
        </div>
      )}

      <div className="pointer-events-none absolute left-3 top-3 flex flex-wrap items-center gap-x-2 gap-y-1 rounded-full bg-paper/80 px-2.5 py-1 text-[11px] text-muted backdrop-blur-[2px]">
        {familyMode ? (
          <>
            <span className="num text-ink">{themes.length.toLocaleString(intl)}</span> {t("topics.mapFamilies")}
            {themeLinks.length > 0 && (
              <>
                <span className="text-faint">·</span>
                <span className="num text-ink">{themeLinks.length}</span> liens
              </>
            )}
            {isolated.length ? <><span className="text-faint">·</span><span className="num">{isolated.length.toLocaleString(intl)}</span> {t("topics.mapDust")}</> : null}
          </>
        ) : (
          <>
            <button type="button" className="pointer-events-auto font-semibold text-accent-strong hover:underline" onClick={back}>
              {t("topics.mapBack")}
            </button>
            <span className="text-faint">/</span>
            <span className="max-w-[220px] truncate font-medium text-ink">{focusTheme?.label}</span>
            <span className="text-faint">·</span>
            <span className="num">{storyRows.length}</span> {t("topics.mapStories")}
          </>
        )}
      </div>
      <div className="pointer-events-none absolute bottom-3 left-3 text-[10.5px] text-faint">
        {familyMode ? "Trait plein = acteur ou journaliste partagé · Pointillé = proximité sémantique · Survolez un sujet ou un lien" : t("topics.hintStories")}
      </div>
    </div>
  );
}
