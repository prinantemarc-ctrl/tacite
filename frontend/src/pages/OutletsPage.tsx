import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Plus, Pencil, Trash2, Upload, Globe2 } from "lucide-react";
import { listOutlets, createOutlet, updateOutlet, deleteOutlet, importOutletsCSV } from "../api";
import CountryManager from "../components/CountryManager";
import {
  Card, Badge, Table, GapBar, Meter, Button, IconButton, Modal, Field, Input, Select,
  Loading, Empty, PageHeader, Callout, Term,
} from "../components";
import { flag, countryName, loadIsoCountries, languageName, maxUsableGapInfo, axisLabel } from "../geo";
import { useI18n } from "../i18n/I18nProvider";
import { confidenceLabel, confidenceTone, orientationLabel } from "../i18n/mapped";

const emptyOutlet = {
  name: "", country: "FR", language: "fr", website_url: "", rss_url: "",
  declared_orientation: "", official_classification: {}, meta: {},
};
const LANGS = ["fr", "en", "de", "es", "it", "nl", "pt", "ar", "ru", "zh", "ja", "tr", "pl", "sv", "da", "el", "he", "hi", "ko", "fa", "uk"];

export default function OutletsPage() {
  const { t, intl, locale } = useI18n();
  const [outlets, setOutlets] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [countryFilter, setCountryFilter] = useState("");
  const [showModal, setShowModal] = useState(false);
  const [showCountry, setShowCountry] = useState(false);
  const [editItem, setEditItem] = useState<any>(null);
  const [form, setForm] = useState(emptyOutlet);
  const [importMsg, setImportMsg] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();
  const [countries, setCountries] = useState<{ code: string; name: string }[]>([]);

  const load = () => listOutlets().then(setOutlets).finally(() => setLoading(false));
  useEffect(() => { load(); }, []);
  useEffect(() => { loadIsoCountries().then(setCountries); }, [locale]);

  const confLabel = (c?: string) => confidenceLabel(c, t) || c || "";

  const openCreate = () => { setEditItem(null); setForm(emptyOutlet); setShowModal(true); };
  const openEdit = (o: any) => {
    setEditItem(o);
    setForm({
      name: o.name, country: o.country, language: o.language, website_url: o.website_url || "", rss_url: o.rss_url || "",
      declared_orientation: o.declared_orientation || "", official_classification: o.official_classification || {}, meta: o.meta || {},
    });
    setShowModal(true);
  };
  const handleSave = async () => {
    if (editItem) await updateOutlet(editItem.id, form); else await createOutlet(form);
    setShowModal(false); load();
  };
  const handleDelete = async (id: number) => {
    if (confirm(t("outlets.deleteConfirm"))) { await deleteOutlet(id); load(); }
  };
  const handleImport = async (file: File) => {
    setImportMsg(t("outlets.importing"));
    try {
      const r = await importOutletsCSV(file);
      const errors = r.errors?.length ? t("outlets.importErrors", { n: r.errors.length }) : "";
      setImportMsg(t("outlets.importDone", { created: r.created, updated: r.updated, errors }));
      load();
    } catch (e: any) {
      setImportMsg(t("outlets.err", { msg: e.message }));
    }
  };

  const present = [...new Set(outlets.map((o) => o.country))].sort((a, b) => countryName(a).localeCompare(countryName(b), locale));
  const rows = (countryFilter ? outlets.filter((o) => o.country === countryFilter) : outlets)
    .slice()
    .sort((a, b) => (b.influence_score || 0) - (a.influence_score || 0) || (b.articles_total || 0) - (a.articles_total || 0));

  if (loading) return <Loading />;

  return (
    <div>
      <PageHeader
        kicker={t("pages.outletsSub")}
        title={t("pages.outlets")}
        subtitle={t("outlets.subtitle", { n: outlets.length, p: present.length })}
        actions={
          <>
            <Select value={countryFilter} onChange={(e) => setCountryFilter(e.target.value)}>
              <option value="">{t("common.allCountries")}</option>
              {present.map((c) => <option key={c} value={c}>{flag(c)} {countryName(c)}</option>)}
            </Select>
            <input ref={fileRef} type="file" accept=".csv,text/csv" className="hidden" onChange={(e) => e.target.files?.[0] && handleImport(e.target.files[0])} />
            <Button onClick={() => fileRef.current?.click()}><Upload size={13} /> {t("outlets.importCsv")}</Button>
            <Button onClick={() => setShowCountry(true)}><Globe2 size={13} /> {t("outlets.manageCountry")}</Button>
            <Button variant="primary" onClick={openCreate}><Plus size={13} /> {t("outlets.add")}</Button>
          </>
        }
      />

      {importMsg && <div className="mb-4"><Callout label={t("outlets.import")}>{importMsg} <span className="text-faint">{t("outlets.importCols")}</span></Callout></div>}

      <Card>
        {rows.length === 0 ? <Empty>{t("outlets.emptyFilter")}</Empty> : (
          <Table headers={[t("outlets.colOutlet"), t("outlets.volume"), <Term k="influence">{t("outlets.influence")}</Term>, <Term k="gap">{t("outlets.colGap")}</Term>, <Term k="drift">{t("outlets.colDrift")}</Term>, <Term k="outlet_topics">{t("outlets.colTopics")}</Term>, <Term k="top_journalists">{t("pages.journalists")}</Term>, ""]}>
            {rows.map((o) => {
              const gap = maxUsableGapInfo(o);
              const drifts = (o.latest_profile?.drift_alerts || []) as { axis: string; change: number }[];
              const topics = (o.topics || []) as { label: string; count: number }[];
              const journalists = (o.top_journalists || []) as { id: number; name: string; articles: number }[];
              const conf = o.confidence as string | undefined;
              const confTone = confidenceTone(conf);
              return (
                <tr key={o.id}>
                  <td className="min-w-[160px]">
                    <button onClick={() => navigate(`/outlets/${o.id}`)} className="text-left font-medium text-ink hover:text-accent-strong">{o.name}{o.collect_enabled === 0 && <Badge tone="faint" className="ml-2">{t("outlets.collectPaused")}</Badge>}</button>
                    <div className="text-[11px] text-faint">{flag(o.country)} {countryName(o.country)} · {languageName(o.language)}</div>
                    {o.declared_orientation && <div className="text-[11px] italic text-faint">{orientationLabel(o.declared_orientation, t)}</div>}
                  </td>
                  <td className="whitespace-nowrap">
                    <button onClick={() => navigate(`/articles?outlet_id=${o.id}`)} className="num text-ink hover:text-accent-strong" title={t("outlets.seeArticles")}>
                      {(o.articles_total ?? 0).toLocaleString(intl)}
                    </button>
                    <div className="text-[11px] text-faint">{(o.articles_week ?? 0).toLocaleString(intl)} {t("outlets.thisWeek")}</div>
                    {o.latest_profile && conf && <Badge tone={confTone} className="mt-0.5">{confLabel(conf)}</Badge>}
                  </td>
                  <td>
                    <Meter value={o.influence_score || 0} label={(o.influence_score || 0).toFixed(0)} />
                    {o.influence_rank ? <div className="num text-[11px] text-faint">#{o.influence_rank}</div> : null}
                  </td>
                  <td className="min-w-[168px]">
                    {gap ? (
                      <>
                        <div className="text-[11px] text-muted">{gap.label}</div>
                        <GapBar value={gap.value} />
                      </>
                    ) : <span className="text-faint">{t("common.dash")}</span>}
                  </td>
                  <td className="min-w-[120px]">
                    {drifts.length ? (
                      <div className="flex flex-wrap gap-1">
                        {drifts.slice(0, 2).map((d, i) => (
                          <Badge key={i} tone={Math.abs(d.change) > 0.5 ? "alert" : "accent"}>
                            {axisLabel(d.axis)} {d.change > 0 ? "+" : ""}{Number(d.change).toFixed(2)}
                          </Badge>
                        ))}
                      </div>
                    ) : <span className="text-faint">{t("common.dash")}</span>}
                  </td>
                  <td className="min-w-[140px] max-w-[200px]">
                    {topics.length ? topics.slice(0, 3).map((topic) => (
                      <div key={topic.label} className="truncate text-[12px] text-ink" title={`${topic.label} ×${topic.count}`}>
                        {topic.label} <span className="num text-faint">×{topic.count}</span>
                      </div>
                    )) : <span className="text-faint">{t("common.dash")}</span>}
                  </td>
                  <td className="min-w-[140px] max-w-[220px]">
                    {journalists.length ? (
                      <>
                        {journalists.map((j) => (
                          <button key={j.id} onClick={() => navigate(`/journalists/${j.id}`)} className="block max-w-full truncate text-left text-[12px] text-ink hover:text-accent-strong">
                            {j.name} <span className="num text-faint">×{j.articles}</span>
                          </button>
                        ))}
                        {(o.journalists_count || 0) > journalists.length && (
                          <div className="text-[11px] text-faint">+{o.journalists_count - journalists.length}</div>
                        )}
                      </>
                    ) : <span className="text-faint">{t("common.dash")}</span>}
                  </td>
                  <td className="whitespace-nowrap text-right">
                    <IconButton onClick={() => openEdit(o)} aria-label={t("common.edit")}><Pencil size={13} /></IconButton>
                    <IconButton danger onClick={() => handleDelete(o.id)} aria-label={t("common.delete")}><Trash2 size={13} /></IconButton>
                  </td>
                </tr>
              );
            })}
          </Table>
        )}
      </Card>

      {showCountry && (
        <CountryManager outlets={outlets} onClose={() => setShowCountry(false)} onChanged={load} initialCountry={countryFilter || undefined} />
      )}

      {showModal && (
        <Modal
          title={editItem ? t("outlets.editTitle") : t("outlets.addTitle")}
          onClose={() => setShowModal(false)}
          footer={
            <>
              <Button variant="ghost" onClick={() => setShowModal(false)}>{t("common.cancel")}</Button>
              <Button variant="primary" onClick={handleSave} disabled={!form.name}>{editItem ? t("common.save") : t("common.create")}</Button>
            </>
          }
        >
          <Field label={t("outlets.name")}><Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} autoFocus /></Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label={t("outlets.country")}>
              <Select className="w-full" value={form.country} onChange={(e) => setForm({ ...form, country: e.target.value })}>
                {countries.map((c) => <option key={c.code} value={c.code}>{flag(c.code)} {c.name}</option>)}
              </Select>
            </Field>
            <Field label={t("outlets.language")}>
              <Select className="w-full" value={form.language} onChange={(e) => setForm({ ...form, language: e.target.value })}>
                {LANGS.map((l) => <option key={l} value={l}>{languageName(l)}</option>)}
              </Select>
            </Field>
          </div>
          <Field label={t("outlets.site")}><Input value={form.website_url} onChange={(e) => setForm({ ...form, website_url: e.target.value })} placeholder="https://…" /></Field>
          <Field label={t("outlets.rss")} hint={t("outlets.rssHint")}><Input value={form.rss_url} onChange={(e) => setForm({ ...form, rss_url: e.target.value })} placeholder="https://…/rss" /></Field>
          <Field label={t("outlets.declared")}><Input value={form.declared_orientation} onChange={(e) => setForm({ ...form, declared_orientation: e.target.value })} placeholder={t("outlets.declaredPh")} /></Field>
          {!editItem && <Badge tone="faint">{t("outlets.declaredHint")}</Badge>}
        </Modal>
      )}
    </div>
  );
}
