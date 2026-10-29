import { canonicalBeat, journalistHasContact, journalistMatchesBeat, journalistMatchesTopic, matchJournalist } from "./journalistFilters";

function assert(cond: boolean, msg: string) {
  if (!cond) throw new Error(msg);
}

assert(canonicalBeat("Tech") === "Technologie", "Tech → Technologie");
assert(canonicalBeat("politique") === "Politique", "politique → Politique");
assert(canonicalBeat("") === "", "vide");
assert(journalistMatchesBeat({ beat: "Tech" }, "Technologie"), "filtre Technologie inclut Tech");
assert(journalistMatchesBeat({ beat: null, bio: "[Politique] bio" }, "Politique"), "beat dans la bio");
assert(journalistMatchesBeat({ beat: "" }, "_none"), "sans beat");
assert(!journalistMatchesBeat({ beat: "Économie" }, "_none"), "éco n'est pas sans beat");
assert(journalistMatchesTopic({ themes: [{ label: "Analyse économique", count: 3 }] }, "Économie") === false, "sujet : libellé distinct");
assert(journalistMatchesTopic({ themes: [{ label: "Gaza", count: 1 }, { label: "Économie", count: 2 }] }, "Économie"), "sujet exact dans la liste");
assert(journalistMatchesTopic({ themes: [{ label: "Gaza", count: 1 }] }, "Gaza"), "sujet exact");
assert(!journalistMatchesTopic({ themes: [{ label: "Sport", count: 1 }] }, "Économie"), "hors sujet");
assert(!journalistHasContact({ contacts: { kinds: ["author_page"], has_contact: false } }), "page auteur ≠ contact");
assert(journalistHasContact({ twitter_handle: "@dupont" }), "twitter = contact");
assert(matchJournalist({ name: "Marie Dupont", beat: "Politique", themes: [{ label: "Retraites", count: 4 }], bio: "" }, "retraites", "Le Monde").score > 0, "recherche sujet");
assert(matchJournalist({ name: "Marie Dupont", beat: "Politique", themes: [], bio: "" }, "Dupont", "Le Monde").score >= 50, "recherche nom");

console.log("journalistFilters ok");
