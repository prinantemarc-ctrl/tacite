import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { getDashboard } from "../api";
import { readView, writeView } from "../viewCache";
import { Card, Stat, Badge, ActionBadge, Empty, Loading, ErrorState, PageHeader, Term, Meter, Callout, Button, ScorePill, Select } from "../components";
import TopicsMap from "../components/maps/TopicsMap";
import { flag, countryName } from "../geo";
import { T } from "../theme";
import { useI18n } from "../i18n/I18nProvider";

const signed = (n: number) => (n > 0 ? "+" : "") + n.toFixed(2);
const DASH_COUNTRY_KEY = "tacite-dash-country";

const HEAT_TONE: Record<string, "accent" | "ink" | "faint" | "default"> = {
  new: "accent", up: "accent", stable: "default", down: "faint",
};

function readSavedCountry() {
  try { return localStorage.getItem(DASH_COUNTRY_KEY) || ""; } catch { return ""; }
}

export default function DashboardPage() {
  const { t, intl, locale } = useI18n();
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [country, setCountry] = useState(readSavedCountry);
  const [mapStory, setMapStory] = useState<number | null>(null);
  const [mapTheme, setMapTheme] = useState<number | null>(null);
  const [opsOpen, setOpsOpen] = useState(false);
  const navigate = useNavigate();

  const today = new Date().toLocaleDateString(intl, { weekday: "long", day: "numeric", month: "long", year: "numeric" });
  const ago = (iso?: string | null) => {
    if (!iso) return t("dash.never");
    const m = Math.round((Date.now() - new Date(iso + (iso.endsWith("Z") ? "" : "Z")).getTime()) / 60000);
    if (m < 2) return t("dash.justNow");
    if (m < 60) return t("dash.agoMin", { n: m });
    if (m < 1440) return t("dash.agoHours", { n: Math.round(m / 60) });
    return t("dash.agoDays", { n: Math.round(m / 1440) });
  };
  const statusLabel = (s: string) => {
    const key = `dash.status_${s}`;
    const v = t(key);
    return v === key ? s : v;
  };
  const recLabel = (s: string) => {
    const key = `dash.rec_${s}`;
    const v = t(key);
    return v === key ? s : v;
  };
  const outcomeLabel = (o: string) => (
    o === "success" ? t("dash.outcome_success") : o === "partial" ? t("dash.outcome_partial") : t("dash.outcome_failure")
  );

  const preparingRef = useRef(false);
  preparingRef.current = !!data?.views_preparing;

  useEffect(() => {
    try {
      if (country) localStorage.setItem(DASH_COUNTRY_KEY, country);
      else localStorage.removeItem(DASH_COUNTRY_KEY);
    } catch { /* ignore */ }
    setMapStory(null);
    setMapTheme(null);
    let cancelled = false;
    const cacheKey = `dashboard:${country || "all"}`;
    readView<any>(cacheKey).then((cached) => { if (!cancelled && cached && !cached.views_preparing) setData(cached); });
    const load = () => getDashboard(country || undefined)
      .then((d) => {
        if (cancelled) return;
        setData(d);
        setError(null);
        if (!d.views_preparing) writeView(cacheKey, d);
      })
      .catch((e) => { if (!cancelled) setError(String(e)); });
    load();
    const slow = setInterval(load, 5 * 60 * 1000);
    const quick = setInterval(() => { if (preparingRef.current) load(); }, 8000);
    return () => { cancelled = true; clearInterval(slow); clearInterval(quick); };
  }, [locale, country]);

  const countries = useMemo(() => {
    const codes = new Set<string>(data?.country_options || []);
    for (const c of data?.pipeline?.captured_by_country || []) if (c.country) codes.add(c.country);
    for (const c of data?.by_country || []) if (c.country) codes.add(c.country);
    return [...codes].sort((a, b) => countryName(a).localeCompare(countryName(b), locale));
  }, [data, locale]);

  if (error && !data) return <ErrorState>{t("dash.loadError")} {error}</ErrorState>;
  if (!data) return <Loading />;
  const countryPending = (data.country || "").toUpperCase() !== (country || "").toUpperCase();

  const k = data.kpis, p = data.pipeline, mv = data.movements, cl = data.clients;
  const alerts: any[] = mv.alerts, moves: any[] = mv.top;
  const maxDay = Math.max(1, ...p.daily.map((d: any) => d.analyzed + d.other));
  const stale = p.last_ingestion ? Date.now() - new Date(p.last_ingestion + "Z").getTime() > 6 * 3600 * 1000 : true;
  const recTotal = Object.values(cl.recommendations as Record<string, number>).reduce((a, b) => a + b, 0);
  const topicsQ = country ? `days=7&country=${country}` : "days=7";
  const hold = data.views_preparing ? t("dash.preparing") : "";
  const kitLabel = data.kit?.label || (country ? t("dash.structuralKit") : "");
  const agendaToday: any[] = data.agenda_today || [];
  const agendaWeek: any[] = data.topics || [];
  const hasMap = (data.topics_map?.themes || []).length > 0;

  const topicRow = (row: any, maxArts: number) => (
    <li key={row.id || row.topic} className="flex items-center justify-between gap-3 py-1.5 text-[12.5px]">
      <Link to={`/topics?${topicsQ}`} className="truncate text-ink hover:text-accent-strong">{row.topic}</Link>
      <span className="flex shrink-0 items-center gap-2">
        {row.heat ? <Badge tone={HEAT_TONE[row.heat] || "default"}>{t(`heat.${row.heat}`)}</Badge> : null}
        <Meter value={row.articles} max={maxArts} width="w-14" />
        <span className="num w-20 whitespace-nowrap text-right text-[11.5px] text-faint">{t("topics.artsMed", { a: row.articles, o: row.outlets })}</span>
      </span>
    </li>
  );

  return (
    <div>
      <PageHeader
        kicker={t("dash.kicker")}
        title={t("dash.title")}
        subtitle={countryPending ? t("common.loading") : <>{t("dash.subtitle", { date: today, ago: ago(p.last_ingestion), n: p.captured_24h })}{p.errors_24h ? <> · <span className="text-confidential">{t("dash.collectErrors", { n: p.errors_24h, s: p.errors_24h > 1 ? "s" : "" })}</span></> : "" }.</>}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Select value={country} onChange={(e) => setCountry(e.target.value)} className="min-w-[180px]">
              <option value="">{t("dash.allCountries")}</option>
              {countries.map((c) => <option key={c} value={c}>{flag(c)} {countryName(c)}</option>)}
            </Select>
            <Button size="sm" onClick={() => navigate("/cartography")}>{t("nav.cartography")}</Button>
            <Button size="sm" variant="primary" onClick={() => navigate("/clients")}>{t("nav.clients")}</Button>
          </div>
        }
      />

      {countryPending ? <Loading /> : <>
      {country && kitLabel && (
        <div className="mb-5 text-[12px] text-muted">
          <Term k="axes">{t("dash.kit")}</Term>
          {" · "}
          <span className="font-medium text-ink">{kitLabel}</span>
          {data.kit?.axes?.length ? <span className="text-faint"> · {data.kit.axes.map((a: any) => a.label || t(`axis.${a.id}`)).join(" · ")}</span> : null}
        </div>
      )}

      <div className="mb-7 grid grid-cols-2 gap-6 md:grid-cols-5">
        <Stat label={t("dash.documented")} value={<>{k.outlets_documented}<span className="text-[15px] font-normal text-faint"> / {k.outlets}</span></>} sub={country ? countryName(country) : t("dash.countriesArts", { n: k.countries })} help="confidence" />
        <Stat label={t("dash.analyzed7d")} value={k.analyzed_7d} sub={k.pending ? `${t("dash.pendingSub", { n: k.pending })}${k.pending_oldest ? t("dash.oldest", { ago: ago(k.pending_oldest) }) : ""}` : t("dash.queueEmpty")} help="status_analyzed" />
        <Stat label={t("dash.journalistsProfiled")} value={<>{k.journalists_profiled}<span className="text-[15px] font-normal text-faint"> / {k.journalists}</span></>} sub={t("dash.llmProfiles")} help="accessibility" />
        <Stat label={t("dash.meanGap")} value={k.mean_gap !== null ? k.mean_gap.toFixed(2) : t("common.dash")} sub={t("dash.meanGapSub")} tone={k.mean_gap > 0.3 ? "alert" : "ink"} help="gap" />
        <Stat label={t("dash.llmCost")} value={`${k.cost_month} $`} sub={<>{t("dash.costSub", { today: k.cost_today, cap: k.cost_cap ? ` / ${k.cost_cap} $` : "" })}</>} tone="accent" help="llm_cost" />
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card title={t("dash.agendaToday")} help={["topic_cluster", "topic_heat"]} aside={<Link to={`/topics?days=1${country ? `&country=${country}` : ""}`} className="hover:text-ink">{t("dash.agendaTodayAside")}</Link>}>
          {agendaToday.length ? (
            <ul className="divide-y divide-hair-soft">{agendaToday.map((row) => topicRow(row, agendaToday[0].articles || 1))}</ul>
          ) : <Empty>{hold || t("dash.noAgendaToday")}</Empty>}
        </Card>
        <Card title={t("dash.agendaWeek")} help={["topic_cluster", "blindspot"]} aside={<Link to={`/topics?${topicsQ}`} className="hover:text-ink">{t("dash.agendaLink")}</Link>}>
          {agendaWeek.length ? (
            <ul className="divide-y divide-hair-soft">{agendaWeek.slice(0, 8).map((row: any) => topicRow(row, agendaWeek[0].articles || 1))}</ul>
          ) : <Empty>{hold || t("dash.noAnalyzed7d")}</Empty>}
          {data.blind_spots.length > 0 && (
            <div className="mt-3 border-t border-hair-soft pt-2">
              <div className="label mb-1"><Term k="blindspot">{t("dash.blind")}</Term></div>
              <ul className="space-y-0.5 text-[12px]">
                {data.blind_spots.slice(0, 3).map((b: any, i: number) => (
                  <li key={i} className="flex justify-between gap-2"><span className="truncate text-muted">{b.topic}</span><Link to={`/outlets/${b.outlet_id}`} className="shrink-0 text-faint hover:text-accent-strong">{b.outlet} · {b.articles}</Link></li>
                ))}
              </ul>
            </div>
          )}
        </Card>
      </div>

      {hasMap && (
        <Card title={t("topics.title")} help={["topic_cluster"]} aside={t("dash.mapHint")} className="mt-5">
          <TopicsMap
            data={data.topics_map}
            selected={mapStory}
            themeId={mapTheme}
            onSelect={(id) => { setMapStory(id); if (id) navigate(`/topics?${topicsQ}`); }}
            onTheme={(id) => { setMapTheme(id); }}
            compact
          />
        </Card>
      )}

      {!country && (data.by_country || []).length > 0 && (
        <Card title={t("dash.topicsByCountry")} help="topic_cluster" aside={t("dash.topicsByCountryAside")} className="mt-5">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {data.by_country.map((row: any) => (
              <div key={row.country} className="rounded-sm border border-hair-soft px-3 py-2.5">
                <div className="mb-1.5 flex items-baseline justify-between gap-2">
                  <button type="button" className="font-medium text-ink hover:text-accent-strong" onClick={() => setCountry(row.country)}>
                    {flag(row.country)} {countryName(row.country)}
                  </button>
                  <span className="num text-[11px] text-faint">{t("dash.nArts", { n: row.n_articles })}</span>
                </div>
                <ul className="space-y-1 text-[12px]">
                  {(row.topics || []).slice(0, 4).map((tp: any) => (
                    <li key={tp.id || tp.topic} className="flex justify-between gap-2">
                      <span className="truncate text-muted">{tp.topic}</span>
                      <span className="num shrink-0 text-faint">{tp.articles}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </Card>
      )}

      <div className="mt-5 grid gap-5 lg:grid-cols-[3fr_2fr]">
        <Card
          title={alerts.length ? `${t("dash.weekDrifts")} · ${alerts.length}` : t("dash.weekMoves")}
          help={["drift", "measured"]}
          aside={alerts.length ? t("dash.aboveThreshold", { n: mv.threshold }) : moves.length ? t("dash.noDrift", { n: mv.threshold }) : undefined}
        >
          {(alerts.length ? alerts : moves).length ? (
            <ul className="divide-y divide-hair-soft">
              {(alerts.length ? alerts : moves).slice(0, 6).map((m: any, i: number) => (
                <li key={i} className="flex items-center gap-3 py-2 text-[12.5px]">
                  <Link to={`/outlets/${m.outlet_id}`} className="w-36 shrink-0 truncate font-medium text-ink hover:text-accent-strong">{m.name}</Link>
                  <span className="w-24 shrink-0 text-muted">{m.label}</span>
                  <span className="flex-1 text-faint">{t("dash.towards")} <i>{m.pole}</i></span>
                  <span className="num text-faint">{signed(m.previous)} → {signed(m.current)}</span>
                  <Badge tone={m.above_threshold ? "alert" : Math.abs(m.value) >= mv.threshold / 2 ? "accent" : "faint"}>{signed(m.value)}</Badge>
                </li>
              ))}
            </ul>
          ) : <Empty>{t("dash.needTwoWeeks")}</Empty>}
        </Card>

        <Card title={t("dash.strongestGaps")} help={["gap", "declared", "measured"]} aside={t("dash.byOutlet")}>
          {data.gaps.length ? (
            <ul className="divide-y divide-hair-soft">
              {data.gaps.slice(0, 6).map((g: any) => (
                <li key={g.outlet_id} className="py-2 text-[12.5px]">
                  <div className="flex items-center justify-between">
                    <Link to={`/outlets/${g.outlet_id}`} className="font-medium text-ink hover:text-accent-strong">{flag(g.country)} {g.name}</Link>
                    <Badge tone={Math.abs(g.value) > 0.5 ? "alert" : "accent"}>{signed(g.value)}</Badge>
                  </div>
                  <div className="mt-0.5 text-[11.5px] text-muted">{g.label}{t("dash.gapValues", { declared: signed(g.declared), measured: signed(g.measured) })} <i>{g.pole}</i> {t("dash.thanAnnounced")}</div>
                </li>
              ))}
            </ul>
          ) : <Empty>{t("dash.noDocumented")}</Empty>}
        </Card>
      </div>

      <div className="mt-5 grid gap-5 lg:grid-cols-3">
        <Card title={t("dash.whoLeads")} help={["leadlag", "comp_agenda"]} aside={t("dash.leadlagAside", { n: data.leadlag_events })}>
          {data.leaders.length ? (
            <ul className="divide-y divide-hair-soft">
              {data.leaders.map((r: any) => (
                <li key={r.outlet_id} className="flex items-center justify-between gap-3 py-1.5 text-[12.5px]">
                  <Link to={`/outlets/${r.outlet_id}`} className="truncate text-ink hover:text-accent-strong">{flag(r.country)} {r.name}</Link>
                  <span className="flex shrink-0 items-center gap-2"><Meter value={r.lead_ratio * 100} width="w-14" /><span className="num w-[92px] whitespace-nowrap text-right text-[11.5px] text-faint">{t("dash.leadFollow", { leads: r.leads, follows: r.follows })}</span></span>
                </li>
              ))}
            </ul>
          ) : <Empty>{hold || t("dash.notEnoughTopics")}</Empty>}
        </Card>

        <Card title={data.dissidents_above_threshold ? t("dash.dissidents") : t("dash.farthestJournalists")} help="dissident" aside={data.dissidents_above_threshold ? t("dash.gapAbove") : t("dash.noneAbove")}>
          {data.dissidents.length ? (
            <ul className="divide-y divide-hair-soft">
              {data.dissidents.map((d: any) => (
                <li key={d.id} className="py-2 text-[12.5px]">
                  <div className="flex items-center justify-between gap-2">
                    <Link to={`/journalists/${d.id}`} className="truncate font-medium text-ink hover:text-accent-strong">{d.name}</Link>
                    <ScorePill value={d.accessibility} />
                  </div>
                  <div className="mt-0.5 text-[11.5px] text-muted">{d.outlet_name} · {t("dash.deviation", { n: d.deviation.toFixed(2) })}{d.axis_label ? <> · {d.axis_label} → <i>{d.direction}</i> ({signed(d.axis_delta)})</> : null}</div>
                </li>
              ))}
            </ul>
          ) : <Empty>{hold || t("dash.noDissident")}</Empty>}
          {data.accessible.length > 0 && data.dissidents.length < 4 && (
            <div className="mt-3 border-t border-hair-soft pt-2">
              <div className="label mb-1"><Term k="accessibility">{t("dash.mostAccessible")}</Term></div>
              <ul className="space-y-0.5 text-[12px]">
                {data.accessible.slice(0, 4).map((j: any) => (
                  <li key={j.id} className="flex justify-between gap-2"><Link to={`/journalists/${j.id}`} className="truncate text-ink hover:text-accent-strong">{j.name}</Link><span className="shrink-0 text-faint">{j.outlet} <ScorePill value={j.accessibility} /></span></li>
                ))}
              </ul>
            </div>
          )}
        </Card>

        <Card title={t("dash.divisive")} help={["valence", "tone"]} aside={t("dash.days30")}>
          {data.divisive.length ? (
            <ul className="divide-y divide-hair-soft">
              {data.divisive.map((e: any) => (
                <li key={e.entity} className="py-2 text-[12.5px]">
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate font-medium text-ink">{e.entity}</span>
                    <span className="num shrink-0 text-faint">{t("dash.mentionsOutlets", { n: e.mentions, o: e.outlets })}</span>
                  </div>
                  {e.most_negative && e.most_positive && (
                    <div className="mt-0.5 text-[11.5px] text-muted">
                      <span className="text-confidential">{e.most_negative.outlet} {e.most_negative.valence.toFixed(2)}</span> ↔ <span className="text-accent-strong">{e.most_positive.outlet} {signed(e.most_positive.valence)}</span>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          ) : <Empty>{hold || t("dash.noEntity")}</Empty>}
        </Card>
      </div>

      <details className="mt-5 rounded-sm border border-hair" open={opsOpen} onToggle={(e) => setOpsOpen((e.target as HTMLDetailsElement).open)}>
        <summary className="cursor-pointer px-4 py-2.5 text-[12px] font-semibold uppercase tracking-[0.08em] text-muted hover:text-ink">{t("dash.opsToggle")}</summary>
        <div className="border-t border-hair-soft p-4">
          <div className="grid gap-5 lg:grid-cols-[3fr_2fr]">
            <Card title={t("dash.activity14")} help={["status_analyzed", "status_embedded", "status_duplicate"]} aside={t("dash.activeFeeds", { n: p.feeds })}>
              <svg width="100%" height={84} viewBox={`0 0 ${p.daily.length * 20} 84`} preserveAspectRatio="none" className="block">
                {p.daily.map((d: any, i: number) => {
                  const tot = d.analyzed + d.other, hT = (tot / maxDay) * 70, hA = (d.analyzed / maxDay) * 70;
                  return (
                    <g key={d.date} transform={`translate(${i * 20 + 3},0)`}>
                      <rect x={0} y={72 - hT} width={14} height={hT} fill={T.hair} />
                      <rect x={0} y={72 - hA} width={14} height={hA} fill={T.accent} />
                      <title>{t("dash.chartTip", { date: d.date, n: d.analyzed, tot })}</title>
                    </g>
                  );
                })}
              </svg>
              <div className="mt-1 flex justify-between text-[10px] text-faint"><span>{p.daily[0]?.date.slice(5)}</span><span>{t("dash.chartLegend")}</span><span>{p.daily[p.daily.length - 1]?.date.slice(5)}</span></div>
              <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 border-t border-hair-soft pt-2 text-[12px]">
                {Object.entries(p.status_counts as Record<string, number>).sort(([, a], [, b]) => b - a).map(([s, n]) => (
                  <span key={s} className="text-muted"><span className="num font-medium text-ink">{n}</span> {statusLabel(s)}</span>
                ))}
              </div>
              {(p.captured_by_country || []).length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {p.captured_by_country.map((c: any) => (
                    <button key={c.country} type="button" onClick={() => setCountry(c.country)} className="inline-flex items-center gap-1 rounded-sm border border-hair px-1.5 py-0.5 text-[11px] text-muted hover:border-accent hover:text-ink">
                      {flag(c.country)} <span className="num font-medium text-ink">{c.n}</span>
                    </button>
                  ))}
                </div>
              )}
              {stale && <div className="mt-3"><Callout warn label={t("dash.collect")}>{t("dash.staleCollect")}</Callout></div>}
              {k.pending > (k.analysis_batch_size || 50) * 3 && <div className="mt-3"><Callout warn label={t("dash.analysisQueue")}>{t("dash.queueBacklog", { n: k.pending, ago: ago(k.pending_oldest) })}</Callout></div>}
            </Card>

            <Card title={cl.count ? `${t("nav.clients")} · ${cl.count}` : t("nav.clients")} help={["actions", "priority", "adaptive"]} aside={recTotal ? Object.entries(cl.recommendations as Record<string, number>).map(([s, n]) => `${n} ${recLabel(s)}`).join(" · ") : undefined}>
              {cl.count === 0 ? (
                <div className="space-y-3">
                  <Callout label={t("dash.noClientFile")}>{t("dash.noClientBody")}</Callout>
                  <Button variant="primary" size="sm" onClick={() => navigate("/clients")}>{t("dash.createClient")}</Button>
                </div>
              ) : cl.recent.length ? (
                <ul className="divide-y divide-hair-soft">
                  {cl.recent.map((r: any) => (
                    <li key={r.id} className="flex items-center justify-between gap-2 py-2 text-[12.5px]">
                      <div className="min-w-0"><ActionBadge type={r.action_type} /> <Link to={`/clients/${r.client_id}`} className="ml-1 text-ink hover:text-accent-strong">{r.outlet}</Link>{r.journalist && <span className="text-faint"> · {r.journalist}</span>}</div>
                      <span className="num shrink-0 text-[11px] text-faint">{r.client} · p. {r.priority.toFixed(2)}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <div className="space-y-3">
                  <ul className="divide-y divide-hair-soft">
                    {cl.list.map((c: any) => <li key={c.id} className="flex justify-between py-1.5 text-[12.5px]"><Link to={`/clients/${c.id}`} className="text-ink hover:text-accent-strong">{c.name}</Link><span className="text-faint">{c.sector}</span></li>)}
                  </ul>
                  <Callout label={t("dash.noRecs")}>{t("dash.noRecsBody")}</Callout>
                </div>
              )}
              {Object.keys(cl.outcomes).length > 0 && (
                <div className="mt-3 flex gap-4 border-t border-hair-soft pt-2 text-[12px] text-muted">
                  {Object.entries(cl.outcomes as Record<string, number>).map(([o, n]) => <span key={o}><span className="num font-medium text-ink">{n}</span> {outcomeLabel(o)}</span>)}
                </div>
              )}
            </Card>
          </div>
        </div>
      </details>
      </>}

      <div className="closing-rule mt-12" />
    </div>
  );
}
