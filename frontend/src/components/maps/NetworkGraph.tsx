import { useEffect, useRef, useState } from "react";
import * as d3 from "d3";
import { T, CHART_FONT } from "../../theme";
import { Tip, Tooltip, clusterStyle, useWidth } from "./shared";
import { useI18n } from "../../i18n/I18nProvider";

type Props = {
  data: any;
  showJournalists: boolean;
  showCocoverage: boolean;
  onSelectOutlet?: (id: number) => void;
  onSelectJournalist?: (id: number) => void;
};

export default function NetworkGraph({ data, showJournalists, showCocoverage, onSelectOutlet, onSelectJournalist }: Props) {
  const { t, intl, locale } = useI18n();
  const [wrapRef, width] = useWidth<HTMLDivElement>(900);
  const height = Math.max(480, Math.round(width * 0.6));
  const svgRef = useRef<SVGSVGElement>(null);
  const [tip, setTip] = useState<Tip>(null);
  const beatName = (b?: string) => {
    if (!b) return "";
    const v = t(`beat.${b}`);
    return v !== `beat.${b}` ? v : b;
  };

  useEffect(() => {
    if (!svgRef.current || !data) return;
    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();

    const nodes = (data.nodes as any[]).filter((n) => showJournalists || n.kind === "outlet").map((n) => ({ ...n }));
    const ids = new Set(nodes.map((n) => n.id));
    const edges = (data.edges as any[])
      .filter((e) => ids.has(e.source) && ids.has(e.target))
      .filter((e) => showCocoverage || e.type !== "cocoverage")
      .map((e) => ({ ...e }));

    const pr = d3.scaleSqrt().domain([0, d3.max(nodes, (n: any) => n.kind === "outlet" ? n.pagerank : 0) || 0.05]).range([5, 22]);
    const radius = (n: any) => (n.kind === "outlet" ? pr(n.pagerank) : 2.5);
    const wScale = d3.scaleSqrt().domain([1, d3.max(edges.filter((e) => e.type === "citation"), (e: any) => e.weight) || 1]).range([0.6, 4]);

    const g = svg.append("g");
    const zoom = d3.zoom<SVGSVGElement, unknown>().scaleExtent([0.4, 5]).on("zoom", (e) => g.attr("transform", e.transform));
    svg.call(zoom);

    svg.append("defs").append("marker").attr("id", "arrow-cite").attr("viewBox", "0 0 10 10").attr("refX", 10).attr("refY", 5)
      .attr("markerWidth", 5).attr("markerHeight", 5).attr("orient", "auto")
      .append("path").attr("d", "M 0 0 L 10 5 L 0 10 z").attr("fill", T.accent);

    const link = g.append("g").selectAll("line").data(edges).join("line")
      .attr("stroke", (e: any) => e.type === "citation" ? T.accent : e.type === "cocoverage" ? T.faint : T.hair)
      .attr("stroke-opacity", (e: any) => e.type === "citation" ? 0.7 : e.type === "cocoverage" ? 0.45 : 0.6)
      .attr("stroke-width", (e: any) => e.type === "citation" ? wScale(e.weight) : e.type === "cocoverage" ? 0.8 + e.weight * 3 : 0.5)
      .attr("stroke-dasharray", (e: any) => e.type === "cocoverage" ? "3 3" : null)
      .attr("marker-end", (e: any) => e.type === "citation" ? "url(#arrow-cite)" : null);

    const node = g.append("g").selectAll("g").data(nodes).join("g").attr("cursor", "pointer");
    node.append("circle")
      .attr("r", radius)
      .attr("fill", (n: any) => n.kind === "outlet" ? clusterStyle(n.community).fill : T.muted)
      .attr("stroke", (n: any) => n.kind === "outlet" ? clusterStyle(n.community).stroke : "none")
      .attr("stroke-width", 1.25)
      .attr("fill-opacity", (n: any) => n.kind === "outlet" ? 0.92 : 0.6);
    node.filter((n: any) => n.kind === "outlet").append("text")
      .text((n: any) => n.name).attr("x", (n: any) => radius(n) + 3).attr("dy", "0.35em")
      .attr("font-size", (n: any) => n.pagerank > 0.05 ? 11 : 9.5).attr("font-weight", (n: any) => n.pagerank > 0.05 ? 600 : 400).attr("fill", T.ink);

    node.on("mousemove", (ev: MouseEvent, n: any) => {
      const [mx, my] = d3.pointer(ev, svgRef.current);
      setTip({ x: mx, y: my, content: n.kind === "outlet" ? (
        <><b>{n.name}</b> <span className="text-faint">{n.country}</span>
          <div className="text-muted">{t("carto.prInfl", { pr: (n.pagerank * 100).toFixed(1), inf: n.influence })}</div>
          <div className="text-faint">{t("map.citedN", { n: n.in_citations })} · {t("carto.citesN", { n: n.out_citations })} · {n.articles} {t("common.articles")}{n.community !== null ? ` · ${t("map.communityN", { n: n.community + 1 })}` : ""}</div></>
      ) : (
        <><b>{n.name}</b><div className="text-muted">{t("carto.jsNetTip", { n: n.articles, access: t("map.accessibility"), a: n.accessibility })}{n.beat ? ` · ${beatName(n.beat)}` : ""}</div></>
      ) });
    }).on("mouseleave", () => setTip(null))
      .on("click", (_: any, n: any) => n.kind === "outlet" ? onSelectOutlet?.(n.ref) : onSelectJournalist?.(n.ref));

    const sim = d3.forceSimulation(nodes as any)
      .force("link", d3.forceLink(edges as any).id((d: any) => d.id)
        .distance((e: any) => e.type === "byline" ? 28 : e.type === "citation" ? 120 : 160)
        .strength((e: any) => e.type === "byline" ? 0.9 : e.type === "citation" ? 0.25 : 0.08 + e.weight * 0.3))
      .force("charge", d3.forceManyBody().strength((n: any) => n.kind === "outlet" ? -420 : -25))
      .force("collide", d3.forceCollide((n: any) => radius(n) + 4))
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force("x", d3.forceX(width / 2).strength(0.04))
      .force("y", d3.forceY(height / 2).strength(0.05));

    sim.on("tick", () => {
      link.attr("x1", (e: any) => e.source.x).attr("y1", (e: any) => e.source.y).attr("x2", (e: any) => e.target.x).attr("y2", (e: any) => e.target.y);
      node.attr("transform", (n: any) => `translate(${n.x},${n.y})`);
    });

    node.call(d3.drag<any, any>()
      .on("start", (ev, n) => { if (!ev.active) sim.alphaTarget(0.3).restart(); n.fx = n.x; n.fy = n.y; })
      .on("drag", (ev, n) => { n.fx = ev.x; n.fy = ev.y; })
      .on("end", (ev, n) => { if (!ev.active) sim.alphaTarget(0); n.fx = null; n.fy = null; }));

    return () => { sim.stop(); svg.on(".zoom", null); };
  }, [data, showJournalists, showCocoverage, width, height, t]);

  return (
    <div ref={wrapRef} className="relative select-none">
      <svg ref={svgRef} width={width} height={height} className="block" style={{ fontFamily: CHART_FONT }} />
      <Tooltip tip={tip} />
    </div>
  );
}
