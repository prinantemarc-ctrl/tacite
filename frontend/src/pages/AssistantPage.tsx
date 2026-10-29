import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Plus, Trash2, MessageSquare } from "lucide-react";
import { listConversations, deleteConversation } from "../api";
import Chat from "../components/chat/Chat";
import { ChatErrorBoundary } from "../components";
import { useI18n } from "../i18n/I18nProvider";

export default function AssistantPage() {
  const { t } = useI18n();
  const { id } = useParams();
  const navigate = useNavigate();
  const cid = id ? +id : null;
  const [convs, setConvs] = useState<any[]>([]);

  const refresh = () => listConversations().then(setConvs);
  useEffect(() => { refresh(); }, []);

  const remove = async (c: any) => {
    if (!confirm(t("assistant.deleteConfirm", { title: c.title }))) return;
    await deleteConversation(c.id);
    if (cid === c.id) navigate("/assistant");
    refresh();
  };

  const groups = groupByDate(convs, t);

  return (
    <div className="flex min-h-0 flex-1">
      {/* Historique */}
      <aside className="flex w-[260px] shrink-0 flex-col border-r border-hair bg-paper">
        <div className="flex items-center justify-between px-4 pb-3 pt-5">
          <div><div className="kicker">{t("assistant.title")}</div><div className="text-[15px] font-bold tracking-tight text-ink">{t("assistant.conversations")}</div></div>
          <button onClick={() => navigate("/assistant")} className="flex h-7 w-7 items-center justify-center rounded-sm border border-hair text-muted hover:border-accent hover:text-accent-strong" title={t("assistant.newChat")}><Plus size={14} /></button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-4">
          {groups.map(([label, list]) => (
            <div key={label} className="mb-3">
              <div className="label mb-1 px-2 text-faint">{label}</div>
              <ul className="space-y-px">
                {list.map((c) => (
                  <li key={c.id} className={`group flex items-center gap-2 rounded-sm border-l-[2px] py-[6px] pl-2.5 pr-1.5 text-[12.5px] ${cid === c.id ? "border-accent bg-tint text-ink" : "border-transparent text-muted hover:bg-surface hover:text-ink"}`}>
                    <MessageSquare size={12} className={cid === c.id ? "text-accent-strong" : "text-faint"} />
                    <button onClick={() => navigate(`/assistant/${c.id}`)} className="min-w-0 flex-1 truncate text-left" title={c.title}>{c.title}</button>
                    <button onClick={() => remove(c)} className="hidden text-faint hover:text-confidential group-hover:block" title={t("common.delete")}><Trash2 size={11} /></button>
                  </li>
                ))}
              </ul>
            </div>
          ))}
          {convs.length === 0 && <p className="px-2 pt-4 text-[12px] italic text-faint">{t("assistant.none")}</p>}
        </div>
        <div className="border-t border-hair px-4 py-2.5 text-[10.5px] text-faint">
          {t("assistant.nConversations", { n: convs.length, s: convs.length > 1 ? "s" : "" })}<span className="num">{convs.reduce((s, c) => s + (c.cost_usd || 0), 0).toFixed(2)} $</span> {t("assistant.total")}
        </div>
      </aside>

      {/* Fil */}
      <main className="flex min-h-0 min-w-0 flex-1 flex-col bg-paper">
        <ChatErrorBoundary>
          <Chat
            conversationId={cid}
            onConversationCreated={(nid) => { navigate(`/assistant/${nid}`, { replace: true }); refresh(); }}
            onTitle={(nid, title) => setConvs((cs) => cs.some((c) => c.id === nid) ? cs.map((c) => (c.id === nid ? { ...c, title } : c)) : cs)}
          />
        </ChatErrorBoundary>
      </main>
    </div>
  );
}

function groupByDate(convs: any[], t: (k: string) => string): [string, any[]][] {
  const now = new Date();
  const day = (d: string) => Math.floor((now.getTime() - new Date(d).getTime()) / 86400000);
  const labels = [t("assistant.today"), t("assistant.yesterday"), t("assistant.thisWeek"), t("assistant.thisMonth"), t("assistant.older")];
  const g: Record<string, any[]> = {};
  for (const c of convs) {
    const n = day(c.updated_at);
    const k = n <= 0 ? labels[0] : n === 1 ? labels[1] : n < 7 ? labels[2] : n < 30 ? labels[3] : labels[4];
    (g[k] ||= []).push(c);
  }
  return labels.filter((k) => g[k]).map((k) => [k, g[k]]);
}
