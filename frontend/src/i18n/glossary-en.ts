/**
 * Tacite glossary — English translations.
 * Same keys as the French `GLOSSARY`. Types only; the French source is not re-exported.
 * `short` : one sentence, shown on hover.
 * `long`  : full definition + method, for card “?” and the Method page.
 * `group` : Method page section.
 */

import type { Term, Group } from "../glossary";

export const GROUP_LABELS_EN: Record<Group, string> = {
  positions: "Positions and gaps",
  axes: "The twelve framing axes",
  influence: "Influence",
  journalists: "Journalists",
  client: "Client, positions and actions",
  map: "Mapping",
  pipeline: "Collection and analysis",
  assistant: "Assistant and reports",
};

export const GLOSSARY_EN: Record<string, Term> = {
  /* ───────────────── positions */
  declared: {
    group: "positions", label: "Declared line",
    short: "What an outlet says it is, or is publicly known for, on the 12 axes.",
    long: "Announced or commonly accepted editorial position of an outlet, mapped onto the 12 axes between −1 and +1. Entered when the outlet is created — by you, or estimated by the LLM from the declared orientation (e.g. “centre-right, liberal”). It does not move: it is the reference point against which what the outlet actually writes is compared.",
  },
  measured: {
    group: "positions", label: "Measured line",
    short: "What Tacite actually reads in the articles of the period.",
    long: "Position computed from the analysed articles. Each article receives a framing score on the 12 axes (scored on the angle, vocabulary and choice of sources, not on the topic). An outlet’s measured position is, for each axis, the mean of the non-zero values of its articles over the period. It is recomputed every week. A value close to 0 means either a balanced treatment, or an axis that is rarely addressed.",
  },
  gap: {
    group: "positions", label: "Gap",
    short: "Measured − declared, per axis. Notable beyond 0.30, strong beyond 0.50.",
    long: "Difference between the measured line and the declared line, axis by axis. A positive gap means the outlet reads more “+” (right-hand pole of the scale) than it announces; negative, more “−”. Below 0.30: consistent (grey). Between 0.30 and 0.50: notable (bronze). Above 0.50: strong (muted red). An outlet’s max. gap is the largest absolute gap among axes with enough data (≥ 10 non-zero articles), named by its axis. Secularism and Institutions are ignored outside FR/BE/CH/LU.",
  },
  outlet_topics: {
    group: "positions", label: "Favourite topics",
    short: "Most frequent themes in the outlet’s articles over 8 weeks.",
    long: "The three themes most often extracted from the outlet’s analysed articles, over the last eight weeks. This is not the editorial line: it is the agenda — what the title covers, not how it frames it. Off-field articles (sport, lifestyle) are excluded. An outlet fixed on two or three topics is predictable; a fragmented agenda is less so.",
  },
  gap_exploitable: {
    group: "positions", label: "Exploitable gap",
    short: "Threshold beyond which a gap becomes a handle for an action (0.35 by default).",
    long: "Threshold, adjustable and automatically tuned by learning, from which the recommendation engine considers that a gap between declared line and measured line can be used: an outlet that claims one side but writes another offers an angle of approach.",
  },
  confidence: {
    group: "positions", label: "Confidence",
    short: "Reliability of the measurement by article count: low < 10, medium 10–29, high ≥ 30.",
    long: "The measured position only makes sense with enough articles. Fewer than 10 articles analysed over the period: low confidence, the point is displayed faded and gaps should not be interpreted. From 10 to 29: medium. 30 and above: high. Confidence is also computed per axis (number of non-zero articles): a sparsely populated axis displays “—” and does not enter the max. gap.",
  },
  drift: {
    group: "positions", label: "Drift",
    short: "Weekly variation of an axis above the drift threshold (0.30 by default).",
    long: "Change in an outlet’s measured position on an axis between two consecutive weeks, when it exceeds the drift threshold set in Settings. A drift signals a recent change of tone or agenda, independently of the absolute position. Recent drifts appear on the dashboard and in the outlets recap.",
  },
  landscape_mean: {
    group: "positions", label: "Landscape mean",
    short: "Average position of all tracked outlets on an axis.",
    long: "Mean of the measured positions of all documented outlets on an axis. Serves as a benchmark: an outlet “in the centre” of Tacite is at the centre of the tracked landscape, not necessarily at the centre of the political spectrum.",
  },

  /* ───────────────── axes */
  axes: {
    group: "axes", label: "Framing axes",
    short: "Twelve dimensions, each from −1 (“−” pole) to +1 (“+” pole). No pole is good or bad.",
    long: "An article’s framing is scored on twelve independent axes, from −1 to +1. It covers how the subject is treated (angle, vocabulary, sources) and not the subject itself: an article on immigration can be scored 0 on Immigration if it does not take a side. The poles: Economy (liberal ↔ interventionist) · Society (conservative ↔ progressive) · Immigration (restrictive ↔ welcoming) · Europe (sovereigntist ↔ federalist) · Ecology (eco-sceptic ↔ eco-activist) · Security (law-and-order ↔ civil liberties) · Secularism (strict ↔ open) · International (Atlanticist ↔ non-aligned) · Institutions (presidential ↔ parliamentary) · Media (distrustful ↔ trusting) · Justice (order ↔ reform) · Technology (technophile ↔ techno-critical). Secularism and Institutions are France-centred: outside France, Belgium, Switzerland and Luxembourg, they are used neither for the max. gap nor for mapping insights.",
  },
  framing: {
    group: "axes", label: "Framing",
    short: "How an article treats its subject, scored on the 12 axes.",
    long: "For each article, the LLM identifies up to three themes and scores the framing of each on the 12 axes; the article’s framing is the per-axis mean of the non-zero values. This is the building block of all measured positions.",
  },

  /* ───────────────── influence */
  influence: {
    group: "influence", label: "Influence score",
    short: "0–100. Weighted sum of six components: audience, citations, agenda, elites, network, longevity.",
    long: "An outlet’s capacity to weigh on the debate. Weighted sum of six components scored 0–100: audience 20%, citations 25%, agenda 20%, elites 15%, network 10%, longevity 10% (weights editable in Settings). Rank is the outlet’s place in the ranking of tracked outlets.",
  },
  comp_audience: {
    group: "influence", label: "Audience",
    short: "Estimated reach of the outlet among the general public.",
    long: "Influence component: size of the readership / audience. Entered when the outlet is created or estimated by the LLM. Static.",
  },
  comp_citation: {
    group: "influence", label: "Citations",
    short: "How often other outlets pick up or mention this outlet over the period.",
    long: "Influence component, measured: number of articles from other outlets that cite this outlet. Anchored scale (logarithmic, ceiling 40 citations/week = 100), without min-max renormalisation of the corpus. Recomputed every week.",
  },
  comp_agenda: {
    group: "influence", label: "Agenda",
    short: "Ability to cover a topic before the others.",
    long: "Influence component, measured: share of topics picked up by several outlets on which this outlet was the first to publish. See “Who sets the tone” in Mapping › Analyses.",
  },
  comp_elite: {
    group: "influence", label: "Elites",
    short: "Weight among decision-makers (political, economic, administrative).",
    long: "Influence component: decision-maker readership. A little-read outlet that is read by ministerial offices weighs more than a popular outlet on certain questions. Entered or estimated, static.",
  },
  comp_network: {
    group: "influence", label: "Network",
    short: "Density of ties with other titles (group, pickups, partnerships).",
    long: "Influence component: the outlet’s insertion in the ecosystem (group membership, cross-pickups, partnerships). Entered or estimated, static.",
  },
  comp_longevity: {
    group: "influence", label: "Longevity",
    short: "Age and stability of the title.",
    long: "Influence component: age, editorial continuity, economic stability. A century-old title has an authority a pure player does not yet have. Entered or estimated, static.",
  },

  /* ───────────────── journalists */
  accessibility: {
    group: "journalists", label: "Accessibility",
    short: "0–100. Probability that a journalist is receptive to an approach. Pitch threshold: 55.",
    long: "LLM estimate, from signed articles, of a journalist’s receptiveness to an approach. High if they are productive, generalist, and rely on varied or institutional sources (press releases, experts). Low if they are an investigator, highly specialised, or work from elite and anonymous sources. The engine only proposes a Feed or Seed action above the pitch threshold (55 by default, tuned by learning).",
  },
  beat: {
    group: "journalists", label: "Beat",
    short: "Journalist’s speciality (Politics, Economy, International…), inferred from their articles.",
    long: "A journalist’s dominant desk, inferred by the LLM from their articles during enrichment. Dedicated `beat` field (plus the “[Politics] …” hack at the start of the bio, still read for backward compatibility).",
  },
  themes: {
    group: "journalists", label: "Fixations",
    short: "Themes that recur most in the journalist’s output.",
    long: "The most frequent themes in the journalist’s articles over the period, with their occurrence counts. A journalist fixed on a topic is predictable — and reachable on that topic.",
  },
  sources: {
    group: "journalists", label: "Preferred sources",
    short: "Types of sources they use: government, expert, anonymous, NGO, company…",
    long: "Breakdown of source types cited in their articles (government, anonymous, expert, NGO, company, judicial, union, party, citizen, media). A journalist who works from press releases and experts is more accessible than one who works from anonymous sources.",
  },
  biases: {
    group: "journalists", label: "Recurring biases",
    short: "Systematic angles spotted in their output.",
    long: "Treatment regularities spotted by the LLM across all articles (e.g. “systematically privileges the union point of view”, “economic angle on social topics”). These are tendencies, not judgements.",
  },
  vulnerabilities: {
    group: "journalists", label: "Vulnerabilities",
    short: "Exploitable traits: seeking recognition, reactive to exclusives, looking for a story…",
    long: "Approach levers identified by the LLM from the output: appetite for exclusivity, need for material, reactivity to new angles, search for visibility. Used by the engine to choose the entry journalist for an action.",
  },
  tone: {
    group: "journalists", label: "Dominant tone",
    short: "Most frequent emotion in their articles (neutral, indignation, concern, hope…).",
    long: "Each article receives a tone (one word: neutral, indignation, concern, hope, fear…). A journalist’s dominant tone is the most frequent over the period.",
  },
  dissident: {
    group: "journalists", label: "Dissident",
    short: "Journalist whose framing clearly diverges from their outlet’s measured line (gap > 0.35).",
    long: "Journalist (≥ 5 articles) whose personal measured position is distant from that of their outlet: mean distance on the 12 axes greater than 0.35. The divergence axis indicates where they diverge most and in which direction. Often the best way into an otherwise hostile outlet.",
  },
  productivity: {
    group: "journalists", label: "Productivity",
    short: "Number of signed articles per week.",
    long: "Articles signed over the last 7 days. A highly productive journalist needs material — they are more accessible.",
  },
  top_journalists: {
    group: "journalists", label: "Most active journalists",
    short: "Most productive bylines of the outlet over 8 weeks.",
    long: "The journalists who signed the most articles of the outlet over the last eight weeks, including co-bylines. The recap displays the top three; the profile ranks them all by volume. This is a way in: a highly productive journalist generally needs material.",
  },

  /* ───────────────── client */
  stance: {
    group: "client", label: "Stance toward the client",
    short: "Hostile (< −0.15), neutral, or favourable (> +0.15) on the client’s topics.",
    long: "Reading, outlet by outlet, of the treatment of the client’s topics (narratives to push, to counter, sensitive topics): score from −1 to +1. Hostile below −0.15, favourable above +0.15, neutral in between. The strategic map crosses this stance with influence.",
  },
  actions: {
    group: "client", label: "Actions",
    short: "Nine verbs, three risk levels, from Feed (deliver an exclusive) to Isolate (sideline an outlet).",
    long: "Low risk — Feed: deliver exclusive information to a receptive journalist. Seed: plant a narrative angle. Monitor: observe without acting. Medium risk — Co-opt: rally an outlet or journalist to the cause. Bypass: go through another channel than the hostile outlet. Dilute: multiply voices to drown out an opposing narrative. High risk — Flip: reverse an outlet’s position. Divide: pit journalists or newsrooms against each other. Isolate: sideline a hostile outlet.",
  },
  risk: {
    group: "client", label: "Risk",
    short: "Exposure of the action. Automatically stepped down if it exceeds the client’s tolerance.",
    long: "Each action has a risk level (low, medium, high): risk of being identified, of triggering a reaction, of damaging the relationship. If the recommended action exceeds the client’s risk tolerance, the engine steps it down to a less exposed action: Flip → Co-opt → Feed; Divide → Bypass → Seed; Isolate → Dilute → Monitor.",
  },
  priority: {
    group: "client", label: "Priority",
    short: "Score that ranks recommendations: influence × exploitable gap × accessibility.",
    long: "Combination of the outlet’s influence (the more it weighs, the more the action matters), the exploitable gap (the larger it is, the more purchase there is) and the entry journalist’s accessibility. Recommendations are displayed by descending priority.",
  },
  adaptive: {
    group: "client", label: "Adaptive thresholds",
    short: "The engine adjusts its thresholds according to recorded outcomes (success, partial, failure).",
    long: "When an action is marked Success, Partial or Failure, the result feeds the history. The engine then raises or lowers the pitch threshold and the exploitable-gap threshold: if actions on journalists at 55 accessibility fail, the threshold rises. This is the learning loop.",
  },
  narratives: {
    group: "client", label: "Narratives",
    short: "To push: what the client wants written. To counter: what they want to see disappear.",
    long: "The client file describes the narratives to push, the narratives to counter and the sensitive topics. They are used to compute each outlet’s stance toward the client and to steer action plans.",
  },
  exposure: {
    group: "client", label: "Exposure",
    short: "The client’s usual level of media exposure.",
    long: "Low, medium or high. A highly exposed client attracts coverage without effort but suffers more hostile angles; the engine weights the urgency of actions accordingly.",
  },

  /* ───────────────── map */
  positions_view: {
    group: "map", label: "Positions by axis",
    short: "One line per axis, every outlet on it. No transformation: what you see is what was measured.",
    long: "Reference view of the mapping. Each line is an axis, from the “−” pole on the left to the “+” pole on the right. Solid point = measured position (size = influence), hollow circle = declared line, bronze tick = landscape mean. Lines are sorted by dispersion: the axis that divides outlets most is at the top. Selecting an outlet traces its declared → measured across the 12 lines.",
  },
  projection: {
    group: "map", label: "Projection (PCA)",
    short: "Reduction of the 12 axes to a plane. Only proximity between points has meaning.",
    long: "Principal component analysis: the 12 axes are combined into two dimensions that retain the maximum of information. The plane’s axes have no names; two nearby points have similar framings, that is all there is to read. Explained variance indicates the share of information retained (e.g. 45% / 23%). To read axis by axis, use Positions.",
  },
  topic_cluster: {
    group: "map", label: "Topic (story)",
    short: "A story, possibly grouped into a broader family.",
    long: "Two levels. A story groups articles at cosine ≥ 0.80 (complete linkage), then reattaches packets with nearly identical labels (“Canada-EU” / “EU-Kanada”). An article leaves the packet if it has both a label and entities disjoint from the rest (veto: the embedding alone is no longer enough). A family only unites stories if all of them are close (cosine ≥ 0.55, complete linkage); it carries an umbrella name (shared tokens and entities), distinct from the stories it contains. Only the 16 most covered families are named.",
  },
  topic_heat: {
    group: "map", label: "Topic heat",
    short: "Volume of the period compared with the previous period of the same length.",
    long: "For each cluster, articles from the previous window whose embedding is close enough to the centroid are counted (same 0.80 threshold). Emerging: nothing before. Rising: at least ×1.5. Falling: ×0.7 or less. Stable otherwise. Independent of the label: a story that changes name from one day to the next stays tracked.",
  },
  topic_polarization: {
    group: "map", label: "Topic polarisation",
    short: "Do outlets frame this story the same way?",
    long: "Mean standard deviation, across the 12 axes, of the per-outlet mean framings inside the cluster. Close to 0: treatment consensus. High: the topic splits. Complements volume: a heavily covered and little-polarised topic is the zeitgeist; heavily covered and polarised, a conflict.",
  },
  cluster: {
    group: "map", label: "Editorial bloc",
    short: "Group of outlets with similar framings, formed automatically.",
    long: "Automatic clustering (k-means) of documented outlets on their measured position. Named by the two axes where the bloc diverges most from the landscape mean (“more welcoming · more eco-activist”). Displayed only if the split is sharp: silhouette ≥ 0.30 and no bloc above 60% of outlets.",
  },
  silhouette: {
    group: "map", label: "Silhouette",
    short: "Sharpness of a clustering, from −1 to 1. Above 0.30: distinct blocs.",
    long: "Quality measure of a clustering: compares an outlet’s distance to members of its bloc and to members of the neighbouring bloc. Close to 1, blocs are well separated; close to 0, they overlap; negative, the split has no meaning.",
  },
  pagerank: {
    group: "map", label: "PageRank",
    short: "Importance in the citation network: being cited by outlets that are themselves cited counts more.",
    long: "Centrality algorithm applied to the citation graph between outlets. An outlet cited by Le Monde weighs more than an outlet cited by a marginal title. Circle sizes on the Network are proportional to PageRank.",
  },
  community: {
    group: "map", label: "Community",
    short: "Group of outlets that cite and overlap with each other more than with the rest.",
    long: "Community detection (Louvain method) on the graph combining citations and co-coverage. Members of a community share an ecosystem: same sources, same pickups, same topics. Distinguished by circle fill and stroke.",
  },
  cocoverage: {
    group: "map", label: "Co-coverage",
    short: "Share of common themes between two outlets (Jaccard index on their 40 main themes).",
    long: "Two outlets are linked in co-coverage when their 40 most frequent themes overlap by more than 12%. Grey dashed stroke in the Network. Reflects a shared agenda, independently of framing.",
  },
  leadlag: {
    group: "map", label: "Who sets the tone (lead / lag)",
    short: "On each topic picked up within 72 h by several outlets, the first “leads”, the others “follow”.",
    long: "For each theme, articles are ordered in time; when at least two outlets publish within a 72 h window, the first leads, the following follow. Ratio = share of events where the outlet is first. Median lag = typical pickup delay when it follows. “Who follows whom” counts leader → follower pairs.",
  },
  pack: {
    group: "map", label: "Pack",
    short: "Pair of outlets that systematically cover the same topics.",
    long: "Two outlets form a pack when the similarity of their themes (cosine on theme frequency, 60 days) is high. Framing similarity indicates whether they treat them the same way: a pack with opposite framing is a debate; with identical framing, an echo.",
  },
  similarity: {
    group: "map", label: "Theme / framing similarity",
    short: "Resemblance of two outlets by what they cover (themes) and by how they cover it (framing).",
    long: "Proximity matrix: each cell compares two outlets. Themes: cosine between their theme-frequency profiles (0 = nothing in common, 100% = same topics in the same proportions). Framing: cosine between their measured positions (−100% = opposite, +100% = identical). Row order comes from hierarchical clustering: outlets neighbouring in the matrix are neighbours in fact.",
  },
  corpus: {
    group: "map", label: "Corpus map",
    short: "Each point is an article, placed by semantic proximity. Dense zones are saturated topics.",
    long: "Articles are represented by a semantic embedding (384-dimension vector computed locally), projected into two dimensions. Two nearby articles talk about the same thing. Bronze washes indicate density: where the press piles up. Labels mark the barycentre of frequent themes.",
  },
  blindspot: {
    group: "map", label: "Blind spot",
    short: "Recurring theme (≥ 3 articles) covered by a single outlet.",
    long: "A topic that recurs at a single outlet and nowhere else. For the client, it is open space: an angle on which there is not yet narrative competition — or a signal that this outlet is preparing something.",
  },
  valence: {
    group: "map", label: "Valence",
    short: "Average tone of articles that cite an entity, from −1 (indignation, fear) to +1 (hope).",
    long: "Each article tone is converted into a value (neutral 0, hope +1, indignation −1, concern −0.5, fear −0.8…). An entity’s valence at an outlet is the mean over that outlet’s articles that cite it. Dispersion measures how much outlets diverge on this entity: high dispersion = polarising figure.",
  },
  world: {
    group: "map", label: "World map",
    short: "Countries tinted and ringed by cumulative influence, number of outlets, articles or journalists. Arrows = cross-border citations.",
    long: "Equal Earth projection. Circle tint and size follow the chosen measure. Arrows link the country of a citing outlet to the country of the cited outlet, excluding domestic citations: they show who looks at whom. Tacite covers the 249 ISO countries and territories; a country appears as soon as it has a tracked outlet.",
  },

  /* ───────────────── pipeline */
  status_analyzed: {
    group: "pipeline", label: "Analysed",
    short: "Article sent through the LLM: themes, framing, sources, tone, angle, entities.",
    long: "Status of an article whose text has been extracted and submitted to the language model. This is the only category that feeds measured positions and profiles.",
  },
  status_embedded: {
    group: "pipeline", label: "Off-field",
    short: "Article detected as non-political (sport, weather, celebrity…), indexed without an LLM call.",
    long: "A lexical filter spots articles clearly outside the political and news field. They are semantically embedded (for search and duplicates) but not analysed — which avoids paying an LLM call for a football result.",
  },
  status_duplicate: {
    group: "pipeline", label: "Duplicate",
    short: "Nearly identical pickup of an article already in the database (very high semantic similarity).",
    long: "Detection by embedding: an article whose vector is almost identical to a recent article is marked as a duplicate and attached to the original. Avoids counting the same wire three times when picked up by three titles.",
  },
  status_pending: {
    group: "pipeline", label: "Pending",
    short: "Captured but not yet analysed — the worker processes in batches.",
    long: "Articles are analysed in batches (adjustable size) at regular intervals, within the daily cost ceiling.",
  },
  angle: {
    group: "pipeline", label: "Journalistic angle",
    short: "Genre of the article: investigation, editorial, brief, analysis, opinion, reaction.",
    long: "Genre classification: investigation, editorial, brief, analysis, opinion, reaction. An outlet that only produces briefs picks up; an outlet that produces investigations sets the agenda.",
  },
  llm_cost: {
    group: "pipeline", label: "LLM cost and ceiling",
    short: "Estimated spend of model calls; beyond the daily ceiling, analysis waits until the next day.",
    long: "Each call is accounted for (input and output tokens × model rate). The daily ceiling, adjustable in Settings, pauses analysis and enrichment when it is reached; collection continues. 0 = no ceiling.",
  },
  sources_ingest: {
    group: "pipeline", label: "Collection sources",
    short: "RSS feeds, Google News, GDELT, and a headless browser for sites without a feed.",
    long: "Per outlet, one or more RSS feeds (by desk); failing that or in addition, Google News “site:” search, the GDELT database, and an automated browser (Playwright) that loads JavaScript-rendered pages and dismisses cookie banners. Articles are deduplicated by URL then by meaning.",
  },
  collect_modes: {
    group: "pipeline", label: "Collection modes",
    short: "RSS feed ✓ = articles received directly (15 min). Indirect collection = via Google News, GDELT and scraping. Robot access blocked = via automated browser.",
    long: "When an outlet is proposed for addition, its site and feeds are tested one by one — never assumed. Three possible outcomes. RSS feed ✓: at least one feed works, articles arrive directly every 15 minutes — the best case. Indirect collection: the site responds but exposes no feed; articles arrive via Google News search on the domain (2 h), the GDELT database (6 h) and homepage scraping (1 h) — a little slower, a little less complete. Robot access blocked: the site works in a browser but refuses automated requests (HTTP 403); collection then goes through the automated browser (Playwright) and Google News. Unreachable: the site did not respond — the precise reason is displayed (domain not found, timeout, server error) and “Retry” relaunches the test.",
  },

  /* ───────────────── assistant */
  assistant: {
    group: "assistant", label: "Assistant",
    short: "Conversational agent: it reads all Tacite data and the web, produces charts, files and reports, and modifies the database after confirmation.",
    long: "The Aleria model chooses its own tools to call: outlet and journalist profiles, semantic article search, mapping, client files, read-only SQL query, Google News, GDELT, URL reading. It cites its sources (links to profiles and articles, web URLs). It does not guess numbers: what it does not have, it goes and fetches. Conversation context is kept from one message to the next; ⌘K opens the assistant in a side panel with the current profile pinned.",
  },
  agent_confirm: {
    group: "assistant", label: "Proposed change",
    short: "Any write requested of the assistant is first proposed; it only applies after you click “Apply”.",
    long: "When the assistant wants to modify an outlet, a journalist, a client, a recommendation, a setting or launch a task, it creates a “proposed” action with an exact description of the change. You apply or reject it in the conversation. Applied actions are logged (before / after) and most can be undone in one click. The “Write confirmation” setting lets you apply directly, at your own risk.",
  },
  report: {
    group: "assistant", label: "Report",
    short: "PDF in the Tacite house style: facts collected automatically, charts, writing by the model constrained to the facts.",
    long: "Six templates: outlet note, journalist file, client brief, landscape panorama (all countries, or one country via the filter), country panorama (tracked outlets of a state: positions, leaders, themes, journalists, cross-border flows), thematic note (free topic, database + web, optional country filter). Collection uses the same tools as the assistant; the model writes the sections from those facts alone, then layout adds key figures, declared/measured radar, per-axis bands, bars. Each report is kept in Reports with its HTML version.",
  },
  artifact: {
    group: "assistant", label: "Produced file",
    short: "CSV, Excel, Markdown, Word, HTML or PDF created by the assistant, downloadable and kept in Reports.",
    long: "The assistant can put any result into a file: list exports (CSV, XLSX), written notes (Markdown, DOCX, PDF in the house style). Files are stored server-side and listed on the Reports page; they stay attached to the message that produced them.",
  },

  /* ───────────────── journalists (contact) */
  contact_channels: {
    group: "journalists", label: "Contact channels",
    short: "A journalist’s e-mail, X, Bluesky, Mastodon, LinkedIn…, each with its proof: source, method, confidence level.",
    long: "Tacite never guesses a contact. Channels come from verifiable sources: structured data of signed articles (JSON-LD), byline-block links, the outlet’s author page, a mailto in the journalist’s name, article text (“contact me: …”), public Bluesky search (profile whose bio cites the outlet), and manual entry. An address pattern observed on at least two verified e-mails of an outlet makes it possible to propose addresses for the other journalists, labelled “inferred”. Detection runs in the background (40 journalists per hour, the most productive first) and can be launched on demand from a profile.",
  },
  contact_confidence: {
    group: "journalists", label: "Verified · Probable · Inferred",
    short: "Verified = link attached to the byline or author page. Probable = article text or public search. Inferred = address pattern, to be checked.",
    long: "Verified: the channel is physically attached to the journalist by the outlet itself (byline, author page, structured data) or entered by you. Probable: found in article text, or a public profile whose bio cites the outlet — strong presumption, no direct proof. Inferred: address built from the outlet’s pattern (firstname.lastname@…); useful for a first send, to be confirmed. A channel can be marked invalid: it remains visible struck through, is no longer proposed or counted.",
  },
};
