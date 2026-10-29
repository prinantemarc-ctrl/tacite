/**
 * Glossaire Tacite — source unique des définitions.
 * `short` : une phrase, affichée au survol d'un terme.
 * `long`  : définition complète + méthode de calcul, pour les « ? » de carte et la page Méthode.
 * `group` : rubrique de la page Méthode.
 */

import { GLOSSARY_EN, GROUP_LABELS_EN } from "./i18n/glossary-en";
import { getLocale } from "./i18n/locale";

export type Term = { label: string; short: string; long: string; group: Group };
export type Group = "positions" | "axes" | "influence" | "journalists" | "client" | "map" | "pipeline" | "assistant";

export const GROUP_LABELS: Record<Group, string> = {
  positions: "Positions et écarts",
  axes: "Les douze axes de cadrage",
  influence: "Influence",
  journalists: "Journalistes",
  client: "Client, positions et actions",
  map: "Cartographie",
  pipeline: "Collecte et analyse",
  assistant: "Assistant et rapports",
};

export const GLOSSARY: Record<string, Term> = {
  /* ───────────────── positions */
  declared: {
    group: "positions", label: "Ligne déclarée",
    short: "Ce qu'un média dit être, ou ce pour quoi il est publiquement connu, sur les 12 axes.",
    long: "Position éditoriale annoncée ou communément admise d'un média, traduite sur les 12 axes entre −1 et +1. Renseignée à la création du média — par vous, ou estimée par le LLM à partir de l'orientation déclarée (ex. « centre-droit, libéral »). Elle ne bouge pas : c'est le point de référence auquel on compare ce que le média écrit réellement.",
  },
  measured: {
    group: "positions", label: "Ligne mesurée",
    short: "Ce que Tacite lit effectivement dans les articles de la période.",
    long: "Position calculée sur les articles analysés. Chaque article reçoit un cadrage sur les 12 axes (noté sur l'angle, le vocabulaire et le choix des sources, pas sur le sujet). La position mesurée d'un média est, pour chaque axe, la moyenne des valeurs non nulles de ses articles sur la période. Elle est recalculée chaque semaine. Une valeur proche de 0 signifie soit un traitement équilibré, soit un axe peu abordé.",
  },
  gap: {
    group: "positions", label: "Écart",
    short: "Mesuré − déclaré, par axe. Notable au-delà de 0,30, fort au-delà de 0,50.",
    long: "Différence entre la ligne mesurée et la ligne déclarée, axe par axe. Un écart positif signifie que le média se lit plus « + » (pôle de droite de la ligne) qu'il ne l'annonce ; négatif, plus « − ». Sous 0,30 : cohérent (gris). Entre 0,30 et 0,50 : notable (bronze). Au-dessus de 0,50 : fort (rouge sourd). L'écart max. d'un média est le plus grand écart absolu parmi les axes assez renseignés (≥ 10 articles non nuls), nommé par son axe. Laïcité et Institutions sont ignorés hors FR/BE/CH/LU.",
  },
  outlet_topics: {
    group: "positions", label: "Sujets de prédilection",
    short: "Thèmes les plus fréquents dans les articles du média sur 8 semaines.",
    long: "Les trois thèmes les plus souvent extraits des articles analysés du média, sur les huit dernières semaines. Ce n'est pas la ligne éditoriale : c'est l'agenda — ce dont le titre parle, pas comment il le cadre. Les articles hors champ (sport, lifestyle) sont exclus. Un média fixé sur deux ou trois sujets est prévisible ; un agenda éclaté l'est moins.",
  },
  gap_exploitable: {
    group: "positions", label: "Écart exploitable",
    short: "Seuil au-delà duquel un écart devient une prise pour une action (0,35 par défaut).",
    long: "Seuil, réglable et ajusté automatiquement par l'apprentissage, à partir duquel le moteur de recommandation considère qu'un écart entre ligne déclarée et ligne mesurée peut être utilisé : un média qui se dit d'un bord mais écrit autrement offre un angle d'approche.",
  },
  confidence: {
    group: "positions", label: "Confiance",
    short: "Fiabilité de la mesure selon le nombre d'articles : faible < 10, moyenne 10–29, élevée ≥ 30.",
    long: "La position mesurée n'a de sens qu'avec assez d'articles. Moins de 10 articles analysés sur la période : confiance faible, le point est affiché estompé et les écarts ne doivent pas être interprétés. De 10 à 29 : moyenne. 30 et plus : élevée. La confiance est aussi calculée par axe (nombre d'articles non nuls) : un axe peu renseigné affiche « — » et n'entre pas dans l'écart max.",
  },
  drift: {
    group: "positions", label: "Dérive",
    short: "Variation hebdomadaire d'un axe supérieure au seuil de dérive (0,30 par défaut).",
    long: "Changement de la position mesurée d'un média sur un axe entre deux semaines consécutives, quand il dépasse le seuil de dérive réglé dans Paramètres. Une dérive signale un changement de ton ou d'agenda récent, indépendamment de la position absolue. Les dérives récentes apparaissent sur le tableau de bord et dans le récap médias.",
  },
  landscape_mean: {
    group: "positions", label: "Moyenne du paysage",
    short: "Position moyenne de tous les médias suivis sur un axe.",
    long: "Moyenne des positions mesurées de l'ensemble des médias documentés sur un axe. Sert de repère : un média « au centre » de Tacite est au centre du paysage suivi, pas nécessairement au centre de l'échiquier politique.",
  },

  /* ───────────────── axes */
  axes: {
    group: "axes", label: "Axes de cadrage",
    short: "Douze dimensions, chacune de −1 (pôle « − ») à +1 (pôle « + »). Aucun pôle n'est bon ou mauvais.",
    long: "Le cadrage d'un article est noté sur douze axes indépendants, de −1 à +1. Il porte sur la manière de traiter (angle, vocabulaire, sources) et non sur le sujet : un article sur l'immigration peut être noté 0 sur Immigration s'il ne prend pas parti. Les pôles : Économie (libéral ↔ interventionniste) · Société (conservateur ↔ progressiste) · Immigration (restrictif ↔ accueillant) · Europe (souverainiste ↔ fédéraliste) · Écologie (éco-sceptique ↔ éco-militant) · Sécurité (sécuritaire ↔ libertés) · Laïcité (stricte ↔ ouverte) · International (atlantiste ↔ non-aligné) · Institutions (présidentiel ↔ parlementaire) · Médias (défiant ↔ confiant) · Justice (ordre ↔ réforme) · Technologie (technophile ↔ technocritique). Laïcité et Institutions sont franco-centrés : hors France, Belgique, Suisse et Luxembourg, ils ne servent ni à l'écart max. ni aux insights de cartographie.",
  },
  framing: {
    group: "axes", label: "Cadrage",
    short: "Façon dont un article traite son sujet, notée sur les 12 axes.",
    long: "Pour chaque article, le LLM identifie jusqu'à trois thèmes et note pour chacun le cadrage sur les 12 axes ; le cadrage de l'article est la moyenne par axe des valeurs non nulles. C'est la brique de base de toutes les positions mesurées.",
  },

  /* ───────────────── influence */
  influence: {
    group: "influence", label: "Score d'influence",
    short: "0–100. Somme pondérée de six composantes : audience, citations, agenda, élites, réseau, longévité.",
    long: "Capacité d'un média à peser sur le débat. Somme pondérée de six composantes notées 0–100 : audience 20 %, citations 25 %, agenda 20 %, élites 15 %, réseau 10 %, longévité 10 % (pondérations modifiables dans Paramètres). Le rang est la place du média dans le classement des médias suivis.",
  },
  comp_audience: {
    group: "influence", label: "Audience",
    short: "Portée estimée du média auprès du grand public.",
    long: "Composante d'influence : taille du lectorat / de l'audience. Renseignée à la création du média ou estimée par le LLM. Statique.",
  },
  comp_citation: {
    group: "influence", label: "Citations",
    short: "Combien de fois les autres médias reprennent ou mentionnent ce média sur la période.",
    long: "Composante d'influence, mesurée : nombre d'articles d'autres médias qui citent ce média. Échelle ancrée (logarithmique, plafond 40 citations/semaine = 100), sans renormalisation min-max du corpus. Recalculée chaque semaine.",
  },
  comp_agenda: {
    group: "influence", label: "Agenda",
    short: "Capacité à traiter un sujet avant les autres.",
    long: "Composante d'influence, mesurée : part des sujets repris par plusieurs médias sur lesquels ce média a été le premier à publier. Voir « Qui donne le ton » dans Cartographie › Analyses.",
  },
  comp_elite: {
    group: "influence", label: "Élites",
    short: "Poids auprès des décideurs (politiques, économiques, administratifs).",
    long: "Composante d'influence : lectorat décideur. Un média peu lu mais lu par les cabinets pèse plus qu'un média populaire sur certaines questions. Renseignée ou estimée, statique.",
  },
  comp_network: {
    group: "influence", label: "Réseau",
    short: "Densité des liens avec les autres titres (groupe, reprises, partenariats).",
    long: "Composante d'influence : insertion du média dans l'écosystème (appartenance à un groupe, reprises croisées, partenariats). Renseignée ou estimée, statique.",
  },
  comp_longevity: {
    group: "influence", label: "Longévité",
    short: "Ancienneté et stabilité du titre.",
    long: "Composante d'influence : ancienneté, continuité éditoriale, stabilité économique. Un titre centenaire a une autorité qu'un pure player n'a pas encore. Renseignée ou estimée, statique.",
  },

  /* ───────────────── journalistes */
  accessibility: {
    group: "journalists", label: "Accessibilité",
    short: "0–100. Probabilité qu'un journaliste soit réceptif à une sollicitation. Seuil de pitch : 55.",
    long: "Estimation par le LLM, à partir des articles signés, de la réceptivité d'un journaliste à une approche. Élevée s'il est productif, généraliste, s'appuie sur des sources variées ou institutionnelles (communiqués, experts). Faible s'il est enquêteur, très spécialisé, ou travaille sur sources d'élite et anonymes. Le moteur ne propose une action « Nourrir » ou « Amorcer » qu'au-dessus du seuil de pitch (55 par défaut, ajusté par apprentissage).",
  },
  beat: {
    group: "journalists", label: "Beat",
    short: "Spécialité du journaliste (Politique, Économie, International…), déduite de ses articles.",
    long: "Rubrique dominante d'un journaliste, déduite par le LLM de ses articles lors de l'enrichissement. Champ dédié `beat` (plus le hack « [Politique] … » en tête de bio, encore lu en rétrocompatibilité).",
  },
  themes: {
    group: "journalists", label: "Fixations",
    short: "Thèmes qui reviennent le plus dans la production du journaliste.",
    long: "Les thèmes les plus fréquents dans les articles du journaliste sur la période, avec leur nombre d'occurrences. Un journaliste fixé sur un sujet est prévisible — et joignable sur ce sujet.",
  },
  sources: {
    group: "journalists", label: "Sources privilégiées",
    short: "Types de sources qu'il mobilise : gouvernement, expert, anonyme, ONG, entreprise…",
    long: "Répartition des types de sources citées dans ses articles (gouvernement, anonyme, expert, ONG, entreprise, judiciaire, syndicat, parti, citoyen, média). Un journaliste qui travaille sur communiqués et experts est plus accessible qu'un journaliste sur sources anonymes.",
  },
  biases: {
    group: "journalists", label: "Biais récurrents",
    short: "Angles systématiques repérés dans sa production.",
    long: "Régularités de traitement repérées par le LLM sur l'ensemble des articles (ex. « privilégie systématiquement le point de vue syndical », « angle économique sur les sujets sociaux »). Ce sont des tendances, pas des jugements.",
  },
  vulnerabilities: {
    group: "journalists", label: "Vulnérabilités",
    short: "Traits exploitables : en quête de reconnaissance, réactif aux exclusivités, en recherche de sujet…",
    long: "Leviers d'approche identifiés par le LLM à partir de la production : appétence pour l'exclusivité, besoin de matière, réactivité aux angles nouveaux, recherche de visibilité. Utilisés par le moteur pour choisir le journaliste d'entrée d'une action.",
  },
  tone: {
    group: "journalists", label: "Ton dominant",
    short: "Émotion la plus fréquente dans ses articles (neutre, indignation, inquiétude, espoir…).",
    long: "Chaque article reçoit un ton (un mot : neutral, indignation, concern, hope, fear…). Le ton dominant d'un journaliste est le plus fréquent sur la période.",
  },
  dissident: {
    group: "journalists", label: "Dissident",
    short: "Journaliste dont le cadrage s'écarte nettement de la ligne mesurée de son média (écart > 0,35).",
    long: "Journaliste (≥ 5 articles) dont la position mesurée personnelle est éloignée de celle de son média : distance moyenne sur les 12 axes supérieure à 0,35. L'axe de divergence indique où il s'écarte le plus et dans quel sens. Souvent la meilleure porte d'entrée dans un média globalement hostile.",
  },
  productivity: {
    group: "journalists", label: "Productivité",
    short: "Nombre d'articles signés par semaine.",
    long: "Articles signés sur les 7 derniers jours. Un journaliste très productif a besoin de matière — il est plus accessible.",
  },
  top_journalists: {
    group: "journalists", label: "Journalistes les plus actifs",
    short: "Signatures les plus productives du média sur 8 semaines.",
    long: "Les journalistes qui ont signé le plus d'articles du média sur les huit dernières semaines, y compris en co-signature. Le récap affiche les trois premiers ; la fiche les classe tous par volume. C'est une porte d'entrée : un journaliste très productif a généralement besoin de matière.",
  },

  /* ───────────────── client */
  stance: {
    group: "client", label: "Position vis-à-vis du client",
    short: "Hostile (< −0,15), neutre, ou favorable (> +0,15) sur les sujets du client.",
    long: "Lecture, média par média, du traitement des sujets du client (narratifs à pousser, à contrer, sujets sensibles) : score de −1 à +1. Hostile en dessous de −0,15, favorable au-dessus de +0,15, neutre entre. La carte stratégique croise cette position avec l'influence.",
  },
  actions: {
    group: "client", label: "Actions",
    short: "Neuf verbes, trois niveaux de risque, du Nourrir (livrer une exclusivité) à l'Isoler (marginaliser un média).",
    long: "Risque faible — Nourrir : livrer une information exclusive à un journaliste réceptif. Amorcer : semer un angle narratif. Surveiller : observer sans agir. Risque moyen — Coopter : rallier un média ou un journaliste à la cause. Contourner : passer par un autre canal que le média hostile. Diluer : multiplier les voix pour noyer un narratif adverse. Risque élevé — Retourner : inverser la position d'un média. Diviser : opposer des journalistes ou des rédactions. Isoler : marginaliser un média hostile.",
  },
  risk: {
    group: "client", label: "Risque",
    short: "Exposition de l'action. Rabattue automatiquement si elle dépasse la tolérance du client.",
    long: "Chaque action a un niveau de risque (faible, moyen, élevé) : risque d'être identifié, de provoquer une réaction, de dégrader la relation. Si l'action recommandée dépasse la tolérance au risque du client, le moteur la rabat sur une action moins exposée : Retourner → Coopter → Nourrir ; Diviser → Contourner → Amorcer ; Isoler → Diluer → Surveiller.",
  },
  priority: {
    group: "client", label: "Priorité",
    short: "Score qui ordonne les recommandations : influence × écart exploitable × accessibilité.",
    long: "Combinaison de l'influence du média (plus il pèse, plus l'action compte), de l'écart exploitable (plus il est grand, plus il y a prise) et de l'accessibilité du journaliste d'entrée. Les recommandations sont affichées par priorité décroissante.",
  },
  adaptive: {
    group: "client", label: "Seuils adaptatifs",
    short: "Le moteur ajuste ses seuils selon les résultats enregistrés (succès, partiel, échec).",
    long: "Quand une action est marquée Succès, Partiel ou Échec, le résultat alimente l'historique. Le moteur relève ou abaisse ensuite le seuil de pitch et le seuil d'écart exploitable : si les actions sur des journalistes à 55 d'accessibilité échouent, le seuil monte. C'est la boucle d'apprentissage.",
  },
  narratives: {
    group: "client", label: "Narratifs",
    short: "À pousser : ce que le client veut voir écrit. À contrer : ce qu'il veut voir disparaître.",
    long: "Le dossier client décrit les narratifs à pousser, les narratifs à contrer et les sujets sensibles. Ils servent à calculer la position de chaque média vis-à-vis du client et à orienter les plans d'action.",
  },
  exposure: {
    group: "client", label: "Exposition",
    short: "Niveau d'exposition médiatique habituel du client.",
    long: "Faible, moyen ou élevé. Un client très exposé attire la couverture sans effort mais subit davantage les angles hostiles ; le moteur pondère l'urgence des actions en conséquence.",
  },

  /* ───────────────── carto */
  positions_view: {
    group: "map", label: "Positions par axe",
    short: "Une ligne par axe, tous les médias dessus. Aucune transformation : ce qu'on voit est ce qui a été mesuré.",
    long: "Vue de référence de la cartographie. Chaque ligne est un axe, du pôle « − » à gauche au pôle « + » à droite. Point plein = position mesurée (taille = influence), cercle creux = ligne déclarée, trait bronze = moyenne du paysage. Les lignes sont triées par dispersion : l'axe qui divise le plus les médias est en haut. Sélectionner un média trace son déclaré → mesuré sur les 12 lignes.",
  },
  projection: {
    group: "map", label: "Projection (ACP)",
    short: "Réduction des 12 axes à un plan. Seule la proximité entre points a un sens.",
    long: "Analyse en composantes principales : les 12 axes sont combinés en deux dimensions qui conservent le maximum d'information. Les axes du plan n'ont pas de nom ; deux points proches ont des cadrages proches, c'est tout ce qu'il faut lire. La variance expliquée indique la part d'information conservée (ex. 45 % / 23 %). Pour lire axe par axe, utiliser Positions.",
  },
  topic_cluster: {
    group: "map", label: "Sujet (affaire)",
    short: "Une affaire, éventuellement regroupée dans une famille plus large.",
    long: "Deux niveaux. Une affaire regroupe les articles au cosinus ≥ 0,80 (liaison complète), puis recolle les paquets au libellé presque identique (« Canada-EU » / « EU-Kanada »). Un article sort du paquet s'il a à la fois un libellé et des entités disjoints du reste (veto : le plongement seul ne suffit plus). Une famille ne réunit des affaires que si toutes sont proches (cosinus ≥ 0,55, liaison complète) ; elle porte un nom d'ensemble (tokens et entités partagés), distinct des affaires qu'elle contient. Seules les 16 familles les plus couvertes sont nommées.",
  },
  topic_heat: {
    group: "map", label: "Chaleur d'un sujet",
    short: "Volume de la période comparé à la période précédente de même durée.",
    long: "Pour chaque affaire, on compte les articles de la fenêtre précédente dont le plongement est assez proche du centroïde (même seuil 0,80). Émergent : rien avant. En hausse : au moins ×1,5. En baisse : ×0,7 ou moins. Stable sinon. Indépendant du libellé : une affaire qui change de nom d'un jour à l'autre reste suivie.",
  },
  topic_polarization: {
    group: "map", label: "Polarisation d'un sujet",
    short: "Les médias cadrent-ils cette affaire de la même façon ?",
    long: "Écart-type moyen, sur les 12 axes, des cadrages moyens par média à l'intérieur du cluster. Proche de 0 : consensus de traitement. Élevé : le sujet clive. Complète le volume : un sujet très couvert et peu polarisé est un air du temps ; très couvert et polarisé, un conflit.",
  },
  cluster: {
    group: "map", label: "Bloc éditorial",
    short: "Groupe de médias aux cadrages proches, formé automatiquement.",
    long: "Regroupement automatique (k-moyennes) des médias documentés sur leur position mesurée. Nommé par les deux axes où le bloc s'écarte le plus de la moyenne du paysage (« plus accueillant · plus éco-militant »). Affiché seulement si le découpage est net : silhouette ≥ 0,30 et aucun bloc au-dessus de 60 % des médias.",
  },
  silhouette: {
    group: "map", label: "Silhouette",
    short: "Netteté d'un regroupement, de −1 à 1. Au-dessus de 0,30 : blocs distincts.",
    long: "Mesure de qualité d'un regroupement : compare la distance d'un média aux membres de son bloc et aux membres du bloc voisin. Proche de 1, les blocs sont bien séparés ; proche de 0, ils se chevauchent ; négatif, le découpage n'a pas de sens.",
  },
  pagerank: {
    group: "map", label: "PageRank",
    short: "Importance dans le réseau des citations : être cité par des médias eux-mêmes cités compte plus.",
    long: "Algorithme de centralité appliqué au graphe des citations entre médias. Un média cité par Le Monde pèse plus qu'un média cité par un titre marginal. La taille des cercles du Réseau est proportionnelle au PageRank.",
  },
  community: {
    group: "map", label: "Communauté",
    short: "Groupe de médias qui se citent et se recoupent entre eux plus qu'avec le reste.",
    long: "Détection de communautés (méthode de Louvain) sur le graphe combinant citations et co-couverture. Les membres d'une communauté partagent un écosystème : mêmes sources, mêmes reprises, mêmes sujets. Distinguées par le remplissage et le trait des cercles.",
  },
  cocoverage: {
    group: "map", label: "Co-couverture",
    short: "Part des thèmes communs entre deux médias (indice de Jaccard sur leurs 40 thèmes principaux).",
    long: "Deux médias sont liés en co-couverture quand leurs 40 thèmes les plus fréquents se recoupent à plus de 12 %. Trait pointillé gris dans le Réseau. Traduit un agenda partagé, indépendamment du cadrage.",
  },
  leadlag: {
    group: "map", label: "Qui donne le ton (lead / lag)",
    short: "Sur chaque sujet repris sous 72 h par plusieurs médias, le premier « mène », les autres « suivent ».",
    long: "Pour chaque thème, les articles sont ordonnés dans le temps ; quand au moins deux médias publient dans une fenêtre de 72 h, le premier mène, les suivants suivent. Ratio = part des événements où le média est premier. Retard médian = délai typique de reprise quand il suit. « Qui suit qui » compte les paires meneur → suiveur.",
  },
  pack: {
    group: "map", label: "Meute",
    short: "Paire de médias qui traitent systématiquement les mêmes sujets.",
    long: "Deux médias forment une meute quand la similarité de leurs thèmes (cosinus sur la fréquence des thèmes, 60 jours) est élevée. La similarité de cadrage indique s'ils les traitent de la même manière : une meute à cadrage opposé est un débat ; à cadrage identique, un écho.",
  },
  similarity: {
    group: "map", label: "Similarité thèmes / cadrage",
    short: "Ressemblance de deux médias par ce qu'ils traitent (thèmes) et par la façon dont ils le traitent (cadrage).",
    long: "Matrice de proximité : chaque case compare deux médias. Thèmes : cosinus entre leurs profils de fréquence des thèmes (0 = rien en commun, 100 % = mêmes sujets dans les mêmes proportions). Cadrage : cosinus entre leurs positions mesurées (−100 % = opposés, +100 % = identiques). L'ordre des lignes vient d'un regroupement hiérarchique : les médias voisins dans la matrice sont voisins dans les faits.",
  },
  corpus: {
    group: "map", label: "Carte du corpus",
    short: "Chaque point est un article, placé par proximité de sens. Les zones denses sont les sujets saturés.",
    long: "Les articles sont représentés par un plongement sémantique (vecteur de 384 dimensions calculé localement), projeté en deux dimensions. Deux articles proches parlent de la même chose. Les nappes bronze indiquent la densité : là où la presse s'entasse. Les étiquettes marquent le barycentre des thèmes fréquents.",
  },
  blindspot: {
    group: "map", label: "Angle mort",
    short: "Thème récurrent (≥ 3 articles) traité par un seul média.",
    long: "Sujet qui revient chez un seul média et nulle part ailleurs. Pour le client, c'est un espace libre : un angle sur lequel il n'y a pas encore de concurrence narrative — ou un signal que ce média prépare quelque chose.",
  },
  valence: {
    group: "map", label: "Valence",
    short: "Tonalité moyenne des articles qui citent une entité, de −1 (indignation, peur) à +1 (espoir).",
    long: "Chaque ton d'article est converti en valeur (neutral 0, hope +1, indignation −1, concern −0,5, fear −0,8…). La valence d'une entité chez un média est la moyenne sur les articles de ce média qui la citent. La dispersion mesure à quel point les médias divergent sur cette entité : forte dispersion = personnage clivant.",
  },
  world: {
    group: "map", label: "Carte du monde",
    short: "Pays teintés et cerclés selon l'influence cumulée, le nombre de médias, d'articles ou de journalistes. Flèches = citations transfrontalières.",
    long: "Projection Equal Earth. La teinte et la taille des cercles suivent la mesure choisie. Les flèches relient le pays d'un média citant au pays du média cité, hors citations domestiques : elles montrent qui regarde qui. Tacite couvre les 249 pays et territoires ISO ; un pays apparaît dès qu'il a un média suivi.",
  },

  /* ───────────────── pipeline */
  status_analyzed: {
    group: "pipeline", label: "Analysé",
    short: "Article passé au LLM : thèmes, cadrage, sources, ton, angle, entités.",
    long: "Statut d'un article dont le texte a été extrait et soumis au modèle de langage. C'est la seule catégorie qui alimente les positions mesurées et les profils.",
  },
  status_embedded: {
    group: "pipeline", label: "Hors champ",
    short: "Article détecté comme non politique (sport, météo, people…), indexé sans appel au LLM.",
    long: "Un filtre lexical repère les articles clairement hors du champ politique et d'actualité. Ils sont plongés sémantiquement (pour la recherche et les doublons) mais pas analysés — ce qui évite de payer un appel LLM pour un résultat de foot.",
  },
  status_duplicate: {
    group: "pipeline", label: "Doublon",
    short: "Reprise quasi identique d'un article déjà en base (similarité sémantique très élevée).",
    long: "Détection par plongement : un article dont le vecteur est presque identique à un article récent est marqué doublon et rattaché à l'original. Évite de compter trois fois la même dépêche reprise par trois titres.",
  },
  status_pending: {
    group: "pipeline", label: "En attente",
    short: "Capturé mais pas encore analysé — le worker traite par lots.",
    long: "Les articles sont analysés par lots (taille réglable) à intervalle régulier, dans la limite du plafond de coût quotidien.",
  },
  angle: {
    group: "pipeline", label: "Angle journalistique",
    short: "Genre de l'article : enquête, éditorial, brève, analyse, opinion, réaction.",
    long: "Classification du genre : investigation (enquête), editorial, brief (brève), analysis, opinion, reaction. Un média qui ne produit que des brèves reprend ; un média qui produit des enquêtes fait l'agenda.",
  },
  llm_cost: {
    group: "pipeline", label: "Coût LLM et plafond",
    short: "Dépense estimée des appels au modèle ; au-delà du plafond quotidien, l'analyse attend le lendemain.",
    long: "Chaque appel est comptabilisé (jetons en entrée et en sortie × tarif du modèle). Le plafond quotidien, réglable dans Paramètres, met l'analyse et l'enrichissement en pause quand il est atteint ; la collecte continue. 0 = pas de plafond.",
  },
  sources_ingest: {
    group: "pipeline", label: "Sources de collecte",
    short: "Flux RSS, Google News, GDELT, et navigateur sans interface pour les sites sans flux.",
    long: "Par média, un ou plusieurs flux RSS (par rubrique) ; à défaut ou en complément, la recherche Google News « site: », la base GDELT, et un navigateur automatisé (Playwright) qui charge les pages rendues en JavaScript et écarte les bandeaux de cookies. Les articles sont dédoublonnés par URL puis par sens.",
  },
};

GLOSSARY.assistant = {
  group: "assistant", label: "Assistant",
  short: "Agent conversationnel : il lit toutes les données Tacite et le web, produit graphiques, fichiers et rapports, et modifie la base après confirmation.",
  long: "Le modèle Aleria choisit lui-même les outils à appeler : fiches médias et journalistes, recherche d'articles par le sens, cartographie, dossiers clients, requête SQL en lecture seule, Google News, GDELT, lecture d'URL. Il cite ses sources (liens vers les fiches et articles, URL web). Il ne devine pas de chiffres : ce qu'il n'a pas, il va le chercher. Le contexte de la conversation est conservé d'un message à l'autre ; ⌘K ouvre l'assistant en panneau latéral avec la fiche courante épinglée.",
};
GLOSSARY.agent_confirm = {
  group: "assistant", label: "Modification proposée",
  short: "Toute écriture demandée à l'assistant est d'abord proposée ; elle ne s'applique qu'après votre clic « Appliquer ».",
  long: "Quand l'assistant veut modifier un média, un journaliste, un client, une recommandation, un réglage ou lancer une tâche, il crée une action « proposée » avec une description exacte du changement. Vous l'appliquez ou la refusez dans la conversation. Les actions appliquées sont journalisées (avant / après) et la plupart peuvent être annulées en un clic. Le réglage « Confirmation des écritures » permet d'appliquer directement, à vos risques.",
};
GLOSSARY.report = {
  group: "assistant", label: "Rapport",
  short: "PDF dans la charte Tacite : faits collectés automatiquement, graphiques, rédaction par le modèle contrainte aux faits.",
  long: "Six modèles : note média, dossier journaliste, brief client, panorama du paysage (tous pays, ou un pays au filtre), panorama pays (médias suivis d'un État : positions, meneurs, thèmes, journalistes, flux transfrontaliers), note thématique (sujet libre, base + web, filtre pays optionnel). La collecte passe par les mêmes outils que l'assistant ; le modèle rédige les sections à partir de ces seuls faits, puis la mise en page ajoute chiffres clés, radar déclaré/mesuré, bandes par axe, barres. Chaque rapport est conservé dans Rapports avec sa version HTML.",
};
GLOSSARY.collect_modes = {
  group: "pipeline", label: "Modes de collecte",
  short: "Flux RSS ✓ = articles reçus directement (15 min). Collecte indirecte = via Google News, GDELT et scraping. Accès robot bloqué = par navigateur automatisé.",
  long: "Quand un média est proposé à l'ajout, son site et ses flux sont testés un par un — jamais supposés. Trois issues possibles. Flux RSS ✓ : au moins un flux fonctionne, les articles arrivent directement toutes les 15 minutes — le meilleur cas. Collecte indirecte : le site répond mais n'expose pas de flux ; les articles arrivent par la recherche Google News sur le domaine (2 h), la base GDELT (6 h) et le scraping de la page d'accueil (1 h) — un peu plus lent, un peu moins complet. Accès robot bloqué : le site fonctionne dans un navigateur mais refuse les requêtes automatiques (HTTP 403) ; la collecte passe alors par le navigateur automatisé (Playwright) et Google News. Injoignable : le site n'a pas répondu — la raison précise est affichée (domaine introuvable, délai dépassé, erreur serveur) et « Réessayer » relance le test.",
};
GLOSSARY.contact_channels = {
  group: "journalists", label: "Canaux de contact",
  short: "E-mail, X, Bluesky, Mastodon, LinkedIn… d'un journaliste, chacun avec sa preuve : source, méthode, niveau de confiance.",
  long: "Tacite ne devine jamais un contact. Les canaux viennent de sources vérifiables : données structurées des articles signés (JSON-LD), liens du bloc signature, page auteur du média, mailto au nom du journaliste, texte des articles (« contactez-moi : … »), recherche publique Bluesky (profil dont la bio cite le média), et saisie manuelle. Un motif d'adresse observé sur au moins deux e-mails vérifiés d'un média permet de proposer l'adresse des autres journalistes, étiquetée « déduit ». La détection tourne en tâche de fond (40 journalistes par heure, les plus productifs d'abord) et se lance à la demande sur une fiche.",
};
GLOSSARY.contact_confidence = {
  group: "journalists", label: "Vérifié · Probable · Déduit",
  short: "Vérifié = lien attaché à la signature ou page auteur. Probable = texte d'article ou recherche publique. Déduit = motif d'adresse, à vérifier.",
  long: "Vérifié : le canal est physiquement rattaché au journaliste par le média lui-même (signature, page auteur, données structurées) ou saisi par vous. Probable : trouvé dans le texte d'un article, ou profil public dont la bio cite le média — forte présomption, pas de preuve directe. Déduit : adresse construite à partir du motif du média (prenom.nom@…) ; utile pour un premier envoi, à confirmer. Un canal peut être marqué invalide : il reste visible barré, n'est plus proposé ni compté.",
};
GLOSSARY.artifact = {
  group: "assistant", label: "Fichier produit",
  short: "CSV, Excel, Markdown, Word, HTML ou PDF créé par l'assistant, téléchargeable et conservé dans Rapports.",
  long: "L'assistant peut mettre n'importe quel résultat dans un fichier : exports de listes (CSV, XLSX), notes rédigées (Markdown, DOCX, PDF dans la charte). Les fichiers sont stockés côté serveur et listés dans la page Rapports ; ils restent attachés au message qui les a produits.",
};

export function getGlossary(): Record<string, Term> {
  return getLocale() === "en" ? GLOSSARY_EN : GLOSSARY;
}

export function getGroupLabels(): Record<Group, string> {
  return getLocale() === "en" ? GROUP_LABELS_EN : GROUP_LABELS;
}

export const term = (k: string): Term => getGlossary()[k] || { label: k, short: "", long: "", group: "pipeline" };
