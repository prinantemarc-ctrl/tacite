import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Search, RefreshCw, Rss, Globe, Pause, Play, ExternalLink } from "lucide-react";
import { suggestOutlets, suggestOutletsCached, resolveOutlet, reverifyOutlet, addOutletsBulk, updateOutlet, listKits, kitForCountry, assignCountryKit, createKit } from "../api";
import { Modal, Button, Select, Input, Textarea, Badge, Callout, Term, Meter, GapBar } from "../components";
import { flag, countryName, loadIsoCountries, maxUsableGap } from "../geo";
import { useI18n } from "../i18n/I18nProvider";
import { audienceLabel, orientationLabel, outletTypeLabel, suggestReasonLabel } from "../i18n/mapped";

type Suggestion = {
  name: string; website_url: string; language: string; type?: string; declared_orientation?: string;
  audience?: string; feeds: string[]; status: "verified" | "site_only" | "robot_blocked" | "already" | "unreachable" | "not_found";
  reason?: string | null;
};

const emptyAxis = () => ({ id: "", label_fr: "", label_en: "", neg_fr: "", pos_fr: "" });

const STATUS: Record<string, { tone: "accent" | "default" | "ink" | "faint" | "alert"; selectable: boolean; key: string }> = {
  verified: { tone: "accent", selectable: true, key: "verified" },
  site_only: { tone: "default", selectable: true, key: "indirect" },
  robot_blocked: { tone: "ink", selectable: true, key: "robot_blocked" },
  already: { tone: "faint", selectable: false, key: "already" },
  unreachable: { tone: "alert", selectable: false, key: "unreachable" },
};

export default function CountryManager({ outlets, onClose, onChanged, initialCountry }: {
  outlets: any[]; onClose: () => void; onChanged: () => void; initialCountry?: string;
}) {
  const { t, intl, locale } = useI18n();
  const [countries, setCountries] = useState<{ code: string; name: string }[]>([]);
  useEffect(() => { loadIsoCountries().then(setCountries); }, [locale]);
  const followedCount = useMemo(() => {
    const m: Record<string, number> = {};
    for (const o of outlets) m[o.country] = (m[o.country] || 0) + 1;
    return m;
  }, [outlets]);

  const [code, setCode] = useState(initialCountry || "");
  const [sugs, setSugs] = useState<Suggestion[] | null>(null);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [freeName, setFreeName] = useState("");
  const [resolving, setResolving] = useState(false);
  const [adding, setAdding] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [kits, setKits] = useState<any[]>([]);
  const [kitInfo, setKitInfo] = useState<any>(null);
  const [kitPick, setKitPick] = useState("");
  const [kitBusy, setKitBusy] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [custom, setCustom] = useState({ label_fr: "", label_en: "", prompt_en: "", axes: [emptyAxis(), emptyAxis(), emptyAxis()] });

  useEffect(() => { listKits().then((r) => setKits(r.kits || [])).catch(() => undefined); }, [locale]);

  const loadKit = async (c: string) => {
    try {
      const r = await kitForCountry(c);
      setKitInfo(r);
      setKitPick(r.kit_id || r.builtin_default || "");
      setShowCreate(false);
    } catch { setKitInfo(null); }
  };

  const existing = useMemo(
    () => outlets.filter((o) => o.country === code).slice().sort((a, b) => (b.influence_score || 0) - (a.influence_score || 0)),
    [outlets, code],
  );
  const maxGapOf = (o: any): number | null => maxUsableGap(o);

  const loadSuggestions = async (c: string, force = false) => {
    setLoading(true); setError(null); setSugs(null); setChecked(new Set()); setResult(null);
    try {
      const r = await suggestOutlets(c, force);
      setSugs(r.suggestions);
      setChecked(new Set((r.suggestions || []).filter((s: Suggestion) => s.status === "verified").map((s: Suggestion) => s.name)));
    } catch (e: any) { setError(e.message); }
    finally { setLoading(false); }
  };
  /** Au choix du pays : on affiche le cache s'il existe (gratuit), sinon rien ne se lance — bouton manuel. */
  const loadCachedOnly = async (c: string) => {
    setError(null); setSugs(null); setChecked(new Set()); setResult(null);
    try {
      const r = await suggestOutletsCached(c);
      if (r.suggestions) {
        setSugs(r.suggestions);
        setChecked(new Set(r.suggestions.filter((s: Suggestion) => s.status === "verified").map((s: Suggestion) => s.name)));
      }
    } catch { /* pas de cache : on attend le clic */ }
  };
  const [retrying, setRetrying] = useState<string | null>(null);
  const retry = async (s: Suggestion) => {
    setRetrying(s.name);
    try {
      const r = await reverifyOutlet(code, s);
      setSugs((list) => (list || []).map((x) => (x.name.toLowerCase() === r.name.toLowerCase() ? r : x)));
      if (r.status === "verified") setChecked((c) => new Set(c).add(r.name));
    } catch (e: any) { setError(e.message); }
    finally { setRetrying(null); }
  };
  const pick = (c: string) => {
    setCode(c);
    setKitInfo(null);
    setShowCreate(false);
    if (c) { loadCachedOnly(c); loadKit(c); }
  };

  useEffect(() => {
    if (code) { loadCachedOnly(code); loadKit(code); }
    // initial country only
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const assignKit = async (id: string) => {
    if (!code || !id) return;
    setKitBusy(true); setError(null);
    try {
      await assignCountryKit(code, id);
      await loadKit(code);
    } catch (e: any) { setError(e.message); }
    finally { setKitBusy(false); }
  };

  const saveCustom = async () => {
    if (!code) return;
    const axes = custom.axes.filter((a) => (a.label_en || a.label_fr).trim());
    if (!axes.length || !(custom.label_fr || custom.label_en).trim()) return;
    setKitBusy(true); setError(null);
    try {
      const kit = await createKit({
        label_fr: custom.label_fr || custom.label_en,
        label_en: custom.label_en || custom.label_fr,
        prompt_en: custom.prompt_en,
        countries: [code],
        axes: axes.map((a) => ({
          id: a.id || undefined,
          label_fr: a.label_fr || a.label_en,
          label_en: a.label_en || a.label_fr,
          neg_fr: a.neg_fr || "−",
          pos_fr: a.pos_fr || "+",
          neg_en: a.neg_fr || "−",
          pos_en: a.pos_fr || "+",
        })),
      });
      await assignCountryKit(code, kit.id);
      const listed = await listKits();
      setKits(listed.kits || []);
      await loadKit(code);
      setShowCreate(false);
    } catch (e: any) { setError(e.message); }
    finally { setKitBusy(false); }
  };

  const kitReady = !!kitInfo?.assigned;

  const toggle = (name: string) => setChecked((s) => { const n = new Set(s); n.has(name) ? n.delete(name) : n.add(name); return n; });

  const addFree = async () => {
    if (!freeName.trim() || !code) return;
    setResolving(true); setError(null);
    try {
      const r = await resolveOutlet(code, freeName.trim());
      if (r.status === "not_found") { setError(t("country.notFound", { name: freeName, reason: suggestReasonLabel(r.reason, t) || t("country.noOfficial") })); }
      else {
        setSugs((s) => [r, ...(s || []).filter((x) => x.name.toLowerCase() !== r.name.toLowerCase())]);
        if (STATUS[r.status]?.selectable) setChecked((s) => new Set(s).add(r.name));
        setFreeName("");
      }
    } catch (e: any) { setError(e.message); }
    finally { setResolving(false); }
  };

  const submit = async () => {
    const items = (sugs || []).filter((s) => checked.has(s.name) && STATUS[s.status]?.selectable);
    if (!items.length) return;
    setAdding(true); setError(null);
    try {
      const r = await addOutletsBulk(code, items);
      const skipped = r.skipped.length ? t("country.skipped", { n: r.skipped.length }) : "";
      const errors = r.errors.length ? t("country.llmFail", { n: r.errors.length }) : "";
      setResult(t("country.addResult", {
        n: r.created.length,
        s: r.created.length > 1 ? "s" : "",
        feeds: r.created.reduce((a: number, c: any) => a + c.feeds, 0),
        skipped,
        errors,
      }));
      onChanged();
      const added = new Set((r.created || []).map((c: any) => String(c.name || "").toLowerCase()));
      setSugs((list) => (list || []).map((s) => (added.has(s.name.toLowerCase()) ? { ...s, status: "already" as const } : s)));
      setChecked(new Set());
    } catch (e: any) { setError(e.message); }
    finally { setAdding(false); }
  };

  const toggleCollect = async (o: any) => {
    await updateOutlet(o.id, { collect_enabled: o.collect_enabled === 0 ? 1 : 0 });
    onChanged();
  };

  const nChecked = (sugs || []).filter((s) => checked.has(s.name) && STATUS[s.status]?.selectable).length;

  return (
    <Modal
      title={t("country.title")}
      onClose={onClose}
      width="max-w-4xl"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>{t("common.close")}</Button>
          <Button variant="primary" onClick={submit} disabled={!nChecked || adding || !kitReady}>{adding ? t("country.creating") : t("country.addSelected", { n: nChecked })}</Button>
        </>
      }
    >
      <div className="flex items-center gap-2">
        <Select value={code} onChange={(e) => pick(e.target.value)} className="min-w-[260px]">
          <option value="">{t("country.chooseCountry")}</option>
          {countries.map((c) => (
            <option key={c.code} value={c.code}>{flag(c.code)} {c.name}{followedCount[c.code] ? t("country.followedN", { n: followedCount[c.code], s: followedCount[c.code] > 1 ? "s" : "" }) : ""}</option>
          ))}
        </Select>
        {code && kitReady && !loading && sugs && <Button size="sm" variant="ghost" onClick={() => loadSuggestions(code, true)} title={t("country.refreshTitle")}><RefreshCw size={12} /> {t("country.refresh")}</Button>}
      </div>

      {result && <Callout label={t("country.add")}>{result}</Callout>}
      {error && <Callout label={t("common.error")} warn>{error}</Callout>}

      {code && (
        <div className="rounded-sm border border-hair bg-surface px-3 py-2.5">
          <div className="mb-1.5 flex items-baseline justify-between gap-2">
            <div className="label"><Term k="axes">{t("country.kitTitle")}</Term></div>
            {kitInfo?.kit?.label && kitReady && <span className="text-[11px] text-muted">{t("country.kitCurrent")} · {kitInfo.kit.label}</span>}
          </div>
          <p className="mb-2 text-[11.5px] leading-relaxed text-muted">{t("country.kitHelp")}</p>
          {!kitReady && <p className="mb-2 text-[12px] text-confidential">{t("country.kitRequired")}</p>}
          {!showCreate && (
            <div className="flex flex-wrap items-center gap-2">
              <Select value={kitPick} onChange={(e) => setKitPick(e.target.value)} className="min-w-[240px]">
                <option value="">{t("common.dash")}</option>
                {kits.map((k) => (
                  <option key={k.id} value={k.id}>{k.label || k.id}</option>
                ))}
              </Select>
              <Button size="sm" variant="primary" onClick={() => assignKit(kitPick)} disabled={!kitPick || kitBusy}>{kitBusy ? t("country.creating") : t("country.kitAssign")}</Button>
              <Button size="sm" variant="ghost" onClick={() => setShowCreate(true)}>{t("country.kitCreate")}</Button>
            </div>
          )}
          {showCreate && (
            <div className="space-y-2">
              <div className="grid gap-2 sm:grid-cols-2">
                <Input value={custom.label_fr} onChange={(e) => setCustom({ ...custom, label_fr: e.target.value })} placeholder={t("country.kitNameFr")} />
                <Input value={custom.label_en} onChange={(e) => setCustom({ ...custom, label_en: e.target.value })} placeholder={t("country.kitNameEn")} />
              </div>
              <Textarea value={custom.prompt_en} onChange={(e) => setCustom({ ...custom, prompt_en: e.target.value })} placeholder={t("country.kitPrompt")} rows={2} />
              <div className="label">{t("country.kitAxes")}</div>
              {custom.axes.map((a, i) => (
                <div key={i} className="grid grid-cols-2 gap-1.5 sm:grid-cols-5">
                  <Input value={a.label_fr} onChange={(e) => { const axes = [...custom.axes]; axes[i] = { ...a, label_fr: e.target.value }; setCustom({ ...custom, axes }); }} placeholder={t("country.kitAxisLabelFr")} />
                  <Input value={a.label_en} onChange={(e) => { const axes = [...custom.axes]; axes[i] = { ...a, label_en: e.target.value }; setCustom({ ...custom, axes }); }} placeholder={t("country.kitAxisLabelEn")} />
                  <Input value={a.neg_fr} onChange={(e) => { const axes = [...custom.axes]; axes[i] = { ...a, neg_fr: e.target.value }; setCustom({ ...custom, axes }); }} placeholder={t("country.kitPoleNeg")} />
                  <Input value={a.pos_fr} onChange={(e) => { const axes = [...custom.axes]; axes[i] = { ...a, pos_fr: e.target.value }; setCustom({ ...custom, axes }); }} placeholder={t("country.kitPolePos")} />
                  <Input value={a.id} onChange={(e) => { const axes = [...custom.axes]; axes[i] = { ...a, id: e.target.value }; setCustom({ ...custom, axes }); }} placeholder={t("country.kitAxisId")} />
                </div>
              ))}
              <div className="flex flex-wrap gap-2">
                <Button size="sm" variant="ghost" onClick={() => setCustom({ ...custom, axes: [...custom.axes, emptyAxis()] })}>{t("country.kitAddAxis")}</Button>
                <Button size="sm" variant="primary" onClick={saveCustom} disabled={kitBusy}>{kitBusy ? t("country.kitCreating") : t("country.kitSave")}</Button>
                <Button size="sm" variant="ghost" onClick={() => setShowCreate(false)}>{t("country.kitCancel")}</Button>
              </div>
            </div>
          )}
          {kitReady && kitInfo?.kit?.axes?.length > 0 && !showCreate && (
            <div className="mt-2 flex flex-wrap gap-1">
              {kitInfo.kit.axes.map((a: any) => (
                <Badge key={a.id} tone="faint">{a.label || t(`axis.${a.id}`)}</Badge>
              ))}
            </div>
          )}
        </div>
      )}

      {code && (
        <div>
          <div className="mb-1.5 flex items-baseline justify-between">
            <div className="label">{t("country.alreadyFollowed", { n: existing.length })}</div>
            <span className="text-[11px] text-faint">
              <Term k="influence">{t("country.influenceWord")}</Term> · {t("common.articles")} · <Term k="gap">{t("country.colGap")}</Term> · <Term k="collect_modes">{t("country.collectWord")}</Term>
            </span>
          </div>
          {existing.length === 0 ? (
            <p className="rounded-sm border border-hair bg-surface px-4 py-3 text-[12.5px] text-muted">{t("country.noneFollowed", { country: countryName(code) })}</p>
          ) : (
            <div className="max-h-56 overflow-y-auto rounded-sm border border-hair">
              <table className="w-full border-collapse text-[12px] [&_td]:border-b [&_td]:border-hair-soft [&_td]:px-2.5 [&_td]:py-1.5 [&_td]:align-middle [&_tbody_tr:last-child_td]:border-0">
                <thead>
                  <tr>
                    {[t("country.colOutlet"), t("country.colArticles"), t("country.colThisWeek"), <Term k="influence">{t("outlets.influence")}</Term>, <Term k="gap">{t("country.colGap")}</Term>, t("country.colCollect"), ""].map((h, i) => (
                      <th key={i} className="label sticky top-0 whitespace-nowrap border-b border-hair bg-tint px-2.5 py-1 text-left font-bold">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {existing.map((o) => {
                    const gap = maxGapOf(o);
                    const paused = o.collect_enabled === 0;
                    return (
                      <tr key={o.id}>
                        <td className="min-w-[140px] max-w-[220px]">
                          <Link to={`/outlets/${o.id}`} className={`block truncate font-medium hover:text-accent-strong ${paused ? "text-faint line-through" : "text-ink"}`}>{o.name}</Link>
                        </td>
                        <td className="num whitespace-nowrap text-muted" title={t("country.artsTotalTip")}>
                          <Link to={`/articles?outlet_id=${o.id}`} className="hover:text-accent-strong">{(o.articles_total ?? 0).toLocaleString(intl)}</Link>
                        </td>
                        <td className="num whitespace-nowrap text-muted" title={t("country.weekArtsTip")}>{o.latest_profile?.article_count ?? t("common.dash")}</td>
                        <td className="min-w-[92px]"><Meter value={o.influence_score || 0} width="w-12" label={(o.influence_score || 0).toFixed(0)} /></td>
                        <td className="min-w-[120px]">{gap !== null ? <GapBar value={gap} /> : <span className="text-faint">{t("common.dash")}</span>}</td>
                        <td className="whitespace-nowrap">
                          <span className="inline-flex flex-wrap items-center gap-1">
                            <Badge tone={o.feeds_count ? "accent" : "default"}>{o.feeds_count ? t("country.nFeeds", { n: o.feeds_count, s: o.feeds_count > 1 ? "s" : "" }) : t("country.indirectShort")}</Badge>
                            {paused && <Badge tone="faint">{t("country.paused")}</Badge>}
                          </span>
                        </td>
                        <td className="w-8 text-right">
                          <button onClick={() => toggleCollect(o)} className="text-faint hover:text-ink" title={paused ? t("country.resumeCollect") : t("country.pauseCollect")}>
                            {paused ? <Play size={12} /> : <Pause size={12} />}
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {code && (
        <div>
          <div className="mb-1.5 flex items-baseline justify-between">
            <div className="label">{t("country.suggestions")}</div>
            {sugs && <span className="text-[11px] text-faint"><Term k="collect_modes">{t("country.howStatuses")}</Term></span>}
          </div>
          {sugs && (
            <div className="mb-2 rounded-sm border border-hair bg-surface px-3 py-1.5 text-[11.5px] leading-relaxed text-muted">
              {t("country.legendLead")} <b className="text-accent-strong">{t("country.verified")}</b> {t("country.legendRss")} <b className="text-ink">{t("country.indirect")}</b> {t("country.legendIndirect")} <b className="text-ink">{t("country.robot_blocked")}</b> {t("country.legendBlocked")} {t("country.legendDeclared")} <Term k="declared">{t("country.declaredLine")}</Term> {t("country.legendDeclaredEnd")}
            </div>
          )}
          {loading ? (
            <div className="flex items-center gap-3 rounded-sm border border-hair bg-surface px-4 py-6 text-[12.5px] text-muted">
              <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-accent" />
              {t("country.searching", { country: countryName(code) })}
            </div>
          ) : sugs === null ? (
            <div className="rounded-sm border border-hair bg-surface px-4 py-5 text-[12.5px] text-muted">
              <p className="mb-3">{t("country.noSearch", { country: countryName(code) })}</p>
              <Button variant="primary" size="sm" onClick={() => loadSuggestions(code)} disabled={!kitReady}><Search size={12} /> {t("country.searchBtn", { country: countryName(code) })}</Button>
            </div>
          ) : (
            <ul className="max-h-[340px] divide-y divide-hair-soft overflow-y-auto rounded-sm border border-hair px-3">
              {sugs.map((s) => {
                const st = STATUS[s.status];
                const label = st ? t(`country.${st.key}`) : s.status;
                const help = st ? t(`country.${st.key}Help`) : "";
                const selectable = st?.selectable ?? false;
                const tone = st?.tone || "default";
                return (
                  <li key={s.name} className={`flex items-start gap-3 py-2 ${selectable ? "" : "opacity-60"}`}>
                    <input type="checkbox" className="mt-1 accent-accent" disabled={!selectable} checked={checked.has(s.name) && selectable} onChange={() => toggle(s.name)} />
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2 text-[13px]">
                        <span className="font-medium text-ink">{s.name}</span>
                        <span title={help}><Badge tone={tone}>{label}</Badge></span>
                        {s.type && <span className="text-[11px] text-faint">{outletTypeLabel(s.type, t)}{s.audience ? ` · ${audienceLabel(s.audience, t)}` : ""}</span>}
                      </div>
                      <div className="mt-0.5 flex flex-wrap items-center gap-x-3 text-[11.5px] text-muted">
                        {s.declared_orientation && <span className="italic">{orientationLabel(s.declared_orientation, t)}</span>}
                        {s.website_url && <a href={s.website_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-faint hover:text-accent-strong"><Globe size={10} />{s.website_url.replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, "")} <ExternalLink size={9} /></a>}
                        {s.feeds?.length > 0 && <span className="inline-flex items-center gap-1 text-faint"><Rss size={10} />{t("country.feedsTested", { n: s.feeds.length, s: s.feeds.length > 1 ? "s" : "" })}</span>}
                      </div>
                      {s.reason && (
                        <div className={`mt-0.5 text-[11.5px] ${s.status === "unreachable" ? "text-confidential" : "text-faint"}`}>
                          {suggestReasonLabel(s.reason, t) || s.reason}
                          {s.status === "unreachable" && (
                            <button onClick={() => retry(s)} disabled={retrying === s.name} className="ml-2 inline-flex items-center gap-1 text-muted underline decoration-hair underline-offset-2 hover:text-ink">
                              <RefreshCw size={10} className={retrying === s.name ? "animate-spin" : ""} /> {retrying === s.name ? t("country.retrying") : t("common.retry")}
                            </button>
                          )}
                        </div>
                      )}
                    </div>
                  </li>
                );
              })}
            </ul>
          )}

          {sugs && (
            <div className="mt-2 flex items-center gap-2">
              <Input value={freeName} onChange={(e) => setFreeName(e.target.value)} onKeyDown={(e) => e.key === "Enter" && addFree()}
                placeholder={t("country.freePh")} className="flex-1" />
              <Button size="sm" onClick={addFree} disabled={!freeName.trim() || resolving}>{resolving ? t("country.resolving") : <><Search size={12} /> {t("country.lookup")}</>}</Button>
            </div>
          )}
        </div>
      )}

      {!code && <p className="py-4 text-center text-[12.5px] italic text-faint">{t("country.pickCountry")}</p>}
    </Modal>
  );
}
