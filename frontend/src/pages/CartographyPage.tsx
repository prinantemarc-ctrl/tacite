import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Download } from "lucide-react";
import {
  getMapLandscape, getMapNetwork, getMapWorld, getMapCorpus, getMapLeadLag, getMapDissidents, getMapPacks, getMapEntities,
  listOutlets, listJournalists,
} from "../api";
import { Card, Badge, Stat, Table, Segmented, Select, Button, Input, Loading, Empty, PageHeader, Callout, ScorePill, Meter, Term } from "../components";
import LandscapeMap from "../components/maps/LandscapeMap";
import AxisStrips from "../components/maps/AxisStrips";
import NetworkGraph from "../components/maps/NetworkGraph";
import WorldMap from "../components/maps/WorldMap";
import CorpusMap from "../components/maps/CorpusMap";
import ProximityMatrix from "../components/maps/ProximityMatrix";
import { Legend, Swatch, clusterStyle } from "../components/maps/shared";
import { T } from "../theme";
import { flag, countryName, FR_AXIS_ZONE, FR_SPECIFIC_AXES } from "../geo";
import { splitBio, journalistBeat } from "./JournalistsPage";
import { useI18n } from "../i18n/I18nProvider";

type View = "positions" | "landscape" | "network" | "world" | "analyses" | "directory";
type TFn = (key: string, vars?: Record<string, string | number>) => string;

const BEAT_I18N = new Set([
  "Politique", "Économie", "International", "Justice", "Société", "Culture",
  "Sport", "Sciences", "Santé", "Environnement", "Tech", "Médias", "Généraliste",
]);

function axisName(t: TFn, k: string, fallback?: string) {
  const v = t(`axis.${k}`);
  return v !== `axis.${k}` ? v : (fallback || k);
}

function beatLabel(raw: string | undefined, t: TFn) {
  if (!raw) return t("carto.unclassified");
  return BEAT_I18N.has(raw) ? t(`beat.${raw}`) : raw;
}

function fmtDate(iso: string | undefined, intl: string) {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString(intl);
}

/** Phrases de lecture, calculées sur les positions mesurées (médias documentés uniquement). */
function insights(data: any, countryFilter: string, t: TFn): string[] {
  if (!data?.outlets?.length) return [];
  const all = data.outlets.filter((o: any) => !countryFilter || o.country === countryFilter);
  const axes: string[] = data.axes.map((a: any) => a.axis).filter((a: string) => {
    if (!FR_SPECIFIC_AXES.has(a)) return true;
    if (countryFilter) return FR_AXIS_ZONE.has(countryFilter);
    return all.every((o: any) => FR_AXIS_ZONE.has(o.country));
  });
  const poles: Record<string, [string, string]> = Object.fromEntries(data.axes.map((a: any) => [a.axis, a.poles]));
  const solid = all.filter((o: any) => o.confidence !== "low");
  if (solid.length < 2) return [t("carto.tooFewDocumented")];
  const out: string[] = [];

  const gapMax = [...solid].sort((a, b) => b.gap - a.gap)[0];
  const [axis, delta] = axes.map((a) => {
    const n = gapMax.axis_n?.[a];
    if (n !== undefined && n < 10) return [a, 0] as [string, number];
    return [a, (gapMax.real[a] ?? 0) - (gapMax.official[a] ?? 0)] as [string, number];
  }).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))[0];
  out.push(t("carto.insightGap", {
    name: gapMax.name,
    axis: axisName(t, axis),
    pole: (() => { const k = `pole.${axis}_${delta > 0 ? "pos" : "neg"}`; const v = t(k); return v === k ? (delta > 0 ? poles[axis][1] : poles[axis][0]) : v; })(),
    delta: `${delta > 0 ? "+" : ""}${delta.toFixed(2)}`,
  }));

  const spread = axes.map((a) => {
    const vals = solid.map((o: any) => o.real[a] ?? 0);
    const m = vals.reduce((s: number, v: number) => s + v, 0) / vals.length;
    return [a, Math.sqrt(vals.reduce((s: number, v: number) => s + (v - m) ** 2, 0) / vals.length)] as [string, number];
  }).sort((a, b) => b[1] - a[1]);
  out.push(t("carto.insightSpread", {
    maxAxis: axisName(t, spread[0][0]),
    d: spread[0][1].toFixed(2),
    minAxis: axisName(t, spread[spread.length - 1][0]),
  }));

  const a0 = spread[0][0];
  const sorted = [...solid].sort((x, y) => (x.real[a0] ?? 0) - (y.real[a0] ?? 0));
  const posVal = sorted[sorted.length - 1].real[a0] ?? 0;
  out.push(t("carto.insightExtremes", {
    axis: axisName(t, a0),
    negName: sorted[0].name,
    negPole: (() => { const k = `pole.${a0}_neg`; const v = t(k); return v === k ? poles[a0][0] : v; })(),
    negVal: (sorted[0].real[a0] ?? 0).toFixed(2),
    posName: sorted[sorted.length - 1].name,
    posPole: (() => { const k = `pole.${a0}_pos`; const v = t(k); return v === k ? poles[a0][1] : v; })(),
    posVal: `${posVal > 0 ? "+" : ""}${posVal.toFixed(2)}`,
  }));

  const dist = (p: any, q: any) => Math.sqrt(axes.reduce((s, a) => s + ((p.real[a] ?? 0) - (q.real[a] ?? 0)) ** 2, 0) / axes.length);
  const isolated = solid.map((o: any) => [o, Math.min(...solid.filter((q: any) => q.id !== o.id).map((q: any) => dist(o, q)))] as [any, number]).sort((a: [any, number], b: [any, number]) => b[1] - a[1])[0];
  const twin = solid.map((o: any) => [o, solid.filter((q: any) => q.id !== o.id).sort((p: any, q: any) => dist(o, p) - dist(o, q))[0]] as [any, any]).sort((a: [any, any], b: [any, any]) => dist(a[0], a[1]) - dist(b[0], b[1]))[0];
  out.push(t("carto.insightIsolated", {
    name: isolated[0].name,
    a: twin[0].name,
    b: twin[1].name,
  }));
  return out;
}

function useLazy<T>(loader: () => Promise<T>, active: boolean, deps: any[] = [], pollEmpty = false) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    let timer: number | undefined;
    setLoading(true); setError(null);
    loader().then((d) => {
      if (cancelled) return;
      setData(d);
      const pending = !!d && typeof d === "object" && !Array.isArray(d) && Boolean((d as { preparing?: boolean }).preparing);
      const emptyList = pollEmpty && Array.isArray(d) && d.length === 0 && tick < 20;
      if (pending || emptyList) timer = window.setTimeout(() => { if (!cancelled) setTick((n) => n + 1); }, 8000);
    }).catch((e) => { if (!cancelled) setError(e.message); }).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [active, tick, ...deps]);
  return { data, loading, error };
}

export default function CartographyPage() {
  const navigate = useNavigate();
  const { t, intl, locale } = useI18n();
  const [view, setView] = useState<View>("positions");
  const VIEWS: { value: View; label: string }[] = [
    { value: "positions", label: t("map.positions") },
    { value: "landscape", label: t("map.projection") },
    { value: "network", label: t("map.network") },
    { value: "world", label: t("map.world") },
    { value: "analyses", label: t("map.analyses") },
    { value: "directory", label: t("map.directory") },
  ];

  // Positions + Projection (même jeu de données)
  const [weeks, setWeeks] = useState(8);
  const [showJournalists, setShowJournalists] = useState(false);
  const [showOfficial, setShowOfficial] = useState(false);
  const [showAxes, setShowAxes] = useState(true);
  const [focusCluster, setFocusCluster] = useState<number | null>(null);
  const [selectedOutlet, setSelectedOutlet] = useState<number | null>(null);
  const [showDeclared, setShowDeclared] = useState(true);
  const [stripJournalists, setStripJournalists] = useState(true);
  const [posCountry, setPosCountry] = useState("");
  const landscape = useLazy(() => getMapLandscape(`weeks=${weeks}${posCountry ? `&country=${posCountry}` : ""}`), view === "positions" || view === "landscape", [weeks, posCountry]);
  const reading = useMemo(() => insights(landscape.data, posCountry, t), [landscape.data, posCountry, t]);

  // Réseau
  const [netJournalists, setNetJournalists] = useState(true);
  const [netCocov, setNetCocov] = useState(true);
  const network = useLazy(getMapNetwork, view === "network");

  // Monde
  const [metric, setMetric] = useState<"influence_sum" | "outlets" | "articles" | "journalists">("articles");
  const [showFlows, setShowFlows] = useState(true);
  const [selectedCountry, setSelectedCountry] = useState<string | null>(null);
  const world = useLazy(getMapWorld, view === "world");

  // Corpus
  const [corpusOutlet, setCorpusOutlet] = useState<number | null>(null);
  const [corpusTopic, setCorpusTopic] = useState<string | null>(null);
  const corpus = useLazy(() => getMapCorpus(1500), view === "analyses");

  // Matrice
  const [matrixMode, setMatrixMode] = useState<"topic_similarity" | "framing_similarity">("topic_similarity");
  const packs = useLazy(() => getMapPacks(60), view === "analyses");

  // Analyses
  const leadlag = useLazy(() => getMapLeadLag(30), view === "analyses");
  const dissidents = useLazy(getMapDissidents, view === "analyses", [], true);
  const entities = useLazy(() => getMapEntities(30), view === "analyses");

  // Annuaire
  const [outlets, setOutlets] = useState<any[]>([]);
  const [journalists, setJournalists] = useState<any[]>([]);
  const [search, setSearch] = useState("");
  const [countryFilter, setCountryFilter] = useState("");
  useEffect(() => { listOutlets("brief").then(setOutlets).catch(() => undefined); }, []);
  useEffect(() => {
    if (view !== "directory") return;
    Promise.all([listOutlets("brief"), listJournalists()]).then(([o, j]) => { setOutlets(o); setJournalists(j); });
  }, [view]);
  const outletMap = useMemo(() => Object.fromEntries(outlets.map((o) => [o.id, o])), [outlets]);
  const countries: string[] = useMemo(() => {
    const src: string[] = outlets.map((o: any) => String(o.country || "")).filter((c: string) => c.length > 0);
    src.sort((a, b) => countryName(a).localeCompare(countryName(b), locale));
    return [...new Set(src)];
  }, [outlets, locale]);

  const exportCSV = () => {
    const rows = journalists.filter((j) => (!countryFilter || outletMap[j.outlet_id]?.country === countryFilter) && (!search || j.name.toLowerCase().includes(search.toLowerCase())));
    const headers = [t("carto.csvName"), t("carto.csvOutlet"), t("carto.csvCountry"), t("carto.csvRole"), t("carto.csvBeat"), t("carto.csvAccess"), "X", "LinkedIn", t("carto.csvBio")];
    const lines = rows.map((j) => { const o = outletMap[j.outlet_id]; const beat = journalistBeat(j); const text = splitBio(j.bio).text; return [j.name, o?.name || "", o?.country || "", j.role || "", beat, (j.accessibility_score || 0).toFixed(0), j.twitter_handle || "", j.linkedin_url || "", text].map((v) => `"${String(v).replace(/"/g, '""')}"`).join(","); });
    const blob = new Blob(["\uFEFF" + [headers.join(","), ...lines].join("\n")], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = `tacite-directory-${new Date().toISOString().slice(0, 10)}.csv`; a.click(); URL.revokeObjectURL(a.href);
  };

  const Check = ({ checked, onChange, children }: { checked: boolean; onChange: (v: boolean) => void; children: React.ReactNode }) => (
    <label className="inline-flex cursor-pointer items-center gap-1.5 text-[12px] text-muted">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} className="accent-accent" />{children}
    </label>
  );

  const weekOptions = [4, 8, 12, 26];
  const unclass = t("carto.unclassified");
  const preparing =
    ((view === "positions" || view === "landscape") && !!landscape.data?.preparing)
    || (view === "network" && !!network.data?.preparing)
    || (view === "world" && !!world.data?.preparing)
    || (view === "analyses" && !!(corpus.data?.preparing || packs.data?.preparing || leadlag.data?.preparing || entities.data?.preparing));

  return (
    <div>
      <PageHeader
        kicker={t("pages.cartography")}
        title={t("carto.title")}
        subtitle={<><Term k="measured">{t("carto.measuredLines")}</Term>{t("carto.sub1")}<Term k="influence">{t("carto.influenceWord")}</Term>{t("carto.sub2")}<Link to="/method" className="text-accent-strong hover:underline">{t("nav.method")}</Link>{t("carto.sub3")}</>}
        actions={<Segmented value={view} onChange={setView} options={VIEWS} />}
      />

      {preparing && <div className="mb-4"><Empty>{t("carto.preparing")}</Empty></div>}

      {/* ───────────────────────── Positions par axe */}
      {view === "positions" && (
        <>
          <div className="mb-3 flex flex-wrap items-center gap-4">
            <Select value={weeks} onChange={(e) => setWeeks(+e.target.value)}>
              {weekOptions.map((n) => <option key={n} value={n}>{t("carto.weeks", { n })}</option>)}
            </Select>
            <Select value={posCountry} onChange={(e) => { setPosCountry(e.target.value); setSelectedOutlet(null); }}>
              <option value="">{t("common.allCountries")}</option>
              {countries.map((c) => <option key={c} value={c}>{flag(c)} {countryName(c)}</option>)}
            </Select>
            <Select value={selectedOutlet ?? ""} onChange={(e) => setSelectedOutlet(e.target.value ? +e.target.value : null)}>
              <option value="">{t("carto.highlightOutlet")}</option>
              {(landscape.data?.outlets || []).filter((o: any) => !posCountry || o.country === posCountry).map((o: any) => <option key={o.id} value={o.id}>{o.name}</option>)}
            </Select>
            <Check checked={showDeclared} onChange={setShowDeclared}>{t("carto.declaredLines")}</Check>
            <Check checked={stripJournalists} onChange={setStripJournalists}>{t("carto.selectedJs")}</Check>
            {landscape.data && <span className="ml-auto text-[11px] text-faint">{t("carto.documentedSince", { n: landscape.data.outlets.filter((o: any) => o.confidence !== "low").length, since: fmtDate(landscape.data.since, intl) })}</span>}
          </div>
          <Card title={t("carto.positionsByAxis")} help={["positions_view", "measured", "declared", "landscape_mean", "confidence"]} aside={<>{t("carto.asideSolid")} = <Term k="measured">{t("series.measured")}</Term> · {t("carto.asideHollow")} = <Term k="declared">{t("series.declared")}</Term> · {t("carto.asideTick")} = <Term k="landscape_mean">{t("carto.termMean")}</Term></>}>
            {landscape.loading && !landscape.data ? <Loading /> : landscape.error ? <Empty>{landscape.error}</Empty> : (
              <AxisStrips data={landscape.data} selected={selectedOutlet} onSelect={setSelectedOutlet} showDeclared={showDeclared} showJournalists={stripJournalists} countryFilter={posCountry} />
            )}
          </Card>
          {reading.length > 0 && (
            <Card title={t("carto.reading")} aside={t("carto.readingAside")} help={["measured", "gap", "landscape_mean"]} className="mt-4">
              <ol className="space-y-1.5 text-[13px] leading-snug text-ink">
                {reading.map((s, i) => <li key={i} className="flex gap-3"><span className="num shrink-0 text-[10px] font-bold tracking-[0.1em] text-accent">{String(i + 1).padStart(2, "0")}</span><span>{s}</span></li>)}
              </ol>
            </Card>
          )}
          {selectedOutlet !== null && landscape.data && (() => {
            const o = landscape.data.outlets.find((x: any) => x.id === selectedOutlet);
            if (!o) return null;
            const js = landscape.data.journalists.filter((j: any) => j.outlet_id === o.id).sort((a: any, b: any) => b.deviation - a.deviation);
            const axisKeys: string[] = (landscape.data.axes || []).map((a: any) => a.axis);
            return (
              <Card title={o.name} aside={<Link to={`/outlets/${o.id}`} className="hover:text-ink">{t("carto.openFile")}</Link>} className="mt-4">
                <div className="grid gap-4 md:grid-cols-2">
                  <div>
                    <div className="label mb-1.5"><Term k="gap">{t("carto.termGap")}</Term> {t("carto.topGaps")} <span className="font-normal normal-case tracking-normal text-faint">{t("carto.measuredMinusDeclared")}</span></div>
                    <ul className="space-y-1 text-[12.5px]">
                      {axisKeys.map((a) => [a, (o.real[a] ?? 0) - (o.official[a] ?? 0)] as [string, number]).sort((x, y) => Math.abs(y[1]) - Math.abs(x[1])).slice(0, 4).map(([a, d]) => (
                        <li key={a} className="flex items-center justify-between"><span className="text-muted">{axisName(t, a)}</span><Badge tone={Math.abs(d) > 0.5 ? "alert" : Math.abs(d) > 0.3 ? "accent" : "faint"}>{d > 0 ? "+" : ""}{d.toFixed(2)}</Badge></li>
                      ))}
                    </ul>
                  </div>
                  <div>
                    <div className="label mb-1.5">{t("carto.documentedJs", { n: js.length })}</div>
                    {js.length ? (
                      <ul className="space-y-1 text-[12.5px]">
                        {js.slice(0, 6).map((j: any) => (
                          <li key={j.id} className="flex items-center justify-between"><Link to={`/journalists/${j.id}`} className="text-ink hover:text-accent-strong">{j.name}</Link><span className="num text-faint">{t("carto.nArtGap", { n: j.n_articles, gap: t("map.gapFromOutlet"), d: j.deviation.toFixed(2) })}{j.deviation > 0.35 ? <> · <Term k="dissident">{t("carto.legDissident")}</Term></> : ""}</span></li>
                        ))}
                      </ul>
                    ) : <p className="text-[12px] italic text-faint">{t("carto.noJs5")}</p>}
                  </div>
                </div>
              </Card>
            );
          })()}
          <div className="mt-4"><Callout label={t("common.howToRead")}>{t("carto.howPos1")}<Term k="axes">{t("carto.termAxes")}</Term>{t("carto.howPos2")}<Term k="measured">{t("carto.termMeasuredLine")}</Term>{t("carto.howPos3")}<Term k="influence">{t("carto.termInfluence")}</Term>{t("carto.howPos4")}<Term k="declared">{t("carto.termDeclaredLine")}</Term>{t("carto.howPos5")}<Term k="gap">{t("carto.termGap")}</Term>{t("carto.howPos6")}<Term k="landscape_mean">{t("carto.termMean")}</Term>{t("carto.howPos7")}<Term k="confidence">{t("carto.lowConf")}</Term>{t("carto.howPos8")}</Callout></div>
        </>
      )}

      {/* ───────────────────────── Projection ACP */}
      {view === "landscape" && (
        <>
          <div className="mb-3 flex flex-wrap items-center gap-4">
            <Select value={weeks} onChange={(e) => setWeeks(+e.target.value)}>
              {weekOptions.map((n) => <option key={n} value={n}>{t("carto.weeks", { n })}</option>)}
            </Select>
            <Check checked={showOfficial} onChange={setShowOfficial}>{t("carto.arrowsDeclaredMeasured")}</Check>
            <Check checked={showJournalists} onChange={setShowJournalists}>{t("pages.journalists")}</Check>
            <Check checked={showAxes} onChange={setShowAxes}>{t("carto.framingAxes")}</Check>
            {landscape.data?.clusters?.length > 0 && (
              <div className="ml-auto flex flex-wrap items-center gap-1.5">
                <span className="label mr-1">{t("carto.blocs")}</span>
                {landscape.data.clusters.map((c: any) => {
                  const st = clusterStyle(c.id);
                  return (
                    <button key={c.id} onClick={() => setFocusCluster(focusCluster === c.id ? null : c.id)}
                      className={`inline-flex items-center gap-1.5 rounded-pill border px-2 py-[2px] text-[11px] transition-colors ${focusCluster === c.id ? "border-ink bg-ink text-paper" : "border-hair text-muted hover:border-faint"}`}>
                      <Swatch fill={st.fill} stroke={st.stroke} dash={st.dash} r={4} /> {c.label} <span className="num opacity-60">{c.size}</span>
                    </button>
                  );
                })}
              </div>
            )}
          </div>
          <Card title={t("carto.projectionTitle")} help={["projection", "cluster", "silhouette"]} aside={landscape.data?.explained_variance?.length >= 2 ? <><Term k="projection">{t("carto.explainedVarLabel")}</Term> {Math.round(landscape.data.explained_variance[0] * 100)} % · {Math.round(landscape.data.explained_variance[1] * 100)} %</> : undefined}>
            {landscape.loading && !landscape.data ? <Loading /> : landscape.error ? <Empty>{landscape.error}</Empty> : (
              <LandscapeMap data={landscape.data} showJournalists={showJournalists} showOfficial={showOfficial} showAxes={showAxes} focusCluster={focusCluster}
                onSelectOutlet={(id) => navigate(`/outlets/${id}`)} onSelectJournalist={(id) => navigate(`/journalists/${id}`)} />
            )}
            <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
              <Legend items={[
                { swatch: <Swatch fill={T.accent} stroke={T.accent} r={5} />, label: t("carto.legOutlet") },
                { swatch: <Swatch fill={T.paper} stroke={T.faint} dash="2 1.5" r={3} />, label: t("carto.legDeclared") },
                { swatch: <Swatch fill={T.muted} stroke={T.muted} r={2} />, label: t("carto.legJournalist") },
                { swatch: <Swatch fill={T.confidential} stroke={T.confidential} r={2} />, label: t("carto.legDissident") },
              ]} />
              {landscape.data && <span className="text-[11px] text-faint">{t("carto.countsSince", { o: landscape.data.outlets.length, j: landscape.data.journalists.length, since: fmtDate(landscape.data.since, intl) })}</span>}
            </div>
          </Card>
          <div className="mt-4"><Callout label={t("common.howToRead")}>{t("carto.howProj1")}<Term k="projection">{t("carto.termPca")}</Term>{t("carto.howProj2")}<Term k="cluster">{t("carto.termBlocs")}</Term>{t("carto.howProj3")}<Term k="silhouette">{t("carto.termSilhouette")}</Term>{t("carto.howProj4")}</Callout></div>
        </>
      )}

      {/* ───────────────────────── Réseau */}
      {view === "network" && (
        <>
          <div className="mb-3 flex flex-wrap items-center gap-4">
            <Check checked={netCocov} onChange={setNetCocov}>{t("carto.thematicCocov")}</Check>
            <Check checked={netJournalists} onChange={setNetJournalists}>{t("carto.prolificJs")}</Check>
            {network.data && <span className="ml-auto text-[11px] text-faint">{t("carto.netStats", { c: network.data.stats.citations, p: network.data.stats.cocoverage_pairs, n: network.data.communities.length })}</span>}
          </div>
          <Card title={t("carto.influenceNetwork")} help={["pagerank", "community", "cocoverage", "comp_citation"]} aside={<>{t("carto.sizeEq")} = <Term k="pagerank">PageRank</Term> · {t("carto.colorEq")} = <Term k="community">{t("carto.termCommunity")}</Term></>}>
            {network.loading && !network.data ? <Loading /> : network.error ? <Empty>{network.error}</Empty> : (
              <NetworkGraph data={network.data} showJournalists={netJournalists} showCocoverage={netCocov}
                onSelectOutlet={(id) => navigate(`/outlets/${id}`)} onSelectJournalist={(id) => navigate(`/journalists/${id}`)} />
            )}
            <div className="mt-3">
              <Legend items={[
                { swatch: <svg width="22" height="8"><line x1="0" y1="4" x2="22" y2="4" stroke={T.accent} strokeWidth="2" /></svg>, label: t("carto.legCitation") },
                { swatch: <svg width="22" height="8"><line x1="0" y1="4" x2="22" y2="4" stroke={T.faint} strokeWidth="1.5" strokeDasharray="3 3" /></svg>, label: t("carto.legCocov") },
                { swatch: <Swatch fill={T.accent} stroke={T.accent} r={5} />, label: t("carto.legOutletPr") },
                { swatch: <Swatch fill={T.muted} stroke={T.muted} r={2} />, label: t("carto.legJournalistShort") },
              ]} />
            </div>
          </Card>
          {network.data?.communities?.length > 0 && (
            <Card title={t("carto.communitiesFound")} aside={t("carto.louvainAside")} help="community" className="mt-4">
              <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
                {network.data.communities.map((c: any) => (
                  <div key={c.id} className="flex items-start gap-2 text-[12.5px]">
                    <Swatch fill={clusterStyle(c.id).fill} stroke={clusterStyle(c.id).stroke} r={5} />
                    <div><b>{t("carto.communityTitle", { n: c.id + 1 })}</b> <span className="text-faint">· {t("carto.nOutlets", { n: c.size, s: c.size > 1 ? "s" : "" })}</span><div className="text-muted">{c.label}</div></div>
                  </div>
                ))}
              </div>
            </Card>
          )}
        </>
      )}

      {/* ───────────────────────── Monde */}
      {view === "world" && (
        <>
          <div className="mb-3 flex flex-wrap items-center gap-4">
            <Segmented value={metric} onChange={setMetric} options={[
              { value: "influence_sum", label: t("map.influence") },
              { value: "outlets", label: t("pages.outlets") },
              { value: "articles", label: t("pages.articles") },
              { value: "journalists", label: t("pages.journalists") },
            ]} />
            <Check checked={showFlows} onChange={setShowFlows}>{t("carto.citationFlows")}</Check>
            {world.data && <span className="ml-auto text-[11px] text-faint">{t("carto.countriesFollowed", { n: world.data.countries.length, t: world.data.total_countries_known, regions: Object.entries(world.data.regions).map(([r, n]) => `${r} ${n}`).join(" · ") })}</span>}
          </div>
          <div className="grid gap-4 lg:grid-cols-[1fr_340px]">
            <Card title={t("carto.worldMap")} help="world" aside={t("carto.worldAside")}>
              {world.loading && !world.data ? <Loading /> : world.error ? <Empty>{world.error}</Empty> : (
                <WorldMap data={world.data} metric={metric} showFlows={showFlows} selected={selectedCountry} onSelect={setSelectedCountry} />
              )}
            </Card>
            <Card title={selectedCountry ? `${flag(selectedCountry)} ${countryName(selectedCountry)}` : t("map.followed")} aside={selectedCountry ? <button className="hover:text-ink" onClick={() => setSelectedCountry(null)}>{t("common.seeAll")}</button> : undefined}>
              {world.data && (() => {
                const raw = selectedCountry ? world.data.countries.filter((c: any) => c.code === selectedCountry) : world.data.countries;
                const list = raw.slice().sort((a: any, b: any) => (b[metric] || 0) - (a[metric] || 0));
                if (!list.length) return <Empty>{t("carto.noOutletInCountry")}</Empty>;
                return (
                  <ul className="divide-y divide-hair-soft">
                    {list.slice(0, 30).map((c: any) => (
                      <li key={c.code} className="py-2 text-[12.5px]">
                        <div className="flex items-center justify-between">
                          <button className="font-medium text-ink hover:text-accent-strong" onClick={() => setSelectedCountry(c.code)}>{flag(c.code)} {countryName(c.code)}</button>
                          <Link to={`/articles?country=${c.code}`} className="num text-faint hover:text-accent-strong">{t("carto.nArt", { n: c.articles })}</Link>
                        </div>
                        <div className="mt-1 flex items-center gap-2"><Meter value={c[metric]} max={world.data.countries[0]?.[metric] || 1} width="w-24" /><span className="num text-[11px] text-faint">{t("carto.outletsJourn", { o: c.outlets, s: c.outlets > 1 ? "s" : "", j: c.journalists })}</span></div>
                        {selectedCountry && (
                          <ul className="mt-2 space-y-0.5">
                            {c.top.map((top: any) => <li key={top.id} className="flex justify-between"><Link to={`/outlets/${top.id}`} className="hover:text-accent-strong">{top.name}</Link><span className="num text-faint">{top.influence}</span></li>)}
                            <li className="mt-1 text-faint">{t("carto.countryDetail", { j: c.journalists, a: c.articles, langs: Object.keys(c.languages).join(", ") })}</li>
                            <li><Link to={`/articles?country=${c.code}`} className="text-accent-strong hover:underline">{t("carto.seeArticles")}</Link></li>
                          </ul>
                        )}
                      </li>
                    ))}
                  </ul>
                );
              })()}
            </Card>
          </div>
          {world.data?.flows?.length > 0 && (
            <Card title={t("carto.crossBorderFlows")} aside={t("carto.flowsAside")} className="mt-4">
              <div className="flex flex-wrap gap-1.5">
                {world.data.flows.slice(0, 24).map((f: any, i: number) => (
                  <Badge key={i} tone={selectedCountry && (f.source === selectedCountry || f.target === selectedCountry) ? "ink" : "default"}>{flag(f.source)} {f.source} → {flag(f.target)} {f.target} <span className="ml-1 num opacity-60">{f.weight}</span></Badge>
                ))}
              </div>
            </Card>
          )}
        </>
      )}

      {/* ───────────────────────── Analyses */}
      {view === "analyses" && (
        <div className="space-y-5">
          <div className="grid grid-cols-2 gap-6 md:grid-cols-4">
            <Stat label={t("carto.editorialBlocs")} value={landscape.data?.clusters?.length ?? t("common.dash")} sub={landscape.data?.clusters?.length ? t("carto.silhouetteN", { s: landscape.data.clusters[0].silhouette }) : undefined} help="cluster" />
            <Stat label={t("carto.multiEvents")} value={leadlag.data?.events ?? t("common.dash")} sub={t("carto.window72")} help="leadlag" />
            <Stat label={t("carto.dissidents")} value={dissidents.data?.filter((d: any) => d.deviation > 0.35).length ?? t("common.dash")} sub={t("carto.gapOver035")} tone="alert" help="dissident" />
            <Stat label={t("carto.trackedEntities")} value={entities.data?.entities?.length ?? t("common.dash")} sub={t("carto.days60")} tone="accent" help="valence" />
          </div>

          <Card title={t("carto.editorialBlocs")} aside={t("carto.blocsAuto")} help={["cluster", "silhouette"]}>
            {landscape.data?.clusters?.length ? (
              <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
                {landscape.data.clusters.map((c: any) => (
                  <div key={c.id} className="rounded-sm border border-hair p-3">
                    <div className="mb-1 flex items-center gap-2"><Swatch fill={clusterStyle(c.id).fill} stroke={clusterStyle(c.id).stroke} r={5} /><span className="label">{c.label}</span></div>
                    <div className="text-[12px] text-muted">{c.members.map((id: number) => landscape.data.outlets.find((o: any) => o.id === id)?.name).filter(Boolean).join(", ")}</div>
                    <div className="mt-2 flex flex-wrap gap-1">
                      {Object.entries(c.centroid).sort(([, a], [, b]) => Math.abs(b as number) - Math.abs(a as number)).slice(0, 4).map(([k, v]) => (
                        <Badge key={k} tone={Math.abs(v as number) > 0.3 ? "accent" : "faint"}>{axisName(t, k, landscape.data.axes.find((a: any) => a.axis === k)?.label)} {(v as number) > 0 ? "+" : ""}{(v as number).toFixed(2)}</Badge>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            ) : <Empty>{landscape.loading ? t("carto.computing") : t("carto.notEnoughBlocs")}</Empty>}
          </Card>

          <div className="grid gap-5 lg:grid-cols-2">
            <Card title={t("dash.whoLeads")} aside={t("carto.whoLeadsAside")} help={["leadlag", "comp_agenda"]}>
              {leadlag.data?.ranking?.length ? (
                <Table headers={[t("carto.thOutlet"), t("carto.thLeads"), t("carto.thFollows"), t("carto.thRatio"), t("carto.thMedianLag")]} dense>
                  {leadlag.data.ranking.slice(0, 15).map((r: any) => (
                    <tr key={r.outlet_id}>
                      <td><Link to={`/outlets/${r.outlet_id}`} className="text-ink hover:text-accent-strong">{flag(r.country)} {r.name}</Link></td>
                      <td className="num text-accent-strong">{r.leads}</td>
                      <td className="num text-muted">{r.follows}</td>
                      <td><Meter value={r.lead_ratio * 100} label={`${(r.lead_ratio * 100).toFixed(0)} %`} /></td>
                      <td className="num text-faint">{r.median_lag_h !== null ? t("carto.hours", { n: r.median_lag_h }) : t("common.dash")}</td>
                    </tr>
                  ))}
                </Table>
              ) : <Empty>{leadlag.loading ? t("carto.computing") : t("carto.noEvents")}</Empty>}
            </Card>

            <Card title={t("carto.whoFollows")} aside={t("carto.whoFollowsAside")} help="leadlag">
              {leadlag.data?.pairs?.length ? (
                <Table headers={[t("carto.thLeader"), t("carto.thFollower"), t("carto.thTimes"), t("carto.thMedianLag")]} dense>
                  {leadlag.data.pairs.slice(0, 15).map((p: any, i: number) => (
                    <tr key={i}>
                      <td className="text-ink">{p.leader_name}</td>
                      <td className="text-muted">{p.follower_name}</td>
                      <td className="num">{p.count}</td>
                      <td className="num text-faint">{t("carto.hours", { n: p.median_lag_h })}</td>
                    </tr>
                  ))}
                </Table>
              ) : <Empty>{t("common.dash")}</Empty>}
            </Card>
          </div>

          <Card title={t("carto.dissidentJournalists")} aside={t("carto.dissidentAside")} help={["dissident", "accessibility"]}>
            {dissidents.data?.length ? (
              <Table headers={[t("carto.thJournalist"), t("carto.thOutlet"), t("carto.thArticles"), t("carto.thGapOutlet"), t("carto.thDivAxis"), <Term k="accessibility">{t("carto.csvAccess")}</Term>]} dense>
                {dissidents.data.slice(0, 20).map((d: any) => (
                  <tr key={d.id}>
                    <td><Link to={`/journalists/${d.id}`} className="font-medium text-ink hover:text-accent-strong">{d.name}</Link></td>
                    <td className="text-muted">{d.outlet_name}</td>
                    <td className="num text-muted">{d.n_articles}</td>
                    <td><Meter value={d.deviation * 100} tone={d.deviation > 0.35 ? "alert" : "accent"} label={d.deviation.toFixed(2)} /></td>
                    <td>{d.axis ? <Badge tone={Math.abs(d.axis_delta) > 0.5 ? "alert" : "default"}>{axisName(t, d.axis, d.axis_label)} → {d.direction} ({d.axis_delta > 0 ? "+" : ""}{d.axis_delta})</Badge> : t("common.dash")}</td>
                    <td><ScorePill value={d.accessibility} /></td>
                  </tr>
                ))}
              </Table>
            ) : <Empty>{dissidents.loading ? t("carto.computing") : t("carto.noJournalistEnough")}</Empty>}
          </Card>

          <Card title={t("carto.entitiesValence")} aside={t("carto.entitiesAside")} help="valence">
            {entities.data?.entities?.length ? (
              <Table headers={[t("carto.thEntity"), t("carto.thType"), t("carto.thMentions"), t("carto.thOutlets"), <Term k="valence">{t("carto.thAvgValence")}</Term>, t("carto.thSpread"), t("carto.thNegPos")]} dense>
                {entities.data.entities.slice(0, 25).map((e: any) => {
                  const cells = [...e.cells].filter((c: any) => c.mentions >= 2).sort((a: any, b: any) => a.valence - b.valence);
                  const neg = cells[0], pos = cells[cells.length - 1];
                  return (
                    <tr key={e.entity}>
                      <td className="font-medium text-ink">{e.entity}</td>
                      <td><Badge tone="faint">{e.kind === "people" ? t("carto.person") : t("carto.org")}</Badge></td>
                      <td className="num">{e.mentions}</td>
                      <td className="num text-muted">{e.outlets}</td>
                      <td><span className={`num ${e.valence < -0.3 ? "text-confidential" : e.valence > 0.2 ? "text-accent-strong" : "text-muted"}`}>{e.valence > 0 ? "+" : ""}{e.valence.toFixed(2)}</span></td>
                      <td><Meter value={e.spread * 100} tone="muted" label={e.spread.toFixed(2)} /></td>
                      <td className="text-[11.5px] text-muted">{neg && pos && neg !== pos ? <>{neg.outlet} <span className="num text-confidential">{neg.valence.toFixed(2)}</span> / {pos.outlet} <span className="num text-accent-strong">{pos.valence > 0 ? "+" : ""}{pos.valence.toFixed(2)}</span></> : t("common.dash")}</td>
                    </tr>
                  );
                })}
              </Table>
            ) : <Empty>{entities.loading ? t("carto.computing") : t("common.dash")}</Empty>}
          </Card>

          {/* Proximité entre médias */}
          <Card
            title={t("carto.proximity")}
            help={["similarity", "pack"]}
            aside={<span className="flex items-center gap-3"><Segmented value={matrixMode} onChange={setMatrixMode} options={[{ value: "topic_similarity", label: t("carto.topicsCovered") }, { value: "framing_similarity", label: t("carto.framing") }]} /><span>{t("carto.matrixHint")}</span></span>}
          >
            {packs.loading && !packs.data ? <Loading /> : packs.error ? <Empty>{packs.error}</Empty> : <ProximityMatrix data={packs.data} mode={matrixMode} />}
          </Card>
          {packs.data?.pairs?.length > 0 && (
            <Card title={t("carto.packs")} aside={t("carto.packsAside")} help={["pack", "similarity"]}>
              <Table headers={[t("carto.thOutletA"), t("carto.thOutletB"), t("carto.thCommonTopics"), t("carto.thCommonFraming")]} dense>
                {packs.data.pairs.slice(0, 12).map((p: any, i: number) => (
                  <tr key={i}>
                    <td><Link to={`/outlets/${p.a}`} className="text-ink hover:text-accent-strong">{p.a_name}</Link></td>
                    <td><Link to={`/outlets/${p.b}`} className="text-ink hover:text-accent-strong">{p.b_name}</Link></td>
                    <td><Meter value={p.topic_similarity * 100} label={`${(p.topic_similarity * 100).toFixed(0)} %`} /></td>
                    <td><Meter value={(p.framing_similarity + 1) * 50} tone="ink" label={`${(p.framing_similarity * 100).toFixed(0)} %`} /></td>
                  </tr>
                ))}
              </Table>
            </Card>
          )}

          {/* Corpus sémantique */}
          <Card
            title={t("carto.corpusMap")}
            help={["corpus", "blindspot"]}
            aside={<span className="flex items-center gap-2">
              <Select value={corpusOutlet ?? ""} onChange={(e) => setCorpusOutlet(e.target.value ? +e.target.value : null)}>
                <option value="">{t("common.allOutlets")}</option>
                {outlets.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
              </Select>
              <Select value={corpusTopic ?? ""} onChange={(e) => setCorpusTopic(e.target.value || null)}>
                <option value="">{t("carto.allTopics")}</option>
                {corpus.data?.topics?.map((tp: any) => <option key={tp.topic} value={tp.topic}>{tp.topic} ({tp.articles})</option>)}
              </Select>
            </span>}
          >
            {corpus.loading && !corpus.data ? <Loading /> : corpus.error ? <Empty>{corpus.error}</Empty> : <CorpusMap data={corpus.data} focusOutlet={corpusOutlet} focusTopic={corpusTopic} />}
          </Card>
          <div className="grid gap-5 lg:grid-cols-2">
            <Card title={t("carto.dominantTopics")} aside={t("carto.topicsAside")}>
              {corpus.data?.topics?.length ? (
                <ul className="divide-y divide-hair-soft">
                  {corpus.data.topics.slice(0, 12).map((tp: any) => (
                    <li key={tp.topic} className="flex items-center justify-between py-1.5 text-[12.5px]">
                      <button className="text-left text-ink hover:text-accent-strong" onClick={() => setCorpusTopic(corpusTopic === tp.topic ? null : tp.topic)}>{tp.topic}</button>
                      <span className="num text-faint">{t("carto.artsOutlets", { a: tp.articles, o: tp.outlets, s: tp.outlets > 1 ? "s" : "" })}</span>
                    </li>
                  ))}
                </ul>
              ) : <Empty>{t("common.dash")}</Empty>}
            </Card>
            <Card title={t("dash.blind")} aside={t("carto.blindAside")} help="blindspot">
              {corpus.data?.blind_spots?.length ? (
                <ul className="divide-y divide-hair-soft">
                  {corpus.data.blind_spots.slice(0, 12).map((b: any, i: number) => (
                    <li key={i} className="flex items-center justify-between gap-3 py-1.5 text-[12.5px]">
                      <span className="text-ink">{b.topic}</span>
                      <span className="whitespace-nowrap text-faint"><Link to={`/outlets/${b.outlet_id}`} className="hover:text-accent-strong">{b.outlet}</Link> · <span className="num">{b.articles}</span></span>
                    </li>
                  ))}
                </ul>
              ) : <Empty>{t("carto.noBlind")}</Empty>}
            </Card>
          </div>
        </div>
      )}

      {/* ───────────────────────── Annuaire */}
      {view === "directory" && (
        <>
          <div className="mb-4 flex flex-wrap items-center gap-2">
            <Input value={search} onChange={(e) => setSearch(e.target.value)} placeholder={t("carto.searchPlaceholder")} className="max-w-sm" />
            <Select value={countryFilter} onChange={(e) => setCountryFilter(e.target.value)}>
              <option value="">{t("common.allCountries")}</option>
              {countries.map((c) => <option key={c} value={c}>{flag(c)} {countryName(c)}</option>)}
            </Select>
            <Button className="ml-auto" onClick={exportCSV}><Download size={13} /> {t("carto.exportCsv")}</Button>
          </div>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {outlets.filter((o) => (!countryFilter || o.country === countryFilter) && (!search || o.name.toLowerCase().includes(search.toLowerCase()) || journalists.some((j) => j.outlet_id === o.id && j.name.toLowerCase().includes(search.toLowerCase())))).map((o) => {
              const js = journalists.filter((j) => j.outlet_id === o.id).sort((a, b) => (b.accessibility_score || 0) - (a.accessibility_score || 0));
              const byBeat: Record<string, any[]> = {};
              for (const j of js) { const b = beatLabel(journalistBeat(j) || splitBio(j.bio).beat, t); (byBeat[b] ||= []).push(j); }
              return (
                <Card key={o.id}>
                  <div className="mb-2 flex items-start justify-between gap-3">
                    <div>
                      <Link to={`/outlets/${o.id}`} className="text-[14px] font-semibold text-ink hover:text-accent-strong">{o.name}</Link>
                      <div className="text-[11px] text-faint">{flag(o.country)} {countryName(o.country)} · {t("carto.nJournalists", { n: js.length, s: js.length !== 1 ? "s" : "" })}</div>
                    </div>
                    <div className="text-right"><div className="num text-[20px] font-bold leading-none text-accent-strong">{(o.influence_score || 0).toFixed(0)}</div><div className="label">{t("carto.termInfluence")}</div></div>
                  </div>
                  {Object.entries(byBeat).sort(([a, ja], [b, jb]) => a === unclass ? 1 : b === unclass ? -1 : jb.length - ja.length).slice(0, 6).map(([beat, list]) => (
                    <div key={beat} className="mb-1.5">
                      <span className="label">{beat} <span className="num font-normal text-faint">{list.length}</span></span>
                      <div className="mt-0.5 flex flex-wrap gap-x-2 gap-y-0.5 text-[12px]">
                        {list.slice(0, 8).map((j) => <Link key={j.id} to={`/journalists/${j.id}`} className="text-muted hover:text-accent-strong">{j.name} <ScorePill value={j.accessibility_score} /></Link>)}
                        {list.length > 8 && <span className="text-faint">+{list.length - 8}</span>}
                      </div>
                    </div>
                  ))}
                </Card>
              );
            })}
          </div>
        </>
      )}

      <div className="closing-rule mt-12" />
    </div>
  );
}
