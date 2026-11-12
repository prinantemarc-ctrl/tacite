# GUIDE DÉVELOPPEUR & PROMPT CURSOR — INDUSTRIALISATION DE TACITE HORIZON

Ce document contient :
1. **Un prompt prêt à copier-coller directement dans Cursor** pour briefer instantanément l'agent IA de développement sur tout le contexte métier, doctrinal et technique d'Horizon ;
2. **Le brief produit & client complet** (pourquoi Horizon existe, à qui il s'adresse, pourquoi les approches naïves échouent) ;
3. **La cartographie exacte du code livré** et la **feuille de route technique priorisée** pour l'industrialisation « en dur » sur le serveur de production mondial.

---

## 1. PROMPT PRÊT À COPIER-COLLER DANS CURSOR (POUR LE DÉVELOPPEUR)

> Copie-colle le bloc ci-dessous dans une nouvelle session Cursor (en mode Plan ou Agent) sur la branche `feat/horizon` (ou après merge dans `master`) :

```markdown
Tu travailles sur **Tacite**, notre plateforme d'intelligence presse multilingue, et plus précisément sur l'industrialisation en production de son nouveau module stratégique : **Tacite Horizon** (Salle de Situation géopolitique, géoéconomique et prédictive).

Avant toute proposition ou modification de code, lis intégralement ces fichiers de référence :
- @tacite_horizon_doctrine.md (Doctrine analytique & prédictive complète, formules mathématiques, critères souverains et architecture cible)
- @tacite_press_intelligence_doctrine.md (Doctrine socle de Tacite : McCombs/Shaw, Entman, ICD 203, OTAN ABCDE)
- @backend/app/services/horizon.py (Moteur actuel d'Horizon v2 : filtrage souverain, clustering sémantique trans-linguistique 384D, détection des ruptures de ligne OutletProfile, synthèse exécutive et cache PreparedView)
- @backend/app/models.py, @backend/app/worker.py et @backend/app/services/prepared.py (Modèle de données PostgreSQL + pgvector, multi-tenant RLS HasTenant, worker et vues précalculées)
- @frontend/src/pages/HorizonPage.tsx, @frontend/src/components/maps/HorizonMap.tsx et @frontend/src/i18n/bundles/horizon.ts (Interface Salle de Situation plein écran : Globe 3D / Planisphère, arcs grands cercles animés, détroits et Notes de Cabinet en 5 blocs)

### Pourquoi Horizon existe et quel est l'objectif client (CRITIQUE)
Notre richesse unique est notre base mondiale de médias (600+ titres suivis dans des dizaines de pays et de langues, avec vecteurs sémantiques multilingues 384D, cadrages politiques comparables `kits.py` et profils hebdomadaires de ligne éditoriale `OutletProfile`).
Là où le reste de Tacite sert à analyser le discours médiatique et recommander des actions d'influence presse, **Horizon transforme cette presse mondiale en capteur d'alerte précoce (Indications & Warning) et de prévision stratégique** pour des clients de niveau **gouvernemental, diplomatique, défense, renseignement économique, fonds souverains ou directions générales**.

Le client d'Horizon se moque totalement de la cuisine statistique ou médiatique :
- Il ne veut JAMAIS lire de la « météo de presse » (« 14 médias parlent de X sur un ton de -0,24 », « +18 % d'articles », « va entrer dans les grands titres »).
- Il ne veut JAMAIS voir remonter de faits divers, accidents de train/avion, catastrophes météo, sport, people ou politique municipale.
- Il ne veut JAMAIS qu'on enfonce des portes ouvertes en résumant l'actualité de la veille.
- Il veut comprendre **en 3 secondes visuellement sur le Globe 3D** où sont les vraies lignes de fracture mondiales, et lire à droite une **Note de Cabinet chirurgicale en 5 blocs** centrée sur **LE COUP D'APRÈS** :
  1. `01 · Prévision opérationnelle` : quel acte politique, militaire, diplomatique, énergétique ou réglementaire précis se prépare et sous quel délai (`14 j`, `30 j`, `60 j`), qualifié en *Probable / Possible / Sous surveillance* ;
  2. `02 · Lecture stratégique & signaux détectés` : quelle manœuvre se joue en coulisses + quelles **inflexions éditoriales inhabituelles** (`Frame Ruptures` vis-à-vis de `OutletProfile`) trahissent un changement de posture ;
  3. `03 · Trajectoires possibles` : 3 scénarios concrets mutuellement distincts (trajectoire centrale, marchandage/gestion sous seuil, rupture/désamorçage), sans pourcentages bidons ;
  4. `04 · Indicateurs de basculement (Signposts)` : le fait observable précis qui confirmera la prévision et celui qui l'invalidera ;
  5. `05 · Enjeu souverain, énergétique & économique` + dépêches primaires multi-pays vérifiables.

### Les 6 garde-fous absolus à ne jamais violer
1. **Zéro bruit civil** : conserver et enrichir le filtrage souverain strict (`INCIDENT_RE` / `SOVEREIGN_RE` + énergie sur les axes géopolitiques).
2. **Zéro jargon statistique dans l'UI** : aucun score de ton, aucun seuil mathématique, aucun compteur brut d'articles dans les textes exécutifs.
3. **Zéro faux conflit bilatéral** : ne jamais déduire un conflit entre le pays A et le pays B simplement parce qu'un journal de A mentionne B dans un article négatif. Toujours raisonner par **théâtres sémantiques multi-pays** et co-implication réelle des États.
4. **Zéro appel LLM bloquant une requête HTTP utilisateur** : le précalcul lourd et la synthèse LLM doivent tourner en tâche de fond dans `worker.py` ; `GET /api/horizon` doit répondre en `< 20 ms` depuis la base, avec timeout socket strict (`<= 12s`) et repli analytique métier (`_fallback_brief`) si le gateway LLM ralentit.
5. **Respect strict du multi-tenant & RLS PostgreSQL** : toute nouvelle table SQLAlchemy doit hériter de `HasTenant`, être ajoutée à `TENANT_MODELS` dans `backend/app/models.py` et respecter les politiques RLS de `backend/app/tenant.py`.
6. **Bilinguisme FR/EN complet et sobriété visuelle Tacite** : maintenir toutes les clés dans `frontend/src/i18n/bundles/horizon.ts` et respecter la palette carbone/bronze (`theme.ts`) en thème sombre comme en thème clair.

### Ta mission d'industrialisation (« En dur »)
À partir du prototype fonctionnel déjà en place, aide-moi à industrialiser Horizon étape par étape selon les 4 chantiers suivants :
1. **Intégration au Worker temps réel (`worker.py` & `prepared.py`)** : intégrer le rafraîchissement automatique d'Horizon (FR + EN) dans `_views_loop` (avec respect de `max_daily_cost_usd`) pour que l'ouverture d'`/horizon` soit toujours instantanée.
2. **Passage à l'échelle 600+ médias (`pgvector` HNSW & Entity Resolver)** : remplacer le clustering `scipy.pdist` en mémoire par un suivi incrémental sur PostgreSQL/pgvector capable d'absorber 100k+ articles sur 14 jours, et enrichir le résolveur d'entités souveraines (États, dirigeants, banques centrales, entreprises critiques, matières premières, détroits).
3. **Tables relationnelles & Mémoire prédictive (`horizon_dossiers`, `horizon_snapshots`, `horizon_outcomes`)** : persister les dossiers dans le temps pour suivre l'évolution d'une alerte d'une semaine à l'autre sur la frise temporelle, archiver les prévisions échues et mesurer automatiquement notre calibration (Score de Brier).
4. **Connexion transversale à l'écosystème Tacite** : ajouter les outils Horizon dans `agent_tools.py` et `mcp_server.py`, permettre l'export PDF en 1 clic d'un dossier Horizon via `reports.py`, et croiser automatiquement chaque dossier Horizon avec les `sensitive_topics` et `narratives_counter` des fiches `Client`.

Commence par inspecter les fichiers mentionnés et propose-moi ton plan d'exécution détaillé pour le Chantier 1 (ou le chantier que je t'indiquerai).
```

---

## 2. POURQUOI HORIZON A ÉTÉ CONÇU AINSI (LEÇONS DU PROTOTYPAGE)

Pour éviter au développeur de refaire des impasses déjà testées et écartées, voici les trois pièges majeurs qui ont été corrigés pendant la conception :

1. **Piège n°1 — Le comptage pays-source $\to$ pays-cible sur tonalité brute**  
   *Ce qui ne marche pas* : dire « 13 médias français mentionnent l'Espagne avec un ton moyen de -0,20, donc tension France–Espagne (probabilité 24 %) ». En réalité, il s'agissait d'un accident de train près de Tolède couvert avec tristesse par la presse française !  
   *La solution implémentée dans `horizon.py`* : porte de gravité souveraine stricte en entrée + regroupement par **événements sémantiques trans-linguistiques** (`cosine >= 0.75` sur les vecteurs `384D`) + extraction pondérée des acteurs étatiques réellement au cœur de la manœuvre.

2. **Piège n°2 — Les phrases au pochoir / statistiques médiatiques**  
   *Ce qui ne marche pas* : afficher des pourcentages arbitraires (`22 %`, `27 %`), des scores (`-0,15`) ou la même phrase mécanique répétée sur 10 lignes (*« D'ici deux semaines, le sujet X quitte la presse spécialisée et entre dans les grands titres »*). Pour un client étatique, cela n'a aucune valeur.  
   *La solution implémentée* : formulation en **Note de Cabinet à 5 blocs** orientée action souveraine, combinant une synthèse LLM unitaire ultra-cadrée (`HORIZON_SINGLE_SYSTEM_FR/EN`) et un moteur analytique de repli par archétypes géopolitiques (`_fallback_brief`) exploitant les vrais acteurs, organisations, dirigeants et ruptures éditoriales du cluster.

3. **Piège n°3 — Les timeouts de modèles à raisonnement caché**  
   *Ce qui ne marche pas* : envoyer un gros batch JSON de 10 dossiers bilingues à un modèle « thinking » lent qui sature les tokens de réflexion interne ou bloque la requête HTTP pendant 3 minutes.  
   *La solution implémentée* : appels unitaires courts avec `chat_template_kwargs: {"enable_thinking": False}` sur `deepseek-v4-flash`, timeout socket strict `httpx.Timeout(12.0, connect=4.0)` sans retry bloquant, et mise en cache persistante dans `PreparedView` (`~10 ms` au chargement de la page).

---

## 3. CARTOGRAPHIE EXACTE DES FICHIERS LIVRÉS SUR LA BRANCHE `feat/horizon`

| Fichier | Rôle exact |
|---|---|
| `tacite_horizon_doctrine.md` | Manuel complet de la doctrine analytique et prédictive (5 piliers théoriques, équations exactes du pipeline, Note de Cabinet 5 blocs, sémiotique visuelle, backtest Brier et schéma SQL cible). |
| `frontend/public/tacite_horizon_doctrine.md` | Copie statique publique de la doctrine Horizon (alignée sur `tacite_press_intelligence_doctrine.md`). |
| `HORIZON_CURSOR_PROMPT.md` | Ce document : prompt Cursor clé-en-main + contexte produit + feuille de route d'industrialisation. |
| `backend/app/services/horizon.py` | Moteur complet d'Horizon v2 : filtrage souverain, résolveur multilingue d'acteurs et de détroits (`CHOKEPOINTS`), clustering vectoriel 384D, calcul d'accélération $J-14$ vs $J-28$, détection des ruptures de ligne `OutletProfile`, synthèse exécutive et persistance `PreparedView`. |
| `backend/app/main.py` | Exposition de l'endpoint `GET /api/horizon?as_of=YYYY-MM-DD&refresh=bool`. |
| `backend/app/data/countries.json` & `.gitignore` | Référentiel ISO 3166-1 + centroïdes géographiques versionné proprement (`/data/` au lieu de `data/` dans `.gitignore`). |
| `frontend/src/pages/HorizonPage.tsx` | Page Salle de Situation plein écran : barre de contrôle (`Globe 3D / Planisphère`, `Situation / Prévision`, filtres par théâtre, bouton d'actualisation), bandeau exécutif, frise temporelle Passé ↔ Projection, liste des dossiers et Note de Cabinet détaillée en 5 blocs + lien direct vers l'Assistant. |
| `frontend/src/components/maps/HorizonMap.tsx` | Composant D3 + TopoJSON : Globe orthographique interactif avec **auto-rotation vers le dossier cliqué**, Planisphère `Equal Earth`, arcs grands cercles animés avec flèches et délais, enveloppes de coalitions, losanges pulsants sur les détroits. |
| `frontend/src/i18n/bundles/horizon.ts` | Dictionnaire bilingue complet (FR / EN) de la Salle de Situation. |
| `frontend/src/Layout.tsx`, `main.tsx`, `api.ts`, `messages.ts`, `MethodPage.tsx`, `bundles/method.ts` | Intégration dans la barre latérale (`06 Horizon` en mode `fullBleed`), routeur React, client API et section dédiée dans la page **Méthode**. |

---

## 4. CHECKLIST D'ACCEPTATION POUR LA MISE EN PRODUCTION (« DEFINITION OF DONE »)

Avant de considérer l'intégration « en dur » terminée sur le nouveau serveur de production, vérifier que :

- [ ] **Worker automatique** : `_views_loop` rafraîchit Horizon toutes les heures (FR + EN) ; un utilisateur ouvrant `/horizon` obtient toujours une réponse `< 20 ms` sans déclencher d'appel LLM synchrone.
- [ ] **Échelle 600+ médias** : le temps de calcul du clustering en arrière-plan reste `< 10 s` même avec 100 000 articles sur 14 jours (grâce à `pgvector` HNSW).
- [ ] **Continuité temporelle** : un dossier détecté lundi conserve le même `id` et historise l'évolution de sa vraisemblance (`Sous surveillance` $\to$ `Possible` $\to$ `Probable`) dans `horizon_snapshots`.
- [ ] **Croisement Clients** : si un dossier Horizon impacte un pays, un secteur ou un `sensitive_topic` d'un dossier `Client` Tacite, une pastille d'exposition client apparaît dans le Bloc 05 de la fiche.
- [ ] **Assistant & Rapports PDF** : l'assistant `⌘K` peut interroger directement les prévisions Horizon via `agent_tools.py`, et un bouton permet d'exporter n'importe quel dossier Horizon en Note PDF officielle Tacite.
