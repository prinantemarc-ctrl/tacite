import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { getMapTopics, listOutlets, listJournalists, createReport } from "../api";
import { Card, Badge, Stat, Select, Button, Loading, Empty, PageHeader, Callout, Meter, Input } from "../components";
import TopicsMap from "../components/maps/TopicsMap";
import { flag, countryName } from "../geo";
import { useI18n } from "../i18n/I18nProvider";
import { angleLabel, toneWordLabel } from "../i18n/mapped";
import { Search, X } from "lucide-react";

const DAYS = [
  { value: 1, key: "topics.day1" },
  { value: 7, key: "topics.d7" },
  { value: 14, key: "topics.d14" },
  { value: 30, key: "topics.d30" },
  { value: 60, key: "topics.d60" },
];

const HEAT_TONE: Record<string, "accent" | "ink" | "faint" | "default"> = {
  new: "accent", up: "accent", stable: "default", down: "faint",
};

export default function TopicsPage() {
  const { t, locale, intl } = useI18n();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [outlets, setOutlets] = useState<any[]>([]);
  const [journalists, setJournalists] = useState<any[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [themeId, setThemeId] = useState<number | null>(null);
  const [reportBusy, setReportBusy] = useState(false);

  const days = Number(params.get("days") || 7);
  const country = params.get("country") || "";
  const outletId = params.get("outlet_id") || "";
  const journalistId = params.get("journalist_id") || "";
  const qParam = (params.get("q") || "").trim();
  const [qDraft, setQDraft] = useState(params.get("q") || "");
  const [searchThemes, setSearchThemes] = useState<any[] | null>(null);
  const [searching, setSearching] = useState(false);

  const set = (k: string, v: string) => {
    const next = new URLSearchParams(params);
    if (v) next.set(k, v); else next.delete(k);
    if (k === "country") { next.delete("outlet_id"); next.delete("journalist_id"); }
    if (k === "outlet_id") next.delete("journalist_id");
    setSelected(null);
    setThemeId(null);
    setParams(next, { replace: true });
  };

  const setQueryParam = (v: string) => {
    const next = new URLSearchParams(params);
    if (v) next.set("q", v); else next.delete("q");
    setParams(next, { replace: true });
  };

  useEffect(() => {
    setQDraft((cur) => (cur.trim() === qParam ? cur : qParam));
  }, [qParam]);

  useEffect(() => {
    listOutlets().then(setOutlets);
    listJournalists().then(setJournalists);
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true); setError(null);
    const filters = [
      `days=${days}`,
      country && `country=${country}`,
      outletId && `outlet_id=${outletId}`,
      journalistId && `journalist_id=${journalistId}`,
    ].filter(Boolean);
    getMapTopics([...filters, "briefs=false"].join("&"))
      .then((d) => {
        if (cancelled) return;
        setData(d); setSelected(null); setThemeId(null); setLoading(false);
        getMapTopics([...filters, "briefs=true"].join("&"))
          .then((full) => { if (!cancelled) setData(full); })
          .catch(() => { /* la carte est déjà à l'écran */ });
      })
      .catch((e) => { if (!cancelled) { setError(e.message); setLoading(false); } });
    return () => { cancelled = true; };
  }, [days, country, outletId, journalistId]);

  useEffect(() => {
    const v = qDraft.trim();
    if (v.length < 2) {
      if (qParam) setQueryParam("");
      return;
    }
    if (v === qParam) return;
    const h = window.setTimeout(() => setQueryParam(v), 400);
    return () => window.clearTimeout(h);
  }, [qDraft]);

  useEffect(() => {
    if (!qParam) {
      setSearchThemes(null);
      setSearching(false);
      return;
    }
    let cancelled = false;
    setSearching(true);
    const qs = [
      `days=${days}`,
      country && `country=${country}`,
      outletId && `outlet_id=${outletId}`,
      journalistId && `journalist_id=${journalistId}`,
      `q=${encodeURIComponent(qParam)}`,
      "briefs=false",
    ].filter(Boolean).join("&");
    getMapTopics(qs)
      .then((d) => { if (!cancelled) setSearchThemes(d.search?.themes || []); })
      .catch(() => { if (!cancelled) setSearchThemes([]); })
      .finally(() => { if (!cancelled) setSearching(false); });
    return () => { cancelled = true; };
  }, [qParam, days, country, outletId, journalistId]);

  const countries = useMemo(() => {
    const codes = [...new Set(outlets.map((o) => String(o.country || "")).filter(Boolean))];
    return codes.sort((a, b) => countryName(a).localeCompare(countryName(b), locale));
  }, [outlets, locale]);
  const outletsForSelect = country ? outlets.filter((o) => o.country === country) : outlets;
  const journalistsForSelect = useMemo(() => {
    let rows = journalists;
    if (outletId) rows = rows.filter((j) => String(j.outlet_id) === outletId);
    else if (country) {
      const ids = new Set(outlets.filter((o) => o.country === country).map((o) => o.id));
      rows = rows.filter((j) => ids.has(j.outlet_id));
    }
    return [...rows].sort((a, b) => a.name.localeCompare(b.name, locale));
  }, [journalists, outlets, country, outletId, locale]);

  const clusters: any[] = data?.clusters || [];
  const themes: any[] = useMemo(() => {
    const base = data?.themes || [];
    if (!searchThemes?.length) return base;
    const byId = new Map(base.map((t: any) => [t.id, t]));
    for (const t of searchThemes) if (!byId.has(t.id)) byId.set(t.id, t);
    return [...byId.values()];
  }, [data, searchThemes]);
  const listThemes = useMemo(() => {
    if (qParam) {
      if (searchThemes === null) return (data?.themes || []).slice(0, 16);
      return searchThemes;
    }
    if (data?.themes?.length) return data.themes;
    return clusters.map((c: any) => ({
      id: c.theme_id ?? c.id, label: c.label, stories: 1, story_ids: [c.id],
      articles: c.articles, outlets: c.outlets, aliases: c.aliases, heat: c.heat,
    })).slice(0, 16);
  }, [qParam, searchThemes, data, clusters]);
  const focusStory = clusters.find((c) => c.id === selected) || null;
  const focusFamily = !focusStory && themeId != null
    ? themes.find((th: any) => th.id === themeId) || null
    : null;
  const defaultFocus = !focusStory && !focusFamily ? (themes.find((th: any) => th.id === listThemes[0]?.id) || clusters[0] || null) : null;
  const focus = focusStory || focusFamily || defaultFocus;
  const isFamilyFocus = Boolean(focusFamily || (defaultFocus && defaultFocus.stories > 1));
  const isolatedArticles: any[] = data?.isolated_articles || [];
  const maxArt = Math.max(1, ...clusters.map((c) => c.articles));
  const nNew = clusters.filter((c) => c.heat === "new").length;
  const nUp = clusters.filter((c) => c.heat === "up").length;

  const selectStory = (id: number | null) => {
    setSelected(id);
    if (id == null) return;
    const c = clusters.find((x) => x.id === id);
    if (c) setThemeId(c.theme_id ?? c.id);
  };
  const selectFamily = (id: number | null) => {
    setThemeId(id);
    setSelected(null);
  };

  const generateNote = async () => {
    if (!focus) return;
    setReportBusy(true);
    try {
      const stories = focusFamily
        ? (focusFamily.story_summaries || []).map((s: any) => s.label).filter(Boolean)
        : [];
      const r = await createReport({
        kind: focusFamily ? "theme" : "topic",
        target: focus.label,
        country: country || undefined,
        weeks: Math.max(1, Math.round(days / 7)),
        notes: stories.length ? stories.join(" · ") : undefined,
      });
      navigate(`/reports/${r.id}`);
    } catch { /* leave the user on the page */ }
    finally { setReportBusy(false); }
  };

  return (
    <div>
      <PageHeader
        kicker={t("topics.kicker")}
        title={t("topics.title")}
        subtitle={t("topics.subtitle")}
      />

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Select value={days} onChange={(e) => set("days", e.target.value)}>
          {DAYS.map((d) => <option key={d.value} value={d.value}>{t(d.key)}</option>)}
        </Select>
        <Select value={country} onChange={(e) => set("country", e.target.value)}>
          <option value="">{t("common.allCountries")}</option>
          {countries.map((c) => <option key={c} value={c}>{flag(c)} {countryName(c)}</option>)}
        </Select>
        <Select value={outletId} onChange={(e) => set("outlet_id", e.target.value)}>
          <option value="">{t("common.allOutlets")}</option>
          {outletsForSelect.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
        </Select>
        <Select value={journalistId} onChange={(e) => set("journalist_id", e.target.value)}>
          <option value="">{t("common.allJournalists")}</option>
          {journalistsForSelect.map((j) => <option key={j.id} value={j.id}>{j.name}{j.outlet_name ? ` · ${j.outlet_name}` : ""}</option>)}
        </Select>
        {data && !loading && (
          <span className="ml-auto text-[11px] text-faint">
            {t("topics.inFamilies", { n: data.n_clustered, f: data.n_themes || clusters.length })}
            {clusters.length ? ` · ${t("topics.nStories", { n: clusters.length })}` : ""}
            {data.n_singletons ? ` · ${t("topics.nIsolated", { n: data.n_singletons })}` : ""}
            {" · "}{t("topics.since")} {data.since}
          </span>
        )}
      </div>

      {error ? <Empty>{error}</Empty> : loading && !data ? <Loading /> : !clusters.length ? (
        <Empty>{t("topics.empty")}</Empty>
      ) : (
        <>
          <div className="mb-5 grid grid-cols-2 gap-6 md:grid-cols-4">
            <Stat label={t("topics.families")} value={data.n_themes || clusters.length} sub={t("topics.storiesArticles", { s: clusters.length, n: data.n_articles })} help="topic_cluster" />
            <Stat label={t("topics.emerging")} value={nNew} sub={t("topics.absentPrev")} help="topic_heat" />
            <Stat label={t("topics.rising")} value={nUp} sub={t("topics.volumeUp")} help="topic_heat" />
            <Stat label={t("topics.isolated")} value={data.n_singletons} sub={t("topics.dustHint")} />
          </div>

          <div className="grid gap-5 lg:grid-cols-[minmax(280px,0.9fr)_minmax(0,1.6fr)]">
            <Card
              title={t("topics.list")}
              help={["topic_cluster", "topic_heat"]}
              aside={qParam && searchThemes?.length ? t("topics.searchAside", { n: searchThemes.length }) : t("topics.listAside")}
              className="max-h-[min(72vh,720px)] overflow-y-auto"
            >
              <div className="sticky top-0 z-10 mb-2 bg-paper pb-2">
                <div className="relative">
                  <Search size={13} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-faint" />
                  <Input
                    value={qDraft}
                    onChange={(e) => setQDraft(e.target.value)}
                    placeholder={t("topics.searchPlaceholder")}
                    aria-label={t("topics.searchPlaceholder")}
                    autoComplete="off"
                    type="search"
                    className="pl-8 pr-8 text-[12.5px]"
                  />
                  {qDraft ? (
                    <button
                      type="button"
                      onClick={() => { setQDraft(""); setQueryParam(""); }}
                      className="absolute right-2 top-1/2 -translate-y-1/2 text-faint hover:text-ink"
                      aria-label={t("common.close")}
                    >
                      <X size={13} />
                    </button>
                  ) : null}
                </div>
                {searching ? <p className="mt-1.5 text-[11px] text-faint">{t("topics.searching")}</p> : null}
              </div>
              {qParam && !searching && listThemes.length === 0 ? (
                <Empty>{t("topics.searchEmpty", { q: qParam })}</Empty>
              ) : (
              <ul className="divide-y divide-hair-soft">
                {listThemes.map((theme: any) => {
                  const stories = clusters.filter((c) => (c.theme_id ?? c.id) === theme.id);
                  const scoreById = new Map((theme.story_summaries || []).map((s: any) => [s.id, s.score]));
                  const rows = (stories.length ? stories : clusters.filter((c) => theme.story_ids?.includes(c.id)))
                    .slice()
                    .sort((a: any, b: any) => (Number(scoreById.get(b.id) ?? 0) - Number(scoreById.get(a.id) ?? 0)));
                  const themeOn = themeId === theme.id;
                  const themeScore = typeof theme.score === "number" ? theme.score : null;
                  if (rows.length <= 1) {
                    const c = rows[0];
                    if (!c) return null;
                    const h = { label: t(`heat.${c.heat}`) !== `heat.${c.heat}` ? t(`heat.${c.heat}`) : t("heat.stable"), tone: HEAT_TONE[c.heat] || HEAT_TONE.stable };
                    const on = selected === c.id || (selected == null && themeId == null && focus?.id === c.id);
                    const hit = themeScore ?? scoreById.get(c.id);
                    const previewArts = (c.members || []).slice(0, 2);
                    return (
                      <li key={c.id} className="py-2">
                        <button type="button" onClick={() => selectStory(selected === c.id ? null : c.id)}
                          className={`flex w-full items-start gap-3 py-1 text-left text-[12.5px] ${on ? "bg-tint -mx-2 px-2" : ""}`}>
                          <span className="min-w-0 flex-1">
                            <span className="font-medium text-ink">{c.label}</span>
                            {c.aliases?.length ? <span className="mt-0.5 block truncate text-[11px] text-faint">{c.aliases.slice(0, 3).join(" · ")}</span> : null}
                          </span>
                          <span className="flex shrink-0 flex-col items-end gap-1">
                            <span className="flex items-center gap-1">
                              {typeof hit === "number" ? <span className="num text-[10px] text-faint">{Math.round(hit * 100)} %</span> : null}
                              <Badge tone={h.tone}>{h.label}</Badge>
                            </span>
                            <span className="flex items-center gap-2">
                              <Meter value={c.articles} max={maxArt} width="w-12" />
                              <span className="num w-[4.5rem] text-right text-[11px] text-faint">{t("topics.artsMed", { a: c.articles, o: c.outlets })}</span>
                            </span>
                          </span>
                        </button>
                        {previewArts.length > 0 && (
                          <ul className="mt-1 space-y-1 border-l border-hair-soft pl-2.5 text-[11.5px]">
                            {previewArts.map((a: any) => (
                              <li key={a.id} className="truncate text-muted">
                                <span className="font-medium text-faint">{a.outlet} · </span>
                                <Link to={`/articles/${a.id}`} className="text-ink hover:text-accent-strong hover:underline">
                                  {a.title || t("common.untitled")}
                                </Link>
                              </li>
                            ))}
                          </ul>
                        )}
                      </li>
                    );
                  }
                  return (
                    <li key={`th-${theme.id}`} className="py-2">
                      <button type="button" onClick={() => selectFamily(themeOn && selected == null ? null : theme.id)}
                        className={`flex w-full items-start gap-3 py-1 text-left text-[12.5px] ${themeOn ? "bg-tint -mx-2 px-2 text-ink" : ""}`}>
                        <span className="min-w-0 flex-1">
                          <span className="font-semibold text-ink">{theme.label}</span>
                          {theme.aliases?.length ? <span className="mt-0.5 block truncate text-[11px] text-faint">{theme.aliases.slice(0, 3).join(" · ")}</span> : null}
                        </span>
                        <span className="flex shrink-0 flex-col items-end gap-0.5">
                          {themeScore != null ? <span className="num text-[10px] text-faint">{Math.round(themeScore * 100)} %</span> : null}
                          <span className="num text-[11px] text-faint">{t("topics.artsMed", { a: theme.articles, o: rows.length })}</span>
                        </span>
                      </button>
                      <ul className="ml-2 border-l border-hair-soft pl-2">
                        {rows.map((c: any) => {
                          const h = { label: t(`heat.${c.heat}`) !== `heat.${c.heat}` ? t(`heat.${c.heat}`) : t("heat.stable"), tone: HEAT_TONE[c.heat] || HEAT_TONE.stable };
                          const on = selected === c.id;
                          const hit = scoreById.get(c.id);
                          const previewArts = (c.members || []).slice(0, 2);
                          return (
                            <li key={c.id} className="py-1">
                              <button type="button" onClick={() => selectStory(on ? null : c.id)}
                                className={`flex w-full items-start gap-3 py-1 text-left text-[12.5px] ${on ? "bg-tint -mx-2 px-2" : ""}`}>
                                <span className="min-w-0 flex-1">
                                  <span className="font-medium text-ink">{c.label}</span>
                                </span>
                                <span className="flex shrink-0 flex-col items-end gap-1">
                                  <span className="flex items-center gap-1">
                                    {typeof hit === "number" ? <span className="num text-[10px] text-faint">{Math.round(hit * 100)} %</span> : null}
                                    <Badge tone={h.tone}>{h.label}</Badge>
                                  </span>
                                  <span className="num text-[11px] text-faint">{t("topics.artsMed", { a: c.articles, o: c.outlets })}</span>
                                </span>
                              </button>
                              {previewArts.length > 0 && (
                                <ul className="mt-0.5 space-y-0.5 pl-2 text-[11px]">
                                  {previewArts.map((a: any) => (
                                    <li key={a.id} className="truncate text-muted">
                                      <span className="font-medium text-faint">{a.outlet} · </span>
                                      <Link to={`/articles/${a.id}`} className="text-ink hover:text-accent-strong hover:underline">
                                        {a.title || t("common.untitled")}
                                      </Link>
                                    </li>
                                  ))}
                                </ul>
                              )}
                            </li>
                          );
                        })}
                      </ul>
                    </li>
                  );
                })}
              </ul>
              )}
              {!qParam && (data.n_themes_all || 0) > (data.themes?.length || 0) ? (
                <p className="mt-2 text-[11px] text-faint">{t("topics.otherTopics", { n: data.n_themes_all - data.themes.length })}</p>
              ) : null}
            </Card>
            <section className="overflow-hidden rounded-kit border border-hair">
              <TopicsMap data={data} selected={selected} themeId={themeId} onSelect={selectStory} onTheme={selectFamily} />
            </section>
          </div>

          {focus && (
            <Card
              className="mt-5"
              title={focus.label}
              help={["topic_polarization", "topic_heat"]}
              aside={
                <span className="flex items-center gap-2">
                  <Badge tone={HEAT_TONE[focus.heat] || HEAT_TONE.stable}>{t(`heat.${focus.heat}`) !== `heat.${focus.heat}` ? t(`heat.${focus.heat}`) : t("heat.stable")}</Badge>
                  <Button size="sm" onClick={generateNote} disabled={reportBusy}>
                    {reportBusy ? t(focusFamily ? "topics.briefing" : "topics.noting") : t(focusFamily ? "topics.brief" : "topics.note")}
                  </Button>
                </span>
              }
            >
              {focusStory && (() => {
                const family = themes.find((th: any) => th.id === focusStory.theme_id);
                return family && family.stories > 1 ? (
                  <p className="mb-3 text-[12px] text-muted">{t("topics.family")} : <button type="button" className="text-ink hover:text-accent-strong" onClick={() => selectFamily(family.id)}>{family.label}</button>{family.aliases?.length ? ` · ${t("topics.also")} ${family.aliases.join(" · ")}` : ""}</p>
                ) : null;
              })()}
              {focus.aliases?.length ? <p className="mb-3 text-[12px] text-muted">{t("topics.alsoNamed")} : {focus.aliases.join(" · ")}</p> : null}
              {focus.brief ? (
                <div className="mb-4">
                  <Callout label={t("topics.execSummary")}>
                    <p className="leading-relaxed text-ink">{focus.brief}</p>
                  </Callout>
                </div>
              ) : null}
              <div className="mb-4 grid gap-3 sm:grid-cols-4">
                <Stat label={t("common.articles")} value={focus.articles} />
                <Stat label={t("common.outlets")} value={focus.outlets} />
                <Stat label={t("common.journalists")} value={focus.journalists ?? "—"} />
                <Stat label={t("common.polarization")} value={(focus.polarization ?? 0).toFixed(2)} sub={t("common.consensus")} help="topic_polarization" />
              </div>

              <div className="mb-5 rounded-sm border border-hair-soft bg-surface p-3">
                <div className="label mb-2">{t("common.articles")} ({(focus.members || []).length})</div>
                <ul className="divide-y divide-hair-soft">
                  {(focus.members || []).map((a: any) => (
                    <li key={a.id} className="py-1.5 text-[12.5px]">
                      <Link to={`/articles/${a.id}`} className="font-medium text-ink hover:text-accent-strong hover:underline">
                        {a.title || t("common.untitled")}
                      </Link>
                      <div className="text-[11.5px] text-faint">
                        {a.outlet}{a.authors?.length ? ` · ${a.authors.map((x: any) => x.name).join(", ")}` : ""}{a.date ? ` · ${a.date}` : ""}
                        {a.tone ? ` · ${toneWordLabel(a.tone, t)}` : ""}
                      </div>
                    </li>
                  ))}
                </ul>
                {focus.articles > (focus.members || []).length && (
                  <p className="mt-2 text-[11px] text-faint">{t(isFamilyFocus ? "topics.otherFamilyArticles" : "topics.otherArticles", { n: focus.articles - focus.members.length })}</p>
                )}
              </div>

              {focus.spread && (
                <p className="mb-4 text-[12.5px] text-muted">
                  {t("topics.framingSplit")} : <span className="text-ink">{focus.spread.label}</span>{t("topics.spreadFrom", {
                    lowPole: focus.spread.low_pole,
                    low: `${focus.spread.low > 0 ? "+" : ""}${focus.spread.low.toFixed(2)}`,
                    highPole: focus.spread.high_pole,
                    high: `${focus.spread.high > 0 ? "+" : ""}${focus.spread.high.toFixed(2)}`,
                  })}
                </p>
              )}
              {focus.lead?.outlet && (
                <p className="mb-4 text-[12.5px] text-muted">
                  {t("topics.firstInCluster")} : <Link to={`/outlets/${focus.lead.outlet_id}`} className="text-ink hover:text-accent-strong">{focus.lead.outlet}</Link>
                  {focus.lead.date ? ` · ${new Date(focus.lead.date).toLocaleString(intl, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}` : ""}
                </p>
              )}

              {focus.opinion?.dominant_tone && (
                <div className="mb-4 rounded-sm border border-hair-soft bg-surface px-3 py-2.5">
                  <div className="label mb-1.5">{t("topics.opinion")}</div>
                  <p className="text-[12.5px] text-muted">
                    {t("topics.toneDominant")} : <span className="text-ink">{toneWordLabel(focus.opinion.dominant_tone, t)}</span>
                    {focus.opinion.dominant_tone_share ? ` (${Math.round(focus.opinion.dominant_tone_share * 100)} %)` : ""}
                    {focus.opinion.angles?.length ? ` · ${t("topics.angles")} : ${focus.opinion.angles.map((a: any) => angleLabel(a.label, t)).join(", ")}` : ""}
                    {typeof focus.opinion.valence === "number" ? ` · ${t("topics.valence")} ${focus.opinion.valence > 0 ? "+" : ""}${focus.opinion.valence.toFixed(2)}` : ""}
                  </p>
                  {focus.opinion.tones?.length > 1 && (
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {focus.opinion.tones.map((row: any) => (
                        <Badge key={row.label}>{toneWordLabel(row.label, t)} · {row.n}</Badge>
                      ))}
                    </div>
                  )}
                  {isFamilyFocus && focus.opinion.by_outlet?.some((o: any) => o.tone) && (
                    <ul className="mt-2 divide-y divide-hair-soft text-[12px]">
                      {focus.opinion.by_outlet.filter((o: any) => o.tone).slice(0, 8).map((o: any) => (
                        <li key={o.id} className="flex items-center justify-between gap-2 py-1">
                          <Link to={`/outlets/${o.id}`} className="truncate text-ink hover:text-accent-strong">{o.name}</Link>
                          <span className="shrink-0 text-faint">{toneWordLabel(o.tone, t)} · {o.n}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}

              {isFamilyFocus && (focus.story_summaries || []).length > 1 && (
                <div className="mb-4">
                  <div className="label mb-1.5">{t("topics.storiesInFamily")}</div>
                  <ul className="divide-y divide-hair-soft text-[12.5px]">
                    {focus.story_summaries.map((s: any) => (
                      <li key={s.id}>
                        <button type="button" onClick={() => selectStory(s.id)} className="flex w-full items-start justify-between gap-3 py-1.5 text-left hover:text-accent-strong">
                          <span className="min-w-0 flex-1">
                            <span className="font-medium text-ink">{s.label}</span>
                            {s.brief ? <span className="mt-0.5 block text-[11.5px] leading-snug text-muted line-clamp-3">{s.brief}</span> : null}
                          </span>
                          <span className="num shrink-0 text-[11px] text-faint">{t("topics.artsMed", { a: s.articles, o: s.outlets })}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              <div className="grid gap-5 md:grid-cols-2">
                <div>
                  <div className="label mb-1.5">{t("common.outlets")}</div>
                  <ul className="divide-y divide-hair-soft text-[12.5px]">
                    {(focus.outlets_detail || []).map((o: any) => (
                      <li key={o.id} className="flex items-center justify-between py-1">
                        <Link to={`/outlets/${o.id}`} className="truncate text-ink hover:text-accent-strong">{o.country ? flag(o.country) + " " : ""}{o.name}</Link>
                        <span className="num text-faint">{o.n}</span>
                      </li>
                    ))}
                  </ul>
                </div>
                <div>
                  <div className="label mb-1.5">{t("common.journalists")}</div>
                  {(focus.journalists_detail || []).length ? (
                    <ul className="divide-y divide-hair-soft text-[12.5px]">
                      {focus.journalists_detail.map((j: any) => (
                        <li key={j.id} className="flex items-center justify-between gap-2 py-1">
                          <Link to={`/journalists/${j.id}`} className="truncate text-ink hover:text-accent-strong">{j.name}</Link>
                          <span className="truncate text-[11px] text-faint">{j.outlet} · {j.n}</span>
                        </li>
                      ))}
                    </ul>
                  ) : <p className="text-[12px] italic text-faint">{t("common.noByline")}</p>}
                </div>
              </div>

              {focus.entities?.length > 0 && (
                <div className="mt-4">
                  <div className="label mb-1.5">{t("common.entities")}</div>
                  <div className="flex flex-wrap gap-1.5">
                    {focus.entities.map((e: any) => <Badge key={e.name} tone={e.kind === "person" ? "ink" : "accent"}>{e.name} · {e.n}</Badge>)}
                  </div>
                </div>
              )}
            </Card>
          )}

          {isolatedArticles.length > 0 && (
            <Card
              className="mt-5"
              title={`${t("topics.isolated")} (${isolatedArticles.length})`}
              aside={t("topics.dustHint")}
            >
              <ul className="grid gap-x-6 gap-y-2 divide-y divide-hair-soft md:grid-cols-2">
                {isolatedArticles.slice(0, 40).map((a: any) => (
                  <li key={a.id} className="py-1.5 text-[12.5px]">
                    {a.topic && <div className="text-[11px] font-semibold text-accent-strong">{a.topic}</div>}
                    <Link to={`/articles/${a.id}`} className="text-ink hover:text-accent-strong hover:underline">
                      {a.title || t("common.untitled")}
                    </Link>
                    <div className="text-[11.5px] text-faint">
                      {a.country ? `${flag(a.country)} ` : ""}{a.outlet}{a.journalist ? ` · ${a.journalist}` : ""}{a.date ? ` · ${a.date}` : ""}
                    </div>
                  </li>
                ))}
              </ul>
            </Card>
          )}

          <div className="mt-4">
            <Callout label={t("common.howToRead")}>
              {t("topics.how")}
            </Callout>
          </div>
        </>
      )}
    </div>
  );
}
