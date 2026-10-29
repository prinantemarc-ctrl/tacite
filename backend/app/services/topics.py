"""Agenda des sujets — clustering sémantique des articles.

Un cluster = une affaire, même si les libellés LLM diffèrent (« réforme des retraites »,
« âge légal », « pensions »). On réutilise les embeddings déjà calculés à l'analyse ;
aucune nouvelle vectorisation.

Les résultats sont mis en cache en mémoire (CACHE_TTL), comme la cartographie.
"""

from __future__ import annotations

import logging
import re
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from inspect import signature

import numpy as np
from sqlalchemy import exists, or_
from sqlalchemy.orm import Session

from ..constants import TONE_VALENCE
from ..i18n import axis_label, axis_poles, get_locale
from ..kits import STRUCTURAL_IDS, axes_for_country
from ..models import Article, ArticleJournalist, Journalist, Outlet
from . import cartography as C

log = logging.getLogger("tacite.topics")


def _call_carto(fn, *args):
    """Les helpers carto ont gagné un argument `axes` ; l'image live peut encore être à l'ancienne."""
    n = len(signature(fn).parameters)
    return fn(*args[:n])

CACHE_TTL = 600
SIM_THRESHOLD = 0.80  # affaire : liaison complète (contrat tests unitaires)
AGENDA_SIM_THRESHOLD = 0.64  # seuil effectif d'agenda pour regrouper les articles d'une même actualité
GENERIC_ENTS = {
    "france", "french", "italia", "italy", "europe", "european", "union",
    "government", "gouvernement", "etat", "state", "commission", "ue", "eu",
    "parlement", "parliament", "media", "press",
}
WEAK_TOKS = {
    "relation", "relations", "relationship", "news", "policy", "issue", "update",
    "deal", "accord", "crisis", "crise", "actualite", "actualites", "dossier",
    "question", "affaire", "sujet", "topic", "story", "report",
    "political", "politics", "politique", "landscape", "challenge", "challenges",
    "future", "impact", "situation", "debate", "controversies",
    "results", "result", "implications", "success", "rise",
}
THEME_THRESHOLD = 0.55  # famille de sujets (contrat tests unitaires)
AGENDA_THEME_THRESHOLD = 0.72  # seuil effectif de famille pour éviter de fusionner des affaires sans rapport
MAX_THEMES = 16
SEARCH_THRESHOLD = 0.42  # barre de recherche : centroïde ou recouvrement lexical
SEARCH_CAP = 24
MIN_CLUSTER = 2
MAX_ARTICLES = 2000
MAX_DAYS = 90
MEMBERS_CAP = 40
_MONTHS_FR = (
    "janv.", "févr.", "mars", "avr.", "mai", "juin",
    "juil.", "août", "sept.", "oct.", "nov.", "déc.",
)
_MONTHS_EN = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)

_TOKEN_RE = re.compile(r"[a-z0-9]{3,}")
_SPELL = {
    "kanada": "canada", "canadas": "canada",
    "usa": "united", "us": "united",
    "uk": "britain", "britain": "britain", "british": "britain",
    "relations": "relation", "relationship": "relation",
    "prices": "price", "pricing": "price",
}

JUNK_LABELS = {
    "boilerplate", "non political", "non-political", "non politique",
    "hors champ", "sports match", "celebrity news",
}

_cache: dict[str, tuple[float, object]] = {}


def _cached(key: str, fn):
    key = f"{get_locale()}:{key}"
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < CACHE_TTL:
        return hit[1]
    val = fn()
    _cache[key] = (now, val)
    return val


def invalidate():
    _cache.clear()


# ───────────────────────────────────────────────────────────── clustering


def cluster_embeddings(emb: np.ndarray, threshold: float = SIM_THRESHOLD, method: str = "complete") -> np.ndarray:
    """Regroupement hiérarchique sur la distance cosinus. Labels 0-indexés."""
    n = len(emb)
    if n == 0:
        return np.array([], dtype=int)
    if n == 1:
        return np.array([0], dtype=int)
    norms = np.linalg.norm(emb, axis=1, keepdims=True)
    x = emb / np.maximum(norms, 1e-9)
    from scipy.cluster.hierarchy import fcluster, linkage
    from scipy.spatial.distance import pdist

    d = np.clip(pdist(x, metric="cosine"), 0, 2)
    if float(d.max()) < 1e-9:
        return np.zeros(n, dtype=int)
    z = linkage(d, method=method)
    return fcluster(z, t=max(1.0 - threshold, 1e-6), criterion="distance") - 1


def _pad3(m: np.ndarray) -> np.ndarray:
    if m.ndim == 1:
        m = m.reshape(-1, 1)
    if m.shape[1] < 3:
        m = np.pad(m, ((0, 0), (0, 3 - m.shape[1])))
    return m.astype(float)


def _repel(points: np.ndarray, min_dist: float = 0.28, iters: int = 50) -> np.ndarray:
    """Écarte les centres de clusters trop proches pour qu'on lise des grappes distinctes."""
    p = points.copy()
    n = len(p)
    if n < 2:
        return p
    for _ in range(iters):
        moved = False
        for a in range(n):
            for b in range(a + 1, n):
                d = p[a] - p[b]
                dist = float(np.linalg.norm(d))
                if dist < 1e-9:
                    p[a, 0] += min_dist * 0.5
                    moved = True
                    continue
                if dist < min_dist:
                    push = ((min_dist - dist) * 0.5 / dist) * d
                    p[a] += push
                    p[b] -= push
                    moved = True
        if not moved:
            break
    return p


def _mst(idxs: list[int], emb_n: np.ndarray) -> list[tuple[int, int, float]]:
    """Arbre couvrant min. sur 1 − cosinus. Au plus n−1 arêtes."""
    if len(idxs) < 2:
        return []
    pairs = []
    for a in range(len(idxs)):
        ia = idxs[a]
        for b in range(a + 1, len(idxs)):
            ib = idxs[b]
            sim = float(np.clip(emb_n[ia] @ emb_n[ib], 0.0, 1.0))
            pairs.append((1.0 - sim, ia, ib, sim))
    pairs.sort()
    parent = {i: i for i in idxs}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    out = []
    for _, a, b, sim in pairs:
        pa, pb = find(a), find(b)
        if pa == pb:
            continue
        parent[pa] = pb
        out.append((a, b, sim))
        if len(out) >= len(idxs) - 1:
            break
    return out


def _closest_pair(a_idxs: list[int], b_idxs: list[int], emb_n: np.ndarray) -> tuple[int, int, float] | None:
    best: tuple[int, int, float] | None = None
    best_sim = -1.0
    for ia in a_idxs:
        va = emb_n[ia]
        for ib in b_idxs:
            sim = float(np.clip(va @ emb_n[ib], 0.0, 1.0))
            if sim > best_sim:
                best_sim = sim
                best = (ia, ib, sim)
    return best


def layout_xyz(
    emb: np.ndarray,
    labels: np.ndarray,
    min_articles: int = MIN_CLUSTER,
    theme_of: dict[int, int] | None = None,
) -> tuple[np.ndarray, dict[int, np.ndarray], np.ndarray, dict[int, np.ndarray]]:
    """Hiérarchie 3D : familles (gros clusters) → affaires (sous-clusters) → articles.

    Retourne xyz, centres d'affaires, centralité, centres de familles.
    """
    n = len(emb)
    xyz = np.zeros((n, 3))
    centrality = np.zeros(n)
    groups: dict[int, list[int]] = defaultdict(list)
    for i, lab in enumerate(labels):
        groups[int(lab)].append(i)
    clustered = [cid for cid, idxs in groups.items() if len(idxs) >= min_articles]
    singletons = [i for cid, idxs in groups.items() if len(idxs) < min_articles for i in idxs]
    if theme_of is None:
        theme_of = {cid: cid for cid in clustered}

    stories_by_theme: dict[int, list[int]] = defaultdict(list)
    for cid in clustered:
        stories_by_theme[theme_of.get(cid, cid)].append(cid)

    story_cent = {cid: emb[groups[cid]].mean(axis=0) for cid in clustered}
    theme_cent_emb = {}
    for tid, cids in stories_by_theme.items():
        theme_cent_emb[tid] = np.mean([story_cent[c] for c in cids], axis=0)

    tids = list(stories_by_theme.keys())
    if len(tids) >= 2:
        tm = np.stack([theme_cent_emb[t] for t in tids])
        tfun, _, _ = C._pca(tm, n_components=min(3, len(tids)))
        txyz = _pad3(tfun(tm))
        txyz = txyz / (float(np.abs(txyz).max()) or 1.0) * 1.05
        min_dist = max(0.42, min(0.82, 2.4 / max(2.0, len(tids) ** (1 / 3))))
        txyz = _repel(txyz, min_dist=min_dist, iters=80)
        rad = float(np.linalg.norm(txyz, axis=1).max()) or 1.0
        txyz = txyz * (1.12 / rad)
        theme_centers = {tids[i]: txyz[i] for i in range(len(tids))}
    elif len(tids) == 1:
        theme_centers = {tids[0]: np.zeros(3)}
    else:
        theme_centers = {}

    story_centers: dict[int, np.ndarray] = {}
    rng = np.random.default_rng(11)
    for tid, cids in stories_by_theme.items():
        origin = theme_centers[tid]
        if len(cids) == 1:
            story_centers[cids[0]] = origin.copy()
            continue
        sm = np.stack([story_cent[c] for c in cids])
        tfun, _, _ = C._pca(sm, n_components=min(3, len(cids)))
        local = _pad3(tfun(sm))
        local = local / (float(np.abs(local).max()) or 1.0)
        radius = 0.12 + 0.035 * np.log1p(len(cids))
        local = _repel(local * radius, min_dist=0.08, iters=30)
        for j, cid in enumerate(cids):
            story_centers[cid] = origin + local[j]

    emb_n = emb / np.maximum(np.linalg.norm(emb, axis=1, keepdims=True), 1e-9)
    for cid in clustered:
        idxs = groups[cid]
        cemb = story_cent[cid]
        cn = cemb / max(float(np.linalg.norm(cemb)), 1e-9)
        sims = emb_n[idxs] @ cn
        residuals = emb[idxs] - cemb
        if len(idxs) >= 4:
            tfun, _, _ = C._pca(residuals, n_components=3)
            local = _pad3(tfun(residuals))
            local = local / (float(np.abs(local).max()) or 1.0)
        else:
            local = rng.normal(size=(len(idxs), 3))
            local = local / np.maximum(np.linalg.norm(local, axis=1, keepdims=True), 1e-9)
        r_max = 0.048 + 0.016 * np.log1p(len(idxs))
        for j, i in enumerate(idxs):
            sim = float(np.clip(sims[j], 0.0, 1.0))
            centrality[i] = sim
            direction = local[j]
            dn = float(np.linalg.norm(direction)) or 1.0
            xyz[i] = story_centers[cid] + (direction / dn) * (r_max * (0.15 + 0.85 * (1.0 - sim)))

    if singletons:
        iso_emb = emb[singletons]
        if len(singletons) >= 3:
            tfun, _, _ = C._pca(iso_emb, n_components=3)
            iso = _pad3(tfun(iso_emb))
        else:
            iso = np.zeros((len(singletons), 3))
            iso[:, 0] = np.linspace(-0.4, 0.4, len(singletons))
        for j, i in enumerate(singletons):
            v = iso[j]
            nrm = float(np.linalg.norm(v)) or 1.0
            xyz[i] = (v / nrm) * (1.48 + 0.16 * ((j % 11) / 10))

    return xyz, story_centers, centrality, theme_centers


_JUNK_PREFIXES = (
    "non-political", "non political", "non politique", "hors champ",
    "hors-champ", "boilerplate", "sports match", "celebrity news",
)
_GENERIC_PREFIX_HEADERS = {
    "government and emergency response", "government response", "state accountability",
    "security dispute", "royal family", "controle parlementaire", "contrôle parlementaire",
}


def _is_junk_label(label: str) -> bool:
    raw = (label or "").strip().casefold()
    if not raw:
        return True
    for p in _JUNK_PREFIXES:
        if raw == p or raw.startswith((f"{p} ", f"{p}:", f"{p} -", f"{p} —", f"{p} –")):
            return True
    k = C._norm_topic(label)
    return not k or k in JUNK_LABELS


def _clean_topic_label(label: str) -> str:
    """Nettoie les libellés verbeux du LLM (parenthèses, snake_case, sous-clauses)."""
    s = (label or "").strip()
    if not s:
        return ""
    was_snake = "_" in s and " " not in s
    if was_snake:
        s = s.replace("_", " ")
    # Supprime les parenthèses explicatives ajoutées par certains modèles
    s = re.sub(r"\s*\([^)]*\)", "", s).strip()
    s = re.sub(r"\s*\([^)]*$", "", s).strip()
    # Si forme "catégorie générique — vrai sujet", garder le vrai sujet
    for sep in (" — ", " – ", ": "):
        if sep in s:
            left, right = s.split(sep, 1)
            left, right = left.strip(), right.strip()
            if left.casefold() in _GENERIC_PREFIX_HEADERS and len(right) >= 8:
                s = right
                break
            if len(left) >= 14 and len(s) > 52:
                s = left
                break
    s = re.sub(r"\s+", " ", s).strip(" -–—:;,.")
    if len(s) > 68:
        words = s.split()
        cut = []
        length = 0
        for w in words:
            if length + len(w) + (1 if cut else 0) > 62 and len(cut) >= 3:
                break
            cut.append(w)
            length += len(w) + (1 if cut else 0)
        s = " ".join(cut).rstrip(",;:-–—")
    if was_snake and s and s[0].islower():
        s = s[0].upper() + s[1:]
    return s


def _usable_topics(data: dict | None) -> list[str]:
    out = []
    for t in (data or {}).get("topics") or []:
        raw = (t.get("label") or "").strip()
        if not raw or _is_junk_label(raw):
            continue
        lab = _clean_topic_label(raw)
        if lab and not _is_junk_label(lab):
            out.append(lab)
    return out


_QUOTE_START_RE = re.compile(r'^[\s"«“”\'‘’]+')
_GENERIC_KICKERS = {
    "video", "vidéo", "direct", "en direct", "live", "liveblog", "podcast",
    "entretien", "interview", "tribune", "chronique", "edito", "édito",
    "editorial", "éditorial", "analyse", "reportage", "enquete", "enquête",
    "opinion", "decryptage", "décryptage", "info", "exclusif", "alerte",
}


def _kicker_from_titles(titles: list[str]) -> str | None:
    """Extrait le sur-titre éditorial ('Sujet : ...') des articles quand il est informatif."""
    cands: Counter = Counter()
    forms: dict[str, str] = {}
    for raw in titles:
        t = (raw or "").strip()
        if not t or _QUOTE_START_RE.match(t):
            continue
        for sep in ("\u00a0: ", " : ", ": "):
            if sep in t:
                head, tail = t.split(sep, 1)
                head = head.strip()
                if _QUOTE_START_RE.match(head) or any(q in head for q in ("«", "»", "“", "”", '"')):
                    break
                norm = C._norm_topic(head)
                if not norm or norm in _GENERIC_KICKERS:
                    break
                if 10 <= len(head) <= 48 and len(norm.split()) >= 2:
                    cands[norm] += 1
                    forms.setdefault(norm, head[0].upper() + head[1:])
                elif 5 <= len(head) < 10 and len(tail) >= 12:
                    # Kicker court (ex. "Ceuta", "Dette", "Citroën") : garder le titre complet tronqué proprement
                    full = f"{head} : {tail.strip()}"
                    if len(full) > 64:
                        full = full[:61].rsplit(" ", 1)[0].rstrip(",;:-–—") + "…"
                    nfull = C._norm_topic(full)
                    cands[nfull] += 1
                    forms.setdefault(nfull, full)
                break
    if not cands:
        return None
    best = max(cands, key=lambda k: (cands[k], -abs(len(forms[k]) - 28)))
    return forms[best]


def _cluster_name(extracted: list[dict | None], titles: list[str]) -> tuple[str, list[str]]:
    counts: Counter = Counter()
    originals: dict[str, Counter] = defaultdict(Counter)
    for data in extracted:
        for lab in _usable_topics(data)[:2]:
            k = C._norm_topic(lab)
            if len(k) < 4:
                continue
            counts[k] += 1
            originals[k][lab] += 1
    if not counts:
        title = next((t.strip() for t in titles if t and t.strip()), "Sans titre")
        return title[:90], []
    top_k = max(counts, key=lambda k: (counts[k], -abs(len(_label_tokens(k)) - 4), -len(k)))
    label = originals[top_k].most_common(1)[0][0]
    # Si aucun libellé LLM ne fait consensus (fréquence 1) et qu'un sur-titre éditorial clair existe dans les articles, l'utiliser.
    if counts[top_k] == 1 and len(titles) >= 2:
        kicker = _kicker_from_titles(titles)
        if kicker:
            label = kicker
    aliases = []
    for k, _ in counts.most_common(6):
        cand = originals[k].most_common(1)[0][0]
        if C._norm_topic(cand) == C._norm_topic(label):
            continue
        aliases.append(cand)
    return label, aliases[:4]


def _label_tokens(label: str) -> set[str]:
    out = set()
    for t in _TOKEN_RE.findall(C._norm_topic(label)):
        out.add(_SPELL.get(t, t))
    return out


def _token_key(label: str) -> tuple[str, ...]:
    """Sac de tokens, ordre canonique — « Elections · Russian » = « Russian · Elections »."""
    return tuple(sorted(t for t in _label_tokens(label) if not _is_weak_token(t)))


_STOP_LABEL_TOKS = {
    "the", "and", "for", "with", "into", "from", "over", "after", "under", "between", "against",
    "amid", "about", "their", "its", "his", "her", "les", "des", "dans", "pour", "avec", "sur",
    "par", "aux", "une", "contre", "entre", "apres", "avant", "chez", "vers", "plus", "moins",
    "entry", "takes", "stake", "minority", "capital",
}


def same_affair_label(a: str, b: str) -> bool:
    """Même affaire malgré un libellé LLM inversé ou traduit à moitié."""
    ca, cb = _clean_topic_label(a), _clean_topic_label(b)
    ka, kb = C._norm_topic(ca), C._norm_topic(cb)
    if not ka or not kb:
        return False
    if ka == kb:
        return True
    if SequenceMatcher(None, ka, kb).ratio() >= 0.78:
        return True
    ta = {t for t in _label_tokens(ca) if t not in _STOP_LABEL_TOKS and not _is_weak_token(t)} or _label_tokens(ca)
    tb = {t for t in _label_tokens(cb) if t not in _STOP_LABEL_TOKS and not _is_weak_token(t)} or _label_tokens(cb)
    if not ta or not tb:
        return False
    union = ta | tb
    inter = ta & tb
    if len(inter) / len(union) >= 0.45:
        return True
    smaller, larger = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    if len(smaller) >= 2 and len(inter) >= 2 and len(inter) / len(smaller) >= 0.6:
        return True
    return len(smaller) >= 2 and smaller <= larger


def _token_surfaces(label: str) -> dict[str, str]:
    """Token normalisé → forme de surface (casse d'origine)."""
    out: dict[str, str] = {}
    for word in re.findall(r"[A-Za-zÀ-ÿ0-9]{3,}", label or ""):
        for raw in _TOKEN_RE.findall(C._norm_topic(word)):
            tok = _SPELL.get(raw, raw)
            if tok and tok not in out:
                out[tok] = word
    return out


def _is_weak_token(tok: str) -> bool:
    return not tok or len(tok) < 3 or tok in WEAK_TOKS


def _umbrella_tok(tok: str) -> str:
    """Pour le nom de famille seulement : elections/electoral → election."""
    tok = _SPELL.get(tok, tok)
    return {"elections": "election", "electoral": "election"}.get(tok, tok)


def _form_close(a: str, b: str) -> bool:
    aa, bb = (a or "").casefold(), (b or "").casefold()
    if not aa or not bb:
        return False
    if aa == bb:
        return True
    short, long = (aa, bb) if len(aa) <= len(bb) else (bb, aa)
    return len(short) >= 4 and long.startswith(short)


def _story_pool_labels(story: dict) -> list[str]:
    """Libellé de l'affaire, plus les alias qui en sont des variantes — pas les topics LLM hors-sujet."""
    lab = (story.get("label") or "").strip()
    out = [lab] if lab else []
    core = {t for t in _label_tokens(lab) if not _is_weak_token(t)}
    if not core:
        return out
    for a in story.get("aliases") or []:
        if not a:
            continue
        toks = {t for t in _label_tokens(a) if not _is_weak_token(t)}
        if toks & core:
            out.append(a)
    return out


def _compose_umbrella(stories: list[dict]) -> str:
    """Nom de famille : tokens/entités majoritaires, pas le libellé d'une affaire fille.

    Pondéré par le volume d'articles : un token porté par 2 articles sur 11
    (ex. « elections » collé à des frappes de drones) ne devient pas le nom.
    """
    child_labels = [s["label"] for s in stories if s.get("label")]
    child_norms = {C._norm_topic(l) for l in child_labels}
    art_w = [max(int(s.get("articles") or 1), 1) for s in stories]
    total_art = sum(art_w) or 1
    story_toks: list[set[str]] = []
    surfaces: dict[str, str] = {}
    tf: Counter = Counter()
    for s, w in zip(stories, art_w):
        toks: set[str] = set()
        for lab in _story_pool_labels(s):
            for tok, form in _token_surfaces(lab).items():
                tok = _umbrella_tok(tok)
                surfaces.setdefault(tok, form)
                toks.add(tok)
                tf[tok] += w
            toks |= {_umbrella_tok(t) for t in _label_tokens(lab)}
        story_toks.append(toks)

    df: Counter = Counter()
    story_df: Counter = Counter()
    for toks, w in zip(story_toks, art_w):
        for t in toks:
            if _is_weak_token(t):
                continue
            df[t] += w
            story_df[t] += 1
    n = max(len(stories), 1)
    shared = [
        t for t, c in story_df.items()
        if c >= 2 or (n == 2 and c == 2) or df[t] >= 0.4 * total_art
    ]
    shared.sort(key=lambda t: (-df[t], -tf[t], -len(t), t))

    ranked = list(shared)
    for t, _ in tf.most_common(12):
        if t not in ranked and not _is_weak_token(t):
            ranked.append(t)

    parts: list[str] = []
    used: set[str] = set()
    uncovered = set(range(n))
    min_second = 0.30 * total_art
    while len(parts) < 2:
        best = None
        best_score = None
        for t in ranked:
            if t in used:
                continue
            cover_all = sum(art_w[i] for i in range(n) if t in story_toks[i])
            if parts and cover_all < min_second:
                continue
            if not uncovered and cover_all < min_second:
                continue
            new_cover = sum(art_w[i] for i in uncovered if t in story_toks[i])
            score = (new_cover, df.get(t, 0), tf[t], len(t))
            if best_score is None or score > best_score:
                best_score = score
                best = t
        if not best:
            break
        form = surfaces.get(best, best)
        label = form[0].upper() + form[1:] if form else best
        if any(_form_close(label, p) for p in parts):
            used.add(best)
            continue
        parts.append(label)
        used.add(best)
        uncovered -= {i for i in range(n) if best in story_toks[i]}
        if not uncovered and len(parts) >= 2:
            break

    ent_df: Counter = Counter()
    ent_form: dict[str, str] = {}
    for s in stories:
        seen = set()
        for e in s.get("entities") or []:
            name = (e.get("name") or "").strip()
            k = C._norm_topic(name)
            if len(k) < 4 or k in GENERIC_ENTS or k in seen:
                continue
            seen.add(k)
            ent_df[k] += 1
            ent_form.setdefault(k, name)
    shared_ents = [k for k, c in ent_df.most_common() if c >= 2 and k not in used]
    if shared_ents and len(parts) < 2:
        name = ent_form[shared_ents[0]]
        part_toks = set().union(*(_label_tokens(p) for p in parts)) if parts else set()
        if name and not (part_toks & _label_tokens(name)) and not any(_form_close(name, p) for p in parts):
            parts.insert(0, name)

    if parts:
        label = " · ".join(parts[:3])
        if C._norm_topic(label) not in child_norms:
            return label

    # Repli : deux affaires les plus courtes, collées — jamais un seul libellé fille.
    shorts = sorted({l for l in child_labels}, key=lambda l: (len(l), l.lower()))
    if len(shorts) >= 2:
        return f"{shorts[0]} · {shorts[1]}"
    return shorts[0] if shorts else "Sans titre"


def _family_name(stories: list[dict]) -> tuple[str, list[str]]:
    """Libellé de famille distinct des affaires ; les affaires passent en alias."""
    child_labels: list[str] = []
    seen: set[str] = set()
    for s in stories:
        for lab in [s.get("label"), *(s.get("aliases") or [])]:
            k = C._norm_topic(lab or "")
            if not k or k in seen:
                continue
            seen.add(k)
            child_labels.append(lab)
    if len(stories) <= 1:
        lab = (stories[0]["label"] if stories else "Sans titre")
        aliases = [a for a in child_labels if C._norm_topic(a) != C._norm_topic(lab)]
        return lab, aliases[:5]
    label = _compose_umbrella(stories)
    aliases = [a for a in child_labels if C._norm_topic(a) != C._norm_topic(label)]
    return label, aliases[:5]


def _counter_rows(c: Counter, limit: int = 6) -> list[dict]:
    return [{"label": k, "n": n} for k, n in c.most_common(limit) if k]


def _opinion_from_counts(tones: Counter, angles: Counter, n_articles: int) -> dict:
    valence_sum = 0.0
    valence_n = 0
    for tone, n in tones.items():
        if not tone:
            continue
        valence_sum += TONE_VALENCE.get(str(tone).lower(), 0.0) * n
        valence_n += n
    top_tone = tones.most_common(1)[0] if tones else (None, 0)
    return {
        "tones": _counter_rows(tones),
        "angles": _counter_rows(angles),
        "valence": round(valence_sum / valence_n, 2) if valence_n else 0.0,
        "dominant_tone": top_tone[0],
        "dominant_tone_n": top_tone[1],
        "dominant_tone_share": round(top_tone[1] / n_articles, 2) if n_articles and top_tone[0] else 0.0,
    }


def _fmt_short_date(iso: str | None) -> str:
    if not iso:
        return ""
    raw = str(iso).strip()[:19]
    try:
        d = datetime.fromisoformat(raw)
    except ValueError:
        try:
            d = datetime.strptime(raw[:10], "%Y-%m-%d")
        except ValueError:
            return ""
    months = _MONTHS_EN if get_locale() == "en" else _MONTHS_FR
    return f"{d.day} {months[d.month - 1]}"


def _title_close(a: str, b: str) -> bool:
    ka, kb = C._norm_topic(a), C._norm_topic(b)
    if not ka or not kb:
        return False
    if ka == kb or ka in kb or kb in ka:
        return True
    return SequenceMatcher(None, ka, kb).ratio() >= 0.72


def _headline_row(row: dict | None) -> dict | None:
    if not row:
        return None
    title = re.sub(r"\s+", " ", (row.get("title") or "").strip())
    if not title:
        return None
    return {
        "title": title,
        "outlet": (row.get("outlet") or "").strip(),
        "date": _fmt_short_date(row.get("date") or row.get("published_at")),
    }


def _distinct_headlines(members: list[dict], lead_title: str | None, limit: int = 2) -> list[dict]:
    out: list[dict] = []
    seen = [lead_title] if lead_title else []
    for m in members or []:
        row = _headline_row(m)
        if not row:
            continue
        if any(_title_close(row["title"], s) for s in seen):
            continue
        out.append(row)
        seen.append(row["title"])
        if len(out) >= limit:
            break
    return out


_NEWSWIRES = {
    "afp", "reuters", "ap", "associated press", "dpa", "ansa", "efe", "apa",
    "belga", "rtr", "staff", "redaction", "redaktion",
}


def _actor_names(entities: list[dict] | None, limit: int = 5) -> list[str]:
    out = []
    for e in entities or []:
        name = (e.get("name") or e.get("entity") or "").strip()
        if not name:
            continue
        k = C._norm_topic(name)
        if k in GENERIC_ENTS or k in _NEWSWIRES:
            continue
        out.append(name)
        if len(out) >= limit:
            break
    return out


def _press_hint(node: dict) -> str | None:
    opinion = node.get("opinion") or {}
    tone = (opinion.get("dominant_tone") or "").strip()
    spread = node.get("spread") or {}
    bits = []
    if tone:
        bits.append(tone)
    if spread.get("label") and (spread.get("spread") or 0) >= 0.25:
        low, high = spread.get("low_pole") or "", spread.get("high_pole") or ""
        if low and high and low != high:
            bits.append(f"{spread['label']}: {low} / {high}")
    return "; ".join(bits) if bits else None


def _title_pack(node: dict, limit: int = 4) -> list[dict]:
    lead = _headline_row(node.get("lead") or {})
    rows = []
    seen: list[str] = []
    if lead:
        rows.append(lead)
        seen.append(lead["title"])
    for h in _distinct_headlines(node.get("members") or [], lead["title"] if lead else None, limit=limit):
        if any(_title_close(h["title"], s) for s in seen):
            continue
        rows.append(h)
        seen.append(h["title"])
        if len(rows) >= limit:
            break
    return [{"title": r["title"][:160], "outlet": r["outlet"], "date": r["date"]} for r in rows]


def brief_item(node: dict, kind: str, sid: str) -> dict:
    """Faits pour le rédacteur : titres + acteurs, sans compteurs."""
    item = {
        "id": sid,
        "kind": kind,
        "label": (node.get("label") or "").strip(),
        "titles": _title_pack(node),
        "actors": _actor_names(node.get("entities")),
    }
    aliases = [a for a in (node.get("aliases") or []) if a][:3]
    if aliases:
        item["aliases"] = aliases
    hint = _press_hint(node)
    if hint:
        item["press"] = hint
    if kind == "family":
        labels = [s.get("label") for s in (node.get("story_summaries") or []) if s.get("label")]
        if labels:
            item["threads"] = labels[:8]
    return item


def apply_briefs(themes: list[dict], clusters: list[dict], mapping: dict[str, str]) -> None:
    """Écrit les briefs LLM sur les dicts déjà copiés."""
    by_id = {c["id"]: c for c in clusters}
    for th in themes:
        text = mapping.get(f"f:{th['id']}")
        if text:
            th["brief"] = text
        for s in th.get("story_summaries") or []:
            b = mapping.get(f"s:{s['id']}")
            if b:
                s["brief"] = b
                cl = by_id.get(s["id"])
                if cl is not None:
                    cl["brief"] = b
    for c in clusters:
        b = mapping.get(f"s:{c['id']}")
        if b:
            c["brief"] = b


def _with_briefs(db: Session, data: dict) -> dict:
    """Copie thèmes/clusters, rédige les briefs des familles affichées, renvoie un nouvel objet."""
    themes = [
        {**t, "story_summaries": [{**s} for s in (t.get("story_summaries") or [])]}
        for t in (data.get("themes") or [])
    ]
    clusters = [{**c} for c in (data.get("clusters") or [])]
    out = {**data, "themes": themes, "clusters": clusters}
    by_id = {c["id"]: c for c in clusters}
    items = []
    for th in themes[:MAX_THEMES]:
        items.append(brief_item(th, "family", f"f:{th['id']}"))
        for s in th.get("story_summaries") or []:
            node = by_id.get(s["id"]) or s
            items.append(brief_item(node, "story", f"s:{s['id']}"))
    if not items:
        return out
    from ..settings_store import get_setting
    from . import llm as llm_svc
    model = get_setting(db, "llm_model") or "aleria"
    mapping = llm_svc.synthesize_topic_briefs(db, model, items, locale=get_locale())
    apply_briefs(themes, clusters, mapping)
    return out


def brief_coverage(db: Session, node: dict) -> str:
    """Un seul brief (note thématique hors agenda)."""
    from ..settings_store import get_setting
    from . import llm as llm_svc
    item = brief_item(node, "story", "s:0")
    mapping = llm_svc.synthesize_topic_briefs(
        db, get_setting(db, "llm_model") or "aleria", [item], locale=get_locale(),
    )
    return mapping.get("s:0") or ""


def _merge_detail(rows_of: list[list[dict]], key: str = "id", cap: int = 20) -> list[dict]:
    by: dict = {}
    order: list = []
    for rows in rows_of:
        for row in rows or []:
            kid = row.get(key)
            if kid is None:
                continue
            if kid not in by:
                by[kid] = dict(row)
                order.append(kid)
            else:
                by[kid]["n"] = int(by[kid].get("n") or 0) + int(row.get("n") or 0)
    order.sort(key=lambda i: -int(by[i].get("n") or 0))
    return [by[i] for i in order[:cap]]


def _merge_entities(stories: list[dict], limit: int = 8) -> list[dict]:
    total: Counter = Counter()
    kind: dict[str, str] = {}
    for s in stories:
        for e in s.get("entities") or []:
            name = (e.get("name") or "").strip()
            if not name:
                continue
            total[name] += int(e.get("n") or 1)
            kind.setdefault(name, e.get("kind") or "org")
    return [{"name": n, "kind": kind[n], "n": c} for n, c in total.most_common(limit)]


def merge_story_labels(labels: np.ndarray, emb: np.ndarray, rows, min_articles: int) -> np.ndarray:
    """Recolle les affaires que le clustering a trop découpées (libellé identique ou quasi-identique)."""
    groups: dict[int, list[int]] = defaultdict(list)
    for i, lab in enumerate(labels):
        groups[int(lab)].append(i)
    all_cids = list(groups.keys())
    if len(all_cids) < 2:
        return labels

    names: dict[int, str] = {}
    for cid in all_cids:
        idxs = groups[cid]
        extracted = [rows[i][6] for i in idxs]
        titles = [rows[i][1] or "" for i in idxs]
        names[cid] = _cluster_name(extracted, titles)[0]

    parent = {c: c for c in all_cids}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i, a in enumerate(all_cids):
        for b in all_cids[i + 1:]:
            if find(a) == find(b):
                continue
            if same_affair_label(names[a], names[b]):
                parent[find(a)] = find(b)

    out = labels.copy()
    for cid in all_cids:
        root = find(cid)
        if root == cid:
            continue
        for i in groups[cid]:
            out[i] = root
    return out


def merge_close_themes(
    theme_of: dict[int, int],
    story_ids: list[int],
    cents: np.ndarray,
    names: dict[int, str],
    sim_merge: float = 0.80,
) -> dict[int, int]:
    """Recolle les familles que la liaison complète a trop découpées.

    Centroïdes ≥ 0,80 : même sujet malgré des libellés différents
    (Allemagne / AfD et élections à Berlin). On ne fusionne pas plus bas :
    0,55 collerait des drones ukrainiens à des législatives russes.
    """
    if len(story_ids) < 2:
        return theme_of
    by_theme: dict[int, list[int]] = defaultdict(list)
    for i, cid in enumerate(story_ids):
        by_theme[int(theme_of[cid])].append(i)
    tids = list(by_theme)
    if len(tids) < 2:
        return theme_of

    parent = {t: t for t in tids}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def unit(idxs: list[int]) -> np.ndarray:
        v = np.mean([cents[i] for i in idxs], axis=0)
        nrm = float(np.linalg.norm(v)) or 1.0
        return v / nrm

    units = {t: unit(by_theme[t]) for t in tids}

    for i, a in enumerate(tids):
        for b in tids[i + 1:]:
            if find(a) == find(b):
                continue
            sim = float(np.clip(units[a] @ units[b], 0.0, 1.0))
            if sim >= sim_merge:
                parent[find(a)] = find(b)

    out = dict(theme_of)
    for cid in story_ids:
        out[cid] = find(int(theme_of[cid]))
    return out


def _article_topics(data: dict | None) -> list[str]:
    return _usable_topics(data)[:2]


def _article_entities(data: dict | None) -> set[str]:
    """Personnes / orgs, hors noms trop génériques (France, UE…)."""
    out: set[str] = set()
    ents = (data or {}).get("entities") or {}
    for bucket in ("people", "organizations"):
        for raw in ents.get(bucket) or []:
            name = raw if isinstance(raw, str) else (raw or {}).get("name") or ""
            k = C._norm_topic(name)
            if len(k) < 4 or k in GENERIC_ENTS:
                continue
            out.add(k)
            for t in _TOKEN_RE.findall(k):
                t = _SPELL.get(t, t)
                if len(t) >= 4 and t not in GENERIC_ENTS:
                    out.add(t)
    return out


def _must_split_pair(data_a: dict | None, data_b: dict | None) -> bool:
    """Vrai seulement si les deux ont une identité (topic + entités) et qu'elle s'oppose."""
    ta, tb = _article_topics(data_a), _article_topics(data_b)
    if ta and tb and any(same_affair_label(a, b) for a in ta for b in tb):
        return False
    ea, eb = _article_entities(data_a), _article_entities(data_b)
    if ea and eb and (ea & eb):
        return False
    return bool(ta and tb and ea and eb)


def split_incoherent_stories(labels: np.ndarray, rows, min_articles: int = MIN_CLUSTER) -> np.ndarray:
    """Éjecte d'une affaire les articles au libellé et aux entités disjoints du reste."""
    if len(labels) == 0:
        return labels
    groups: dict[int, list[int]] = defaultdict(list)
    for i, lab in enumerate(labels):
        groups[int(lab)].append(i)
    out = labels.copy()
    next_id = int(labels.max()) + 1

    for idxs in groups.values():
        if len(idxs) < min_articles:
            continue
        parent = {i: i for i in idxs}

        def find(x: int, _p=parent) -> int:
            while _p[x] != x:
                _p[x] = _p[_p[x]]
                x = _p[x]
            return x

        for a in range(len(idxs)):
            ia = idxs[a]
            da = rows[ia][6]
            for b in range(a + 1, len(idxs)):
                ib = idxs[b]
                if not _must_split_pair(da, rows[ib][6]):
                    parent[find(ia)] = find(ib)
        comps: dict[int, list[int]] = defaultdict(list)
        for i in idxs:
            comps[find(i)].append(i)
        if len(comps) < 2:
            continue
        ordered = sorted(comps.values(), key=lambda c: (-len(c), c[0]))
        for comp in ordered[1:]:
            for i in comp:
                out[i] = next_id
            next_id += 1
    return out


def _heat(curr: int, prev: int) -> tuple[str, float]:
    if prev <= 0:
        return ("new", 99.0 if curr else 0.0)
    ratio = curr / prev
    if ratio >= 1.5:
        return "up", round(ratio, 2)
    if ratio <= 0.7:
        return "down", round(ratio, 2)
    return "stable", round(ratio, 2)


def _polarization(by_outlet: dict[int, list[np.ndarray]], n_axes: int) -> float:
    vecs = [_call_carto(C._mean_nonzero, vs, n_axes) for vs in by_outlet.values() if vs]
    if len(vecs) < 2:
        return 0.0
    return round(float(np.stack(vecs).std(axis=0).mean()), 3)


def _spread_axis(by_outlet: dict[int, list[np.ndarray]], axes: list[str]) -> dict | None:
    vecs = [_call_carto(C._mean_nonzero, vs, len(axes)) for vs in by_outlet.values() if vs]
    if len(vecs) < 2:
        return None
    m = np.stack(vecs)
    spread = m.max(axis=0) - m.min(axis=0)
    i = int(np.argmax(spread))
    if i >= len(axes) or spread[i] < 0.25:
        return None
    ax = axes[i]
    neg, pos = axis_poles(ax)
    lo, hi = float(m[:, i].min()), float(m[:, i].max())
    return {
        "axis": ax, "label": axis_label(ax),
        "spread": round(float(spread[i]), 2),
        "low": round(lo, 2), "high": round(hi, 2),
        "low_pole": neg if lo < 0 else pos, "high_pole": pos if hi > 0 else neg,
    }


_NOISE_ENTITIES = {
    "google", "abonnez", "abonnez-vous", "lire aussi", "newsletter", "afp", "reuters",
    "ap", "dpa", "ansa", "efe", "belga", "ats", "keystone", "wam", "sabc", "enca",
    "franceinfo", "france info", "le monde", "le figaro", "liberation", "libération",
    "les echos", "les échos", "le parisien", "la croix", "mediapart", "médiapart",
    "valeurs actuelles", "courrier international", "l'opinion", "lopinion", "rtl",
    "die welt", "der spiegel", "faz", "sueddeutsche", "süddeutsche zeitung",
    "el pais", "el país", "el mundo", "abc", "la repubblica", "corriere della sera",
    "il giornale", "the guardian", "bbc", "bbc news", "the times", "the telegraph",
    "the daily telegraph", "la libre", "la libre belgique", "le soir", "de standaard",
    "het laatste nieuws", "nzz", "neue zurcher zeitung", "le temps", "tribune de geneve",
    "gulf news", "khaleej times", "al-khaleej", "the national", "sky news arabia",
    "al-ittihad", "al-bayan", "emarat al youm", "cnbc arabia", "timeslive", "news24",
    "daily maverick", "mail & guardian", "iol", "the sowetan", "business day", "city press",
}


def _is_noise_entity(name: str) -> bool:
    norm = C._norm_topic(name)
    if not norm or len(norm) < 3 or norm in GENERIC_ENTS or norm in _NOISE_ENTITIES:
        return True
    if any(norm.startswith(p) for p in ("abonnez", "lire aussi", "info franceinfo", "video ")):
        return True
    return False


def _top_entities(extracted: list[dict | None], limit: int = 8) -> list[dict]:
    total: Counter = Counter()
    kind: dict[str, str] = {}
    for data in extracted:
        ents = (data or {}).get("entities") or {}
        for bucket in ("people", "organizations"):
            for e in ents.get(bucket) or []:
                name = (e or "").strip()
                if 3 <= len(name) <= 60 and not _is_noise_entity(name):
                    total[name] += 1
                    kind.setdefault(name, "person" if bucket == "people" else "org")
    return [{"name": n, "kind": kind[n], "n": c} for n, c in total.most_common(limit)]


# ───────────────────────────────────────────────────────────── search


def _strip_private(row: dict) -> dict:
    return {k: v for k, v in row.items() if not str(k).startswith("_")}


def _unit(vec) -> np.ndarray | None:
    if vec is None:
        return None
    v = np.asarray(vec, dtype=float).reshape(-1)
    nrm = float(np.linalg.norm(v))
    if nrm < 1e-9:
        return None
    return v / nrm


def _node_texts(node: dict) -> list[str]:
    texts = [node.get("label") or ""]
    texts.extend(a for a in (node.get("aliases") or []) if a)
    for e in node.get("entities") or []:
        name = e.get("name") if isinstance(e, dict) else str(e or "")
        if name:
            texts.append(name)
    return texts


def _family_search_texts(node: dict) -> list[str]:
    """Libellé de famille + acteurs — pas les alias (ce sont les affaires filles)."""
    texts = [node.get("label") or ""]
    for e in node.get("entities") or []:
        name = e.get("name") if isinstance(e, dict) else str(e or "")
        if name:
            texts.append(name)
    return texts


def _phrase_in(qnorm: str, blob: str) -> bool:
    if not qnorm or not blob:
        return False
    padded = f" {blob} "
    return f" {qnorm} " in padded


def lexical_overlap(query: str, texts: list[str]) -> float:
    """1 si la requête (normalisée) est dans les textes, sinon part des tokens couverts."""
    qnorm = C._norm_topic(query or "")
    blob = C._norm_topic(" ".join(t for t in texts if t))
    if len(qnorm) >= 3 and _phrase_in(qnorm, blob):
        return 1.0
    qtoks = _label_tokens(query or "")
    if not qtoks:
        return 0.0
    pool: set[str] = set()
    for t in texts:
        pool |= _label_tokens(t)
    if not pool:
        return 0.0
    hit = 0
    for tok in qtoks:
        if tok in pool:
            hit += 1
            continue
        if len(tok) >= 5 and any(len(p) >= 5 and (p.startswith(tok) or tok.startswith(p)) for p in pool):
            hit += 1
    return hit / len(qtoks)


def blend_score(semantic: float, lexical: float) -> float:
    """Cosinus du centroïde, relevé si les libellés / acteurs recouvrent la requête."""
    score = max(0.0, float(semantic))
    lex = max(0.0, min(1.0, float(lexical)))
    if lex >= 0.34:
        score = max(score, 0.38 + 0.57 * lex)
    if lex >= 0.99:
        score = max(score, 0.78)
    return round(min(score, 1.0), 4)


def search_agenda(data: dict, query: str, query_vec: np.ndarray | None = None) -> list[dict]:
    """Classe les familles par proximité sémantique (et lexicale) à la requête."""
    q = (query or "").strip()
    if not q:
        return []
    qn = _unit(query_vec)
    if qn is None:
        from . import embeddings
        qn = _unit(embeddings.embed_text(q))
    if qn is None:
        qn = np.zeros(1)

    story_score: dict[int, float] = {}
    for c in data.get("clusters") or []:
        vec = _unit(c.get("_vec"))
        sem = float(np.clip(qn @ vec, 0.0, 1.0)) if vec is not None and vec.shape == qn.shape else 0.0
        story_score[c["id"]] = blend_score(sem, lexical_overlap(q, _node_texts(c)))

    hits: list[dict] = []
    for th in data.get("themes") or []:
        vec = _unit(th.get("_vec"))
        sem = float(np.clip(qn @ vec, 0.0, 1.0)) if vec is not None and vec.shape == qn.shape else 0.0
        label_lex = lexical_overlap(q, [th.get("label") or ""])
        lex = max(label_lex, lexical_overlap(q, _family_search_texts(th)))
        child_ids = [s["id"] for s in (th.get("story_summaries") or [])]
        child_scores = [story_score.get(i, 0.0) for i in child_ids]
        own = blend_score(sem, lex)
        score = max([own, *child_scores]) if child_scores else own
        if score < SEARCH_THRESHOLD:
            continue
        summaries = sorted(
            th.get("story_summaries") or [],
            key=lambda s: (-story_score.get(s["id"], 0.0), -int(s.get("articles") or 0)),
        )
        row = _strip_private(th)
        row["story_summaries"] = [
            {**s, "score": round(story_score.get(s["id"], 0.0), 3)} for s in summaries
        ]
        row["score"] = round(score, 3)
        row["_label"] = label_lex
        hits.append(row)
    hits.sort(key=lambda t: (-t["_label"], -t["score"], -int(t.get("articles") or 0), t.get("label") or ""))
    return [_strip_private(h) for h in hits[:SEARCH_CAP]]


def _compute_theme_links(themes: list[dict], max_per_node: int = 3) -> list[dict]:
    """Calcule les ponts significatifs entre familles de sujets (acteurs partagés, journalistes, proximité sémantique)."""
    candidates: list[dict] = []
    n = len(themes)
    for i in range(n):
        a = themes[i]
        va = _unit(a.get("_vec"))
        ea = {
            C._norm_topic(e["name"]): e["name"]
            for e in (a.get("entities") or [])
            if e.get("name") and not _is_noise_entity(e["name"])
        }
        ja = {j["id"]: j["name"] for j in (a.get("journalists_detail") or []) if j.get("id") and j.get("name")}
        oa = {o["id"]: o["name"] for o in (a.get("outlets_detail") or []) if o.get("id") and o.get("name")}
        ta = {t for t in _label_tokens(a.get("label") or "") if not _is_weak_token(t) and t not in _STOP_LABEL_TOKS}

        for j_idx in range(i + 1, n):
            b = themes[j_idx]
            vb = _unit(b.get("_vec"))
            sim = float(np.clip(va @ vb, 0.0, 1.0)) if va is not None and vb is not None and va.shape == vb.shape else 0.0
            eb = {
                C._norm_topic(e["name"]): e["name"]
                for e in (b.get("entities") or [])
                if e.get("name") and not _is_noise_entity(e["name"])
            }
            jb = {j["id"]: j["name"] for j in (b.get("journalists_detail") or []) if j.get("id") and j.get("name")}
            ob = {o["id"]: o["name"] for o in (b.get("outlets_detail") or []) if o.get("id") and o.get("name")}
            tb = {t for t in _label_tokens(b.get("label") or "") if not _is_weak_token(t) and t not in _STOP_LABEL_TOKS}

            shared_ent_keys = [k for k in ea if k in eb]
            shared_entities = [ea[k] for k in shared_ent_keys][:3]
            shared_journalists = [ja[jid] for jid in ja if jid in jb][:2]
            shared_outlets = [oa[oid] for oid in oa if oid in ob]
            shared_toks = ta & tb

            has_bridge = bool(shared_entities or shared_journalists)
            if not has_bridge and sim < 0.54:
                continue
            if has_bridge and sim < 0.34:
                continue

            weight = sim
            if shared_entities:
                weight += 0.18 * min(2, len(shared_entities))
            if shared_journalists:
                weight += 0.12
            if shared_toks:
                weight += 0.10

            if shared_entities:
                kind = "entity"
                label = shared_entities[0]
                if len(shared_entities) > 1:
                    label = f"{shared_entities[0]} +{len(shared_entities) - 1}"
            elif shared_journalists:
                kind = "journalist"
                label = f"✒ {shared_journalists[0]}"
            else:
                kind = "semantic"
                label = f"{round(sim * 100)} %"

            candidates.append({
                "source": a["id"],
                "target": b["id"],
                "source_label": a.get("label") or "",
                "target_label": b.get("label") or "",
                "similarity": round(sim, 3),
                "weight": round(min(1.0, weight), 3),
                "kind": kind,
                "label": label,
                "shared_entities": shared_entities,
                "shared_journalists": shared_journalists,
                "shared_outlets": shared_outlets[:4],
                "shared_outlets_count": len(shared_outlets),
            })

    candidates.sort(key=lambda c: (-1 if c["kind"] != "semantic" else 0, -c["weight"], -c["similarity"]))
    deg: Counter = Counter()
    kept: list[dict] = []
    for link in candidates:
        s, t = link["source"], link["target"]
        if deg[s] >= max_per_node or deg[t] >= max_per_node:
            continue
        deg[s] += 1
        deg[t] += 1
        kept.append(link)
    return kept


def _public_agenda(data: dict) -> dict:
    """Payload API : 16 familles pour la carte, sans vecteurs internes."""
    all_themes = data.get("themes") or []
    top_themes_raw = all_themes[:MAX_THEMES]
    theme_links = _compute_theme_links(top_themes_raw)
    themes = [_strip_private(t) for t in top_themes_raw]
    clusters = [_strip_private(c) for c in (data.get("clusters") or [])]
    return {
        **data,
        "themes": themes,
        "theme_links": theme_links,
        "clusters": clusters,
        "n_themes": len(themes),
        "n_themes_all": int(data.get("n_themes_all") or len(all_themes)),
    }


# ───────────────────────────────────────────────────────────── query


def agenda(
    db: Session,
    days: int = 7,
    country: str | None = None,
    outlet_id: int | None = None,
    journalist_id: int | None = None,
    min_articles: int = MIN_CLUSTER,
    include_singletons: bool = False,
    briefs: bool = False,
    q: str | None = None,
    cap: int | None = None,
) -> dict:
    days = max(1, min(int(days or 7), MAX_DAYS))
    min_articles = 1 if include_singletons else max(1, int(min_articles or MIN_CLUSTER))
    country = (country or "").upper() or None
    cap_n = MAX_ARTICLES if not cap else max(50, min(int(cap), MAX_ARTICLES))
    key = f"agenda:{days}:{country}:{outlet_id}:{journalist_id}:{min_articles}:{include_singletons}:{cap_n}"
    data = _cached(key, lambda: _agenda(db, days, country, outlet_id, journalist_id, min_articles, include_singletons, cap_n))
    if briefs:
        data = _cached(f"{key}:briefs", lambda: _with_briefs(db, data))
    out = _public_agenda(data)
    query = (q or "").strip()
    if query:
        hits = search_agenda(data, query)
        out["query"] = query
        out["search"] = {"query": query, "n": len(hits), "themes": hits}
    return out


def _filtered_query(db: Session, since: datetime, until: datetime | None,
                    country: str | None, outlet_id: int | None, journalist_id: int | None):
    q = db.query(
        Article.id, Article.title, Article.url, Article.outlet_id, Article.journalist_id,
        Article.published_at, Article.extracted_data, Article.embedding,
    ).filter(
        Article.analysis_status == "analyzed",
        Article.embedding.isnot(None),
        Article.published_at >= since,
        Article.published_at.isnot(None),
    )
    if until:
        q = q.filter(Article.published_at < until)
    if outlet_id:
        q = q.filter(Article.outlet_id == outlet_id)
    if country:
        q = q.join(Outlet, Outlet.id == Article.outlet_id).filter(Outlet.country == country)
    if journalist_id:
        q = q.filter(or_(
            Article.journalist_id == journalist_id,
            exists().where(
                ArticleJournalist.article_id == Article.id,
                ArticleJournalist.journalist_id == journalist_id,
            ),
        ))
    return q


def _agenda(db: Session, days: int, country: str | None, outlet_id: int | None,
            journalist_id: int | None, min_articles: int, include_singletons: bool,
            cap: int = MAX_ARTICLES) -> dict:
    now = datetime.utcnow()
    since = now - timedelta(days=days)
    prev_since = since - timedelta(days=days)
    axes = axes_for_country(country, db) if country else list(STRUCTURAL_IDS)
    n_ax = len(axes)

    rows = (
        _filtered_query(db, since, None, country, outlet_id, journalist_id)
        .order_by(Article.published_at.desc())
        .limit(cap)
        .all()
    )
    empty = {
        "since": since.date().isoformat(), "until": now.date().isoformat(), "days": days,
        "threshold": SIM_THRESHOLD, "theme_threshold": THEME_THRESHOLD,
        "n_articles": 0, "n_clustered": 0, "n_singletons": 0, "n_themes": 0, "n_themes_all": 0,
        "explained_variance": [], "clusters": [], "points": [], "themes": [], "edges": [],
        "filters": {"country": country, "outlet_id": outlet_id, "journalist_id": journalist_id},
    }
    if len(rows) < 2:
        empty["n_articles"] = len(rows)
        return empty

    emb = np.stack([np.asarray(r[7], dtype=float) for r in rows])
    labels = cluster_embeddings(emb, AGENDA_SIM_THRESHOLD, method="complete")
    labels = merge_story_labels(labels, emb, rows, min_articles)
    labels = split_incoherent_stories(labels, rows, min_articles)

    # Période précédente : vecteurs seulement, pour la chaleur. Plafonnée comme
    # la fenêtre courante — sans limite, la requête charge tout le corpus.
    prev_rows = (
        _filtered_query(db, prev_since, since, country, outlet_id, journalist_id)
        .order_by(Article.published_at.desc())
        .limit(cap)
        .all()
    )
    prev_emb = None
    if prev_rows:
        prev_raw = np.stack([np.asarray(r[7], dtype=float) for r in prev_rows if r[7] is not None])
        if len(prev_raw):
            nrm = np.linalg.norm(prev_raw, axis=1, keepdims=True)
            prev_emb = prev_raw / np.maximum(nrm, 1e-9)

    outlets = C._outlet_index(db)
    jids = {r[4] for r in rows if r[4]}
    article_ids = [r[0] for r in rows]
    authors: dict[int, list[tuple[int, int]]] = defaultdict(list)  # article -> [(jid, pos)]
    extra_jids: set[int] = set()
    if article_ids:
        for aid, jid, pos in (
            db.query(ArticleJournalist.article_id, ArticleJournalist.journalist_id, ArticleJournalist.position)
            .filter(ArticleJournalist.article_id.in_(article_ids)).all()
        ):
            authors[aid].append((jid, pos))
            extra_jids.add(jid)
    jids |= extra_jids
    journalists = {j.id: j for j in db.query(Journalist).filter(Journalist.id.in_(jids)).all()} if jids else {}

    groups: dict[int, list[int]] = defaultdict(list)
    for i, lab in enumerate(labels):
        groups[int(lab)].append(i)
    story_ids = [cid for cid, idxs in groups.items() if len(idxs) >= min_articles]
    if len(story_ids) >= 2:
        cents = np.stack([emb[groups[cid]].mean(axis=0) for cid in story_ids])
        tlab = cluster_embeddings(cents, AGENDA_THEME_THRESHOLD, method="complete")
        theme_of = {story_ids[i]: int(tlab[i]) for i in range(len(story_ids))}
        story_names = {
            cid: _cluster_name([rows[i][6] for i in groups[cid]], [rows[i][1] or "" for i in groups[cid]])[0]
            for cid in story_ids
        }
        theme_of = merge_close_themes(theme_of, story_ids, cents, story_names)
    else:
        theme_of = {cid: 0 for cid in story_ids}
    xyz, centers, centrality, theme_centers = layout_xyz(emb, labels, min_articles, theme_of)
    var = []
    if len(theme_centers) >= 2:
        _, _, var = C._pca(np.stack(list(theme_centers.values())), n_components=min(3, len(theme_centers)))
    elif len(centers) >= 2:
        _, _, var = C._pca(np.stack(list(centers.values())), n_components=min(3, len(centers)))

    clusters = []
    points = []
    isolated_articles = []
    n_singletons = 0

    def _pt(i: int, cluster_id: int | None) -> dict:
        r = rows[i]
        o = outlets.get(r[3])
        j = journalists.get(r[4]) if r[4] else None
        tid = theme_of.get(cluster_id) if cluster_id is not None else None
        return {
            "id": r[0], "cluster_id": cluster_id, "theme_id": tid,
            "x": round(float(xyz[i, 0]), 4), "y": round(float(xyz[i, 1]), 4), "z": round(float(xyz[i, 2]), 4),
            "title": (r[1] or "Sans titre")[:180],
            "outlet_id": r[3], "outlet": o.name if o else "",
            "country": o.country if o else None,
            "influence": round(float(o.influence_score or 0), 1) if o else 0.0,
            "journalist": j.name if j else None,
            "topic": (_usable_topics(r[6]) or [None])[0],
            "tone": (r[6] or {}).get("tone") if isinstance(r[6], dict) else None,
            "date": r[5].date().isoformat() if r[5] else None,
            "centrality": round(float(centrality[i]), 3),
        }

    for cid, idxs in groups.items():
        if len(idxs) < min_articles:
            n_singletons += len(idxs)
            for i in idxs:
                pt = _pt(i, None)
                points.append(pt)
                isolated_articles.append(pt)
            continue
        members = [rows[i] for i in idxs]
        extracted = [m[6] for m in members]
        titles = [m[1] or "" for m in members]
        label, aliases = _cluster_name(extracted, titles)

        framing_by_outlet: dict[int, list[np.ndarray]] = defaultdict(list)
        outlet_n: Counter = Counter()
        jour_n: Counter = Counter()
        tone_n: Counter = Counter()
        angle_n: Counter = Counter()
        first = min(members, key=lambda m: m[5] or now)
        for m in members:
            oid = m[3]
            outlet_n[oid] += 1
            data = m[6] if isinstance(m[6], dict) else {}
            v = _call_carto(C._framing_vec, data, axes)
            if v is not None:
                framing_by_outlet[oid].append(v)
            if data.get("tone"):
                tone_n[data["tone"]] += 1
            if data.get("angle"):
                angle_n[data["angle"]] += 1
            seen_j = set()
            for jid, _ in authors.get(m[0], []):
                seen_j.add(jid)
            if m[4]:
                seen_j.add(m[4])
            for jid in seen_j:
                jour_n[jid] += 1

        member_emb = emb[idxs]
        centroid = member_emb.mean(axis=0)
        cnorm = np.linalg.norm(centroid)
        if prev_emb is not None and cnorm > 0:
            prev_n = int((prev_emb @ (centroid / cnorm) >= SIM_THRESHOLD).sum())
        else:
            prev_n = 0
        heat, heat_ratio = _heat(len(idxs), prev_n)

        center = centers.get(cid, xyz[idxs].mean(axis=0))
        cx, cy, cz = float(center[0]), float(center[1]), float(center[2])
        mean_fr = _call_carto(C._mean_nonzero, [v for vs in framing_by_outlet.values() for v in vs], n_ax)

        member_rows = []
        ordered = sorted(idxs, key=lambda i: rows[i][5] or now, reverse=True)
        for i in ordered[:MEMBERS_CAP]:
            r = rows[i]
            o = outlets.get(r[3])
            j = journalists.get(r[4]) if r[4] else None
            bylines = []
            for jid, pos in sorted(authors.get(r[0], []), key=lambda x: x[1]):
                jj = journalists.get(jid)
                if jj:
                    bylines.append({"id": jj.id, "name": jj.name, "position": pos})
            if not bylines and j:
                bylines = [{"id": j.id, "name": j.name, "position": 0}]
            member_rows.append({
                "id": r[0], "title": r[1], "url": r[2], "date": r[5].date().isoformat() if r[5] else None,
                "outlet_id": r[3], "outlet": o.name if o else "", "country": o.country if o else None,
                "journalist_id": r[4], "journalist": j.name if j else None,
                "authors": bylines, "topic": (_usable_topics(r[6]) or [None])[0],
                "tone": (r[6] or {}).get("tone") if isinstance(r[6], dict) else None,
                "angle": (r[6] or {}).get("angle") if isinstance(r[6], dict) else None,
                "x": round(float(xyz[i, 0]), 4), "y": round(float(xyz[i, 1]), 4), "z": round(float(xyz[i, 2]), 4),
                "influence": round(float(o.influence_score or 0), 1) if o else 0.0,
            })

        for i in idxs:
            points.append(_pt(i, cid))

        lead_o = outlets.get(first[3])
        clusters.append({
            "id": cid,
            "theme_id": theme_of.get(cid, cid),
            "label": label,
            "aliases": aliases,
            "articles": len(idxs),
            "outlets": len(outlet_n),
            "journalists": len(jour_n),
            "x": round(cx, 4), "y": round(cy, 4), "z": round(cz, 4),
            "heat": heat, "heat_ratio": heat_ratio, "prev_articles": prev_n,
            "polarization": _polarization(framing_by_outlet, n_ax),
            "spread": _spread_axis(framing_by_outlet, axes),
            "framing": _call_carto(C._vec_to_dict, mean_fr, axes),
            "entities": _top_entities(extracted),
            "tones": _counter_rows(tone_n),
            "angles": _counter_rows(angle_n),
            "opinion": _opinion_from_counts(tone_n, angle_n, len(idxs)),
            "lead": {
                "outlet_id": first[3], "outlet": lead_o.name if lead_o else "",
                "date": first[5].isoformat() if first[5] else None,
                "title": first[1], "article_id": first[0],
            },
            "outlets_detail": [
                {
                    "id": oid, "name": outlets[oid].name if oid in outlets else "",
                    "country": outlets[oid].country if oid in outlets else None,
                    "website": outlets[oid].website_url if oid in outlets else None,
                    "n": n,
                }
                for oid, n in outlet_n.most_common()
            ],
            "journalists_detail": [
                {"id": jid, "name": journalists[jid].name if jid in journalists else "", "outlet_id": journalists[jid].outlet_id if jid in journalists else None,
                 "outlet": (outlets[journalists[jid].outlet_id].name if jid in journalists and journalists[jid].outlet_id in outlets else ""), "n": n}
                for jid, n in jour_n.most_common(20) if jid in journalists
            ],
            "members": member_rows,
        })

    clusters.sort(key=lambda c: (-c["outlets"] * c["articles"], -c["outlets"], -c["articles"], c["label"].lower()))
    # Ids stables pour l'UI : rang dans la liste triée, l'id interne de clustering reste en `cid`.
    for i, c in enumerate(clusters):
        c["rank"] = i
        idxs = groups[c["id"]]
        cvec = emb[idxs].mean(axis=0)
        nrm = float(np.linalg.norm(cvec)) or 1.0
        c["_vec"] = cvec / nrm

    stories_of: dict[int, list] = defaultdict(list)
    for c in clusters:
        stories_of[c["theme_id"]].append(c)
    themes = []
    for tid, stories in stories_of.items():
        primary = max(stories, key=lambda s: s["outlets"] * s["articles"])
        label, aliases = _family_name(stories)
        tcenter = theme_centers.get(tid)
        if tcenter is None:
            tcenter = np.mean([[s["x"], s["y"], s["z"]] for s in stories], axis=0)
        radius = 0.18
        for s in stories:
            dist = float(np.linalg.norm(np.array([s["x"], s["y"], s["z"]], dtype=float) - tcenter))
            radius = max(radius, dist + 0.14)
        n_art = sum(s["articles"] for s in stories)
        prev_n = sum(s.get("prev_articles") or 0 for s in stories)
        heat, heat_ratio = _heat(n_art, prev_n)
        outlets_detail = _merge_detail([s.get("outlets_detail") or [] for s in stories])
        journalists_detail = _merge_detail([s.get("journalists_detail") or [] for s in stories])
        tone_n: Counter = Counter()
        angle_n: Counter = Counter()
        for s in stories:
            for row in s.get("tones") or []:
                tone_n[row["label"]] += row["n"]
            for row in s.get("angles") or []:
                angle_n[row["label"]] += row["n"]
        opinion = _opinion_from_counts(tone_n, angle_n, n_art)
        by_outlet_tone: dict[int, Counter] = defaultdict(Counter)
        for s in stories:
            for m in s.get("members") or []:
                oid = m.get("outlet_id")
                if oid is not None and m.get("tone"):
                    by_outlet_tone[oid][m["tone"]] += 1
        opinion["by_outlet"] = [
            {
                "id": o["id"], "name": o["name"], "n": o["n"],
                "tone": (by_outlet_tone.get(o["id"]) or Counter()).most_common(1)[0][0]
                if by_outlet_tone.get(o["id"]) else None,
            }
            for o in outlets_detail[:12]
        ]
        spreads = [s.get("spread") for s in stories if s.get("spread")]
        spread = max(spreads, key=lambda x: x.get("spread") or 0) if spreads else None
        pols = [s["polarization"] for s in stories if s.get("polarization") is not None]
        polarization = round(float(np.mean(pols)), 3) if pols else 0.0
        pool = [m for s in stories for m in (s.get("members") or [])]
        pool.sort(key=lambda m: m.get("date") or "", reverse=True)
        leads = [s.get("lead") for s in stories if s.get("lead") and s["lead"].get("date")]
        lead = min(leads, key=lambda L: L["date"]) if leads else primary.get("lead")
        j_ids: set[int] = set()
        for s in stories:
            for j in s.get("journalists_detail") or []:
                if j.get("id") is not None:
                    j_ids.add(j["id"])
        themes.append({
            "id": tid,
            "label": label,
            "aliases": aliases,
            "articles": n_art,
            "stories": len(stories),
            "story_ids": [s["id"] for s in stories],
            "story_summaries": [
                {
                    "id": s["id"], "label": s["label"], "articles": s["articles"],
                    "outlets": s["outlets"], "heat": s["heat"],
                    "polarization": s["polarization"],
                    "brief": s.get("brief") or "",
                }
                for s in sorted(stories, key=lambda s: (-s["articles"], s["label"].lower()))
            ],
            "outlets": len(outlets_detail) or int(sum(s["outlets"] for s in stories)),
            "journalists": len(j_ids) or int(sum(s.get("journalists") or 0 for s in stories)),
            "x": round(float(tcenter[0]), 4),
            "y": round(float(tcenter[1]), 4),
            "z": round(float(tcenter[2]), 4),
            "radius": round(float(radius), 4),
            "heat": heat, "heat_ratio": heat_ratio, "prev_articles": prev_n,
            "polarization": polarization,
            "spread": spread,
            "entities": _merge_entities(stories),
            "tones": _counter_rows(tone_n),
            "angles": _counter_rows(angle_n),
            "opinion": opinion,
            "lead": lead,
            "outlets_detail": outlets_detail,
            "journalists_detail": journalists_detail,
            "members": pool[:MEMBERS_CAP],
        })
    # Homonymes (y compris libellés inversés) : token discriminant.
    seen_labs: Counter = Counter(_token_key(t["label"]) for t in themes)
    for th in themes:
        k = _token_key(th["label"])
        if not k or seen_labs[k] < 2:
            continue
        existing = set(_label_tokens(th["label"]))
        extra = None
        for a in th.get("aliases") or []:
            for tok, form in _token_surfaces(a).items():
                if tok in existing or _is_weak_token(tok):
                    continue
                surface = form[0].upper() + form[1:] if form else tok
                if any(_form_close(surface, p) for p in th["label"].split(" · ")):
                    continue
                extra = surface
                break
            if extra:
                break
        if extra:
            th["label"] = f"{th['label']} · {extra}"
    themes.sort(key=lambda t: (-t["articles"], -t["stories"], t["label"].lower()))
    by_cid = {c["id"]: c for c in clusters}
    for th in themes:
        acc = None
        for sid in th.get("story_ids") or []:
            story = by_cid.get(sid)
            vec = None if story is None else story.get("_vec")
            if vec is None:
                continue
            w = float((story or {}).get("articles") or 1)
            acc = np.asarray(vec, dtype=float) * w if acc is None else acc + np.asarray(vec, dtype=float) * w
        if acc is not None:
            th["_vec"] = acc / (float(np.linalg.norm(acc)) or 1.0)
    n_themes_all = len(themes)

    emb_n = emb / np.maximum(np.linalg.norm(emb, axis=1, keepdims=True), 1e-9)
    edges = []
    for cid, idxs in groups.items():
        if len(idxs) < min_articles:
            continue
        tid = theme_of.get(cid)
        for a, b, sim in _mst(idxs, emb_n):
            edges.append({
                "a": rows[a][0], "b": rows[b][0], "w": round(float(sim), 3),
                "kind": "article", "cluster_id": cid, "theme_id": tid,
            })
    story_cent_n: dict[int, np.ndarray] = {}
    for cid in story_ids:
        cvec = emb[groups[cid]].mean(axis=0)
        nrm = float(np.linalg.norm(cvec)) or 1.0
        story_cent_n[cid] = cvec / nrm
    by_theme_cids: dict[int, list[int]] = defaultdict(list)
    for cid in story_ids:
        by_theme_cids[theme_of[cid]].append(cid)
    for tid, cids in by_theme_cids.items():
        if len(cids) < 2:
            continue
        parent = {c: c for c in cids}

        def find(x: int, _p=parent) -> int:
            while _p[x] != x:
                _p[x] = _p[_p[x]]
                x = _p[x]
            return x

        pairs = []
        for i, ca in enumerate(cids):
            na = story_cent_n[ca]
            for cb in cids[i + 1:]:
                sim = float(np.clip(na @ story_cent_n[cb], 0.0, 1.0))
                pairs.append((1.0 - sim, ca, cb, sim))
        pairs.sort()
        linked = 0
        for _, ca, cb, _sim in pairs:
            pa, pb = find(ca), find(cb)
            if pa == pb:
                continue
            parent[pa] = pb
            pair = _closest_pair(groups[ca], groups[cb], emb_n)
            if pair:
                a, b, s = pair
                edges.append({
                    "a": rows[a][0], "b": rows[b][0], "w": round(float(s), 3),
                    "kind": "story", "cluster_id": None, "theme_id": tid,
                })
            linked += 1
            if linked >= len(cids) - 1:
                break

    isolated_articles.sort(key=lambda a: (a.get("date") or "", a.get("id") or 0), reverse=True)
    return {
        "since": since.date().isoformat(), "until": now.date().isoformat(), "days": days,
        "threshold": SIM_THRESHOLD, "theme_threshold": THEME_THRESHOLD,
        "n_articles": len(rows),
        "n_clustered": int(sum(c["articles"] for c in clusters)),
        "n_singletons": n_singletons,
        "n_themes": len(themes), "n_themes_all": n_themes_all,
        "explained_variance": var, "clusters": clusters, "points": points,
        "isolated_articles": isolated_articles[:120],
        "themes": themes, "edges": edges,
        "filters": {"country": country, "outlet_id": outlet_id, "journalist_id": journalist_id},
    }
