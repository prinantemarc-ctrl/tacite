/** Filtres et appariement de la liste journalistes — beat, sujets, contact. */

export const BEATS = [
  "Politique", "Économie", "International", "Justice", "Société", "Écologie",
  "Santé", "Éducation", "Culture", "Médias", "Technologie", "Sciences",
  "Défense", "Religion", "Sport", "Régions", "Généraliste",
] as const;

const REACHABLE = new Set(["email", "x", "bluesky", "mastodon", "linkedin", "instagram", "threads", "facebook", "phone", "signal", "website", "other"]);
const STOP = new Set(["de", "du", "des", "le", "la", "les", "un", "une", "et", "ou", "sur", "pour", "dans", "par", "au", "aux", "en", "a", "d", "l", "the", "of", "avec"]);

const ALIAS_TO_BEAT: Record<string, string> = {
  tech: "Technologie", technologie: "Technologie", numerique: "Technologie", ia: "Technologie", digital: "Technologie",
  economie: "Économie", finance: "Économie", entreprises: "Économie", business: "Économie", bourse: "Économie", eco: "Économie",
  social: "Société", societe: "Société",
  environnement: "Écologie", ecologie: "Écologie", climat: "Écologie", energie: "Écologie", nucleaire: "Écologie",
  monde: "International", europe: "International", geopolitique: "International", diplomatie: "International",
  police: "Justice", securite: "Justice",
  renseignement: "Défense", armees: "Défense", defense: "Défense",
  science: "Sciences", sciences: "Sciences", espace: "Sciences",
  medias: "Médias", presse: "Médias", television: "Médias",
  education: "Éducation", enseignement: "Éducation",
  sante: "Santé", medecine: "Santé",
  culture: "Culture", cinema: "Culture", livres: "Culture", musique: "Culture", arts: "Culture",
  sport: "Sport", sports: "Sport", football: "Sport",
  religion: "Religion", laicite: "Religion",
  regions: "Régions", local: "Régions",
  politique: "Politique", elections: "Politique",
};

export function splitBio(bio?: string | null): { beat: string; text: string } {
  const m = (bio || "").match(/^\[([^\]]*)\]\s*/);
  return { beat: m ? m[1] : "", text: (bio || "").replace(/^\[[^\]]*\]\s*/, "") };
}

export function journalistBeat(j: { beat?: string | null; bio?: string | null }): string {
  return (j.beat || splitBio(j.bio).beat || "").trim();
}

export function fold(s: string): string {
  return (s || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
}

export function canonicalBeat(raw: string): string {
  const b = (raw || "").trim().replace(/^\[|\]$/g, "").trim();
  if (!b) return "";
  if ((BEATS as readonly string[]).includes(b)) return b;
  const f = fold(b);
  if (ALIAS_TO_BEAT[f]) return ALIAS_TO_BEAT[f];
  for (const x of BEATS) {
    if (fold(x) === f) return x;
  }
  for (const [k, v] of Object.entries(ALIAS_TO_BEAT)) {
    if (k.length >= 4 && f.includes(k)) return v;
  }
  return b;
}

export function journalistHasContact(j: { contacts?: { has_contact?: boolean; kinds?: string[] }; twitter_handle?: string | null; linkedin_url?: string | null }): boolean {
  if (j.contacts?.has_contact) return true;
  if ((j.contacts?.kinds || []).some((k) => REACHABLE.has(k))) return true;
  return Boolean((j.twitter_handle || "").trim() || (j.linkedin_url || "").trim());
}

export function themeLabels(j: { themes?: any[] }): { label: string; count: number }[] {
  return (j.themes || [])
    .map((t) => (typeof t === "string" ? { label: t, count: 0 } : { label: t?.label || "", count: t?.count || 0 }))
    .filter((t) => t.label);
}

export function journalistMatchesBeat(j: { beat?: string | null; bio?: string | null }, beatFilter: string): boolean {
  const c = canonicalBeat(journalistBeat(j));
  if (beatFilter === "_none") return !c;
  if (!beatFilter) return true;
  return c === canonicalBeat(beatFilter);
}

export function journalistMatchesTopic(j: { themes?: any[] }, topic: string): boolean {
  if (!topic) return true;
  const f = fold(topic);
  if (!f) return true;
  return themeLabels(j).some((t) => {
    const ft = fold(t.label);
    if (ft === f) return true;
    const tokens = ft.split(/[^a-z0-9]+/g).filter(Boolean);
    return tokens.includes(f);
  });
}

function searchTokens(q: string): string[] {
  return fold(q).split(/[^a-z0-9]+/g).filter((t) => t.length >= 2 && !STOP.has(t));
}

function tokenHits(haystack: string, tok: string): boolean {
  if (!haystack || !tok) return false;
  if (haystack.includes(tok)) return true;
  if (tok.length < 4) return false;
  return haystack.split(/[^a-z0-9]+/g).some((w) => w.length >= 4 && (w.startsWith(tok) || tok.startsWith(w)));
}

export function matchJournalist(j: any, q: string, outletName: string): { score: number; matchedThemes: string[] } {
  const query = q.trim();
  if (!query) return { score: 0, matchedThemes: [] };
  const name = fold(j.name);
  const outlet = fold(outletName || "");
  const beat = fold(journalistBeat(j));
  const bio = fold(splitBio(j.bio).text);
  const themes = themeLabels(j).map((t) => ({ ...t, f: fold(t.label) }));
  const full = fold(query);
  const toks = searchTokens(query);
  if (!toks.length) {
    return { score: name.includes(full) || outlet.includes(full) ? 10 : 0, matchedThemes: [] };
  }

  let score = 0;
  const matched: string[] = [];
  if (name.includes(full) || toks.every((t) => name.includes(t))) score += 50;
  if (outlet.includes(full)) score += 8;

  for (const tok of toks) {
    const variants = [...new Set([tok, ALIAS_TO_BEAT[tok] ? fold(ALIAS_TO_BEAT[tok]) : ""].filter(Boolean))];
    const hits = (h: string) => variants.some((v) => tokenHits(h, v));
    for (const t of themes) {
      if (hits(t.f)) {
        if (!matched.includes(t.label)) matched.push(t.label);
        score += 40 + Math.min(t.count, 15);
      }
    }
    if (hits(beat)) score += 22;
    if (hits(bio)) score += 10;
    if (hits(name) && !name.includes(full)) score += 12;
    if (hits(outlet)) score += 6;
  }
  return { score, matchedThemes: matched };
}
