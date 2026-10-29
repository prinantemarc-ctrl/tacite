import { useEffect, useState } from "react";
import { getSettings, updateSettings, triggerIngestAll, triggerAnalysis, triggerJournalistProfiles, triggerOutletProfiles, getCostStats, countPolluted, requalifyPolluted, contactsStatus, runContactsDiscovery, runBylinesBackfill, getPipelineHealth, ingestOutlet, getToken, setToken } from "../api";
import { Card, Stat, Button, Field, Input, Select, Loading, PageHeader, Callout, Meter, Segmented } from "../components";
import { useTheme } from "../ThemeProvider";
import { useI18n } from "../i18n/I18nProvider";
import type { ThemePref } from "../theme";
import type { Locale } from "../i18n/locale";

export default function SettingsPage() {
  const { t, locale, setLocale, intl } = useI18n();
  const [settings, setSettings] = useState<Record<string, any>>({});
  const [cost, setCost] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<{ text: string; warn?: boolean } | null>(null);
  const [polluted, setPolluted] = useState<number | null>(null);
  const [recoverable, setRecoverable] = useState<number | null>(null);
  const [job, setJob] = useState<any>(null);

  useEffect(() => {
    Promise.all([getSettings(), getCostStats()]).then(([s, c]) => { setSettings(s); setCost(c); }).finally(() => setLoading(false));
  }, []);
  const [cstat, setCstat] = useState<any>(null);
  const [health, setHealth] = useState<any>(null);
  const [token, setTok] = useState(getToken());
  const { pref, setPref } = useTheme();
  useEffect(() => { getPipelineHealth().then(setHealth).catch(() => undefined); }, []);
  useEffect(() => {
    let alive = true;
    const tick = () => contactsStatus().then((s) => alive && setCstat(s)).catch(() => undefined);
    tick();
    const id = setInterval(tick, cstat?.job?.running ? 4000 : 30000);
    return () => { alive = false; clearInterval(id); };
  }, [cstat?.job?.running]);
  useEffect(() => {
    let alive = true;
    const tick = () => countPolluted().then((r) => { if (!alive) return; setJob(r.job); if (r.count !== null) { setPolluted(r.count); setRecoverable(r.recoverable); } }).catch(() => alive && setPolluted(0));
    tick();
    const id = setInterval(tick, job?.running ? 3000 : 30000);
    return () => { alive = false; clearInterval(id); };
  }, [job?.running]);

  const flash = (text: string, warn = false, ms = 4000) => { setMsg({ text, warn }); setTimeout(() => setMsg(null), ms); };
  const handleSave = async () => {
    setSaving(true);
    try { await updateSettings(settings); flash(t("settings.saved")); } catch (e: any) { flash(t("settings.err", { msg: e.message }), true); } finally { setSaving(false); }
  };
  const runAction = async (fn: () => Promise<any>, label: string, done?: (r: any) => string) => {
    setMsg({ text: t("settings.running", { label }) });
    try { const r = await fn(); flash(done ? done(r) : t("settings.done", { label }), false, done ? 15000 : 4000); } catch (e: any) { flash(t("settings.err", { msg: e.message }), true, 8000); }
  };
  const set = (key: string, value: any) => setSettings((p) => ({ ...p, [key]: value }));
  const setWeight = (key: string, value: number) => setSettings((p) => ({ ...p, influence_weights: { ...(p.influence_weights || {}), [key]: value } }));

  if (loading) return <Loading />;
  const weights: Record<string, number> = settings.influence_weights || {};
  const weightSum = Object.values(weights).reduce((a, b) => a + (+b || 0), 0);

  return (
    <div>
      <PageHeader kicker={t("settings.kicker")} title={t("settings.title")} actions={<Button variant="primary" onClick={handleSave} disabled={saving}>{saving ? t("common.saving") : t("common.save")}</Button>} />

      {msg && <div className="mb-5"><Callout label={msg.warn ? t("common.alert") : t("common.state")} warn={msg.warn}>{msg.text}</Callout></div>}

      <Card title={t("settings.appearance")} aside={t("settings.appearanceAside")} className="mb-5">
        <div>
          <div className="label mb-1">{t("settings.theme")}</div>
          <Segmented<ThemePref>
            value={pref}
            onChange={setPref}
            options={[
              { value: "light", label: t("theme.light") },
              { value: "dark", label: t("theme.dark") },
              { value: "system", label: t("theme.system") },
            ]}
          />
          <p className="mt-1 text-[11px] text-faint">{t("settings.themeHint")}</p>
        </div>
        <div className="mt-4">
          <div className="label mb-1">{t("settings.language")}</div>
          <Segmented<Locale>
            value={locale}
            onChange={setLocale}
            options={[
              { value: "fr", label: locale === "fr" ? t("lang.name") : t("lang.other") },
              { value: "en", label: locale === "en" ? t("lang.name") : t("lang.other") },
            ]}
          />
          <p className="mt-1 text-[11px] text-faint">{t("settings.languageHint")}</p>
        </div>
      </Card>

      {cost && (
        <div className="mb-6 grid grid-cols-2 gap-6 md:grid-cols-4">
          <Stat label={t("settings.costMonth")} value={`${cost.total_usd} $`} tone="accent" />
          <Stat label={t("settings.extraction")} value={`${(cost.by_purpose?.extraction || 0).toFixed(2)} $`} />
          <Stat label={t("settings.profiles")} value={`${(cost.by_purpose?.profile || 0).toFixed(2)} $`} />
          <Stat label={t("settings.enrichment")} value={`${(cost.by_purpose?.enrichment || 0).toFixed(2)} $`} />
        </div>
      )}

      <Card title={t("settings.manualActions")} aside={t("settings.manualActionsAside")}>
        <div className="flex flex-wrap gap-2">
          <Button onClick={() => runAction(triggerIngestAll, t("settings.ingest"))}>{t("settings.ingestFeeds")}</Button>
          <Button onClick={() => runAction(triggerAnalysis, t("settings.analysis"))}>{t("settings.analyzePending")}</Button>
          <Button onClick={() => runAction(triggerJournalistProfiles, t("settings.journalistProfiles"))}>{t("settings.journalistProfiles")}</Button>
          <Button onClick={() => runAction(triggerOutletProfiles, t("settings.outletProfiles"))}>{t("settings.outletProfilesInfluence")}</Button>
        </div>
        {cstat && (
          <div className="mt-3 flex flex-wrap items-center gap-3 border-t border-hair-soft pt-3 text-[12.5px] text-muted">
            <span>
              {t("settings.contacts")} <span className="num font-medium text-ink">{cstat.directly_reachable}</span> {t("settings.reachableOn")} {cstat.journalists} · <span className="num">{cstat.scanned}</span> {t("settings.scanned")}
              {cstat.by_kind && Object.keys(cstat.by_kind).length > 0 && <span className="text-faint"> · {Object.entries(cstat.by_kind as Record<string, number>).sort(([, a], [, b]) => b - a).map(([k, n]) => `${n} ${k}`).join(", ")}</span>}
              {cstat.job?.running && <span className="text-accent-strong"> · {t("settings.discoveryRunning", { done: cstat.job.done, total: cstat.job.total })}</span>}
            </span>
            <Button size="sm" disabled={cstat.job?.running} onClick={() => runAction(() => runContactsDiscovery(500), t("settings.discovery"), () => t("settings.discoveryStarted"))}>{t("settings.detectContacts")}</Button>
            <Button size="sm" onClick={() => runAction(runBylinesBackfill, t("settings.bylines"), (r) => t("settings.bylinesDone", { scanned: r.scanned, attached: r.attached, created: r.created }))}>{t("settings.attachBylines")}</Button>
          </div>
        )}
        <div className="mt-3 border-t border-hair-soft pt-3 text-[12.5px] text-muted">
          {job?.running ? (
            <div className="flex items-center gap-3">
              <span>{t("settings.requalifyRunning")} · <span className="num font-medium text-ink">{job.done} / {job.total}</span></span>
              <Meter value={job.done} max={Math.max(1, job.total)} width="w-48" />
              {job.stats && <span className="num text-faint">{t("settings.requalifyStats", { recovered: job.stats.recovered, duplicate: job.stats.duplicate, boilerplate: job.stats.boilerplate })}{job.stats.deferred ? t("settings.requalifyDeferred", { n: job.stats.deferred }) : ""}</span>}
            </div>
          ) : (
            <div className="flex flex-wrap items-center gap-3">
              <span>
                <span className="num font-medium text-ink">{polluted === null ? "…" : polluted}</span> {t(polluted === 1 ? "settings.pollutedOne" : "settings.pollutedMany")}
                {recoverable ? <> · <span className="num font-medium text-ink">{recoverable}</span> {t(recoverable > 1 ? "settings.recoverableMany" : "settings.recoverableOne")}</> : null}.
                {job?.stats && job.finished_at && <span className="text-faint">{job.stats.deferred
                  ? t("settings.lastPassDeferred", { found: job.stats.found, recovered: job.stats.recovered, duplicate: job.stats.duplicate, boilerplate: job.stats.boilerplate, deferred: job.stats.deferred })
                  : t("settings.lastPass", { found: job.stats.found, recovered: job.stats.recovered, duplicate: job.stats.duplicate, boilerplate: job.stats.boilerplate })}</span>}
              </span>
              <Button size="sm" disabled={!polluted && !recoverable} onClick={() => runAction(
                async () => { const r = await requalifyPolluted(); setJob(r.job); return r; },
                t("settings.requalify"),
                () => t("settings.requalifyStarted"),
              )}>{t("settings.recoverOrClassify")}</Button>
            </div>
          )}
        </div>
      </Card>

      {health && (
        <Card title={t("settings.feedHealth")} aside={health.google_news_backoff_s > 0 ? t("settings.gnBackoffAside", { min: Math.round(health.google_news_backoff_s / 60) }) : t("settings.pendingQueue", { n: health.pending })} className="mt-5" help="sources_ingest">
          {health.google_news_backoff_s > 0 && <div className="mb-3"><Callout warn label="Google News">{t("settings.gnBackoffCallout", { min: Math.round(health.google_news_backoff_s / 60) })}</Callout></div>}
          <div className="max-h-80 overflow-auto">
            <table className="w-full text-left text-[12.5px]">
              <thead className="text-[10.5px] uppercase tracking-[0.1em] text-faint"><tr><th className="py-1">{t("settings.colOutlet")}</th><th>{t("settings.colLastArticle")}</th><th>{t("settings.colStatus")}</th><th></th></tr></thead>
              <tbody className="divide-y divide-hair-soft">
                {(health.outlets || []).filter((o: any) => o.stale_48h || o.last_status === "error" || o.collect_enabled === 0).map((o: any) => (
                  <tr key={o.id} className={o.last_status === "error" || o.stale_48h ? "text-confidential" : "text-muted"}>
                    <td className="py-1.5 font-medium text-ink">{o.name}</td>
                    <td className="num">{o.last_article ? new Date(o.last_article).toLocaleDateString(intl) : t("settings.noArticle")}</td>
                    <td>{o.last_status === "error" ? (o.last_error || t("settings.statusError")) : o.stale_48h ? t("settings.statusStale") : o.collect_enabled === 0 ? t("settings.statusSuspended") : o.last_status || t("common.dash")}</td>
                    <td className="text-right"><Button size="sm" onClick={() => runAction(() => ingestOutlet(o.id), t("settings.retryOutlet", { name: o.name }), (r) => t("settings.captured", { n: r.captured }))}>{t("settings.retryFeed")}</Button></td>
                  </tr>
                ))}
              </tbody>
            </table>
            {(health.outlets || []).filter((o: any) => o.stale_48h || o.last_status === "error").length === 0 && <p className="py-3 text-[12px] text-faint">{t("settings.noAlert")}</p>}
          </div>
        </Card>
      )}

      <div className="mt-5 grid grid-cols-1 gap-5 lg:grid-cols-2">
        <Card title={t("settings.collect")} help={["sources_ingest", "status_embedded"]}>
          <div className="grid grid-cols-2 gap-4">
            <Field label={t("settings.rssInterval")} hint={t("settings.minutes")}><Input type="number" value={settings.rss_interval_minutes ?? 15} onChange={(e) => set("rss_interval_minutes", +e.target.value)} /></Field>
            <Field label={t("settings.scrapeInterval")} hint={t("settings.minutes")}><Input type="number" value={settings.scrape_interval_minutes ?? 60} onChange={(e) => set("scrape_interval_minutes", +e.target.value)} /></Field>
            <Field label={t("settings.gnInterval")} hint={t("settings.minutes")}><Input type="number" value={settings.google_news_interval_minutes ?? 120} onChange={(e) => set("google_news_interval_minutes", +e.target.value)} /></Field>
            <Field label={t("settings.gdeltInterval")} hint={t("settings.minutes")}><Input type="number" value={settings.gdelt_interval_minutes ?? 360} onChange={(e) => set("gdelt_interval_minutes", +e.target.value)} /></Field>
            <Field label={t("settings.analysisBatch")} hint={t("settings.analysisBatchHint")}><Input type="number" value={settings.analysis_batch_size ?? 50} onChange={(e) => set("analysis_batch_size", +e.target.value)} /></Field>
            <Field label={t("settings.minLength")} hint={t("settings.minLengthHint")}><Input type="number" value={settings.min_text_length_for_llm ?? 400} onChange={(e) => set("min_text_length_for_llm", +e.target.value)} /></Field>
          </div>
        </Card>

        <Card title={t("settings.modelsCosts")} help={["llm_cost", "drift", "gap_exploitable"]}>
          <div className="grid grid-cols-2 gap-4">
            <Field label={t("settings.extractModel")}><Input value={settings.llm_model ?? ""} onChange={(e) => set("llm_model", e.target.value)} className="font-mono" /></Field>
            <Field label={t("settings.profileModel")}><Input value={settings.llm_profile_model ?? ""} onChange={(e) => set("llm_profile_model", e.target.value)} className="font-mono" /></Field>
            <Field label={t("settings.dailyCap")} hint={t("settings.dailyCapHint")}><Input type="number" step="0.5" value={settings.max_daily_cost_usd ?? 0} onChange={(e) => set("max_daily_cost_usd", +e.target.value)} /></Field>
            <Field label={t("settings.driftThreshold")} hint={t("settings.driftHint")}><Input type="number" step="0.05" value={settings.drift_threshold ?? 0.3} onChange={(e) => set("drift_threshold", +e.target.value)} /></Field>
            <Field label={t("settings.recCycle")} hint={t("settings.days")}><Input type="number" value={settings.recommendation_interval_days ?? 7} onChange={(e) => set("recommendation_interval_days", +e.target.value)} /></Field>
          </div>
        </Card>
      </div>

      <Card title={t("nav.assistant")} aside={t("settings.assistantAside")} className="mt-5">
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          <Field label={t("settings.assistantModel")} hint={t("settings.assistantModelHint")}><Input value={settings.llm_agent_model ?? "aleria"} onChange={(e) => set("llm_agent_model", e.target.value)} className="font-mono" /></Field>
          <Field label={t("settings.webSearch")} hint={t("settings.webSearchHint")}>
            <Select value={settings.agent_web_search === false ? "0" : "1"} onChange={(e) => set("agent_web_search", e.target.value === "1")}><option value="1">{t("settings.enabled")}</option><option value="0">{t("settings.disabled")}</option></Select>
          </Field>
          <Field label={t("settings.confirmWrites")} hint={t("settings.confirmWritesHint")}>
            <Select value={settings.agent_confirm_writes === false ? "0" : "1"} onChange={(e) => set("agent_confirm_writes", e.target.value === "1")}><option value="1">{t("settings.askBefore")}</option><option value="0">{t("settings.applyDirect")}</option></Select>
          </Field>
          <Field label={t("settings.assistantSpend")} hint={t("settings.thisMonth")}><div className="num pt-1.5 text-[18px] font-bold text-ink">{(cost?.by_purpose?.assistant || 0).toFixed(2)} $ <span className="text-[11px] font-normal text-faint">{t("settings.plusReports", { n: (cost?.by_purpose?.report || 0).toFixed(2) })}</span></div></Field>
          <Field label={t("settings.accessToken")} hint={t("settings.accessTokenHint")}>
            <Input value={token} onChange={(e) => { setTok(e.target.value); setToken(e.target.value); }} className="font-mono" placeholder="Bearer…" />
          </Field>
          <Field label="MCP · Cursor" hint={`${window.location.origin}/api/mcp`}>
            <div className="pt-1">
              <Button
                variant="primary"
                size="sm"
                onClick={async () => {
                  const w = window as any;
                  if (w.tacite?.connectCursor) {
                    const r = await w.tacite.connectCursor({ token: token || undefined, url: `${window.location.origin}/api/mcp`, showDialog: true });
                    if (r?.ok) setMsg({ text: "Tacite est connecté à Cursor (~/.cursor/mcp.json mis à jour)." });
                    return;
                  }
                  const cfgObj: any = { url: `${window.location.origin}/api/mcp` };
                  if (token) cfgObj.headers = { Authorization: `Bearer ${token}` };
                  const b64 = btoa(JSON.stringify(cfgObj));
                  window.location.href = `cursor://anysphere.cursor-deeplink/mcp/install?name=tacite&config=${encodeURIComponent(b64)}`;
                  setMsg({ text: "Ouverture de Cursor pour installer le serveur MCP Tacite…" });
                }}
              >
                Connecter à Cursor
              </Button>
            </div>
          </Field>
        </div>
      </Card>

      <Card title={t("settings.influenceWeights")} help={["influence", "comp_audience", "comp_citation", "comp_agenda", "comp_elite", "comp_network", "comp_longevity"]} aside={<span className={Math.abs(weightSum - 1) > 0.01 ? "text-confidential" : ""}>{t("settings.weightSum", { n: weightSum.toFixed(2) })}{Math.abs(weightSum - 1) > 0.01 ? t("settings.weightSumWarn") : ""}</span>} className="mt-5">
        <div className="grid grid-cols-3 gap-4 md:grid-cols-6">
          {Object.entries(weights).map(([key, val]) => (
            <Field key={key} label={t(`weight.${key}`)}><Input type="number" step="0.05" min={0} max={1} value={val} onChange={(e) => setWeight(key, +e.target.value)} /></Field>
          ))}
        </div>
      </Card>

      <div className="closing-rule mt-12" />
    </div>
  );
}
