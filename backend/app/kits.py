"""Référentiels politiques : couche structurelle (comparable) + kits régionaux.

Un média est scoré sur la couche A (toujours) et sur les axes du kit de son pays.
Sans kit assigné, seule la couche A est extraite. Les kits custom et le mapping
pays → kit vivent dans les settings (country_kits, axis_kits_custom).
"""

from __future__ import annotations

from typing import Any

# ───────────────────────────────────────────── primitives

def _ax(
    id: str,
    label_fr: str, label_en: str,
    neg_fr: str, pos_fr: str,
    neg_en: str, pos_en: str,
    hint_en: str = "",
) -> dict:
    return {
        "id": id,
        "label_fr": label_fr, "label_en": label_en,
        "neg_fr": neg_fr, "pos_fr": pos_fr,
        "neg_en": neg_en, "pos_en": pos_en,
        "hint_en": hint_en,
    }


STRUCTURAL_AXES: list[dict] = [
    _ax("loyalty", "Loyauté au pouvoir", "Loyalty to power",
        "critique / contestataire", "loyaliste / aligné",
        "critical of power", "loyalist / aligned",
        "How the article stands toward the ruling authority, not left vs right."),
    _ax("pluralism", "Pluralisme", "Pluralism",
        "voix unique, agenda officiel", "contradictoire, adversarial",
        "monophonic, official agenda", "adversarial, contested",
        "Does the article admit conflicting voices, or relay a single line?"),
    _ax("openness", "Ouverture", "Openness",
        "national-fermé", "cosmopolite / extraverti",
        "national-closed", "cosmopolitan / outward",
        "Inward national frame vs openness to the outside, foreigners, global flows."),
    _ax("economy", "Économie", "Economy",
        "libéral / marché", "interventionniste / État",
        "market-liberal", "interventionist / state",
        "Market allocation vs state direction, planning, subsidies."),
    _ax("order", "Ordre", "Order",
        "sécurité, stabilité", "droits, contestation",
        "security, stability", "rights, contestation",
        "Priority given to order and stability vs civil rights and protest."),
]

STRUCTURAL_IDS = [a["id"] for a in STRUCTURAL_AXES]

# Kit Europe : les 12 axes historiques, pour ne pas casser FR.
_EUROPE_AXES = [
    _ax("economy", "Économie", "Economy", "libéral", "interventionniste", "liberal", "interventionist"),
    _ax("society", "Société", "Society", "conservateur", "progressiste", "conservative", "progressive"),
    _ax("immigration", "Immigration", "Immigration", "restrictif", "accueillant", "restrictive", "welcoming"),
    _ax("europe", "Europe", "Europe", "souverainiste", "fédéraliste", "sovereigntist", "federalist"),
    _ax("ecology", "Écologie", "Environment", "éco-sceptique", "éco-militant", "eco-sceptical", "eco-militant"),
    _ax("security", "Sécurité", "Security", "sécuritaire", "libertés", "law-and-order", "civil liberties"),
    _ax("secularism", "Laïcité", "Secularism", "laïcité stricte", "laïcité ouverte", "strict secularism", "open secularism"),
    _ax("international", "International", "International", "atlantiste", "non-aligné", "atlanticist", "non-aligned"),
    _ax("institutions", "Institutions", "Institutions", "présidentiel", "parlementaire", "presidential", "parliamentary"),
    _ax("media", "Médias", "Media", "défiant envers les médias", "confiant envers les médias", "media-sceptic", "media-trusting"),
    _ax("justice", "Justice", "Justice", "ordre", "réforme judiciaire", "order", "judicial reform"),
    _ax("technology", "Technologie", "Technology", "technophile", "technocritique", "technophile", "techno-critical"),
]

BUILTIN_KITS: dict[str, dict] = {
    "europe_west": {
        "id": "europe_west", "builtin": True,
        "label_fr": "Europe de l'ouest", "label_en": "Western Europe",
        "prompt_en": (
            "This is a Western European public debate. Left/right, EU, secularism, "
            "immigration and the presidential/parliamentary split are meaningful. "
            "Score the local axes below; do not invent Gulf or Chinese cleavages."
        ),
        "countries": [
            "FR", "BE", "CH", "LU", "DE", "AT", "NL", "IT", "ES", "PT", "IE", "GR",
            "SE", "NO", "DK", "FI", "PL", "CZ", "HU", "SK", "SI", "HR", "RO", "BG",
            "EE", "LV", "LT", "MT", "CY", "GB", "IS",
        ],
        "axes": _EUROPE_AXES,
    },
    "gulf": {
        "id": "gulf", "builtin": True,
        "label_fr": "Golfe", "label_en": "Gulf",
        "prompt_en": (
            "This is a Gulf (GCC) media space. There is no Western left/right. "
            "Opposition parties barely exist. Score loyalty, Islam in public life, "
            "foreign alignment, national identity vs expatriate labor, public morals, "
            "and rent vs economic diversification. Do NOT score EU, laïcité, or "
            "conservative/progressive in the French sense."
        ),
        "countries": ["AE", "SA", "QA", "KW", "BH", "OM"],
        "axes": [
            _ax("islam_public", "Islam public", "Public Islam",
                "conservateur religieux", "moderniste",
                "religious-conservative", "modernist",
                "Role of Islam in law, schooling, gender visibility, public morals."),
            _ax("alignment", "Alignement", "Alignment",
                "axe iranien / résistance", "Occident / CCG",
                "Iran / resistance axis", "West / GCC",
                "Foreign alignment: Iran-centred resistance vs US/West/GCC camp."),
            _ax("nation_labor", "Nation / main-d'œuvre", "Nation / labor",
                "identité nationale, nationalisation de l'emploi", "cosmopolitisme de la main-d'œuvre",
                "national identity, workforce nationalisation", "cosmopolitan labor force",
                "Emiratisation/Saudisation vs reliance on a foreign workforce."),
            _ax("morals", "Mœurs publiques", "Public morals",
                "famille, genre, visibilité conservatrice", "libéralisation des mœurs",
                "family, gender, conservative visibility", "social liberalisation",
                "Public morality, gender mixing, entertainment, dress."),
            _ax("rent", "Rente / diversification", "Rent / diversification",
                "rente hydrocarbure, statu quo", "diversification, Vision, business",
                "hydrocarbon rent, status quo", "diversification, Vision, business",
                "Oil/gas rentier frame vs economic diversification and business reform."),
        ],
    },
    "china": {
        "id": "china", "builtin": True,
        "label_fr": "Chine", "label_en": "China",
        "prompt_en": (
            "This is a PRC media space. Party line, sovereignty (Taiwan, Xinjiang, Hong Kong, "
            "South China Sea), stability vs reform, US rivalry, social control, and growth vs "
            "environment are the real cleavages. Do NOT score Western left/right, EU, or laïcité."
        ),
        "countries": ["CN", "HK", "MO"],
        "axes": [
            _ax("party_line", "Ligne du Parti", "Party line",
                "marge éditoriale", "ligne officielle",
                "editorial margin", "official line",
                "Distance from the Party/state narrative."),
            _ax("sovereignty", "Souveraineté", "Sovereignty",
                "souple, ouverture", "Taiwan / Xinjiang / mer de Chine, intransigeant",
                "flexible, open", "Taiwan / Xinjiang / SCS, uncompromising",
                "Territorial integrity and nationalist sovereignty frames."),
            _ax("reform_stability", "Réforme / stabilité", "Reform / stability",
                "stabilité, contrôle", "réforme, assouplissement",
                "stability, control", "reform, easing",
                "Political/economic reform vs maintaining stability."),
            _ax("us_rivalry", "Rivalité EUA", "US rivalry",
                "accommodant", "confrontationnel",
                "accommodating", "confrontational",
                "Framing of the United States: engagement vs strategic rivalry."),
            _ax("social_control", "Contrôle social", "Social control",
                "ouverture, vie privée", "surveillance, discipline",
                "openness, privacy", "surveillance, discipline",
                "Social management, censorship, zero-COVID-style discipline vs easing."),
            _ax("growth_env", "Croissance / environnement", "Growth / environment",
                "croissance d'abord", "environnement, qualité de vie",
                "growth first", "environment, quality of life",
                "GDP/industrial growth vs pollution, climate, liveability."),
        ],
    },
    "usa": {
        "id": "usa", "builtin": True,
        "label_fr": "États-Unis", "label_en": "United States",
        "prompt_en": (
            "This is the US partisan and culture-war space. Score partisan lean, culture war, "
            "internationalism vs restraint, identity/race, and economic regulation. "
            "EU federalism and French laïcité are irrelevant."
        ),
        "countries": ["US"],
        "axes": [
            _ax("partisan", "Partisan", "Partisan",
                "républicain / conservateur", "démocrate / progressiste",
                "Republican / conservative", "Democrat / progressive"),
            _ax("culture_war", "Guerre culturelle", "Culture war",
                "traditionaliste", "woke / progressiste identitaire",
                "traditionalist", "woke / identitarian progressive"),
            _ax("intervention", "Internationalisme", "Internationalism",
                "restraint / isolationniste", "interventionniste / atlantiste",
                "restraint / isolationist", "interventionist / atlanticist"),
            _ax("identity", "Identité / race", "Identity / race",
                "color-blind, majority", "racial justice, DEI",
                "color-blind, majority", "racial justice, DEI"),
            _ax("regulation", "Régulation", "Regulation",
                "dérégulation, business", "État, filets sociaux",
                "deregulation, business", "state, social safety net"),
        ],
    },
    "russia": {
        "id": "russia", "builtin": True,
        "label_fr": "Russie", "label_en": "Russia",
        "prompt_en": "Russian media space: Kremlin line, the West as adversary, imperial/Soviet memory, Orthodox traditionalism. Not Western left/right.",
        "countries": ["RU", "BY"],
        "axes": [
            _ax("kremlin", "Ligne du Kremlin", "Kremlin line",
                "critique, indépendant", "aligné", "critical, independent", "aligned"),
            _ax("west", "Occident", "The West",
                "engagement", "hostilité, forteresse", "engagement", "hostility, fortress"),
            _ax("imperial", "Mémoire impériale", "Imperial memory",
                "post-impérial, repli", "grandeur, sphère d'influence", "post-imperial, retrenchment", "greatness, sphere of influence"),
            _ax("orthodox", "Orthodoxie / mœurs", "Orthodoxy / morals",
                "sécularisé, libéral", "traditionaliste orthodoxe", "secular, liberal", "Orthodox traditionalist"),
        ],
    },
    "maghreb": {
        "id": "maghreb", "builtin": True,
        "label_fr": "Maghreb", "label_en": "Maghreb",
        "prompt_en": "Maghreb public debate: Islam and the state, contestation vs order, relation to Europe/France, social liberalisation. Not EU federalism.",
        "countries": ["MA", "TN", "DZ", "LY", "MR"],
        "axes": [
            _ax("islam_state", "Islam et État", "Islam and the state",
                "sécularisant", "islam politique / conservateur",
                "secularising", "political Islam / conservative"),
            _ax("contestation", "Contestation", "Contestation",
                "ordre, régime", "hirak, rue, libertés",
                "order, regime", "hirak, street, liberties"),
            _ax("europe_tie", "Lien à l'Europe", "Tie to Europe",
                "souverainiste, anti-Françafrique", "partenariat, diaspora",
                "sovereigntist, anti-Françafrique", "partnership, diaspora"),
            _ax("social_lib", "Libéralisation sociale", "Social liberalisation",
                "conservateur, famille", "individualisation, genre",
                "conservative, family", "individualisation, gender"),
        ],
    },
    "india": {
        "id": "india", "builtin": True,
        "label_fr": "Inde", "label_en": "India",
        "prompt_en": "Indian media space: Hindutva vs secular republic, centre-state, economic reform, Pakistan/China. Not European left/right.",
        "countries": ["IN"],
        "axes": [
            _ax("hindutva", "Hindutva / république", "Hindutva / republic",
                "république laïque, pluraliste", "nationalisme hindou",
                "secular republic, pluralist", "Hindu nationalism"),
            _ax("centre_state", "Centre / États", "Centre / states",
                "fédéral, États", "centralisé", "federal, states", "centralised"),
            _ax("reform_in", "Réforme économique", "Economic reform",
                "licence raj, protection", "libéralisation, business",
                "licence raj, protection", "liberalisation, business"),
            _ax("neighbors", "Voisinage", "Neighborhood",
                "accommodant", "sécuritaire, Pakistan/Chine",
                "accommodating", "securitised, Pakistan/China"),
        ],
    },
    "israel": {
        "id": "israel", "builtin": True,
        "label_fr": "Israël", "label_en": "Israel",
        "prompt_en": "Israeli media space: security vs peace process, religion and state, judicial/democratic conflict, occupation. Not French laïcité as such.",
        "countries": ["IL"],
        "axes": [
            _ax("security_peace", "Sécurité / processus", "Security / process",
                "sécurité, annexion", "processus, deux États",
                "security, annexation", "process, two-state"),
            _ax("religion_state", "Religion et État", "Religion and state",
                "laïque, libéral", "national-religieux",
                "secular, liberal", "national-religious"),
            _ax("judiciary_il", "Justice / démocratie", "Judiciary / democracy",
                "réforme judiciaire, exécutif fort", "indépendance des juges",
                "judicial reform, strong executive", "judicial independence"),
        ],
    },
    "latam": {
        "id": "latam", "builtin": True,
        "label_fr": "Amérique latine", "label_en": "Latin America",
        "prompt_en": "Latin American space: left/right still exists but around Bolivarian vs liberal, church, US, security. Score those, not EU axes.",
        "countries": ["MX", "BR", "AR", "CL", "CO", "PE", "UY", "EC", "BO", "VE", "PY", "CR", "PA", "GT"],
        "axes": [
            _ax("bolivarian", "Gauche / libéral", "Left / liberal",
                "libéral, marché, anti-Bolivar", "gauche, Bolivar, État",
                "liberal, market, anti-Bolivarian", "left, Bolivarian, state"),
            _ax("church", "Église", "Church",
                "laïc, progressiste", "catholique conservateur",
                "secular, progressive", "conservative Catholic"),
            _ax("us_latam", "États-Unis", "United States",
                "souverainiste, anti-impérial", "aligné Washington",
                "sovereigntist, anti-imperial", "aligned with Washington"),
            _ax("crime", "Sécurité", "Security",
                "mano dura", "droits, causes sociales",
                "mano dura", "rights, social causes"),
        ],
    },
}

STRUCTURAL_ONLY_ID = "_structural"

FR_AXIS_ZONE = frozenset({"FR", "BE", "CH", "LU"})
FR_SPECIFIC_AXES = ("secularism", "institutions")

# Fallback: old 12-axis scores → structural keys when the new ones are missing.
STRUCTURAL_FALLBACK = {"order": "security"}

COUNTRY_KITS_KEY = "country_kits"
CUSTOM_KITS_KEY = "axis_kits_custom"


def _index_builtin_countries() -> dict[str, str]:
    out: dict[str, str] = {}
    for kid, kit in BUILTIN_KITS.items():
        for c in kit["countries"]:
            out[c] = kid
    return out


DEFAULT_COUNTRY_KIT = _index_builtin_countries()


def _all_axis_catalog() -> dict[str, dict]:
    cat = {a["id"]: a for a in STRUCTURAL_AXES}
    for kit in BUILTIN_KITS.values():
        for a in kit["axes"]:
            cat.setdefault(a["id"], a)
    return cat


AXIS_CATALOG = _all_axis_catalog()


def all_axis_ids() -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for a in list(STRUCTURAL_AXES) + list(AXIS_CATALOG.values()):
        i = a.get("id")
        if i and i not in seen:
            ids.append(i); seen.add(i)
    for kit in BUILTIN_KITS.values():
        for a in kit["axes"]:
            if a["id"] not in seen:
                ids.append(a["id"]); seen.add(a["id"])
    return ids


def axis_labels_for(locale: str) -> dict[str, str]:
    key = "label_en" if locale == "en" else "label_fr"
    return {i: AXIS_CATALOG[i][key] for i in AXIS_CATALOG}


def axis_poles_for(locale: str) -> dict[str, tuple[str, str]]:
    if locale == "en":
        return {i: (AXIS_CATALOG[i]["neg_en"], AXIS_CATALOG[i]["pos_en"]) for i in AXIS_CATALOG}
    return {i: (AXIS_CATALOG[i]["neg_fr"], AXIS_CATALOG[i]["pos_fr"]) for i in AXIS_CATALOG}


def _custom_kits(db) -> list[dict]:
    if db is None:
        return []
    from .settings_store import get_setting
    rows = get_setting(db, CUSTOM_KITS_KEY) or []
    if not isinstance(rows, list):
        return []
    for c in rows:
        for a in c.get("axes") or []:
            if a.get("id"):
                AXIS_CATALOG.setdefault(a["id"], a)
    return rows


def _country_overrides(db) -> dict[str, str]:
    if db is None:
        return {}
    from .settings_store import get_setting
    raw = get_setting(db, COUNTRY_KITS_KEY) or {}
    return {str(k).upper(): str(v) for k, v in raw.items()} if isinstance(raw, dict) else {}


def list_kits(db=None) -> list[dict]:
    rows = []
    for kit in BUILTIN_KITS.values():
        rows.append({**kit, "n_countries": len(kit["countries"])})
    for c in _custom_kits(db):
        rows.append({**c, "builtin": False, "n_countries": len(c.get("countries") or [])})
    rows.append({
        "id": STRUCTURAL_ONLY_ID, "builtin": True,
        "label_fr": "Couche structurelle seulement",
        "label_en": "Structural layer only",
        "prompt_en": "No local political space. Score only the five structural axes.",
        "countries": [], "axes": [], "n_countries": 0,
    })
    return rows


def get_kit(kit_id: str | None, db=None) -> dict | None:
    if not kit_id or kit_id == STRUCTURAL_ONLY_ID:
        return None
    if kit_id in BUILTIN_KITS:
        return BUILTIN_KITS[kit_id]
    for c in _custom_kits(db):
        if c.get("id") == kit_id:
            return c
    return None


def kit_id_for_country(code: str | None, db=None) -> str | None:
    c = (code or "").upper()
    if not c:
        return None
    ov = _country_overrides(db)
    if c in ov:
        return ov[c] or None
    return DEFAULT_COUNTRY_KIT.get(c)


def kit_for_country(code: str | None, db=None) -> dict | None:
    return get_kit(kit_id_for_country(code, db), db)


def axes_for_country(code: str | None, db=None) -> list[str]:
    """Axes locaux affichés (radar, écarts). Pas la couche A, sauf si aucun kit."""
    kit = kit_for_country(code, db)
    if kit is None:
        return list(STRUCTURAL_IDS)
    ids = [a["id"] for a in (kit.get("axes") or [])]
    if (kit.get("id") == "europe_west") and (code or "").upper() not in FR_AXIS_ZONE:
        ids = [a for a in ids if a not in FR_SPECIFIC_AXES]
    return ids or list(STRUCTURAL_IDS)


def extract_axes_for_country(code: str | None, db=None) -> list[dict]:
    """Axes à faire scorer au LLM : couche A ∪ kit local, sans doublon."""
    seen: set[str] = set()
    out: list[dict] = []
    for a in STRUCTURAL_AXES:
        if a["id"] not in seen:
            out.append(a); seen.add(a["id"])
    kit = kit_for_country(code, db)
    if kit:
        for a in kit.get("axes") or []:
            if a["id"] not in seen:
                out.append(a); seen.add(a["id"])
    return out


def serialize_kit(kit: dict | None, locale: str = "fr") -> dict | None:
    if kit is None:
        return {
            "id": STRUCTURAL_ONLY_ID,
            "label": "Structural layer only" if locale == "en" else "Couche structurelle seulement",
            "builtin": True,
            "axes": [_public_axis(a, locale) for a in STRUCTURAL_AXES],
        }
    loc_label = kit.get("label_en") if locale == "en" else kit.get("label_fr")
    return {
        "id": kit["id"],
        "label": loc_label or kit.get("label_en") or kit["id"],
        "builtin": bool(kit.get("builtin")),
        "prompt": kit.get("prompt_en") or "",
        "countries": list(kit.get("countries") or []),
        "axes": [_public_axis(a, locale) for a in (kit.get("axes") or [])],
    }


def _public_axis(a: dict, locale: str) -> dict:
    if locale == "en":
        return {"id": a["id"], "label": a.get("label_en") or a["id"], "neg": a.get("neg_en") or "−", "pos": a.get("pos_en") or "+"}
    return {"id": a["id"], "label": a.get("label_fr") or a["id"], "neg": a.get("neg_fr") or "−", "pos": a.get("pos_fr") or "+"}


def public_axis_meta(axis_id: str, locale: str = "fr") -> dict:
    a = AXIS_CATALOG.get(axis_id)
    if not a:
        return {"id": axis_id, "label": axis_id, "neg": "−", "pos": "+"}
    return _public_axis(a, locale)


def assign_country_kit(db, code: str, kit_id: str | None) -> dict:
    from .settings_store import get_setting, set_setting
    code = code.upper()
    mapping = dict(_country_overrides(db))
    if not kit_id:
        mapping.pop(code, None)
    else:
        if kit_id != STRUCTURAL_ONLY_ID and get_kit(kit_id, db) is None and kit_id not in BUILTIN_KITS:
            raise ValueError(f"unknown kit: {kit_id}")
        mapping[code] = kit_id
        kit = get_kit(kit_id, db)
        if kit and not kit.get("builtin"):
            countries = list(kit.get("countries") or [])
            if code not in countries:
                countries.append(code)
                customs = _custom_kits(db)
                for c in customs:
                    if c.get("id") == kit_id:
                        c["countries"] = countries
                set_setting(db, CUSTOM_KITS_KEY, customs)
    set_setting(db, COUNTRY_KITS_KEY, mapping)
    return {"country": code, "kit_id": mapping.get(code) or STRUCTURAL_ONLY_ID}


def create_custom_kit(db, data: dict) -> dict:
    from .settings_store import set_setting
    import re
    slug = re.sub(r"[^a-z0-9_]+", "_", (data.get("id") or data.get("label_en") or "kit").lower()).strip("_")[:40]
    if not slug:
        slug = "kit"
    if slug in BUILTIN_KITS or slug == STRUCTURAL_ONLY_ID:
        raise ValueError("id reserved")
    existing = _custom_kits(db)
    if any(c.get("id") == slug for c in existing):
        slug = f"{slug}_{len(existing)+1}"
    axes_in = data.get("axes") or []
    axes = []
    for a in axes_in:
        aid = re.sub(r"[^a-z0-9_]+", "_", str(a.get("id") or a.get("label_en") or "axis").lower()).strip("_")[:32]
        if not aid:
            continue
        axes.append(_ax(
            aid,
            a.get("label_fr") or a.get("label_en") or aid,
            a.get("label_en") or a.get("label_fr") or aid,
            a.get("neg_fr") or a.get("neg_en") or "−",
            a.get("pos_fr") or a.get("pos_en") or "+",
            a.get("neg_en") or a.get("neg_fr") or "−",
            a.get("pos_en") or a.get("pos_fr") or "+",
            a.get("hint_en") or "",
        ))
    if not axes:
        raise ValueError("kit needs at least one axis")
    kit = {
        "id": slug,
        "builtin": False,
        "label_fr": data.get("label_fr") or data.get("label_en") or slug,
        "label_en": data.get("label_en") or data.get("label_fr") or slug,
        "prompt_en": data.get("prompt_en") or data.get("prompt") or "",
        "countries": [str(c).upper() for c in (data.get("countries") or []) if c],
        "axes": axes,
    }
    existing.append(kit)
    set_setting(db, CUSTOM_KITS_KEY, existing)
    AXIS_CATALOG.update({a["id"]: a for a in axes})
    return kit


def framing_value(fr: dict | None, axis: str) -> float:
    """Lit un axe, avec repli des anciens noms (security → order)."""
    if not fr:
        return 0.0
    v = fr.get(axis)
    if v:
        return float(v)
    alias = STRUCTURAL_FALLBACK.get(axis)
    if alias:
        return float(fr.get(alias) or 0)
    return 0.0
