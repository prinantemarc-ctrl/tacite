import { useEffect, useRef, useState, KeyboardEvent, useCallback } from "react";
import { Link } from "react-router-dom";
import { ArrowUp, Paperclip, Square, Check, X, Undo2, ChevronDown, Globe, Wrench, FileText, Download, AlertTriangle, Pin, Pencil } from "lucide-react";
import { getConversation, streamMessage, uploadAttachment, actOnAction, createConversation } from "../../api";
import Markdown from "./Markdown";
import ChartBlock from "./ChartBlock";
import { Loading } from "../../components";
import { useI18n, translate } from "../../i18n/I18nProvider";
import { TOOLS_EN, TOOLS_FR } from "../../i18n/messages";
import { getLocale } from "../../i18n/locale";

type Part = any;
type Msg = { id?: number; role: "user" | "assistant"; content: string; parts: Part[]; streaming?: boolean; cost_usd?: number };

export default function Chat({ conversationId, onConversationCreated, context, compact = false, onTitle }: {
  conversationId: number | null;
  onConversationCreated?: (id: number) => void;
  context?: { page: string; label: string } | null;
  compact?: boolean;
  onTitle?: (id: number, title: string) => void;
}) {
  const { t: tr } = useI18n();
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [loading, setLoading] = useState(false);
  const [input, setInput] = useState("");
  const [attachments, setAttachments] = useState<{ name: string; text: string; chars: number }[]>([]);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [pinned, setPinned] = useState<any>(context || null);
  const abortRef = useRef<AbortController | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const taRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const skipLoadRef = useRef(false);
  const busyRef = useRef(false);

  useEffect(() => {
    if (skipLoadRef.current) {
      skipLoadRef.current = false;
      return;
    }
    abortRef.current?.abort();
    if (conversationId === null) { setMsgs([]); setPinned(context || null); return; }
    let cancel = false;
    let timer = 0;
    setLoading(true);
    const load = (first: boolean) => {
      getConversation(conversationId)
        .then((c) => {
          if (cancel || busyRef.current) return;
          const messages = Array.isArray(c.messages) ? c.messages : [];
          setMsgs(messages);
          setPinned(c.context?.label ? c.context : null);
          const last = messages[messages.length - 1];
          const age = last?.created_at ? Date.now() - serverTime(last.created_at) : Infinity;
          // Le tour continue côté serveur même si l'utilisateur a quitté la page.
          if (last?.role === "user" && age >= 0 && age < 3 * 60 * 1000) {
            timer = window.setTimeout(() => load(false), 1500);
          }
        })
        .catch(() => { if (!cancel && first) setMsgs([]); })
        .finally(() => { if (!cancel && first) setLoading(false); });
    };
    load(true);
    return () => { cancel = true; window.clearTimeout(timer); };
  }, [conversationId]);

  useEffect(() => () => { abortRef.current?.abort(); }, []);

  useEffect(() => { endRef.current?.scrollIntoView({ block: "end" }); }, [msgs, busy]);

  const send = useCallback(async (text?: string) => {
    const t = (text ?? input).trim();
    if (!t || busy) return;
    setInput("");
    setBusy(true);
    busyRef.current = true;
    setStatus(tr("assistant.thinking"));
    let cid = conversationId;
    let finished = false;
    try {
      if (cid === null) {
        const c = await createConversation({ title: titleFromQuestion(t), context: pinned || undefined });
        cid = c.id;
        skipLoadRef.current = true;
        onConversationCreated?.(c.id);
      }
      const atts = attachments;
      setAttachments([]);
      const userMsg: Msg = { role: "user", content: t + (atts.length ? `\n\n${atts.map((a) => `📎 ${a.name}`).join("\n")}` : ""), parts: [] };
      const draft: Msg = { role: "assistant", content: "", parts: [], streaming: true };
      setMsgs((m) => [...m, userMsg, draft]);
      const ac = new AbortController();
      abortRef.current = ac;
      const update = (fn: (d: Msg) => void) => setMsgs((m) => {
        if (!m.length) return m;
        const copy = [...m];
        const last = copy[copy.length - 1];
        const d = { ...last, parts: [...(last.parts || [])] };
        fn(d);
        copy[copy.length - 1] = d;
        return copy;
      });
      await streamMessage(cid!, t, atts.map((a) => ({ name: a.name, text: a.text })), (e) => {
        switch (e.type) {
          case "text":
            update((d) => {
              const last = d.parts[d.parts.length - 1];
              if (last?.type === "text" && last.live) last.text += e.delta; else d.parts.push({ type: "text", text: e.delta, live: true });
              d.content += e.delta;
            });
            setStatus(null);
            break;
          case "tool_pending": setStatus(tr("chat.prepare", { tool: labelTool(e.name) })); break;
          case "status": setStatus(e.text); break;
          case "tool_start":
            setStatus(`${labelTool(e.name)}…`);
            update((d) => { d.parts.forEach((p) => { if (p.type === "text") p.live = false; }); d.parts.push({ type: "tool", id: e.id, name: e.name, args: e.args, running: true }); });
            break;
          case "tool_end":
            update((d) => { const p = d.parts.find((x) => x.type === "tool" && x.id === e.id); if (p) { p.running = false; p.summary = e.summary; p.ms = e.ms; } });
            setStatus(tr("assistant.thinking"));
            break;
          case "web_search":
            setStatus(e.status === "searching" ? tr("assistant.webSearchDot") : tr("chat.reading"));
            if (e.status === "searching") update((d) => { d.parts.forEach((p) => { if (p.type === "text") p.live = false; }); d.parts.push({ type: "web" }); });
            break;
          case "chart": case "artifact": case "confirm": case "citations":
            update((d) => { d.parts.forEach((p) => { if (p.type === "text") p.live = false; }); d.parts.push({ ...e }); });
            break;
          case "title":
            if (e.title && cid) onTitle?.(cid, e.title);
            break;
          case "done":
            finished = true;
            update((d) => { d.streaming = false; d.id = e.message_id; d.cost_usd = e.cost; d.parts.forEach((p) => { if (p.type === "text") p.live = false; }); });
            if (e.title && cid) onTitle?.(cid, e.title);
            break;
          case "error":
            finished = true;
            update((d) => { d.streaming = false; d.parts.push({ type: "error", text: e.message }); });
            if (e.title && cid) onTitle?.(cid, e.title);
            break;
        }
      }, ac.signal);
    } catch (err: any) {
      finished = true;
      const aborted = err?.name === "AbortError";
      setMsgs((m) => {
        const copy = [...m];
        const d = copy[copy.length - 1];
        if (d?.role !== "assistant") return m;
        copy[copy.length - 1] = aborted
          ? { ...d, streaming: false }
          : { ...d, streaming: false, parts: [...d.parts, { type: "error", text: err.message }] };
        return copy;
      });
    } finally {
      if (!finished) setMsgs((m) => {
        if (!m.length) return m;
        const last = m[m.length - 1];
        if (last?.role !== "assistant" || !last.streaming) return m;
        const copy = [...m];
        copy[copy.length - 1] = { ...last, streaming: false, parts: [...(last.parts || []), { type: "error", text: tr("chat.interrupted") }] };
        return copy;
      });
      setBusy(false);
      busyRef.current = false;
      setStatus(null);
      abortRef.current = null;
      taRef.current?.focus();
    }
  }, [input, busy, conversationId, attachments, pinned, tr]);

  const onKey = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
  };
  const onFiles = async (files: FileList | null) => {
    if (!files) return;
    for (const f of Array.from(files)) {
      try { const r = await uploadAttachment(f); setAttachments((a) => [...a, r]); } catch (err: any) { alert(tr("chat.attachRefused", { msg: err.message })); }
    }
  };
  const stop = () => abortRef.current?.abort();

  const setAction = (actionId: number, status: string) => setMsgs((m) => m.map((msg) => ({ ...msg, parts: msg.parts.map((p) => (p.type === "confirm" && p.action_id === actionId ? { ...p, status } : p)) })));
  const act = async (actionId: number, verb: "apply" | "reject" | "undo") => {
    try { const r = await actOnAction(actionId, verb); setAction(actionId, r.status); if (r.status === "failed") alert(tr("chat.fail", { msg: r.error })); }
    catch (e: any) { alert(e.message); }
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-paper">
      <div className={`min-h-0 flex-1 overflow-y-auto ${compact ? "px-4" : "px-6"} py-4`}>
        {loading ? <Loading /> : msgs.length === 0 ? (
          <Welcome compact={compact} pinned={pinned} onPick={(s) => send(s)} />
        ) : (
          <div className={`mx-auto ${compact ? "" : "max-w-[820px]"} space-y-6`}>
            {msgs.map((m, i) => <MessageView key={m.id ?? `m${i}`} m={m} compact={compact} onAct={act} />)}
            {busy && status && <div className="flex items-center gap-2 text-[11.5px] text-faint"><span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-accent" />{status}</div>}
            <div ref={endRef} />
          </div>
        )}
      </div>

      <div className={`border-t border-hair bg-paper ${compact ? "px-3 py-3" : "px-6 py-4"}`}>
        <div className={`mx-auto ${compact ? "" : "max-w-[820px]"}`}>
          {pinned?.label && (
            <div className="mb-2 flex items-center gap-2 text-[11px] text-muted">
              <Pin size={11} className="text-accent" /> {tr("assistant.context")} <b className="text-ink">{pinned.label}</b>
              <button className="text-faint hover:text-ink" onClick={() => setPinned(null)} title={tr("chat.unpin")}><X size={11} /></button>
            </div>
          )}
          {attachments.length > 0 && (
            <div className="mb-2 flex flex-wrap gap-1.5">
              {attachments.map((a, i) => (
                <span key={i} className="inline-flex items-center gap-1.5 rounded-pill border border-hair bg-surface px-2 py-[2px] text-[11px] text-muted">
                  <Paperclip size={10} /> {a.name} <span className="text-faint">{Math.round(a.chars / 1000)} k</span>
                  <button onClick={() => setAttachments((x) => x.filter((_, j) => j !== i))} className="text-faint hover:text-ink"><X size={10} /></button>
                </span>
              ))}
            </div>
          )}
          <div className="flex items-end gap-2 rounded-kit border border-hair bg-paper px-3 py-2 focus-within:border-accent">
            <button className="mb-[3px] text-faint hover:text-ink" onClick={() => fileRef.current?.click()} title={tr("chat.attach")}><Paperclip size={15} /></button>
            <input ref={fileRef} type="file" multiple className="hidden" onChange={(e) => onFiles(e.target.files)} accept=".txt,.md,.csv,.pdf,.docx,.xlsx,.html,.json" />
            <textarea
              ref={taRef} value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={onKey} rows={1}
              placeholder={compact ? tr("chat.ask") : tr("chat.placeholder")}
              className="max-h-40 min-h-[24px] flex-1 resize-none bg-transparent text-[13.5px] leading-6 text-ink outline-none placeholder:text-faint"
              onInput={(e) => { const t = e.currentTarget; t.style.height = "auto"; t.style.height = Math.min(160, t.scrollHeight) + "px"; }}
            />
            {busy ? (
              <button onClick={stop} className="mb-[1px] flex h-7 w-7 items-center justify-center rounded-full bg-ink text-paper hover:bg-confidential" title={tr("chat.stop")}><Square size={12} /></button>
            ) : (
              <button onClick={() => send()} disabled={!input.trim()} className="mb-[1px] flex h-7 w-7 items-center justify-center rounded-full bg-accent text-paper transition-colors hover:bg-accent-strong disabled:bg-hair disabled:text-faint" title={tr("chat.send")}><ArrowUp size={14} /></button>
            )}
          </div>
          {!compact && <div className="mt-1.5 text-[10.5px] text-faint">{tr("chat.sendHintLong")}</div>}
        </div>
      </div>
    </div>
  );
}

function Welcome({ compact, pinned, onPick }: { compact: boolean; pinned: any; onPick: (s: string) => void }) {
  const { t } = useI18n();
  const suggestions = pinned?.label
    ? [t("chat.pin1", { label: pinned.label }), t("chat.pin2", { label: pinned.label }), t("chat.pin3", { label: pinned.label }), t("chat.pin4", { label: pinned.label })]
    : [t("chat.s1"), t("chat.s2"), t("chat.s3"), t("chat.s4"), t("chat.s5"), t("chat.s6")];
  return (
    <div className={`mx-auto ${compact ? "" : "max-w-[820px]"} pt-6`}>
      <div className="h-[2px] w-[52px] bg-accent" />
      <h2 className="mt-4 text-[20px] font-bold tracking-tight text-ink">{pinned?.label ? <>{t("chat.about")} <span className="text-accent-strong">{pinned.label}</span></> : t("assistant.placeholder")}</h2>
      <p className="mt-2 max-w-[560px] text-[13px] leading-relaxed text-muted">
        {t("chat.intro")}
      </p>
      <div className={`mt-6 grid gap-2 ${compact ? "" : "md:grid-cols-2"}`}>
        {suggestions.map((s) => (
          <button key={s} onClick={() => onPick(s)} className="rounded-kit border border-hair bg-paper px-3.5 py-2.5 text-left text-[12.5px] leading-snug text-muted transition-colors hover:border-accent hover:bg-tint hover:text-ink">{s}</button>
        ))}
      </div>
    </div>
  );
}

function MessageView({ m, compact, onAct }: { m: Msg; compact: boolean; onAct: (id: number, verb: "apply" | "reject" | "undo") => void }) {
  if (m.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] whitespace-pre-wrap rounded-kit bg-tint px-4 py-2.5 text-[13.5px] leading-relaxed text-ink">{m.content}</div>
      </div>
    );
  }
  const raw = Array.isArray(m.parts) ? m.parts : [];
  const parts = raw.length ? raw : (m.content ? [{ type: "text", text: m.content }] : []);
  // regroupe les outils consécutifs
  const groups: any[] = [];
  for (const p of parts) {
    const last = groups[groups.length - 1];
    if ((p.type === "tool" || p.type === "web") && last?.type === "tools") last.items.push(p);
    else if (p.type === "tool" || p.type === "web") groups.push({ type: "tools", items: [p] });
    else groups.push(p);
  }
  return (
    <div className="flex gap-3">
      <div className="mt-1 h-5 w-5 shrink-0 rounded-full border border-accent/50 bg-tint text-center text-[9px] font-bold leading-[18px] text-accent-strong">T</div>
      <div className="min-w-0 flex-1">
        {groups.map((g, i) => {
          switch (g.type) {
            case "text": return <Markdown key={i} text={g.text} compact={compact} />;
            case "tools": return <ToolGroup key={i} items={g.items} />;
            case "chart": return <ChartBlock key={i} spec={g.spec} />;
            case "artifact": return <ArtifactCard key={i} a={g} />;
            case "confirm": return <ConfirmCard key={i} p={g} onAct={onAct} />;
            case "citations": return (
              <div key={i} className="mt-3 border-t border-hair-soft pt-2 text-[11px] text-faint">
                <span className="label mr-2">{translate("chat.webSources")}</span>
                {g.items.slice(0, 8).map((c: any, j: number) => <a key={j} href={c.url} target="_blank" rel="noreferrer" className="mr-3 inline-flex items-center gap-1 text-muted hover:text-accent-strong"><Globe size={10} />{shortHost(c.url)}</a>)}
              </div>
            );
            case "error": return <div key={i} className="mt-2 flex items-start gap-2 rounded-sm border border-confidential/30 bg-paper px-3 py-2 text-[12px] text-confidential"><AlertTriangle size={13} className="mt-0.5 shrink-0" />{g.text}</div>;
            default: return null;
          }
        })}
        {m.streaming && !m.content && groups.length === 0 && <span className="inline-block h-4 w-1.5 animate-pulse bg-accent/60 align-middle" />}
        {!m.streaming && m.cost_usd !== undefined && m.cost_usd > 0 && <div className="mt-2 text-[10px] text-faint num">{m.cost_usd < 0.01 ? "< 0,01" : m.cost_usd.toFixed(2)} $</div>}
      </div>
    </div>
  );
}

const labelTool = (n: string) => (getLocale() === "en" ? TOOLS_EN : TOOLS_FR)[n] || n;

function ToolGroup({ items }: { items: any[] }) {
  const [open, setOpen] = useState(false);
  const running = items.some((p) => p.running);
  return (
    <div className="my-2">
      <button onClick={() => setOpen(!open)} className="flex items-center gap-1.5 text-[11px] text-faint hover:text-muted">
        <ChevronDown size={11} className={`transition-transform ${open ? "" : "-rotate-90"}`} />
        {running ? <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-accent" /> : <Wrench size={10} />}
        {items.length === 1 ? (items[0].type === "web" ? translate("assistant.webSearch") : labelTool(items[0].name)) : translate("assistant.consultations", { n: items.length })}
        {!open && !running && <span className="text-faint/70">· {items.filter((p) => p.type === "tool").map((p) => p.summary).filter(Boolean).slice(0, 3).join(" · ")}</span>}
      </button>
      {open && (
        <ul className="mt-1 space-y-0.5 border-l border-hair pl-3 text-[11px] text-muted">
          {items.map((p, i) => p.type === "web" ? <li key={i} className="flex items-center gap-1.5"><Globe size={10} /> {translate("assistant.webSearch")}</li> : (
            <li key={i}><span className="font-medium text-ink">{labelTool(p.name)}</span>{p.args && <span className="text-faint"> ({p.args})</span>}{p.summary && <span> → {p.summary}</span>}{p.ms !== undefined && <span className="num text-faint"> · {p.ms} ms</span>}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ArtifactCard({ a }: { a: any }) {
  const kb = a.size ? translate("assistant.kb", { n: Math.max(1, Math.round(a.size / 1024)) }) : "";
  return (
    <div className="my-2 inline-flex items-center gap-3 rounded-kit border border-hair bg-paper px-3 py-2">
      <div className="flex h-8 w-8 items-center justify-center rounded-sm bg-tint text-accent-strong"><FileText size={15} /></div>
      <div className="min-w-0">
        <div className="truncate text-[12.5px] font-medium text-ink">{a.title || a.filename}</div>
        <div className="text-[10.5px] uppercase tracking-[0.08em] text-faint">{a.kind}{a.report ? ` · ${translate("chat.reportTag")}` : ""} {kb && `· ${kb}`}</div>
      </div>
      {a.report_id && <Link to={`/reports/${a.report_id}`} className="ml-1 text-muted hover:text-ink" title={translate("reports.openEditor")}><Pencil size={14} /></Link>}
      <a href={`${a.url}${a.kind === "pdf" || a.kind === "html" ? "?inline=true" : ""}`} target="_blank" rel="noreferrer" className="ml-2 text-muted hover:text-ink" title={translate("common.open")}><Download size={14} /></a>
    </div>
  );
}

function ConfirmCard({ p, onAct }: { p: any; onAct: (id: number, verb: "apply" | "reject" | "undo") => void }) {
  const st = p.status || "proposed";
  const tone = st === "applied" ? "border-accent" : st === "rejected" || st === "failed" ? "border-hair" : st === "undone" ? "border-hair" : "border-ink";
  return (
    <div className={`my-2 rounded-kit border border-l-[3px] bg-paper px-3.5 py-2.5 ${tone}`}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="label mb-0.5">{st === "proposed" ? translate("assistant.proposed") : st === "applied" ? translate("common.applied") : st === "rejected" ? translate("common.reject") : st === "undone" ? translate("common.undone") : translate("common.failed")}</div>
          <div className="text-[12.5px] text-ink">{p.description}</div>
          <details className="mt-1 text-[10.5px] text-faint"><summary className="cursor-pointer hover:text-muted">{translate("common.detail")}</summary><pre className="mt-1 whitespace-pre-wrap font-mono">{p.tool} {JSON.stringify(p.args, null, 1)}</pre></details>
        </div>
        <div className="flex shrink-0 gap-1.5">
          {st === "proposed" && <>
            <button onClick={() => onAct(p.action_id, "apply")} className="inline-flex items-center gap-1 rounded-sm bg-accent px-2.5 py-1 text-[11.5px] font-semibold text-paper hover:bg-accent-strong"><Check size={12} /> {translate("common.apply")}</button>
            <button onClick={() => onAct(p.action_id, "reject")} className="inline-flex items-center gap-1 rounded-sm border border-hair px-2.5 py-1 text-[11.5px] text-muted hover:border-faint hover:text-ink"><X size={12} /> {translate("common.reject")}</button>
          </>}
          {st === "applied" && ["update_outlet", "update_journalist", "update_client", "update_recommendation", "update_settings", "create_outlet", "create_journalist", "create_client", "add_outlet_feed"].includes(p.tool) && (
            <button onClick={() => onAct(p.action_id, "undo")} className="inline-flex items-center gap-1 rounded-sm border border-hair px-2.5 py-1 text-[11.5px] text-muted hover:border-faint hover:text-ink"><Undo2 size={12} /> {translate("common.cancel")}</button>
          )}
        </div>
      </div>
    </div>
  );
}

function shortHost(u: string) { try { return new URL(u).hostname.replace(/^www\./, ""); } catch { return u; } }

function titleFromQuestion(text: string): string {
  let t = text.split("\n")[0].replace(/\s+/g, " ").trim().replace(/^["«»']+|["«»']+$/g, "");
  t = t.replace(/[ ?.!…]+$/, "");
  if (!t) return "Conversation";
  if (t.length <= 72) return t;
  const cut = t.slice(0, 72);
  const sp = cut.lastIndexOf(" ");
  return (sp > 24 ? cut.slice(0, sp) : cut).replace(/[ .,;:—-]+$/, "") + "…";
}

/** Horodatages API naïfs : ils sont en UTC. */
function serverTime(d: string): number {
  const zoned = /[zZ]|[+-]\d\d:?\d\d$/.test(d) ? d : `${d}Z`;
  return new Date(zoned).getTime();
}
