import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Plus, Pencil, Trash2, Sparkles, Eraser, AtSign, X } from "lucide-react";
import { listJournalists, createJournalist, updateJournalist, deleteJournalist, listOutlets, cleanupJournalists, enrichJournalists, runContactsDiscovery, getSettings } from "../api";
import { kindIcon } from "../components/ContactsCard";
import {
  Card, Table, Badge, Button, IconButton, Modal, Field, Input, Select, Textarea, Loading, Empty, PageHeader, ScorePill, Callout, Term, Segmented,
} from "../components";
import { flag, countryName } from "../geo";
import {
  canonicalBeat, fold, journalistBeat, journalistHasContact, journalistMatchesBeat, journalistMatchesTopic,
  matchJournalist, splitBio, themeLabels,
} from "../journalistFilters";
import { useI18n } from "../i18n/I18nProvider";

const emptyJournalist = { name: "", outlet_id: 0, role: "Journaliste", twitter_handle: "", linkedin_url: "", bio: "", beat: "" };

const FILTER_BEATS = new Set([
  "Politique", "Économie", "International", "Justice", "Société", "Culture",
  "Sport", "Sciences", "Santé", "Environnement", "Tech", "Médias", "Généraliste",
]);

function beatFilterLabel(beat: string, t: (key: string) => string): string {
  return FILTER_BEATS.has(beat) ? t(`beat.${beat}`) : beat;
}

export { journalistBeat, splitBio, journalistHasContact, matchJournalist } from "../journalistFilters";

export default function JournalistsPage() {
  const { t, intl, locale } = useI18n();
  const [journalists, setJournalists] = useState<any[]>([]);
  const [outlets, setOutlets] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [editItem, setEditItem] = useState<any>(null);
  const [form, setForm] = useState(emptyJournalist);
  const [msg, setMsg] = useState("");
  const [pitch, setPitch] = useState(55);
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();

  const q = params.get("q") || "";
  const outletFilter = params.get("outlet_id") || "";
  const beatFilter = params.get("beat") || "";
  const topicFilter = params.get("topic") || "";
  const contactFilter = (params.get("contact") || "all") as "all" | "yes" | "no";
  const countryFilter = (params.get("country") || "").toUpperCase();
  const accessFilter = (params.get("access") || "all") as "all" | "pitch" | "low";

  const set = (k: string, v: string) => {
    const next = new URLSearchParams(params);
    if (k === "country") v = (v || "").toUpperCase();
    if (v && v !== "all") next.set(k, v); else next.delete(k);
    if (k === "country" && v) {
      const oid = next.get("outlet_id");
      const o = outlets.find((x: any) => String(x.id) === oid);
      if (o && o.country !== v) next.delete("outlet_id");
    }
    setParams(next, { replace: true });
  };

  const load = () => Promise.all([listJournalists(), listOutlets("brief")]).then(([j, o]) => { setJournalists(j); setOutlets(o); }).finally(() => setLoading(false));
  useEffect(() => { load(); }, []);
  useEffect(() => { getSettings().then((s) => { if (s?.accessibility_pitch_threshold != null) setPitch(Number(s.accessibility_pitch_threshold)); }).catch(() => {}); }, []);

  const outletMap = useMemo(() => Object.fromEntries(outlets.map((o: any) => [o.id, o])), [outlets]);
  const presentCountries = useMemo(
    () => [...new Set(outlets.map((o: any) => (o.country || "").toUpperCase()).filter(Boolean))].sort((a, b) => countryName(a).localeCompare(countryName(b), locale)),
    [outlets, locale],
  );
  const outletsForSelect = countryFilter ? outlets.filter((o: any) => (o.country || "").toUpperCase() === countryFilter) : outlets;

  const beats = useMemo(() => {
    const setB = new Set<string>();
    for (const j of journalists) {
      const c = canonicalBeat(journalistBeat(j));
      if (c) setB.add(c);
    }
    return [...setB].sort((a, b) => beatFilterLabel(a, t).localeCompare(beatFilterLabel(b, t), locale));
  }, [journalists, t, locale]);

  const topics = useMemo(() => {
    const byFold = new Map<string, { label: string; n: number }>();
    for (const j of journalists) {
      const seen = new Set<string>();
      for (const theme of themeLabels(j)) {
        const f = fold(theme.label);
        if (!f || seen.has(f)) continue;
        seen.add(f);
        const cur = byFold.get(f);
        if (cur) cur.n += 1;
        else byFold.set(f, { label: theme.label, n: 1 });
      }
    }
    return [...byFold.values()].sort((a, b) => b.n - a.n || a.label.localeCompare(b.label, locale)).slice(0, 50);
  }, [journalists, locale]);

  const withContact = journalists.filter(journalistHasContact).length;

  const rows = useMemo(() => {
    const query = q.trim();
    const scored = journalists.map((j) => {
      const o = outletMap[j.outlet_id];
      return { j, match: matchJournalist(j, query, o?.name || j.outlet_name || "") };
    }).filter(({ j, match }) => {
      const country = (j.country || outletMap[j.outlet_id]?.country || "").toUpperCase();
      if (countryFilter && country !== countryFilter) return false;
      if (outletFilter && String(j.outlet_id) !== outletFilter) return false;
      if (beatFilter && !journalistMatchesBeat(j, beatFilter)) return false;
      if (topicFilter && !journalistMatchesTopic(j, topicFilter)) return false;
      if (contactFilter === "yes" && !journalistHasContact(j)) return false;
      if (contactFilter === "no" && journalistHasContact(j)) return false;
      const acc = j.accessibility_score || 0;
      if (accessFilter === "pitch" && acc < pitch) return false;
      if (accessFilter === "low" && acc >= pitch) return false;
      if (query && match.score <= 0) return false;
      return true;
    });
    if (query) scored.sort((a, b) => b.match.score - a.match.score || a.j.name.localeCompare(b.j.name, locale));
    return scored;
  }, [journalists, outletMap, outletFilter, beatFilter, topicFilter, contactFilter, countryFilter, accessFilter, q, pitch, locale]);

  const active = Boolean(q || outletFilter || beatFilter || topicFilter || countryFilter || contactFilter !== "all" || accessFilter !== "all");
  const reset = () => setParams(new URLSearchParams(), { replace: true });
  const resultS = locale === "en" ? (rows.length === 1 ? "" : "s") : (rows.length > 1 ? "s" : "");

  const openCreate = () => { setEditItem(null); setForm({ ...emptyJournalist, outlet_id: outlets[0]?.id || 0 }); setShowModal(true); };
  const openEdit = (j: any) => { setEditItem(j); setForm({ name: j.name, outlet_id: j.outlet_id, role: j.role || "Journaliste", twitter_handle: j.twitter_handle || "", linkedin_url: j.linkedin_url || "", bio: splitBio(j.bio).text, beat: journalistBeat(j) }); setShowModal(true); };
  const handleSave = async () => { if (editItem) await updateJournalist(editItem.id, form); else await createJournalist(form); setShowModal(false); load(); };
  const handleDelete = async (id: number) => { if (confirm(t("journalists.deleteConfirm"))) { await deleteJournalist(id); load(); } };
  const run = async (fn: () => Promise<any>, fmt: (r: any) => string) => {
    setMsg(t("journalists.processing"));
    try { const r = await fn(); setMsg(fmt(r)); load(); } catch (e: any) { setMsg(t("settings.err", { msg: e.message })); }
  };

  if (loading) return <Loading />;

  return (
    <div>
      <PageHeader
        kicker={t("nav.kJournalists")}
        title={t("pages.journalists")}
        subtitle={<>{t("journalists.nSignatures", { n: journalists.length })}{countryFilter ? ` · ${flag(countryFilter)} ${countryName(countryFilter)}` : ""} · {t("journalists.nQualified", { n: journalists.filter((j) => journalistBeat(j)).length })} · <Term k="contact_channels">{t("journalists.nWithContact", { n: withContact })}</Term>.</>}
        actions={
          <>
            <Select value={countryFilter} onChange={(e) => set("country", e.target.value)} aria-label={t("journalists.countryAria")}>
              <option value="">{t("common.allCountries")}</option>
              {presentCountries.map((c) => <option key={c} value={c}>{flag(c)} {countryName(c)}</option>)}
            </Select>
            <Button onClick={() => run(cleanupJournalists, (r) => t("journalists.cleaned", { removed: r.removed, merged: r.merged, renamed: r.renamed }))}><Eraser size={13} /> {t("journalists.clean")}</Button>
            <Button onClick={() => run(() => enrichJournalists(50), (r) => t("journalists.enriched", { n: r.enriched }))}><Sparkles size={13} /> {t("journalists.enrich50")}</Button>
            <Button onClick={() => run(() => runContactsDiscovery(300), (r) => r.started ? t("journalists.contactsStarted") : t("journalists.contactsBusy"))}><AtSign size={13} /> {t("journalists.contacts")}</Button>
            <Button variant="primary" onClick={openCreate}><Plus size={13} /> {t("journalists.add")}</Button>
          </>
        }
      />

      {msg && <div className="mb-4"><Callout label={t("journalists.maintenance")}>{msg}</Callout></div>}

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Input value={q} onChange={(e) => set("q", e.target.value)} placeholder={t("journalists.searchPlaceholder")} className="max-w-xs" aria-label={t("common.search")} />
        <Select value={outletFilter} onChange={(e) => set("outlet_id", e.target.value)} aria-label={t("journalists.fieldOutlet")}>
          <option value="">{t("common.allOutlets")}</option>
          {outletsForSelect.map((o: any) => <option key={o.id} value={o.id}>{o.name}</option>)}
        </Select>
        <Select value={beatFilter} onChange={(e) => set("beat", e.target.value)} aria-label={t("journalists.fieldBeat")}>
          <option value="">{t("journalists.allBeats")}</option>
          <option value="_none">{t("journalists.noBeat")}</option>
          {beats.map((b) => <option key={b} value={b}>{beatFilterLabel(b, t)}</option>)}
        </Select>
        <Select value={topicFilter} onChange={(e) => set("topic", e.target.value)} aria-label={t("journalists.allTopics")}>
          <option value="">{t("journalists.allTopics")}</option>
          {topicFilter && !topics.some((topic) => topic.label === topicFilter) && <option value={topicFilter}>{topicFilter}</option>}
          {topics.map((topic) => <option key={topic.label} value={topic.label}>{topic.label} ({topic.n})</option>)}
        </Select>
        <Segmented
          value={contactFilter}
          onChange={(v) => set("contact", v)}
          options={[
            { value: "all", label: t("common.all") },
            { value: "yes", label: t("journalists.contactYes") },
            { value: "no", label: t("journalists.contactNo") },
          ]}
        />
        <Segmented
          value={accessFilter}
          onChange={(v) => set("access", v)}
          options={[
            { value: "all", label: t("common.all") },
            { value: "pitch", label: t("journalists.pitchMin", { n: pitch }) },
            { value: "low", label: t("journalists.lowAccess") },
          ]}
        />
        {active && (
          <Button size="sm" variant="ghost" onClick={reset}><X size={13} /> {t("journalists.reset")}</Button>
        )}
        <span className="ml-auto num text-[11px] text-faint">{t("common.results", { n: rows.length, s: resultS })}{active ? ` / ${journalists.length}` : ""}</span>
      </div>

      <Card>
        {rows.length === 0 ? (
          <Empty>
            {t("journalists.empty")}
            {active && <button type="button" onClick={reset} className="ml-2 text-accent-strong hover:underline">{t("journalists.resetFilters")}</button>}
          </Empty>
        ) : (
          <Table headers={[t("journalists.colName"), t("journalists.colOutlet"), t("journalists.colRole"), <Term k="beat">{t("journalists.fieldBeat")}</Term>, <Term k="accessibility">{t("journalists.accessibility")}</Term>, <Term k="contact_channels">{t("journalists.colContact")}</Term>, t("journalists.colChannels"), ""]} dense>
            {rows.slice(0, 400).map(({ j, match }) => {
              const o = outletMap[j.outlet_id];
              const country = (j.country || o?.country || "").toUpperCase();
              const beat = canonicalBeat(journalistBeat(j)) || journalistBeat(j);
              const text = splitBio(j.bio).text;
              const themes = themeLabels(j);
              const shown = (match.matchedThemes.length ? themes.filter((theme) => match.matchedThemes.includes(theme.label)) : themes).slice(0, 3);
              const has = journalistHasContact(j);
              return (
                <tr key={j.id}>
                  <td>
                    <button onClick={() => navigate(`/journalists/${j.id}`)} className="text-left font-medium text-ink hover:text-accent-strong">{j.name}</button>
                    {text && <div className="max-w-[280px] truncate text-[11px] text-faint">{text}</div>}
                    {shown.length > 0 && (
                      <div className="mt-1 flex max-w-[320px] flex-wrap gap-1">
                        {shown.map((theme) => (
                          <button key={theme.label} type="button" onClick={() => set("topic", topicFilter === theme.label ? "" : theme.label)} title={t("journalists.filterTopic")}>
                            <Badge tone={(topicFilter && journalistMatchesTopic({ themes: [theme] }, topicFilter)) || match.matchedThemes.includes(theme.label) ? "accent" : "faint"}>
                              {theme.label}{theme.count ? <span className="ml-1 num opacity-70">×{theme.count}</span> : null}
                            </Badge>
                          </button>
                        ))}
                      </div>
                    )}
                  </td>
                  <td className="whitespace-nowrap text-muted">
                    {country && (
                      <button type="button" className="mr-1 hover:text-accent-strong" title={t("journalists.filterCountry", { name: countryName(country) })} onClick={() => set("country", countryFilter === country ? "" : country)}>
                        {flag(country)}
                      </button>
                    )}
                    <button type="button" onClick={() => set("outlet_id", outletFilter === String(j.outlet_id) ? "" : String(j.outlet_id))} className="hover:text-accent-strong">{o?.name || j.outlet_name || `#${j.outlet_id}`}</button>
                  </td>
                  <td className="text-muted">{j.role}</td>
                  <td>
                    {beat ? (
                      <button type="button" onClick={() => set("beat", beatFilter === beat ? "" : beat)} title={t("journalists.filterBeat")}>
                        <Badge tone={beatFilter === beat ? "accent" : "default"}>{beatFilterLabel(beat, t)}</Badge>
                      </button>
                    ) : <span className="text-faint">{t("common.dash")}</span>}
                  </td>
                  <td><ScorePill value={j.accessibility_score} /></td>
                  <td>
                    <button type="button" onClick={() => set("contact", contactFilter === (has ? "yes" : "no") ? "all" : has ? "yes" : "no")}>
                      <Badge tone={has ? "accent" : "faint"}>{has ? t("common.yes") : t("common.no")}</Badge>
                    </button>
                  </td>
                  <td className="whitespace-nowrap text-[11.5px]">
                    {j.contacts?.kinds?.length ? (
                      <span className="inline-flex items-center gap-1.5" title={j.contacts.best ? `${j.contacts.best.value} (${j.contacts.best.confidence === "verified" ? t("confidence.verified") : j.contacts.best.confidence === "probable" ? t("confidence.probable") : t("confidence.guess")})` : t("journalists.nChannels", { n: j.contacts.n })}>
                        {j.contacts.kinds.filter((k: string) => k !== "author_page").slice(0, 4).map((k: string) => <span key={k} className={j.contacts.best?.kind === k && j.contacts.best?.confidence !== "guess" ? "text-accent-strong" : "text-faint"}>{kindIcon(k, 12)}</span>)}
                        {j.contacts.best && j.contacts.best.confidence !== "guess" && <span className="max-w-[150px] truncate font-mono text-muted">{j.contacts.best.value}</span>}
                      </span>
                    ) : <span className="text-faint">{t("common.dash")}</span>}
                  </td>
                  <td className="whitespace-nowrap text-right">
                    <IconButton onClick={() => openEdit(j)} aria-label={t("common.edit")}><Pencil size={13} /></IconButton>
                    <IconButton danger onClick={() => handleDelete(j.id)} aria-label={t("common.delete")}><Trash2 size={13} /></IconButton>
                  </td>
                </tr>
              );
            })}
          </Table>
        )}
        {rows.length > 400 && <p className="mt-3 text-center text-[11px] text-faint">{t("journalists.truncated")}</p>}
      </Card>

      {showModal && (
        <Modal
          title={editItem ? t("journalists.editTitle") : t("journalists.addTitle")}
          onClose={() => setShowModal(false)}
          footer={<><Button variant="ghost" onClick={() => setShowModal(false)}>{t("common.cancel")}</Button><Button variant="primary" onClick={handleSave} disabled={!form.name || !form.outlet_id}>{editItem ? t("common.save") : t("common.create")}</Button></>}
        >
          <Field label={t("journalists.fieldName")}><Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} autoFocus /></Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label={t("journalists.fieldOutlet")}>
              <Select className="w-full" value={form.outlet_id} onChange={(e) => setForm({ ...form, outlet_id: +e.target.value })}>
                {outlets.map((o: any) => <option key={o.id} value={o.id}>{o.name}</option>)}
              </Select>
            </Field>
            <Field label={t("journalists.fieldRole")}><Input value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })} /></Field>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Field label={t("journalists.fieldTwitter")}><Input value={form.twitter_handle} onChange={(e) => setForm({ ...form, twitter_handle: e.target.value })} placeholder={t("journalists.handlePlaceholder")} className="font-mono" /></Field>
            <Field label={t("journalists.fieldLinkedin")}><Input value={form.linkedin_url} onChange={(e) => setForm({ ...form, linkedin_url: e.target.value })} placeholder={t("journalists.linkedinPlaceholder")} /></Field>
          </div>
          <Field label={t("journalists.fieldBeat")} hint={t("journalists.fieldBeatHint")}><Input value={(form as any).beat || ""} onChange={(e) => setForm({ ...form, beat: e.target.value })} /></Field>
          <Field label={t("journalists.fieldBio")}><Textarea value={form.bio} onChange={(e) => setForm({ ...form, bio: e.target.value })} rows={3} /></Field>
        </Modal>
      )}
    </div>
  );
}
