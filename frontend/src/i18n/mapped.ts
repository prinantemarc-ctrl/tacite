/** Mapped stored labels (outlet type, audience, declared line, sources…) follow UI locale. */

type TFn = (key: string, vars?: Record<string, string | number>) => string;

function fold(s: string): string {
  return s.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase().replace(/œ/g, "oe").replace(/\s+/g, " ").trim();
}

function catalog(raw: string, alias: Record<string, string>, prefix: string, t: TFn): string {
  const key = alias[fold(raw)];
  if (!key) return raw;
  const v = t(`${prefix}.${key}`);
  return v === `${prefix}.${key}` ? raw : v;
}

const KIND_ALIAS: Record<string, string> = {
  quotidien: "quotidien", daily: "quotidien", "daily newspaper": "quotidien",
  "presse quotidienne": "quotidien", newspaper: "quotidien", journal: "quotidien",
  hebdomadaire: "hebdomadaire", weekly: "hebdomadaire", weeklies: "hebdomadaire",
  mensuel: "mensuel", monthly: "mensuel",
  television: "television", tv: "television", "tv channel": "television",
  chaine: "television", "chaine tv": "television", broadcaster: "television",
  "news channel": "television",
  radio: "radio",
  "pure player": "purePlayer", pureplayer: "purePlayer", "digital native": "purePlayer",
  "pure-player": "purePlayer", online: "purePlayer",
  agence: "agence", agency: "agence", "news agency": "agence", "wire service": "agence",
  magazine: "magazine",
};

const AUD_ALIAS: Record<string, "high" | "medium" | "low"> = {
  high: "high", eleve: "high", elevee: "high", fort: "high", forte: "high",
  large: "high", grande: "high", mass: "high",
  medium: "medium", moyen: "medium", moyenne: "medium", moderate: "medium", moderee: "medium",
  low: "low", faible: "low", bas: "low", basse: "low", small: "low",
};

const ORIENT_ALIAS: Record<string, string> = {
  "centre-droit": "centreRight", "centre droit": "centreRight",
  "center-right": "centreRight", "center right": "centreRight", "centre-right": "centreRight",
  "centre-gauche": "centreLeft", "centre gauche": "centreLeft",
  "center-left": "centreLeft", "center left": "centreLeft", "centre-left": "centreLeft",
  centriste: "centrist", centre: "centrist", center: "centrist",
  droite: "right", right: "right", gauche: "left", left: "left",
  "extreme droite": "farRight", "extreme-droite": "farRight",
  "far right": "farRight", "far-right": "farRight",
  "extreme gauche": "farLeft", "extreme-gauche": "farLeft",
  "far left": "farLeft", "far-left": "farLeft",
  nationaliste: "nationalist", nationalist: "nationalist",
  conservateur: "conservative", conservatrice: "conservative", conservative: "conservative",
  liberal: "liberal", liberale: "liberal",
  progressiste: "progressive", progressive: "progressive",
  "pro-gouvernemental": "proGovernment", "pro-gouvernementale": "proGovernment",
  "pro gouvernemental": "proGovernment", gouvernemental: "proGovernment",
  "pro-government": "proGovernment", "pro government": "proGovernment",
  "proche du pouvoir": "proGovernment",
  independant: "independent", independante: "independent", independent: "independent",
  souverainiste: "sovereigntist", sovereigntist: "sovereigntist",
  populiste: "populist", populist: "populist",
  etatiste: "statist", statist: "statist",
  laic: "secular", laique: "secular", secular: "secular",
  republicain: "republican", republicaine: "republican", republican: "republican",
  "social-democrate": "socialDemocrat", "social democrate": "socialDemocrat",
  "social-democrat": "socialDemocrat", "social democrat": "socialDemocrat",
  socialiste: "socialist", socialist: "socialist",
  communiste: "communist", communist: "communist",
  ecologiste: "green", vert: "green", verte: "green", green: "green",
  islamiste: "islamist", islamist: "islamist",
  royaliste: "royalist", royalist: "royalist",
  atlantiste: "atlanticist", atlanticist: "atlanticist",
  eurosceptique: "eurosceptic", eurosceptic: "eurosceptic",
  "pro-europeen": "proEuropean", "pro-europeenne": "proEuropean", "pro-european": "proEuropean",
  generaliste: "generalist", generalist: "generalist",
  tabloid: "tabloid", people: "tabloid",
  "service public": "publicService", "public service": "publicService", "public-service": "publicService",
  officiel: "official", official: "official",
};

const SRC_ALIAS: Record<string, string> = {
  government: "government", gouvernement: "government", officiel: "government", official: "government",
  anonymous: "anonymous", anonyme: "anonymous",
  expert: "expert",
  ngo: "ngo", ong: "ngo",
  corporate: "corporate", entreprise: "corporate", prive: "corporate",
  judicial: "judicial", judiciaire: "judicial",
  union: "union", syndicat: "union", syndicale: "union",
  political_party: "political_party", "political party": "political_party", parti: "political_party",
  citizen: "citizen", citoyen: "citizen", citoyenne: "citizen",
  media: "media", medias: "media", presse: "media",
  other: "other", autre: "other",
};

const ANGLE_ALIAS: Record<string, string> = {
  investigation: "investigation", enquete: "investigation",
  editorial: "editorial", editorialiste: "editorial", edito: "editorial",
  brief: "brief", breve: "brief", depêche: "brief", depeche: "brief",
  analysis: "analysis", analyse: "analysis",
  opinion: "opinion", tribune: "opinion",
  reaction: "reaction",
};

const EMO_ALIAS: Record<string, string> = {
  neutral: "neutral", neutre: "neutral",
  anger: "anger", colere: "anger",
  fear: "fear", peur: "fear", inquietude: "fear",
  hope: "hope", espoir: "hope",
  indignation: "indignation",
  irony: "irony", ironie: "irony",
  outrage: "outrage",
};

export function outletTypeLabel(raw: string | undefined, t: TFn): string {
  if (!raw) return "";
  return catalog(raw, KIND_ALIAS, "kind", t);
}

export function audienceLabel(raw: string | undefined, t: TFn): string {
  if (!raw) return "";
  const lvl = AUD_ALIAS[fold(raw)];
  if (!lvl) return raw;
  const k = lvl === "high" ? "country.audHigh" : lvl === "medium" ? "country.audMid" : "country.audLow";
  return t(k);
}

export function orientationLabel(raw: string | undefined, t: TFn): string {
  if (!raw) return "";
  return raw.split(/[,;/|]+/).map((part) => {
    const token = part.trim();
    if (!token) return token;
    return catalog(token, ORIENT_ALIAS, "orient", t);
  }).filter(Boolean).join(", ");
}

export function sourceTypeLabel(raw: string | undefined, t: TFn): string {
  if (!raw) return "";
  return catalog(raw, SRC_ALIAS, "srcType", t);
}

export function angleLabel(raw: string | undefined, t: TFn): string {
  if (!raw) return "";
  return catalog(raw, ANGLE_ALIAS, "angle", t);
}

export function toneWordLabel(raw: string | undefined, t: TFn): string {
  if (!raw) return "";
  return catalog(raw, EMO_ALIAS, "emo", t);
}

export function confidenceLabel(raw: string | undefined, t: TFn): string {
  if (!raw) return "";
  const k = fold(raw);
  if (k === "elevee" || k === "high") return t("confidence.high");
  if (k === "moyenne" || k === "medium") return t("confidence.medium");
  if (k === "faible" || k === "low") return t("confidence.low");
  return raw;
}

export function confidenceTone(raw: string | undefined): "accent" | "default" | "faint" {
  const k = fold(raw || "");
  if (k === "elevee" || k === "high") return "accent";
  if (k === "moyenne" || k === "medium") return "default";
  return "faint";
}

export function beatLabel(raw: string | undefined, t: TFn): string {
  if (!raw) return "";
  const v = t(`beat.${raw}`);
  return v === `beat.${raw}` ? raw : v;
}

export function suggestReasonLabel(raw: string | undefined, t: TFn): string {
  if (!raw) return "";
  const k = fold(raw);
  const http = raw.match(/HTTP\s+(\d+)/i)?.[1] || "";
  if (k.includes("page d'accueil bloquee") || k.includes("homepage blocked")) return t("country.reasonHomeBlocked");
  if (k.includes("bloque les robots") || k.includes("blocks robots")) return t("country.reasonRobot", { code: http });
  if (k.includes("page introuvable") || k.includes("http 404")) return t("country.reasonNotFound");
  if (k.includes("erreur du serveur") || k.includes("server error")) return t("country.reasonServer", { code: http });
  if (k.includes("reponse inattendue") || k.includes("unexpected response")) return t("country.reasonHttp", { code: http });
  if (k.includes("ne renvoie pas une page") || k.includes("not a web page")) return t("country.reasonNotHtml");
  if (k.includes("pas de reponse") || k.includes("no response") || k.includes("timeout")) {
    const sec = raw.match(/(\d+)\s*s(?:\b|$)/i)?.[1] || "";
    return t("country.reasonTimeout", { n: sec });
  }
  if (k.includes("domaine introuvable") || k.includes("domain not found")) return t("country.reasonDns");
  if (k.includes("certificat") || k.includes("certificate")) return t("country.reasonTls");
  if (k.includes("connexion refusee") || k.includes("connection refused")) return t("country.reasonConnect");
  if (k.includes("reponse du modele") || k.includes("unreadable")) return t("country.reasonLlm");
  if (k.includes("erreur inattendue") || k.includes("unexpected error")) return t("country.reasonOther");
  return raw;
}
