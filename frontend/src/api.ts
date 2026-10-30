const BASE = "/api";

export function getToken(): string {
  try {
    return localStorage.getItem("tacite_token") || (import.meta as any).env?.VITE_TACITE_TOKEN || "";
  } catch {
    return (import.meta as any).env?.VITE_TACITE_TOKEN || "";
  }
}

export function setToken(t: string) {
  if (t) localStorage.setItem("tacite_token", t);
  else localStorage.removeItem("tacite_token");
}

function authHeaders(): Record<string, string> {
  const t = getToken();
  return t ? { Authorization: `Bearer ${t}` } : {};
}

function rejectIfUnauthorized(status: number, path: string) {
  if (status === 401 && !path.startsWith("/auth/")) {
    setToken("");
    if (!window.location.pathname.startsWith("/login")) window.location.assign("/login");
  }
}

function localeHeader(): Record<string, string> {
  try {
    const loc = localStorage.getItem("tacite-locale") || "fr";
    return { "Accept-Language": loc === "en" ? "en" : "fr" };
  } catch {
    return { "Accept-Language": "fr" };
  }
}

async function request<T>(path: string, opts?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...opts,
    headers: { "Content-Type": "application/json", ...authHeaders(), ...localeHeader(), ...(opts?.headers || {}) },
  });
  if (!res.ok) {
    rejectIfUnauthorized(res.status, path);
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`API ${res.status}: ${text}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

// Dashboard
export const getDashboard = (country?: string) => request<any>(`/dashboard${country ? `?country=${country}` : ""}`);

// Assistant
export const listConversations = () => request<any[]>("/agent/conversations");
export const createConversation = (data: { title?: string; context?: any } = {}) => request<any>("/agent/conversations", { method: "POST", body: JSON.stringify(data) });
export const getConversation = (id: number) => request<any>(`/agent/conversations/${id}`);
export const updateConversation = (id: number, data: { title?: string; context?: any }) => request<any>(`/agent/conversations/${id}`, { method: "PUT", body: JSON.stringify(data) });
export const deleteConversation = (id: number) => request<void>(`/agent/conversations/${id}`, { method: "DELETE" });
export const actOnAction = (id: number, verb: "apply" | "reject" | "undo") => request<any>(`/agent/actions/${id}/${verb}`, { method: "POST" });
export const listAgentActions = () => request<any[]>("/agent/actions");
export const listArtifacts = () => request<any[]>("/artifacts");
export const deleteArtifact = (id: number) => request<void>(`/artifacts/${id}`, { method: "DELETE" });
export const createReport = (data: { kind: string; target?: string; notes?: string; weeks?: number; country?: string }) => request<any>("/reports", { method: "POST", body: JSON.stringify(data) });
export const listReports = () => request<any[]>("/reports");
export const getReport = (id: number) => request<any>(`/reports/${id}`);
export const patchReport = (id: number, data: any) => request<any>(`/reports/${id}`, { method: "PATCH", body: JSON.stringify(data) });
export const deleteReport = (id: number) => request<void>(`/reports/${id}`, { method: "DELETE" });
export const exportReport = (id: number) => request<any>(`/reports/${id}/export`, { method: "POST" });
export async function uploadAttachment(file: File): Promise<{ name: string; chars: number; text: string }> {
  const fd = new FormData();
  fd.append("file", file);
  const res = await fetch(`${BASE}/agent/upload`, { method: "POST", body: fd, headers: { ...authHeaders(), ...localeHeader() } });
  if (!res.ok) {
    rejectIfUnauthorized(res.status, "/agent/upload");
    throw new Error(`API ${res.status}: ${await res.text()}`);
  }
  return res.json();
}
/** Flux SSE d'un tour de conversation. Appelle onEvent pour chaque événement ; résout à la fin. */
export async function streamMessage(cid: number, text: string, attachments: { name: string; text: string }[], onEvent: (e: any) => void, signal?: AbortSignal): Promise<void> {
  const res = await fetch(`${BASE}/agent/conversations/${cid}/messages`, {
    method: "POST", headers: { "Content-Type": "application/json", ...authHeaders(), ...localeHeader() }, body: JSON.stringify({ text, attachments }), signal,
  });
  if (!res.ok || !res.body) {
    rejectIfUnauthorized(res.status, "/agent/conversations");
    throw new Error(`API ${res.status}: ${await res.text().catch(() => res.statusText)}`);
  }
  const reader = res.body.getReader();
  const dec = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let idx: number;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const chunk = buf.slice(0, idx); buf = buf.slice(idx + 2);
      for (const line of chunk.split("\n")) {
        if (line.startsWith("data: ")) { try { onEvent(JSON.parse(line.slice(6))); } catch { /* ignore */ } }
      }
    }
  }
}

// Outlets
export const listOutlets = (view: "brief" | "full" = "full") =>
  request<any[]>(view === "brief" ? "/outlets?view=brief" : "/outlets");
export const getOutlet = (id: number) => request<any>(`/outlets/${id}`);
export const createOutlet = (data: any) => request<any>("/outlets", { method: "POST", body: JSON.stringify(data) });
export const updateOutlet = (id: number, data: any) => request<any>(`/outlets/${id}`, { method: "PUT", body: JSON.stringify(data) });
export const deleteOutlet = (id: number) => request<void>(`/outlets/${id}`, { method: "DELETE" });
export const getOutletProfiles = (id: number) => request<any[]>(`/outlets/${id}/profiles`);
export const getOutletArticles = (id: number) => request<any[]>(`/outlets/${id}/articles`);

// Journalists
export const listJournalists = () => request<any[]>("/journalists");
export const getJournalist = (id: number) => request<any>(`/journalists/${id}`);
export const createJournalist = (data: any) => request<any>("/journalists", { method: "POST", body: JSON.stringify(data) });
export const updateJournalist = (id: number, data: any) => request<any>(`/journalists/${id}`, { method: "PUT", body: JSON.stringify(data) });
export const deleteJournalist = (id: number) => request<void>(`/journalists/${id}`, { method: "DELETE" });
export const getJournalistProfiles = (id: number) => request<any[]>(`/journalists/${id}/profiles`);
export const getJournalistArticles = (id: number) => request<any[]>(`/journalists/${id}/articles`);

// Gestion des médias par pays
export const suggestOutlets = (code: string, force = false) => request<{ country: string; suggestions: any[] }>(`/countries/${code}/suggest-outlets${force ? "?force=true" : ""}`);
export const suggestOutletsCached = (code: string) => request<{ country: string; suggestions: any[] | null }>(`/countries/${code}/suggest-outlets?cached=true`);
export const resolveOutlet = (code: string, name: string) => request<any>(`/countries/${code}/resolve-outlet?name=${encodeURIComponent(name)}`, { method: "POST" });
export const reverifyOutlet = (code: string, item: any) => request<any>(`/countries/${code}/reverify-outlet`, { method: "POST", body: JSON.stringify({ name: item.name, website_url: item.website_url, language: item.language, type: item.type, declared_orientation: item.declared_orientation, audience: item.audience }) });
export const addOutletsBulk = (code: string, items: any[]) => request<any>(`/countries/${code}/outlets`, { method: "POST", body: JSON.stringify({ items }) });

// Contacts
export const getJournalistContacts = (jid: number) => request<any>(`/journalists/${jid}/contacts`);
export const addJournalistContact = (jid: number, data: { kind: string; value: string; note?: string }) => request<any[]>(`/journalists/${jid}/contacts`, { method: "POST", body: JSON.stringify(data) });
export const discoverJournalistContacts = (jid: number) => request<any>(`/journalists/${jid}/contacts/discover`, { method: "POST" });
export const setContactInvalid = (cid: number, invalid: boolean) => request<any>(`/contacts/${cid}?invalid=${invalid}`, { method: "PUT" });
export const deleteContact = (cid: number) => request<void>(`/contacts/${cid}`, { method: "DELETE" });
export const contactsStatus = () => request<any>("/maintenance/contacts");
export const runContactsDiscovery = (limit = 300) => request<any>(`/maintenance/contacts?limit=${limit}`, { method: "POST" });
export const runBylinesBackfill = () => request<any>("/maintenance/bylines", { method: "POST" });

// Articles
export const listArticles = (params?: string) => request<any[]>(`/articles${params ? `?${params}` : ""}`);
export const getArticle = (id: number) => request<any>(`/articles/${id}`);
export const searchArticles = (query: string) => request<any[]>("/articles/search", { method: "POST", body: JSON.stringify({ query }) });

// Clients
export const listClients = () => request<any[]>("/clients");
export const getClient = (id: number) => request<any>(`/clients/${id}`);
export const createClient = (data: any) => request<any>("/clients", { method: "POST", body: JSON.stringify(data) });
export const updateClient = (id: number, data: any) => request<any>(`/clients/${id}`, { method: "PUT", body: JSON.stringify(data) });
export const deleteClient = (id: number) => request<void>(`/clients/${id}`, { method: "DELETE" });
export const addContact = (cid: number, data: any) => request<any>(`/clients/${cid}/contacts`, { method: "POST", body: JSON.stringify(data) });
export const addBlacklist = (cid: number, data: any) => request<any>(`/clients/${cid}/blacklist`, { method: "POST", body: JSON.stringify(data) });

// Recommendations
export const getClientRecommendations = (cid: number, params?: string) =>
  request<any[]>(`/clients/${cid}/recommendations${params ? `?${params}` : ""}`);
export const updateRecommendation = (rid: number, data: any) =>
  request<any>(`/recommendations/${rid}`, { method: "PUT", body: JSON.stringify(data) });
export const recordOutcome = (rid: number, data: any) =>
  request<any>(`/recommendations/${rid}/outcome`, { method: "POST", body: JSON.stringify(data) });
export const getStrategicMap = (cid: number) => request<any[]>(`/clients/${cid}/strategic-map`);
export const getClientHistory = (cid: number) => request<any[]>(`/clients/${cid}/history`);

// Influence
export const getInfluenceRanking = () => request<any[]>("/influence-ranking");
export const getDoubleClassification = (outletId: number) => request<any>(`/double-classification/${outletId}`);

// Jobs
export const triggerIngestAll = () => request<any>("/ingest", { method: "POST" });
export const triggerAnalysis = () => request<any>("/analyze", { method: "POST" });
export const triggerJournalistProfiles = () => request<any>("/profiles/journalists", { method: "POST" });
export const triggerOutletProfiles = () => request<any>("/profiles/outlets", { method: "POST" });
export const countPolluted = () => request<{ count: number | null; recoverable: number | null; job: any }>("/maintenance/polluted");
export const requalifyPolluted = () => request<any>("/maintenance/requalify", { method: "POST" });
export const triggerRecommendations = (cid: number) => request<any>(`/recommendations/generate/${cid}`, { method: "POST" });

// Settings
export const getSettings = () => request<any>("/settings");
export const updateSettings = (values: any) => request<any>("/settings", { method: "PUT", body: JSON.stringify({ values }) });

// Cost
export const getCostStats = () => request<any>("/stats/cost");

// Constants
export const getConstants = () => request<any>("/constants");
export const listKits = () => request<any>("/kits");
export const kitForCountry = (code: string) => request<any>(`/kits/for-country/${code}`);
export const assignCountryKit = (code: string, kit_id: string) => request<any>(`/kits/assign/${code}`, { method: "POST", body: JSON.stringify({ kit_id }) });
export const createKit = (data: any) => request<any>("/kits", { method: "POST", body: JSON.stringify(data) });

// Countries (dataset monde : code, nom, région, centroïde, nb de médias)
export const listCountries = (all = false) => request<any[]>(`/countries${all ? "?all=true" : ""}`);
export const getPipelineHealth = () => request<any>("/pipeline/health");
export const ingestOutlet = (id: number) => request<any>(`/ingest/${id}`, { method: "POST" });

// Import CSV de médias
export async function importOutletsCSV(file: File) {
  const fd = new FormData();
  fd.append("file", file);
  const res = await fetch(`${BASE}/outlets/import`, { method: "POST", body: fd, headers: authHeaders() });
  if (!res.ok) {
    rejectIfUnauthorized(res.status, "/outlets/import");
    throw new Error(`API ${res.status}: ${await res.text()}`);
  }
  return res.json();
}

// Cartographie
export const getMapLandscape = (params?: string) => request<any>(`/map/landscape${params ? `?${params}` : ""}`);
export const getMapNetwork = () => request<any>("/map/network");
export const getMapWorld = () => request<any>("/map/world");
export const getMapCorpus = (limit = 1500) => request<any>(`/map/corpus?limit=${limit}`);
export const getMapLeadLag = (days = 30) => request<any>(`/map/leadlag?days=${days}`);
export const getMapDissidents = () => request<any>("/map/dissidents");
export const getMapPacks = (days = 60) => request<any>(`/map/packs?days=${days}`);
export const getMapEntities = (limit = 40) => request<any>(`/map/entities?limit=${limit}`);
export const getMapTopics = (params?: string) => request<any>(`/map/topics${params ? `?${params}` : ""}`);

// Journalists maintenance
export const cleanupJournalists = () => request<any>("/journalists/cleanup", { method: "POST" });
export const enrichJournalists = (limit = 50) => request<any>(`/journalists/enrich?limit=${limit}`, { method: "POST" });

export const login = (username: string, password: string) =>
  request<{ token: string; user: { id: number; username: string } }>("/auth/login", { method: "POST", body: JSON.stringify({ username, password }) });
export const register = (username: string, password: string) =>
  request<{ token: string; user: { id: number; username: string } }>("/auth/register", { method: "POST", body: JSON.stringify({ username, password }) });
export const me = () => request<{ id: number; username: string }>("/auth/me");
export const logout = () => request<{ ok: boolean }>("/auth/logout", { method: "POST" });
