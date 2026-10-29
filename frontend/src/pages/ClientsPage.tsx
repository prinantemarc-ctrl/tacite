import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Plus, Pencil, Trash2 } from "lucide-react";
import { listClients, createClient, updateClient, deleteClient } from "../api";
import { Card, Table, Badge, Button, IconButton, Modal, Field, Input, Select, Textarea, Loading, Empty, PageHeader, RiskBadge, Term } from "../components";
import { useI18n } from "../i18n/I18nProvider";

const CLIENT_TYPES = ["corporate", "government", "ngo", "political"] as const;
const TYPE_KEYS: Record<string, string> = {
  corporate: "typeCorporate",
  government: "typeGovernment",
  ngo: "typeNgo",
  political: "typePolitical",
};
const LEVEL_KEYS: Record<string, string> = { high: "levelHigh", medium: "levelMedium", low: "levelLow" };
const emptyClient = { name: "", sector: "", type: "corporate", exposure: "medium", risk_tolerance: "medium", budget_level: "medium", objectives: {}, narratives_push: [], narratives_counter: [], sensitive_topics: [] };

export default function ClientsPage() {
  const { t } = useI18n();
  const [clients, setClients] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [editItem, setEditItem] = useState<any>(null);
  const [form, setForm] = useState(emptyClient);
  const [pushText, setPushText] = useState("");
  const [counterText, setCounterText] = useState("");
  const [sensitiveText, setSensitiveText] = useState("");
  const navigate = useNavigate();

  const typeLabel = (type: string) => t(`clients.${TYPE_KEYS[type] || type}`);
  const levelLabel = (level: string) => {
    const key = LEVEL_KEYS[level];
    return key ? t(`clients.${key}`) : level;
  };

  const load = () => listClients().then(setClients).finally(() => setLoading(false));
  useEffect(() => { load(); }, []);

  const openCreate = () => { setEditItem(null); setForm(emptyClient); setPushText(""); setCounterText(""); setSensitiveText(""); setShowModal(true); };
  const openEdit = (c: any) => {
    setEditItem(c);
    setForm({ name: c.name, sector: c.sector || "", type: c.type, exposure: c.exposure, risk_tolerance: c.risk_tolerance, budget_level: c.budget_level, objectives: c.objectives || {}, narratives_push: c.narratives_push || [], narratives_counter: c.narratives_counter || [], sensitive_topics: c.sensitive_topics || [] });
    setPushText((c.narratives_push || []).join("\n"));
    setCounterText((c.narratives_counter || []).join("\n"));
    setSensitiveText((c.sensitive_topics || []).join("\n"));
    setShowModal(true);
  };
  const lines = (s: string) => s.split("\n").map((x) => x.trim()).filter(Boolean);
  const handleSave = async () => {
    const data = { ...form, narratives_push: lines(pushText), narratives_counter: lines(counterText), sensitive_topics: lines(sensitiveText) };
    if (editItem) await updateClient(editItem.id, data); else await createClient(data);
    setShowModal(false); load();
  };
  const handleDelete = async (id: number) => { if (confirm(t("clients.deleteConfirm"))) { await deleteClient(id); load(); } };

  if (loading) return <Loading />;

  return (
    <div>
      <PageHeader
        kicker={t("pages.clientsSub")}
        title={t("pages.clients")}
        subtitle={t("clients.activeCount", { n: clients.length, s: clients.length > 1 ? "s" : "" })}
        actions={<Button variant="primary" onClick={openCreate}><Plus size={13} /> {t("clients.newFile")}</Button>}
      />

      <Card>
        {clients.length === 0 ? <Empty>{t("clients.empty")}</Empty> : (
          <Table headers={[t("clients.colClient"), t("clients.sector"), t("clients.type"), <Term k="exposure">{t("clients.exposure")}</Term>, <Term k="risk">{t("clients.riskTolerance")}</Term>, t("clients.budget"), <Term k="narratives">{t("clients.narratives")}</Term>, ""]}>
            {clients.map((c) => (
              <tr key={c.id}>
                <td><button onClick={() => navigate(`/clients/${c.id}`)} className="text-left font-medium text-ink hover:text-accent-strong">{c.name}</button></td>
                <td className="text-muted">{c.sector || "—"}</td>
                <td><Badge>{TYPE_KEYS[c.type] ? typeLabel(c.type) : c.type}</Badge></td>
                <td className="text-muted">{levelLabel(c.exposure)}</td>
                <td><RiskBadge level={c.risk_tolerance} /></td>
                <td className="text-muted">{levelLabel(c.budget_level)}</td>
                <td className="num text-muted">{t("clients.narrativesCount", { n: c.narratives_push?.length || 0, m: c.narratives_counter?.length || 0 })}</td>
                <td className="whitespace-nowrap text-right">
                  <IconButton onClick={() => openEdit(c)} aria-label={t("common.edit")}><Pencil size={13} /></IconButton>
                  <IconButton danger onClick={() => handleDelete(c.id)} aria-label={t("common.delete")}><Trash2 size={13} /></IconButton>
                </td>
              </tr>
            ))}
          </Table>
        )}
      </Card>

      {showModal && (
        <Modal
          title={editItem ? t("clients.editFile") : t("clients.newClientFile")}
          width="max-w-2xl"
          onClose={() => setShowModal(false)}
          footer={<><Button variant="ghost" onClick={() => setShowModal(false)}>{t("common.cancel")}</Button><Button variant="primary" onClick={handleSave} disabled={!form.name}>{editItem ? t("common.save") : t("common.create")}</Button></>}
        >
          <div className="grid grid-cols-2 gap-3">
            <Field label={t("clients.name")}><Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} autoFocus /></Field>
            <Field label={t("clients.sector")}><Input value={form.sector} onChange={(e) => setForm({ ...form, sector: e.target.value })} placeholder={t("clients.sectorPh")} /></Field>
          </div>
          <div className="grid grid-cols-4 gap-3">
            <Field label={t("clients.type")}>
              <Select className="w-full" value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })}>
                {CLIENT_TYPES.map((k) => <option key={k} value={k}>{typeLabel(k)}</option>)}
              </Select>
            </Field>
            {(["exposure", "risk_tolerance", "budget_level"] as const).map((k) => (
              <Field key={k} label={k === "exposure" ? t("clients.exposure") : k === "risk_tolerance" ? t("clients.riskToleranceShort") : t("clients.budget")}>
                <Select className="w-full" value={(form as any)[k]} onChange={(e) => setForm({ ...form, [k]: e.target.value })}>
                  <option value="high">{t("clients.levelHigh")}</option><option value="medium">{t("clients.levelMedium")}</option><option value="low">{t("clients.levelLow")}</option>
                </Select>
              </Field>
            ))}
          </div>
          <Field label={t("clients.narrativesPush")} hint={t("clients.onePerLine")}><Textarea value={pushText} onChange={(e) => setPushText(e.target.value)} rows={3} placeholder={t("clients.pushPh")} /></Field>
          <Field label={t("clients.narrativesCounter")} hint={t("clients.onePerLine")}><Textarea value={counterText} onChange={(e) => setCounterText(e.target.value)} rows={3} placeholder={t("clients.counterPh")} /></Field>
          <Field label={t("clients.sensitiveTopics")} hint={t("clients.sensitiveHint")}><Textarea value={sensitiveText} onChange={(e) => setSensitiveText(e.target.value)} rows={2} /></Field>
        </Modal>
      )}
    </div>
  );
}
