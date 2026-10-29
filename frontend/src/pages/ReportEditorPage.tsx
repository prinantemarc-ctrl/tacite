import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { ArrowDown, ArrowUp, Plus, Trash2 } from "lucide-react";
import { getReport, patchReport, exportReport } from "../api";
import { Button, PageHeader, Loading, ErrorState, Empty, Input, Textarea, Select } from "../components";
import Markdown from "../components/chat/Markdown";
import { useI18n } from "../i18n/I18nProvider";

type Block = {
  id: string;
  type: string;
  heading?: string;
  markdown?: string;
  label?: string;
  title?: string;
  caption?: string;
  svg?: string;
  widget?: string;
  items?: any[];
};

const bid = () => (crypto.randomUUID ? crypto.randomUUID().slice(0, 10) : Math.random().toString(36).slice(2, 12));

export default function ReportEditorPage() {
  const { t, intl } = useI18n();
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [report, setReport] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [subtitle, setSubtitle] = useState("");
  const [blocks, setBlocks] = useState<Block[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [exporting, setExporting] = useState(false);
  const saveTimer = useRef<number | null>(null);

  useEffect(() => {
    if (!id) return;
    getReport(+id).then((r) => {
      setReport(r);
      setTitle(r.title || "");
      setSubtitle(r.subtitle || "");
      setBlocks((r.body?.blocks || []) as Block[]);
      setDirty(false);
    }).catch((e) => setError(String(e)));
  }, [id]);

  const persist = useCallback(async (nextTitle: string, nextSubtitle: string, nextBlocks: Block[]) => {
    if (!id) return;
    setSaving(true);
    try {
      const r = await patchReport(+id, { title: nextTitle, subtitle: nextSubtitle, blocks: nextBlocks });
      setReport(r);
      setDirty(false);
    } catch (e: any) { setError(e.message); }
    finally { setSaving(false); }
  }, [id]);

  const scheduleSave = (nextTitle: string, nextSubtitle: string, nextBlocks: Block[]) => {
    setDirty(true);
    if (saveTimer.current) window.clearTimeout(saveTimer.current);
    saveTimer.current = window.setTimeout(() => persist(nextTitle, nextSubtitle, nextBlocks), 700);
  };

  const update = (patch: Partial<{ title: string; subtitle: string; blocks: Block[] }>) => {
    const nt = patch.title ?? title;
    const ns = patch.subtitle ?? subtitle;
    const nb = patch.blocks ?? blocks;
    if (patch.title !== undefined) setTitle(patch.title);
    if (patch.subtitle !== undefined) setSubtitle(patch.subtitle);
    if (patch.blocks) setBlocks(patch.blocks);
    scheduleSave(nt, ns, nb);
  };

  const move = (i: number, dir: -1 | 1) => {
    const j = i + dir;
    if (j < 0 || j >= blocks.length) return;
    const next = [...blocks];
    [next[i], next[j]] = [next[j], next[i]];
    update({ blocks: next });
  };
  const remove = (i: number) => {
    if (!confirm(t("reports.confirmDeleteBlock"))) return;
    const gone = blocks[i];
    const next = blocks.filter((_, k) => k !== i);
    if (selected === gone.id) setSelected(next[Math.max(0, i - 1)]?.id || null);
    update({ blocks: next });
  };
  const patchBlock = (i: number, p: Partial<Block>) => {
    const next = blocks.map((b, k) => (k === i ? { ...b, ...p } : b));
    update({ blocks: next });
  };
  const addSection = () => {
    const b: Block = { id: bid(), type: "section", heading: t("reports.heading"), markdown: "" };
    update({ blocks: [...blocks, b] });
    setSelected(b.id);
  };
  const addCallout = () => {
    const b: Block = { id: bid(), type: "callout", label: t("reports.blockCallout"), markdown: "" };
    update({ blocks: [...blocks, b] });
    setSelected(b.id);
  };
  const addWidget = (idx: number) => {
    const w = (report?.catalog || [])[idx];
    if (!w) return;
    const b: Block = { id: bid(), type: "widget", widget: w.widget || "chart", title: w.title || "", caption: w.caption || "", svg: w.svg || "" };
    const methodAt = blocks.findIndex((x) => x.type === "method");
    const next = [...blocks];
    next.splice(methodAt >= 0 ? methodAt : next.length, 0, b);
    update({ blocks: next });
    setSelected(b.id);
  };

  const exportPdf = async () => {
    if (!id) return;
    if (dirty) await persist(title, subtitle, blocks);
    setExporting(true);
    try {
      const r = await exportReport(+id);
      setReport(r);
      if (r.url) window.open(`${r.url}?inline=true`, "_blank");
    } catch (e: any) { setError(e.message); }
    finally { setExporting(false); }
  };

  const blockLabel = (b: Block) => {
    const key = `reports.block${b.type[0].toUpperCase()}${b.type.slice(1)}`;
    const mapped = t(key);
    const kind = mapped === key ? b.type : mapped;
    const extra = b.heading || b.title || b.label || "";
    return extra ? `${kind} · ${extra}` : kind;
  };

  const catalog: any[] = report?.catalog || [];

  if (error && !report) return <ErrorState>{error}</ErrorState>;
  if (!report) return <Loading />;

  return (
    <div>
      <PageHeader
        kicker={t("reports.editorKicker")}
        title={<input className="w-full bg-transparent text-[inherit] font-[inherit] tracking-[inherit] outline-none placeholder:text-faint" value={title} onChange={(e) => update({ title: e.target.value })} />}
        subtitle={<>
          <input className="w-full bg-transparent text-[13px] text-muted outline-none placeholder:text-faint" value={subtitle} onChange={(e) => update({ subtitle: e.target.value })} placeholder={t("reports.notes")} />
          <span className="mt-1 block text-[11px] text-faint">
            {saving ? t("common.saving") : dirty ? t("reports.unsaved") : t("reports.saved")}
            {report.status === "exported" ? ` · ${t("reports.statusExported")}` : ` · ${t("reports.statusDraft")}`}
            {report.updated_at ? ` · ${new Date(report.updated_at).toLocaleString(intl, { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}` : ""}
          </span>
        </>}
        actions={
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="ghost" onClick={() => navigate("/reports")}>{t("reports.backList")}</Button>
            <Button size="sm" variant="primary" onClick={exportPdf} disabled={exporting}>{exporting ? t("reports.exporting") : t("reports.exportPdf")}</Button>
          </div>
        }
      />
      {error && <p className="mb-3 text-[12px] text-confidential">{error}</p>}

      <div className="grid gap-5 lg:grid-cols-[260px_1fr]">
        <aside className="space-y-3">
          <div className="label">{t("reports.addBlock")}</div>
          <div className="flex flex-wrap gap-1.5">
            <Button size="sm" variant="ghost" onClick={addSection}><Plus size={11} /> {t("reports.addSection")}</Button>
            <Button size="sm" variant="ghost" onClick={addCallout}><Plus size={11} /> {t("reports.addCallout")}</Button>
          </div>
          {catalog.length ? (
            <Select value="" onChange={(e) => { if (e.target.value) addWidget(+e.target.value); e.target.value = ""; }}>
              <option value="">{t("reports.addWidget")}…</option>
              {catalog.map((w: any, i: number) => <option key={i} value={i}>{w.title || t("reports.blockWidget")}</option>)}
            </Select>
          ) : <p className="text-[11px] text-faint">{t("reports.noWidget")}</p>}
          <ol className="divide-y divide-hair-soft rounded-sm border border-hair">
            {blocks.map((b, i) => (
              <li key={b.id} className={`flex items-center gap-1 px-2 py-1.5 text-[12px] ${selected === b.id ? "bg-tint" : ""}`}>
                <button type="button" className="min-w-0 flex-1 truncate text-left text-ink hover:text-accent-strong" onClick={() => setSelected(b.id)}>{blockLabel(b)}</button>
                <button type="button" className="text-faint hover:text-ink" onClick={() => move(i, -1)} disabled={i === 0}><ArrowUp size={11} /></button>
                <button type="button" className="text-faint hover:text-ink" onClick={() => move(i, 1)} disabled={i === blocks.length - 1}><ArrowDown size={11} /></button>
                {b.type !== "method" && <button type="button" className="text-faint hover:text-confidential" onClick={() => remove(i)}><Trash2 size={11} /></button>}
              </li>
            ))}
          </ol>
        </aside>

        <div className="rounded-sm border border-hair bg-paper px-8 py-8 shadow-[0_12px_40px_-24px_rgba(0,0,0,.35)]">
          <div className="label text-accent">{report.body?.kicker || "Tacite"}</div>
          <h2 className="mt-1 text-[26px] font-semibold leading-tight tracking-[-0.01em] text-ink">{title || t("common.untitled")}</h2>
          {subtitle ? <p className="mt-1 text-[13px] text-muted">{subtitle}</p> : null}
          <div className="mt-3 h-[1.5px] bg-accent" />
          {blocks.length === 0 && <Empty>{t("reports.emptyBody")}</Empty>}
          {blocks.map((b, i) => (
            <div key={b.id} className={`mt-6 cursor-pointer rounded-sm p-1 ${selected === b.id ? "ring-1 ring-accent" : ""}`} onClick={() => setSelected(b.id)}>
              <BlockView b={b} active={selected === b.id} onChange={(p) => patchBlock(i, p)} t={t} />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function BlockView({ b, active, onChange, t }: { b: Block; active: boolean; onChange: (p: Partial<Block>) => void; t: (k: string, v?: Record<string, string | number>) => string }) {
  if (b.type === "stats") {
    return (
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        {(b.items || []).map((it: any, i: number) => (
          <div key={i} className="border-l-[1.5px] border-accent pl-2">
            <div className="label">{it.label}</div>
            <div className="text-[22px] font-semibold text-ink">{it.value}</div>
            <div className="text-[11px] text-faint">{it.sub}</div>
          </div>
        ))}
      </div>
    );
  }
  if (b.type === "callout") {
    return (
      <div className="border border-hair border-l-[3px] border-l-accent bg-surface px-3 py-2">
        {active ? (
          <>
            <Input value={b.label || ""} onChange={(e) => onChange({ label: e.target.value })} className="mb-2" />
            <Textarea rows={5} value={b.markdown || ""} onChange={(e) => onChange({ markdown: e.target.value })} />
          </>
        ) : (
          <>
            <div className="label mb-1">{b.label}</div>
            <Markdown text={b.markdown || ""} compact />
          </>
        )}
      </div>
    );
  }
  if (b.type === "stories") {
    return (
      <div>
        <div className="label mb-2">{b.heading}</div>
        <ul className="space-y-2 text-[13px]">
          {(b.items || []).map((s: any, i: number) => (
            <li key={i}><strong className="text-ink">{s.label}</strong><p className="text-muted">{s.brief}</p></li>
          ))}
        </ul>
      </div>
    );
  }
  if (b.type === "section") {
    return active ? (
      <div className="space-y-2">
        <Input value={b.heading || ""} onChange={(e) => onChange({ heading: e.target.value })} placeholder={t("reports.heading")} />
        <Textarea rows={10} value={b.markdown || ""} onChange={(e) => onChange({ markdown: e.target.value })} />
      </div>
    ) : (
      <div>
        <div className="label mb-2 border-b border-hair pb-1">{b.heading}</div>
        <div className="text-[13.5px] leading-relaxed text-ink"><Markdown text={b.markdown || ""} /></div>
      </div>
    );
  }
  if (b.type === "widget") {
    return (
      <div>
        {active ? (
          <div className="mb-2 grid gap-2 sm:grid-cols-2">
            <Input value={b.title || ""} onChange={(e) => onChange({ title: e.target.value })} placeholder={t("reports.widgetTitle")} />
            <Input value={b.caption || ""} onChange={(e) => onChange({ caption: e.target.value })} placeholder={t("reports.caption")} />
          </div>
        ) : b.title ? <div className="mb-1 text-[13px] font-medium text-ink">{b.title}</div> : null}
        {b.svg ? <div className="overflow-x-auto [&_svg]:max-w-full" dangerouslySetInnerHTML={{ __html: b.svg }} /> : null}
        {b.caption ? <div className="mt-1 text-[11px] text-faint">{b.caption}</div> : null}
      </div>
    );
  }
  if (b.type === "sources") {
    return active ? (
      <div>
        <div className="label mb-1">{t("reports.blockSources")}</div>
        <Textarea rows={6} value={(b.items || []).join("\n")} onChange={(e) => onChange({ items: e.target.value.split("\n") })} />
        <p className="mt-1 text-[11px] text-faint">{t("reports.sourcesHint")}</p>
      </div>
    ) : (
      <div>
        <div className="label mb-2">{t("reports.blockSources")}</div>
        <ul className="list-disc pl-4 text-[12px] text-muted">{(b.items || []).map((x: string, i: number) => <li key={i}>{x}</li>)}</ul>
      </div>
    );
  }
  if (b.type === "method") {
    return (
      <div className="border border-hair border-l-[3px] border-l-accent bg-surface px-3 py-2 text-[12px] text-muted">
        <div className="label mb-1">{t("reports.blockMethod")}</div>
        {t("reports.methodLocked")}
      </div>
    );
  }
  return null;
}
