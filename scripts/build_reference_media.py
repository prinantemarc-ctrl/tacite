#!/usr/bin/env python3
"""Catalogue mondial de médias de référence pour Tacite.

Barre d'entrée (les trois ensemble) :
- reconnaissance au moins nationale ;
- rédaction professionnelle identifiable ;
- crédibilité d'une rédaction identifiable. Une ligne d'opinion assumée
  n'écarte pas un titre reconnu nationalement. Restent dehors les organes
  d'État sans rédaction indépendante et les tabloïds de sensation.

Socle : article Wikipédia « Newspaper of record », section
« Examples of existing newspapers » (journaux de référence par réputation,
exemples sourcés). Compléments : pairs nationaux du même standing
(l'équivalent du Figaro à côté du Monde), services publics à indépendance
statutaire, agences qui publient un site d'articles, rédactions indépendantes
là où le quotidien dominant est un organe de pouvoir.

Les flux RSS et les sitemaps ne sont inscrits que s'ils répondent.

Le fichier data/reference_media.json a été corrigé après la première passe
(pays mal lus dans les rowspan du tableau, flux connus des grands titres,
titres dont la page d'accueil bloque les robots). Relancer ce script écrase
cette correction.
"""

from __future__ import annotations

import csv
import json
import re
import subprocess
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse

ROOT = Path("/Users/mp/press analysis")
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data"
COUNTRIES = ROOT / "backend" / "app" / "data" / "countries.json"
WIKI = RAW / "record_examples.wiki"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
UA_WD = "TaciteReferenceCatalog/1.0 (local press-intelligence research)"

# Noms (ou titres Wikipédia) retirés du socle : la notoriété nationale ne suffit pas.
EXCLUSIONS = {
    "Granma": "Organe du Parti communiste de Cuba, pas une rédaction indépendante.",
    "Rodong Sinmun": "Organe du Parti du travail de Corée.",
    "The London Gazette": "Journal officiel britannique : avis légaux, pas une rédaction d'information.",
    "L'Osservatore Romano": "Organe du Saint-Siège, pas un journal indépendant.",
    "Al-Ahram": "Quotidien d'État égyptien.",
    "Ettela'at": "Quotidien historique iranien sous contrôle de l'État.",
    "Akhbar Al Khaleej": "Quotidien bahreïni sans indépendance éditoriale établie.",
    "Gulf Daily News": "Quotidien anglophone bahreïni, environnement de censure, indépendance non établie.",
    "The Straits Times": "Groupe SPH, ligne structurellement alignée sur le gouvernement de Singapour.",
    "New Straits Times": "Quotidien malaisien historiquement lié à l'UMNO.",
    "Al Ra'i": "Quotidien jordanien semi-officiel.",
    "L'Union": "Quotidien dominant au Gabon, proche du pouvoir.",
    "Lidové noviny": "Titre historique passé dans le groupe Mafra. L'indépendance éditoriale n'est plus le standard du journal.",
    "South China Morning Post": "Journal historique de Hong Kong, détenu par Alibaba ; marge d'indépendance réduite depuis 2020.",
    "The Times of India": "Plus gros tirage indien, mais les pratiques de « paid news » empêchent de le tenir pour une référence incontestable.",
    "Al-Masry Al-Youm": "Quotidien privé égyptien, autocensure structurelle depuis la fermeture de l'espace civique.",
}

# Cités parce qu'on les cherche, et écartés pour un motif précis.
CONSIDERED = [
    {"name": "Al Jazeera", "country": "QA", "reason": "Influence régionale majeure. Financement de l'État du Qatar, indépendance contestée sur le Golfe et les dossiers régionaux."},
    {"name": "RT / Sputnik / TASS", "country": "RU", "reason": "Organes d'État russes."},
    {"name": "Xinhua / Quotidien du Peuple / CGTN / Global Times", "country": "CN", "reason": "Organes du Parti communiste chinois."},
    {"name": "Daily Mail, The Sun, Bild, New York Post", "country": "—", "reason": "Tabloïds nationaux. Modèle sensationnaliste, pas une crédibilité de référence."},
    {"name": "Kommersant, Vedomosti", "country": "RU", "reason": "Quotidiens économiques historiques. Contrôle éditorial resserré depuis 2022 : l'indépendance n'est plus incontestable."},
    {"name": "Press TV, IRNA, KCNA", "country": "—", "reason": "Agences ou chaînes d'État sans rédaction indépendante."},
]

ALIASES = {
    "united states": "united states of america",
    "united kingdom": "united kingdom of great britain and northern ireland",
    "czech republic": "czechia",
    "portuguese republic": "portugal",
    "vatican city": "holy see",
    "south korea": "korea, republic of",
    "north korea": "korea, democratic people's republic of",
    "republic of the congo": "congo",
    "netherlands": "netherlands, kingdom of the",
    "russia": "russian federation",
    "bolivia": "bolivia, plurinational state of",
    "venezuela": "venezuela, bolivarian republic of",
    "tanzania": "tanzania, united republic of",
    "iran": "iran, islamic republic of",
    "syria": "syrian arab republic",
    "laos": "lao people's democratic republic",
    "moldova": "moldova, republic of",
    "taiwan": "taiwan, province of china",
    "turkey": "türkiye",
    "türkiye": "türkiye",
    "vietnam": "viet nam",
    "brunei": "brunei darussalam",
    "cape verde": "cabo verde",
    "swaziland": "eswatini",
    "palestine": "palestine, state of",
    "democratic republic of the congo": "congo, democratic republic of the",
    "dr congo": "congo, democratic republic of the",
    "ivory coast": "côte d'ivoire",
    "cote d'ivoire": "côte d'ivoire",
    "czech": "czechia",
    "south korea (republic of korea)": "korea, republic of",
}

LANG = {
    "english": "en", "french": "fr", "german": "de", "spanish": "es", "arabic": "ar",
    "portuguese": "pt", "italian": "it", "russian": "ru", "chinese": "zh", "japanese": "ja",
    "korean": "ko", "hebrew": "he", "turkish": "tr", "polish": "pl", "dutch": "nl",
    "swedish": "sv", "norwegian": "no", "danish": "da", "finnish": "fi", "greek": "el",
    "hindi": "hi", "bengali": "bn", "persian": "fa", "indonesian": "id", "thai": "th",
    "ukrainian": "uk", "romanian": "ro", "hungarian": "hu", "czech": "cs", "slovak": "sk",
    "bulgarian": "bg", "serbian": "sr", "croatian": "hr", "catalan": "ca", "azeri": "az",
    "azerbaijani": "az", "icelandic": "is", "malay": "ms", "swahili": "sw", "urdu": "ur",
    "nepali": "ne", "burmese": "my", "georgian": "ka", "armenian": "hy", "lithuanian": "lt",
    "latvian": "lv", "estonian": "et", "slovenian": "sl", "albanian": "sq", "bosnian": "bs",
    "macedonian": "mk", "khmer": "km", "vietnamese": "vi", "filipino": "fil", "tagalog": "tl",
}

# Lignes courtes, alignées sur le vocabulaire déjà utilisé dans le seed Tacite.
# Uniquement quand le positionnement public est établi. Sinon on ne l'invente pas.
LINES = {
    "la nación": ("Centre-droit, conservateur", "Quotidien de référence de Buenos Aires, ligne conservatrice-libérale."),
    "the age": ("Centre-gauche, libéral", "Quotidien de qualité de Melbourne, groupe Nine."),
    "the sydney morning herald": ("Centre, libéral", "Quotidien de qualité de Sydney, groupe Nine."),
    "die presse": ("Centre-droit, libéral", "Quotidien de référence viennois, ligne libérale-conservatrice."),
    "der standard": ("Centre-gauche, libéral", "Quotidien viennois de qualité, ligne libérale et européenne."),
    "the daily star": ("Centre, indépendant", "Principal quotidien anglophone du Bangladesh, rédaction indépendante."),
    "le soir": ("Centre-gauche, progressiste", "Quotidien de référence francophone belge."),
    "de standaard": ("Centre-gauche, qualité", "Quotidien de référence flamand."),
    "o estado de s. paulo": ("Centre-droit, libéral", "Quotidien de référence de São Paulo, ligne libérale-conservatrice."),
    "folha de s.paulo": ("Centre, libéral", "Quotidien national brésilien, pluraliste, fort sur l'enquête."),
    "o globo": ("Centre-droit, conservateur-libéral", "Quotidien national du groupe Globo, ligne libérale-conservatrice."),
    "le devoir": ("Centre-gauche, qualité", "Quotidien indépendant québécois, ligne souverainiste modérée et culturelle."),
    "la presse": ("Centre, libéral", "Quotidien québécois de référence, ligne libérale."),
    "the globe and mail": ("Centre, libéral", "Quotidien de référence du Canada anglophone."),
    "el mercurio": ("Droite, conservateur", "Quotidien de référence chilien. Ligne conservatrice. Rôle de soutien à la dictature documenté : la rédaction actuelle reste le journal national de la droite, l'historique pèse sur la crédibilité."),
    "el tiempo": ("Centre, libéral", "Quotidien national colombien, historiquement lié au Parti libéral."),
    "el espectador": ("Centre-gauche, libéral", "Quotidien national colombien, ligne libérale, tradition d'enquête."),
    "la nación (costa rica)": ("Centre, libéral", "Quotidien de référence du Costa Rica."),
    "lidové noviny": ("Centre-droit, libéral", "Quotidien historique tchèque. Le titre a perdu de son indépendance au sein du groupe Mafra : conservé comme titre historique, à surveiller."),
    "berlingske": ("Centre-droit, libéral-conservateur", "Plus ancien quotidien danois encore publié, ligne libérale-conservatrice."),
    "helsingin sanomat": ("Centre, libéral", "Quotidien de référence finlandais."),
    "le monde": ("Centre-gauche, libéral-progressiste", "Quotidien national de référence, ligne sociale-démocrate et européenne, fort sur l'international et l'enquête."),
    "libération": ("Gauche, progressiste", "Quotidien national, ligne de gauche sociale et culturelle."),
    "frankfurter allgemeine zeitung": ("Centre-droit, libéral", "Quotidien de référence allemand, ligne libérale-conservatrice, très lu des élites."),
    "süddeutsche zeitung": ("Centre-gauche, libéral", "Quotidien de référence de Munich, ligne libérale de centre-gauche."),
    "die welt": ("Droite, conservateur-libéral", "Quotidien national du groupe Axel Springer, ligne conservatrice-libérale."),
    "die zeit": ("Centre-gauche, libéral", "Hebdomadaire de référence, ligne libérale, long format."),
    "kathimerini": ("Centre-droit, libéral-conservateur", "Quotidien de référence athénien, ligne libérale-conservatrice."),
    "the hindu": ("Centre-gauche, qualité", "Quotidien indien de référence, ligne sociale-libérale, fort sur l'enquête."),
    "kompas": ("Centre, généraliste", "Quotidien national indonésien de référence."),
    "the irish times": ("Centre, libéral", "Quotidien de référence irlandais, ligne libérale."),
    "haaretz": ("Centre-gauche, libéral", "Quotidien de référence israélien, ligne libérale, édition hébraïque et anglaise."),
    "corriere della sera": ("Centre, libéral", "Quotidien de référence italien, ligne libérale, ancré à Milan."),
    "la repubblica": ("Centre-gauche, progressiste", "Quotidien national, ligne de centre-gauche."),
    "il sole 24 ore": ("Économique, libéral", "Quotidien économique de référence, organe de Confindustria."),
    "la stampa": ("Centre, libéral", "Quotidien national historique de Turin, ligne libérale."),
    "il messaggero": ("Centre, généraliste", "Quotidien romain à diffusion nationale."),
    "the asahi shimbun": ("Centre-gauche, libéral", "Un des grands quotidiens nationaux, ligne libérale."),
    "nihon keizai shimbun (nikkei)": ("Économique, libéral", "Quotidien économique de référence du Japon."),
    "yomiuri shimbun": ("Centre-droit, conservateur", "Plus gros tirage mondial, ligne conservatrice, rédaction professionnelle."),
    "mainichi shimbun": ("Centre-gauche, libéral", "Quotidien national, ligne libérale, plus petit que Asahi et Yomiuri."),
    "daily nation": ("Centre, généraliste", "Quotidien de référence kényan, groupe Nation Media."),
    "an-nahar": ("Centre, libéral", "Quotidien historique libanais, ligne libérale et souverainiste."),
    "nrc": ("Centre, libéral", "Quotidien de qualité néerlandais."),
    "the new zealand herald": ("Centre, généraliste", "Quotidien national néo-zélandais de plus large audience."),
    "the guardian (nigeria)": ("Centre, qualité", "Quotidien nigérian de référence, à ne pas confondre avec le Guardian britannique."),
    "aftenposten": ("Centre, libéral-conservateur", "Quotidien de référence norvégien, groupe Schibsted."),
    "gazeta wyborcza": ("Centre-gauche, libéral", "Quotidien issu de Solidarność, ligne libérale et pro-européenne."),
    "rzeczpospolita": ("Centre-droit, libéral-conservateur", "Quotidien de référence, ligne libérale-conservatrice, fort sur le droit et l'économie."),
    "público": ("Centre-gauche, qualité", "Quotidien portugais de référence, ligne de centre-gauche."),
    "diário de notícias": ("Centre, historique", "Quotidien historique lisboète."),
    "danas": ("Centre-gauche, indépendant", "Quotidien serbe indépendant, ligne démocratique et pro-européenne."),
    "mail & guardian": ("Centre-gauche, investigation", "Hebdomadaire sud-africain d'enquête, ligne de centre-gauche."),
    "the chosun ilbo": ("Droite, conservateur", "Un des trois grands quotidiens conservateurs coréens."),
    "the dong-a ilbo": ("Centre-droit, conservateur", "Quotidien national conservateur."),
    "joongang ilbo": ("Centre-droit, conservateur", "Quotidien national conservateur, édition anglaise Korea JoongAng Daily."),
    "la vanguardia": ("Centre-droit, catalaniste modéré", "Quotidien de référence de Barcelone, diffusion nationale, ligne libérale-conservatrice."),
    "abc": ("Droite, conservateur", "Quotidien national, ligne monarchiste et conservatrice."),
    "el mundo": ("Centre-droit, libéral", "Quotidien national, ligne libérale de centre-droit, tradition d'enquête."),
    "el país": ("Centre-gauche, progressiste", "Quotidien de référence espagnol, ligne sociale-démocrate et européenne."),
    "dagens nyheter": ("Centre, libéral", "Quotidien de référence suédois, ligne libérale."),
    "neue zürcher zeitung": ("Centre-droit, libéral", "Quotidien de référence suisse alémanique, ligne libérale."),
    "le temps": ("Centre, qualité", "Quotidien de référence romand."),
    "bangkok post": ("Centre, anglophone", "Quotidien anglophone de référence en Thaïlande."),
    "matichon": ("Centre-gauche, qualité", "Quotidien thaïlandais de qualité, ligne progressiste modérée."),
    "cumhuriyet": ("Centre-gauche, laïc", "Quotidien historique kémaliste. Rédaction sous pression judiciaire ; le titre reste la référence laïque, pas un organe de pouvoir."),
    "the daily telegraph": ("Droite, conservateur", "Quotidien national britannique, ligne conservatrice."),
    "financial times": ("Économique, libéral", "Quotidien économique international de référence, ligne libérale et libre-échangiste. L'éditorial est distinct des pages news."),
    "the guardian": ("Centre-gauche, progressiste", "Quotidien national, ligne sociale-démocrate, fort sur l'international, l'enquête et le climat."),
    "the times": ("Centre-droit, conservateur", "Quotidien de référence britannique, ligne conservatrice-libérale."),
    "los angeles times": ("Centre-gauche, libéral", "Quotidien de référence de la côte Ouest, ligne libérale."),
    "the new york times": ("Centre-gauche, libéral", "Quotidien de référence américain, ligne libérale, très repris à l'international."),
    "the wall street journal": ("Économique, centre-droit", "Quotidien économique de référence. Éditorial conservateur-libéral, rédaction news séparée."),
    "the washington post": ("Centre, libéral", "Quotidien de référence de Washington, ligne libérale, fort sur la politique fédérale et l'enquête."),
    "le figaro": ("Centre-droit, conservateur-libéral", "Quotidien national, ligne conservatrice-libérale, très lu des élites économiques et politiques."),
    "les échos": ("Centre, pro-business", "Quotidien économique de référence, ligne libérale et pro-entreprise."),
    "la croix": ("Centre, chrétien-social", "Quotidien national, ligne catholique sociale, réputé pour le social et l'international."),
    "france info": ("Centre, service public", "Offre d'information de France Télévisions et Radio France. Mandat de service public."),
    "médiapart": ("Gauche, contre-pouvoir", "Pure player d'enquête, ligne de gauche, modèle abonné sans publicité."),
    "le parisien": ("Centre, populaire", "Quotidien national populaire, rédaction généraliste, ligne modérée."),
    "l'opinion": ("Centre-droit, libéral", "Quotidien d'opinion et d'élèves, ligne libérale pro-entreprise."),
    "courrier international": ("Centre-gauche, internationaliste", "Hebdomadaire de reprise de la presse étrangère."),
    "le monde diplomatique": ("Gauche, altermondialiste", "Mensuel de référence sur l'international, ligne critique de la mondialisation."),
    "rtl": ("Centre, généraliste", "Première radio privée d'information généraliste."),
    "afp": ("Agence, factuelle", "Agence de presse mondiale. Statut d'indépendance fixé par la loi de 1957, tour de table public et privé."),
    "associated press": ("Agence, factuelle", "Coopérative d'éditeurs américains. Agence de référence mondiale, copie factuelle."),
    "reuters": ("Agence, factuelle", "Agence mondiale, rédaction à Londres, détention Thomson Reuters. Standard de copie factuelle."),
    "bloomberg": ("Économique, factuel", "Agence et site économiques. Rédaction news séparée de l'éditorial et du terminal."),
    "bbc news": ("Centre, service public", "Information de la BBC. Mandat d'impartialité, régulation Ofcom."),
    "the economist": ("Centre, libéral", "Hebdomadaire international, ligne libérale classique : marchés, ouverture, institutions."),
    "npr": ("Centre-gauche, service public", "Réseau public américain. Ligne perçue centre-gauche, charte d'indépendance."),
    "propublica": ("Investigation, non partisan", "Rédaction d'enquête à but non lucratif. Pas de ligne partisane affichée."),
    "der spiegel": ("Centre-gauche, progressiste", "News magazine de référence, ligne de centre-gauche, tradition d'enquête."),
    "handelsblatt": ("Économique, libéral", "Quotidien économique de référence."),
    "tagesschau": ("Centre, service public", "Information de l'ARD, consortium régional de service public."),
    "el confidencial": ("Centre, investigation", "Pure player national, réputé pour l'enquête politique et économique."),
    "nos": ("Centre, service public", "Information du service public néerlandais."),
    "srF": ("Centre, service public", "Information de la SRG SSR en allemand."),
    "rts": ("Centre, service public", "Information de la SRG SSR en français."),
}

# Compléments : pairs nationaux, services publics, agences à site public,
# rédactions indépendantes là où le titre dominant ne passe pas la barre.
# Champs : name, iso, lang, url, type, famille, orientation, ligne, note
def S(name, iso, lang, url, typ, famille, orientation, ligne, note=""):
    return {
        "name": name, "iso": iso, "lang": lang, "url": url, "type": typ,
        "famille": famille, "orientation": orientation, "ligne": ligne, "note": note,
    }

SUPPLEMENTS = [
    S("Le Figaro", "FR", "fr", "https://www.lefigaro.fr", "quotidien", "reference", "Centre-droit, conservateur-libéral", "Quotidien national, ligne conservatrice-libérale, très lu des élites économiques et politiques."),
    S("Les Échos", "FR", "fr", "https://www.lesechos.fr", "quotidien", "economique", "Centre, pro-business", "Quotidien économique de référence, ligne libérale et pro-entreprise."),
    S("La Croix", "FR", "fr", "https://www.la-croix.com", "quotidien", "reference", "Centre, chrétien-social", "Quotidien national, ligne catholique sociale."),
    S("AFP", "FR", "fr", "https://www.afp.com", "agence", "agence", "Agence, factuelle", "Agence mondiale. Indépendance organisée par la loi de 1957."),
    S("franceinfo", "FR", "fr", "https://www.francetvinfo.fr", "service_public", "service_public", "Centre, service public", "Information de France Télévisions et Radio France."),
    S("Médiapart", "FR", "fr", "https://www.mediapart.fr", "pure_player", "investigation", "Gauche, contre-pouvoir", "Pure player d'enquête, sans publicité, ligne de gauche."),
    S("Le Parisien", "FR", "fr", "https://www.leparisien.fr", "quotidien", "reference", "Centre, populaire", "Quotidien national populaire, rédaction généraliste."),
    S("Le Monde diplomatique", "FR", "fr", "https://www.monde-diplomatique.fr", "magazine", "international", "Gauche, altermondialiste", "Mensuel de référence sur l'international."),
    S("L'Opinion", "FR", "fr", "https://www.lopinion.fr", "quotidien", "economique", "Centre-droit, libéral", "Quotidien d'élites, ligne libérale pro-entreprise."),
    S("Courrier international", "FR", "fr", "https://www.courrierinternational.com", "hebdo", "international", "Centre-gauche, internationaliste", "Hebdomadaire de reprise de la presse étrangère."),
    S("RFI", "FR", "fr", "https://www.rfi.fr", "radio", "international", "Centre, service public", "Radio publique internationale, groupe France Médias Monde."),
    S("France 24", "FR", "fr", "https://www.france24.com", "television", "international", "Centre, service public", "Chaîne publique d'information internationale, France Médias Monde."),
    S("RTL", "FR", "fr", "https://www.rtl.fr", "radio", "reference", "Centre, généraliste", "Radio privée généraliste, forte audience d'information."),
    S("La Libre", "BE", "fr", "https://www.lalibre.be", "quotidien", "reference", "Centre, catholique", "Quotidien francophone, ligne de centre historiquement catholique."),
    S("De Morgen", "BE", "nl", "https://www.demorgen.be", "quotidien", "reference", "Centre-gauche, progressiste", "Quotidien flamand de qualité, ligne progressiste."),
    S("RTBF", "BE", "fr", "https://www.rtbf.be", "service_public", "service_public", "Centre, service public", "Service public audiovisuel de la Fédération Wallonie-Bruxelles."),
    S("VRT", "BE", "nl", "https://www.vrt.be", "service_public", "service_public", "Centre, service public", "Service public audiovisuel flamand."),
    S("L'Echo", "BE", "fr", "https://www.lecho.be", "quotidien", "economique", "Économique, libéral", "Quotidien économique francophone, jumelé à De Tijd."),
    S("De Tijd", "BE", "nl", "https://www.tijd.be", "quotidien", "economique", "Économique, libéral", "Quotidien économique flamand."),
    S("Tages-Anzeiger", "CH", "de", "https://www.tagesanzeiger.ch", "quotidien", "reference", "Centre-gauche, libéral", "Quotidien de Zurich, ligne libérale de centre-gauche, groupe Tamedia."),
    S("RTS", "CH", "fr", "https://www.rts.ch", "service_public", "service_public", "Centre, service public", "Information de la SRG SSR en français."),
    S("SRF", "CH", "de", "https://www.srf.ch", "service_public", "service_public", "Centre, service public", "Information de la SRG SSR en allemand."),
    S("Der Spiegel", "DE", "de", "https://www.spiegel.de", "magazine", "reference", "Centre-gauche, progressiste", "News magazine de référence, tradition d'enquête."),
    S("Handelsblatt", "DE", "de", "https://www.handelsblatt.com", "quotidien", "economique", "Économique, libéral", "Quotidien économique de référence."),
    S("taz", "DE", "de", "https://taz.de", "quotidien", "reference", "Gauche, écologiste", "Quotidien coopératif, ligne de gauche écologiste."),
    S("tagesschau", "DE", "de", "https://www.tagesschau.de", "service_public", "service_public", "Centre, service public", "Site d'information de l'ARD."),
    S("ZDF heute", "DE", "de", "https://www.zdfheute.de", "service_public", "service_public", "Centre, service public", "Information du ZDF, seconde chaîne publique fédérale."),
    S("ORF", "AT", "de", "https://orf.at", "service_public", "service_public", "Centre, service public", "Service public autrichien."),
    S("BBC News", "GB", "en", "https://www.bbc.com/news", "service_public", "service_public", "Centre, service public", "Information de la BBC, mandat d'impartialité."),
    S("The Economist", "GB", "en", "https://www.economist.com", "hebdo", "international", "Centre, libéral", "Hebdomadaire international, ligne libérale classique."),
    S("Reuters", "GB", "en", "https://www.reuters.com", "agence", "agence", "Agence, factuelle", "Agence mondiale, rédaction à Londres."),
    S("Sky News", "GB", "en", "https://news.sky.com", "television", "reference", "Centre, généraliste", "Chaîne d'information continue, rédaction généraliste distincte de la presse tabloïd du groupe."),
    S("Channel 4 News", "GB", "en", "https://www.channel4.com/news", "television", "service_public", "Centre-gauche, service public", "Journal télévisé de Channel 4, éditeur ITN, réputé pour l'enquête."),
    S("Associated Press", "US", "en", "https://apnews.com", "agence", "agence", "Agence, factuelle", "Coopérative d'éditeurs. Agence de référence."),
    S("Bloomberg News", "US", "en", "https://www.bloomberg.com", "agence", "economique", "Économique, factuel", "Rédaction économique mondiale. Newsroom distincte du terminal et de l'éditorial."),
    S("NPR", "US", "en", "https://www.npr.org", "radio", "service_public", "Centre-gauche, service public", "Réseau de radios publiques. Ligne perçue centre-gauche."),
    S("PBS NewsHour", "US", "en", "https://www.pbs.org/newshour", "television", "service_public", "Centre, service public", "Journal télévisé du réseau public PBS."),
    S("CNN", "US", "en", "https://www.cnn.com", "television", "reference", "Centre, généraliste", "Chaîne d'information continue à audience nationale et internationale."),
    S("Fox News", "US", "en", "https://www.foxnews.com", "television", "reference", "Droite, conservateur", "Chaîne d'information et d'opinion du groupe Fox, audience nationale, ligne conservatrice assumée."),
    S("MS NOW", "US", "en", "https://www.ms.now", "television", "reference", "Centre-gauche, progressiste", "Chaîne d'opinion à audience nationale, ancienne marque MSNBC. msnbc.com redirige vers ms.now."),
    S("CNews", "FR", "fr", "https://www.cnews.fr", "television", "reference", "Droite, conservateur", "Chaîne d'information du groupe Canal+, ligne de droite assumée, audience nationale."),
    S("GB News", "GB", "en", "https://www.gbnews.com", "television", "reference", "Droite, conservateur", "Chaîne britannique d'information et d'opinion, ligne conservatrice assumée."),
    S("ABC News", "US", "en", "https://abcnews.go.com", "television", "reference", "Centre, généraliste", "Rédaction du réseau ABC."),
    S("CBS News", "US", "en", "https://www.cbsnews.com", "television", "reference", "Centre, généraliste", "Rédaction du réseau CBS."),
    S("NBC News", "US", "en", "https://www.nbcnews.com", "television", "reference", "Centre, généraliste", "Rédaction du réseau NBC."),
    S("ProPublica", "US", "en", "https://www.propublica.org", "pure_player", "investigation", "Investigation, non partisan", "Rédaction d'enquête à but non lucratif."),
    S("Politico", "US", "en", "https://www.politico.com", "pure_player", "reference", "Centre, politique", "Rédaction politique de Washington, factuelle, lue par les décideurs."),
    S("The Atlantic", "US", "en", "https://www.theatlantic.com", "magazine", "reference", "Centre-gauche, libéral", "Magazine national de long format, ligne libérale."),
    S("CBC News", "CA", "en", "https://www.cbc.ca/news", "service_public", "service_public", "Centre, service public", "Information anglophone de CBC/Radio-Canada."),
    S("Radio-Canada", "CA", "fr", "https://ici.radio-canada.ca", "service_public", "service_public", "Centre, service public", "Information francophone de CBC/Radio-Canada."),
    S("National Post", "CA", "en", "https://nationalpost.com", "quotidien", "reference", "Centre-droit, conservateur", "Quotidien national, ligne conservatrice, groupe Postmedia."),
    S("Toronto Star", "CA", "en", "https://www.thestar.com", "quotidien", "reference", "Centre-gauche, libéral", "Quotidien à diffusion nationale, ligne libérale de centre-gauche."),
    S("ANSA", "IT", "it", "https://www.ansa.it", "agence", "agence", "Agence, factuelle", "Agence de presse italienne, coopérative d'éditeurs."),
    S("RaiNews", "IT", "it", "https://www.rainews.it", "service_public", "service_public", "Centre, service public", "Information de la RAI."),
    S("RTVE", "ES", "es", "https://www.rtve.es", "service_public", "service_public", "Centre, service public", "Service public espagnol, information de TVE et RNE."),
    S("EFE", "ES", "es", "https://efe.com", "agence", "agence", "Agence, factuelle", "Agence de presse hispanophone. Capitaux publics, rédaction à vocation internationale."),
    S("El Confidencial", "ES", "es", "https://www.elconfidencial.com", "pure_player", "investigation", "Centre, investigation", "Pure player national réputé pour l'enquête."),
    S("Expansión", "ES", "es", "https://www.expansion.com", "quotidien", "economique", "Économique, libéral", "Quotidien économique, groupe Unidad Editorial."),
    S("de Volkskrant", "NL", "nl", "https://www.volkskrant.nl", "quotidien", "reference", "Centre-gauche, progressiste", "Quotidien de qualité, ligne de centre-gauche."),
    S("Trouw", "NL", "nl", "https://www.trouw.nl", "quotidien", "reference", "Centre, protestant social", "Quotidien de qualité, origine protestante, ligne sociale."),
    S("Het Financieele Dagblad", "NL", "nl", "https://fd.nl", "quotidien", "economique", "Économique, libéral", "Quotidien économique de référence."),
    S("NOS", "NL", "nl", "https://nos.nl", "service_public", "service_public", "Centre, service public", "Information du service public néerlandais."),
    S("Svenska Dagbladet", "SE", "sv", "https://www.svd.se", "quotidien", "reference", "Centre-droit, libéral-conservateur", "Quotidien de Stockholm, ligne libérale-conservatrice, pendant de Dagens Nyheter."),
    S("Dagens Industri", "SE", "sv", "https://www.di.se", "quotidien", "economique", "Économique, libéral", "Quotidien économique de référence."),
    S("SVT", "SE", "sv", "https://www.svt.se", "service_public", "service_public", "Centre, service public", "Télévision publique suédoise."),
    S("Dagens Næringsliv", "NO", "no", "https://www.dn.no", "quotidien", "economique", "Économique, libéral", "Quotidien économique de référence."),
    S("NRK", "NO", "no", "https://www.nrk.no", "service_public", "service_public", "Centre, service public", "Service public norvégien."),
    S("Politiken", "DK", "da", "https://politiken.dk", "quotidien", "reference", "Centre-gauche, libéral", "Quotidien de Copenhague, ligne sociale-libérale, pendant de Berlingske."),
    S("Information", "DK", "da", "https://www.information.dk", "quotidien", "reference", "Gauche, indépendant", "Quotidien indépendant, ligne de gauche intellectuelle."),
    S("DR", "DK", "da", "https://www.dr.dk", "service_public", "service_public", "Centre, service public", "Service public danois."),
    S("Yle", "FI", "fi", "https://yle.fi", "service_public", "service_public", "Centre, service public", "Service public finlandais."),
    S("RÚV", "IS", "is", "https://www.ruv.is", "service_public", "service_public", "Centre, service public", "Service public islandais."),
    S("Irish Independent", "IE", "en", "https://www.independent.ie", "quotidien", "reference", "Centre, généraliste", "Quotidien national à plus fort tirage, ligne modérée, groupe Mediahuis."),
    S("RTÉ", "IE", "en", "https://www.rte.ie", "service_public", "service_public", "Centre, service public", "Service public irlandais."),
    S("Expresso", "PT", "pt", "https://expresso.pt", "hebdo", "reference", "Centre, libéral", "Hebdomadaire de référence, groupe Impresa."),
    S("RTP", "PT", "pt", "https://www.rtp.pt", "service_public", "service_public", "Centre, service public", "Service public portugais."),
    S("Lusa", "PT", "pt", "https://www.lusa.pt", "agence", "agence", "Agence, factuelle", "Agence de presse portugaise, capitaux publics, copie reprise par toute la presse."),
    S("TVN24", "PL", "pl", "https://tvn24.pl", "television", "reference", "Centre, libéral", "Chaîne d'information du groupe TVN, principale rédaction audiovisuelle indépendante du pouvoir."),
    S("Polityka", "PL", "pl", "https://www.polityka.pl", "hebdo", "reference", "Centre-gauche, libéral", "Hebdomadaire de référence, ligne libérale de centre-gauche."),
    S("OKO.press", "PL", "pl", "https://oko.press", "pure_player", "investigation", "Centre-gauche, investigation", "Pure player d'enquête et de fact-checking, à but non lucratif."),
    S("Deník N", "CZ", "cs", "https://denikn.cz", "quotidien", "reference", "Centre, libéral", "Quotidien indépendant fondé par les journalistes partis de presse sous influence oligarchique."),
    S("Respekt", "CZ", "cs", "https://www.respekt.cz", "hebdo", "reference", "Centre, libéral", "Hebdomadaire d'enquête de référence."),
    S("ČT24", "CZ", "cs", "https://ct24.ceskatelevize.cz", "service_public", "service_public", "Centre, service public", "Chaîne d'information de la télévision publique tchèque."),
    S("Telex", "HU", "hu", "https://telex.hu", "pure_player", "reference", "Centre, indépendant", "Pure player fondé par la rédaction de l'Index après la prise de contrôle de 2020. Principale rédaction indépendante à large audience."),
    S("HVG", "HU", "hu", "https://hvg.hu", "hebdo", "reference", "Centre, libéral", "Hebdomadaire économique et politique, une des dernières rédactions indépendantes historiques."),
    S("444", "HU", "hu", "https://444.hu", "pure_player", "investigation", "Centre-gauche, investigation", "Pure player indépendant, enquête et politique."),
    S("Ta Nea", "GR", "el", "https://www.tanea.gr", "quotidien", "reference", "Centre-gauche, libéral", "Quotidien historique de centre-gauche, pendant de Kathimerini."),
    S("ERT News", "GR", "el", "https://www.ertnews.gr", "service_public", "service_public", "Centre, service public", "Information de la radio-télévision publique, rétablie après la fermeture de 2013."),
    S("Recorder", "RO", "ro", "https://recorder.ro", "pure_player", "investigation", "Investigation, indépendant", "Rédaction vidéo d'enquête, référence actuelle du journalisme indépendant roumain."),
    S("G4 Media", "RO", "ro", "https://www.g4media.ro", "pure_player", "reference", "Centre, pro-européen", "Pure player politique, ligne pro-européenne, rédaction identifiable."),
    S("Postimees", "EE", "et", "https://www.postimees.ee", "quotidien", "reference", "Centre, généraliste", "Principal quotidien estonien."),
    S("ERR", "EE", "et", "https://www.err.ee", "service_public", "service_public", "Centre, service public", "Service public estonien."),
    S("LSM", "LV", "lv", "https://www.lsm.lv", "service_public", "service_public", "Centre, service public", "Service public letton, portail commun radio et télévision."),
    S("LRT", "LT", "lt", "https://www.lrt.lt", "service_public", "service_public", "Centre, service public", "Service public lituanien."),
    S("SME", "SK", "sk", "https://www.sme.sk", "quotidien", "reference", "Centre, libéral", "Quotidien de référence slovaque, ligne libérale."),
    S("Denník N", "SK", "sk", "https://dennikn.sk", "quotidien", "reference", "Centre, libéral", "Quotidien indépendant, frère du Deník N tchèque."),
    S("Delo", "SI", "sl", "https://www.delo.si", "quotidien", "reference", "Centre, libéral", "Quotidien de référence slovène."),
    S("Jutarnji list", "HR", "hr", "https://www.jutarnji.hr", "quotidien", "reference", "Centre, libéral", "Quotidien national croate, groupe Hanza Media."),
    S("Capital", "BG", "bg", "https://www.capital.bg", "hebdo", "economique", "Centre, libéral", "Hebdomadaire économique du groupe Economedia, une des rares rédactions indépendantes du pays."),
    S("Dnevnik", "BG", "bg", "https://www.dnevnik.bg", "quotidien", "reference", "Centre, libéral", "Quotidien du groupe Economedia."),
    S("N1", "RS", "sr", "https://n1info.rs", "television", "reference", "Centre, indépendant", "Chaîne d'information régionale (Serbie, Croatie, Bosnie), rédaction indépendante des pouvoirs locaux. Fiche rattachée à la Serbie, diffusion Adria."),
    S("Oslobođenje", "BA", "bs", "https://www.oslobodjenje.ba", "quotidien", "reference", "Centre, indépendant", "Quotidien historique de Sarajevo."),
    S("Reporter.al", "AL", "sq", "https://www.reporter.al", "pure_player", "investigation", "Investigation, indépendant", "Site albanais du Balkan Investigative Reporting Network."),
    S("Vijesti", "ME", "sr", "https://www.vijesti.me", "quotidien", "reference", "Centre, indépendant", "Principal quotidien indépendant du Monténégro."),
    S("Ukrainska Pravda", "UA", "uk", "https://www.pravda.com.ua", "pure_player", "reference", "Centre, indépendant", "Pure player politique de référence, fondé en 2000, rédaction indépendante."),
    S("Kyiv Independent", "UA", "en", "https://kyivindependent.com", "pure_player", "reference", "Centre, indépendant", "Rédaction anglophone créée en 2021 par des journalistes du Kyiv Post, indépendante."),
    S("Suspilne", "UA", "uk", "https://suspilne.media", "service_public", "service_public", "Centre, service public", "Audiovisuel public ukrainien, réformé après 2014 pour l'éloigner du pouvoir."),
    S("European Pravda", "UA", "uk", "https://www.eurointegration.com.ua", "pure_player", "international", "Centre, pro-européen", "Rédaction spécialisée dans la politique européenne et internationale de l'Ukraine."),
    S("Civil.ge", "GE", "en", "https://civil.ge", "pure_player", "reference", "Centre, indépendant", "Site d'actualité géorgien en anglais, référence pour la politique nationale."),
    S("Netgazeti", "GE", "ka", "https://netgazeti.ge", "pure_player", "reference", "Centre, indépendant", "Pure player géorgien indépendant."),
    S("Ziarul de Gardă", "MD", "ro", "https://www.zdg.md", "pure_player", "investigation", "Investigation, indépendant", "Rédaction d'enquête de référence en Moldavie."),
    S("NewsMaker", "MD", "ru", "https://newsmaker.md", "pure_player", "reference", "Centre, indépendant", "Pure player indépendant, principalement en russe."),
    S("Meduza", "RU", "ru", "https://meduza.io", "pure_player", "reference", "Centre, indépendant", "Rédaction russe en exil (Riga). Référence de l'information indépendante en russe.", "Rédaction en exil. Pays éditorial : Russie."),
    S("Novaya Gazeta Europe", "RU", "ru", "https://novayagazeta.eu", "pure_player", "investigation", "Centre-gauche, investigation", "Poursuite en exil de la rédaction de Novaïa Gazeta.", "Rédaction en exil."),
    S("The Moscow Times", "RU", "en", "https://www.themoscowtimes.com", "pure_player", "reference", "Centre, indépendant", "Quotidien anglophone historique, rédaction désormais hors de Russie.", "Rédaction en exil."),
    S("Mediazona", "RU", "ru", "https://zona.media", "pure_player", "investigation", "Investigation, indépendant", "Rédaction spécialisée justice et répression, fondée par Pussy Riot, travaillant hors censure.", "Rédaction en exil."),
    S("iStories", "RU", "ru", "https://istories.media", "pure_player", "investigation", "Investigation, indépendant", "Rédaction d'enquête en exil, importante investigations sur l'appareil d'État.", "Rédaction en exil."),
    S("Zerkalo", "BY", "ru", "https://zerkalo.io", "pure_player", "reference", "Centre, indépendant", "Poursuite de Tut.by après sa liquidation. Principale rédaction indépendante biélorusse.", "Rédaction en exil."),
    S("Nasha Niva", "BY", "be", "https://nashaniva.com", "pure_player", "reference", "Centre, indépendant", "Titre historique biélorusse, rédaction indépendante désormais hors du pays.", "Rédaction en exil."),
    S("Vlast", "KZ", "ru", "https://vlast.kz", "pure_player", "reference", "Centre, indépendant", "Magazine et site indépendants, une des rares rédactions critiques encore publiées au Kazakhstan."),
    S("Kloop", "KG", "ru", "https://kloop.kg", "pure_player", "investigation", "Investigation, indépendant", "Rédaction d'enquête kirghize, sous pression judiciaire."),
    S("The Times of Israel", "IL", "en", "https://www.timesofisrael.com", "pure_player", "reference", "Centre, libéral", "Pure player anglophone, ligne centriste libérale, sans paywall."),
    S("The Jerusalem Post", "IL", "en", "https://www.jpost.com", "quotidien", "reference", "Centre-droit, conservateur", "Quotidien anglophone historique, ligne de centre-droit."),
    S("Globes", "IL", "he", "https://www.globes.co.il", "quotidien", "economique", "Économique, libéral", "Quotidien économique israélien."),
    S("Kan", "IL", "he", "https://www.kan.org.il", "service_public", "service_public", "Centre, service public", "Radiodiffusion publique israélienne, créée en 2017 pour succéder à l'IBA."),
    S("L'Orient-Le Jour", "LB", "fr", "https://www.lorientlejour.com", "quotidien", "reference", "Centre, libéral", "Quotidien francophone de référence à Beyrouth."),
    S("T24", "TR", "tr", "https://t24.com.tr", "pure_player", "reference", "Centre-gauche, indépendant", "Pure player indépendant, une des rares rédactions nationales encore critiques."),
    S("Bianet", "TR", "tr", "https://bianet.org", "pure_player", "investigation", "Gauche, droits", "Rédaction indépendante spécialisée droits et médias, à Istanbul."),
    S("Caixin", "CN", "zh", "https://www.caixin.com", "pure_player", "economique", "Économique, investigation", "Média économique privé. Meilleure rédaction d'enquête encore publiée en Chine, dans les limites de la censure."),
    S("Hong Kong Free Press", "HK", "en", "https://hongkongfp.com", "pure_player", "reference", "Centre, indépendant", "Pure player anglophone indépendant, à but non lucratif."),
    S("Ming Pao", "HK", "zh", "https://news.mingpao.com", "quotidien", "reference", "Centre, libéral", "Quotidien de qualité historique. L'environnement légal de Hong Kong pèse sur toute la presse ; la rédaction reste un titre professionnel identifié."),
    S("United Daily News", "TW", "zh", "https://udn.com", "quotidien", "reference", "Centre-droit, conservateur", "Un des grands quotidiens taïwanais, ligne pan-bleue modérée."),
    S("Liberty Times", "TW", "zh", "https://www.ltn.com.tw", "quotidien", "reference", "Centre-gauche, souverainiste", "Quotidien national, ligne pan-verte."),
    S("Taipei Times", "TW", "en", "https://www.taipeitimes.com", "quotidien", "reference", "Centre-gauche, souverainiste", "Quotidien anglophone du groupe Liberty Times."),
    S("CNA", "TW", "zh", "https://focustaiwan.tw", "agence", "agence", "Agence, factuelle", "Agence centrale de presse, site anglophone Focus Taiwan. Établissement public à charte d'indépendance."),
    S("NHK", "JP", "ja", "https://www.nhk.or.jp", "service_public", "service_public", "Centre, service public", "Radiodiffusion publique. Redevance et loi d'indépendance."),
    S("Kyodo News", "JP", "en", "https://english.kyodonews.net", "agence", "agence", "Agence, factuelle", "Coopérative des journaux japonais. Site anglophone public."),
    S("Hankyoreh", "KR", "ko", "https://www.hani.co.kr", "quotidien", "reference", "Centre-gauche, progressiste", "Quotidien progressiste, pendant des trois grands titres conservateurs."),
    S("Yonhap", "KR", "en", "https://en.yna.co.kr", "agence", "agence", "Agence, factuelle", "Agence nationale. Capitaux mêlés, site anglophone public. Pression politique récurrente, copie largement reprise."),
    S("KBS", "KR", "ko", "https://news.kbs.co.kr", "service_public", "service_public", "Centre, service public", "Radiodiffusion publique. L'indépendance varie selon les présidences ; le mandat légal reste celui d'un service public."),
    S("The Indian Express", "IN", "en", "https://indianexpress.com", "quotidien", "reference", "Centre, investigation", "Quotidien national de référence, tradition d'enquête depuis l'état d'urgence."),
    S("Hindustan Times", "IN", "en", "https://www.hindustantimes.com", "quotidien", "reference", "Centre, libéral", "Quotidien national, groupe Birla, ligne de centre."),
    S("Business Standard", "IN", "en", "https://www.business-standard.com", "quotidien", "economique", "Économique, libéral", "Quotidien économique de référence."),
    S("Mint", "IN", "en", "https://www.livemint.com", "quotidien", "economique", "Économique, libéral", "Quotidien économique, partenariat éditorial historique avec le Wall Street Journal."),
    S("The Wire", "IN", "en", "https://thewire.in", "pure_player", "investigation", "Centre-gauche, investigation", "Pure player d'enquête à but non lucratif."),
    S("Dawn", "PK", "en", "https://www.dawn.com", "quotidien", "reference", "Centre, libéral", "Quotidien de référence du Pakistan, ligne libérale, groupe Herald Publications."),
    S("The News International", "PK", "en", "https://www.thenews.com.pk", "quotidien", "reference", "Centre, généraliste", "Quotidien anglophone national du groupe Jang."),
    S("Business Recorder", "PK", "en", "https://www.brecorder.com", "quotidien", "economique", "Économique, libéral", "Quotidien économique de Karachi."),
    S("Prothom Alo", "BD", "bn", "https://www.prothomalo.com", "quotidien", "reference", "Centre, libéral", "Premier quotidien bengali, même groupe que The Daily Star."),
    S("The Kathmandu Post", "NP", "en", "https://kathmandupost.com", "quotidien", "reference", "Centre, libéral", "Quotidien anglophone de référence, groupe Kantipur."),
    S("Daily FT", "LK", "en", "https://www.ft.lk", "quotidien", "economique", "Économique, libéral", "Quotidien économique sri-lankais."),
    S("EconomyNext", "LK", "en", "https://economynext.com", "pure_player", "economique", "Économique, libéral", "Pure player économique indépendant, lu pour la macroéconomie du pays."),
    S("Tempo", "ID", "id", "https://www.tempo.co", "magazine", "investigation", "Centre, investigation", "News magazine historique, principale rédaction d'enquête du pays."),
    S("The Jakarta Post", "ID", "en", "https://www.thejakartapost.com", "quotidien", "reference", "Centre, libéral", "Quotidien anglophone de référence."),
    S("Malaysiakini", "MY", "en", "https://www.malaysiakini.com", "pure_player", "reference", "Centre, indépendant", "Premier pure player indépendant du pays. Abonnement, rédaction identifiée, plusieurs prix régionaux."),
    S("Rappler", "PH", "en", "https://www.rappler.com", "pure_player", "investigation", "Centre, investigation", "Pure player d'enquête. Harcèlement judiciaire documenté ; la rédaction reste une référence."),
    S("Philippine Star", "PH", "en", "https://www.philstar.com", "quotidien", "reference", "Centre, généraliste", "Quotidien national anglophone."),
    S("ABS-CBN News", "PH", "en", "https://news.abs-cbn.com", "television", "reference", "Centre, généraliste", "Rédaction du principal réseau, privé de franchise hertzienne en 2020, poursuite en ligne."),
    S("Thai PBS", "TH", "th", "https://www.thaipbs.or.th", "service_public", "service_public", "Centre, service public", "Télévision publique thaïlandaise, plus distante du pouvoir que les chaînes militaires et commerciales."),
    S("ABC News", "AU", "en", "https://www.abc.net.au/news", "service_public", "service_public", "Centre, service public", "Information de l'Australian Broadcasting Corporation."),
    S("The Australian", "AU", "en", "https://www.theaustralian.com.au", "quotidien", "reference", "Centre-droit, conservateur", "Quotidien national, groupe News Corp, ligne conservatrice. Rédaction broadsheet, distincte des tabloïds du groupe."),
    S("Australian Financial Review", "AU", "en", "https://www.afr.com", "quotidien", "economique", "Économique, libéral", "Quotidien économique de référence, groupe Nine."),
    S("RNZ", "NZ", "en", "https://www.rnz.co.nz", "service_public", "service_public", "Centre, service public", "Radio publique néo-zélandaise."),
    S("Stuff", "NZ", "en", "https://www.stuff.co.nz", "pure_player", "reference", "Centre, généraliste", "Principal site national, issu du groupe de journaux Stuff, désormais détenu par ses rédactions."),
    S("Newsroom", "NZ", "en", "https://newsroom.co.nz", "pure_player", "investigation", "Centre, investigation", "Pure player d'enquête et de politique."),
    S("Daily Maverick", "ZA", "en", "https://www.dailymaverick.co.za", "pure_player", "investigation", "Centre, investigation", "Pure player d'enquête, une des rédactions les plus citées du pays."),
    S("Business Day", "ZA", "en", "https://www.businesslive.co.za", "quotidien", "economique", "Économique, libéral", "Quotidien économique, groupe Arena."),
    S("News24", "ZA", "en", "https://www.news24.com", "pure_player", "reference", "Centre, généraliste", "Principal site d'information, groupe Naspers. Rédaction professionnelle à large audience."),
    S("The Standard", "KE", "en", "https://www.standardmedia.co.ke", "quotidien", "reference", "Centre, généraliste", "Second quotidien national, groupe Standard."),
    S("The EastAfrican", "KE", "en", "https://www.theeastafrican.co.ke", "hebdo", "international", "Centre, régional", "Hebdomadaire régional du groupe Nation Media, couverture Afrique de l'Est."),
    S("Premium Times", "NG", "en", "https://www.premiumtimesng.com", "pure_player", "investigation", "Centre, investigation", "Pure player d'enquête de référence au Nigeria."),
    S("The Punch", "NG", "en", "https://punchng.com", "quotidien", "reference", "Centre, généraliste", "Quotidien national à plus fort tirage, rédaction généraliste."),
    S("BusinessDay", "NG", "en", "https://businessday.ng", "quotidien", "economique", "Économique, libéral", "Quotidien économique de Lagos."),
    S("Channels Television", "NG", "en", "https://www.channelstv.com", "television", "reference", "Centre, généraliste", "Principale chaîne privée d'information."),
    S("MyJoyOnline", "GH", "en", "https://www.myjoyonline.com", "radio", "reference", "Centre, généraliste", "Site de Joy FM, principale rédaction privée du pays."),
    S("Citi Newsroom", "GH", "en", "https://citinewsroom.com", "radio", "reference", "Centre, généraliste", "Site de Citi FM, rédaction d'information d'Accra."),
    S("Le Quotidien", "SN", "fr", "https://lequotidien.sn", "quotidien", "reference", "Centre, indépendant", "Quotidien privé sénégalais, une des rédactions nationales distinctes du quotidien d'État Le Soleil."),
    S("Le Desk", "MA", "fr", "https://ledesk.ma", "pure_player", "investigation", "Centre, investigation", "Pure player d'enquête marocain."),
    S("TelQuel", "MA", "fr", "https://telquel.ma", "magazine", "reference", "Centre-gauche, libéral", "News magazine francophone de référence."),
    S("Médias24", "MA", "fr", "https://medias24.com", "pure_player", "economique", "Économique, factuel", "Site économique de référence."),
    S("L'Économiste", "MA", "fr", "https://www.leconomiste.com", "quotidien", "economique", "Économique, libéral", "Quotidien économique historique."),
    S("Inkyfada", "TN", "fr", "https://inkyfada.com", "pure_player", "investigation", "Investigation, indépendant", "Rédaction d'enquête tunisienne, long format."),
    S("Nawaat", "TN", "ar", "https://nawaat.org", "pure_player", "investigation", "Gauche, indépendant", "Plateforme indépendante historique, née avant 2011."),
    S("Mada Masr", "EG", "en", "https://www.madamasr.com", "pure_player", "investigation", "Centre-gauche, investigation", "Dernière rédaction indépendante d'ampleur en Égypte. Site souvent bloqué dans le pays.", "Site fréquemment bloqué en Égypte."),
    S("The Citizen", "TZ", "en", "https://www.thecitizen.co.tz", "quotidien", "reference", "Centre, généraliste", "Quotidien anglophone du groupe Nation Media en Tanzanie."),
    S("Daily Monitor", "UG", "en", "https://www.monitor.co.ug", "quotidien", "reference", "Centre, indépendant", "Quotidien ougandais du groupe Nation Media, plus distant du pouvoir que New Vision."),
    S("The Namibian", "NA", "en", "https://www.namibian.com.na", "quotidien", "reference", "Centre, indépendant", "Quotidien de référence namibien."),
    S("Mmegi", "BW", "en", "https://www.mmegi.bw", "quotidien", "reference", "Centre, indépendant", "Quotidien de référence du Botswana."),
    S("L'Express", "MU", "fr", "https://lexpress.mu", "quotidien", "reference", "Centre, généraliste", "Quotidien de référence mauricien. Homonyme du magazine français, groupe La Sentinelle."),
    S("Radio Okapi", "CD", "fr", "https://www.radiookapi.net", "radio", "service_public", "Centre, indépendant", "Radio de la Fondation Hirondelle et de la MONUSCO. Principale rédaction nationale crédible en RDC."),
    S("NewsDay", "ZW", "en", "https://www.newsday.co.zw", "quotidien", "reference", "Centre, indépendant", "Quotidien du groupe Alpha Media Holdings, distinct de la presse d'État."),
    S("Addis Standard", "ET", "en", "https://addisstandard.com", "pure_player", "reference", "Centre, indépendant", "Magazine et site indépendants, une des rares rédactions critiques encore publiées."),
    S("El Universal", "MX", "es", "https://www.eluniversal.com.mx", "quotidien", "reference", "Centre, généraliste", "Quotidien national historique de Mexico."),
    S("El Financiero", "MX", "es", "https://www.elfinanciero.com.mx", "quotidien", "economique", "Économique, libéral", "Quotidien économique de référence."),
    S("Animal Político", "MX", "es", "https://www.animalpolitico.com", "pure_player", "investigation", "Centre, investigation", "Pure player d'enquête de référence."),
    S("Proceso", "MX", "es", "https://www.proceso.com.mx", "magazine", "investigation", "Centre-gauche, investigation", "News magazine d'enquête, fondé en 1976."),
    S("Clarín", "AR", "es", "https://www.clarin.com", "quotidien", "reference", "Centre, généraliste", "Plus gros quotidien national, ligne de centre, groupe Clarín. Acteur politique autant que rédaction."),
    S("Infobae", "AR", "es", "https://www.infobae.com", "pure_player", "reference", "Centre-droit, libéral", "Principal pure player hispanophone d'Argentine, audience régionale."),
    S("Ámbito", "AR", "es", "https://www.ambito.com", "quotidien", "economique", "Économique, libéral", "Quotidien économique."),
    S("Página/12", "AR", "es", "https://www.pagina12.com.ar", "quotidien", "reference", "Gauche, progressiste", "Quotidien national, ligne de gauche."),
    S("La Tercera", "CL", "es", "https://www.latercera.com", "quotidien", "reference", "Centre-droit, libéral", "Quotidien national, pendant plus libéral d'El Mercurio, groupe Copesa."),
    S("CIPER", "CL", "es", "https://www.ciperchile.cl", "pure_player", "investigation", "Investigation, non partisan", "Centre d'enquête à but non lucratif, référence du journalisme d'investigation."),
    S("Diario Financiero", "CL", "es", "https://www.df.cl", "quotidien", "economique", "Économique, libéral", "Quotidien économique."),
    S("La Silla Vacía", "CO", "es", "https://www.lasillavacia.com", "pure_player", "investigation", "Centre, investigation", "Pure player de politique et d'enquête."),
    S("El Comercio", "PE", "es", "https://elcomercio.pe", "quotidien", "reference", "Centre-droit, libéral", "Quotidien de référence de Lima, groupe El Comercio."),
    S("La República", "PE", "es", "https://larepublica.pe", "quotidien", "reference", "Centre-gauche, progressiste", "Quotidien national, ligne de centre-gauche."),
    S("IDL-Reporteros", "PE", "es", "https://www.idl-reporteros.pe", "pure_player", "investigation", "Investigation, non partisan", "Rédaction d'enquête de l'Institut de défense légale, à l'origine des révélations Lava Jato au Pérou."),
    S("OjoPúblico", "PE", "es", "https://ojo-publico.com", "pure_player", "investigation", "Investigation, non partisan", "Rédaction d'enquête indépendante."),
    S("El País", "UY", "es", "https://www.elpais.com.uy", "quotidien", "reference", "Centre-droit, libéral", "Quotidien de référence de Montevideo. Homonyme du quotidien espagnol, autre société."),
    S("El Observador", "UY", "es", "https://www.elobservador.com.uy", "quotidien", "reference", "Centre, libéral", "Second quotidien national."),
    S("Última Hora", "PY", "es", "https://www.ultimahora.com", "quotidien", "reference", "Centre, généraliste", "Quotidien national, pendant d'ABC Color."),
    S("El Deber", "BO", "es", "https://eldeber.com.bo", "quotidien", "reference", "Centre, régional", "Principal quotidien de Santa Cruz, couverture nationale de fait."),
    S("El Universo", "EC", "es", "https://www.eluniverso.com", "quotidien", "reference", "Centre, libéral", "Quotidien de Guayaquil, diffusion nationale."),
    S("Primicias", "EC", "es", "https://www.primicias.ec", "pure_player", "reference", "Centre, libéral", "Pure player politique et économique de Quito."),
    S("Efecto Cocuyo", "VE", "es", "https://efectococuyo.com", "pure_player", "reference", "Centre, indépendant", "Rédaction indépendante vénézuélienne, une des dernières à pratique de terrain.", "Rédaction sous contrainte, partie de l'équipe hors du pays."),
    S("Armando.Info", "VE", "es", "https://armando.info", "pure_player", "investigation", "Investigation, indépendant", "Rédaction d'enquête vénézuélienne, installée à l'étranger après des poursuites.", "Rédaction en exil."),
    S("14ymedio", "CU", "es", "https://www.14ymedio.com", "pure_player", "reference", "Centre, indépendant", "Quotidien numérique indépendant fondé par Yoani Sánchez. Bloqué sur l'île.", "Rédaction indépendante, site bloqué à Cuba."),
    S("La Prensa", "NI", "es", "https://www.laprensani.com", "quotidien", "reference", "Centre, indépendant", "Quotidien historique. Rédaction occupée en 2021, poursuite hors du pays.", "Marque occupée ; archive et poursuite à vérifier à la collecte."),
    S("Confidencial", "NI", "es", "https://confidencial.digital", "pure_player", "investigation", "Centre, investigation", "Rédaction d'enquête de Carlos Fernando Chamorro, en exil.", "Rédaction en exil."),
    S("El Faro", "SV", "es", "https://elfaro.net", "pure_player", "investigation", "Investigation, indépendant", "Premier pure player d'Amérique centrale, rédaction partie au Costa Rica sous la pression du gouvernement Bukele.", "Rédaction en exil."),
    S("Valor Econômico", "BR", "pt", "https://valor.globo.com", "quotidien", "economique", "Économique, libéral", "Quotidien économique du groupe Globo."),
    S("Agência Pública", "BR", "pt", "https://apublica.org", "pure_player", "investigation", "Investigation, non partisan", "Agence d'enquête à but non lucratif."),
    S("Luxemburger Wort", "LU", "de", "https://www.wort.lu", "quotidien", "reference", "Centre, catholique", "Quotidien de référence, groupe Saint-Paul, ligne de centre historiquement catholique."),
    S("Paperjam", "LU", "fr", "https://paperjam.lu", "pure_player", "economique", "Économique, libéral", "Média économique de la place luxembourgeoise."),
    S("Times of Malta", "MT", "en", "https://timesofmalta.com", "quotidien", "reference", "Centre, libéral", "Quotidien de référence maltais."),
    S("Cyprus Mail", "CY", "en", "https://cyprus-mail.com", "quotidien", "reference", "Centre, libéral", "Quotidien anglophone de référence à Chypre."),
    S("Jeune Afrique", "FR", "fr", "https://www.jeuneafrique.com", "magazine", "international", "Centre, panafricain", "News magazine panafricain, siège à Paris, couverture politique et économique du continent."),
    S("Deutsche Welle", "DE", "de", "https://www.dw.com", "service_public", "international", "Centre, service public", "Audiovisuel public international allemand."),
    S("Politico Europe", "BE", "en", "https://www.politico.eu", "pure_player", "reference", "Centre, politique", "Rédaction bruxelloise de Politico, référence sur les institutions européennes."),
    S("The Irrawaddy", "MM", "en", "https://www.irrawaddy.com", "pure_player", "reference", "Centre, indépendant", "Média birman indépendant, rédaction en exil depuis le coup d'État de 2021.", "Rédaction en exil."),
    S("Myanmar Now", "MM", "en", "https://myanmar-now.org", "pure_player", "investigation", "Investigation, indépendant", "Rédaction d'enquête birmane, en exil.", "Rédaction en exil."),
    S("Honduras: Contracorriente", "HN", "es", "https://contracorriente.red", "pure_player", "investigation", "Investigation, indépendant", "Rédaction d'enquête hondurienne. Le pays n'a pas de quotidien de référence à indépendance incontestable ; c'est la rédaction qui passe la barre."),
]

FAMILLE_BY_NAME = {
    "financial times": "economique", "the wall street journal": "economique",
    "il sole 24 ore": "economique", "nihon keizai shimbun (nikkei)": "economique",
    "die zeit": "reference", "mail & guardian": "investigation",
    "le monde diplomatique": "international",
}

COMMON_FEEDS = ["/rss", "/feed", "/feed/", "/rss.xml", "/feed.xml", "/atom.xml", "/index.rss", "/rss/une.xml"]
SITEMAP_PATHS = ["/sitemap.xml", "/sitemap_index.xml", "/sitemap-news.xml", "/news-sitemap.xml"]
FEED_LINK_RE = re.compile(r"<link\b[^>]*type=[\"']application/(?:rss|atom)\+xml[\"'][^>]*>", re.I)
HREF_RE = re.compile(r"href=[\"']([^\"']+)[\"']", re.I)
FLAG_RE = re.compile(r"flagicon\|([^}]+)", re.I)
NAME_RE = re.compile(r"''\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|([^\]]+))?\]\]''")


def curl(url: str, timeout: int = 20, ua: str = UA, method: str = "GET", data: str | None = None, accept: str | None = None) -> tuple[int, str, bytes]:
    cmd = ["curl", "-sS", "-L", "--http1.1", "--compressed", "--max-time", str(timeout), "-A", ua, "-w", "\n%{http_code}", "-o", "-"]
    if accept:
        cmd += ["-H", f"Accept: {accept}"]
    if method == "POST" and data is not None:
        cmd += ["-X", "POST", "--data", data]
    cmd.append(url)
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout + 5)
    except subprocess.TimeoutExpired:
        return 0, "", b""
    raw = p.stdout or b""
    # status is the last line
    if b"\n" not in raw:
        return 0, "", raw
    body, _, code_b = raw.rpartition(b"\n")
    try:
        code = int(code_b.strip() or b"0")
    except ValueError:
        code = 0
    ctype = ""
    # curl -w doesn't give content-type this way; sniff
    head = body[:80].lstrip().lower()
    if head.startswith(b"<?xml") or head.startswith(b"<rss") or head.startswith(b"<feed") or head.startswith(b"<urlset") or head.startswith(b"<sitemapindex"):
        ctype = "xml"
    elif head.startswith(b"<!doctype html") or head.startswith(b"<html") or b"<html" in body[:500].lower():
        ctype = "html"
    elif head.startswith(b"{") or head.startswith(b"["):
        ctype = "json"
    return code, ctype, body


def curl_json(url: str, timeout: int = 60, data: str | None = None) -> dict:
    code, _, body = curl(url, timeout=timeout, ua=UA_WD, method="POST" if data else "GET", data=data, accept="application/json")
    if code != 200 or not body:
        return {}
    try:
        return json.loads(body.decode("utf-8", "replace"))
    except json.JSONDecodeError:
        return {}


def load_countries() -> dict[str, dict]:
    rows = json.loads(COUNTRIES.read_text())
    by_name = {}
    for c in rows:
        by_name[c["name_en"].casefold()] = c
    return by_name


def iso_of(country_name: str, by_name: dict) -> str | None:
    if not country_name:
        return None
    key = country_name.strip().casefold()
    key = ALIASES.get(key, key)
    hit = by_name.get(key)
    return hit["code"] if hit else None


def region_of(code: str | None, by_code: dict) -> str:
    if not code:
        return "—"
    return (by_code.get(code) or {}).get("region") or "—"


def parse_wiki() -> list[dict]:
    text = WIKI.read_text()
    rows = re.split(r"\n\|-", text)
    country = None
    out = []
    for row in rows[1:]:
        lines = [l for l in row.splitlines() if l.startswith("|")]
        cells = [l[1:].strip() for l in lines]
        joined = "\n".join(cells)
        m = FLAG_RE.search(joined)
        if m and "flagicon" in joined.casefold():
            # country is the flag cell's visible name if present, else the flag target
            for c in cells:
                fm = FLAG_RE.search(c)
                if fm:
                    country = fm.group(1).strip()
                    # visible name after the template
                    vis = re.sub(r"\{\{[^}]+\}\}", "", c)
                    vis = re.sub(r"style=\"[^\"]*\"", "", vis)
                    vis = vis.replace("|", " ").strip()
                    if vis:
                        country = vis.split("\n")[0].strip()
                    break
        name = article = None
        for c in cells:
            mm = NAME_RE.search(c)
            if mm:
                article = mm.group(1).strip()
                name = (mm.group(2) or mm.group(1)).strip()
                break
        if not name:
            continue
        founded = None
        language = None
        for c in cells:
            cc = re.sub(r"<ref[\s\S]*?</ref>", "", c)
            cc = re.sub(r"<ref[^>]*/>", "", cc)
            cc = re.sub(r"\{\{[^}]+\}\}", "", cc)
            cc = re.sub(r"style=\"[^\"]*\"\s*\|", "", cc).strip().strip("|").strip()
            if founded is None and re.match(r"\d{4}", cc):
                founded = cc[:4]
            low = cc.casefold()
            if low in LANG:
                language = low
        out.append({
            "name": name,
            "wikipedia": article,
            "country_name": country,
            "founded": founded,
            "lang_name": language,
            "source": "wikipedia_record",
        })
    return out


def longevity(year: str | None) -> int | None:
    if not year or not year.isdigit():
        return None
    y = int(year)
    if y < 1850:
        return 98
    if y < 1900:
        return 92
    if y < 1945:
        return 85
    if y < 1980:
        return 75
    if y < 2000:
        return 62
    if y < 2015:
        return 48
    return 35


def wiki_qids(titles: list[str]) -> dict[str, str]:
    """wikipedia title -> QID, following redirects."""
    found = {}
    for i in range(0, len(titles), 40):
        chunk = titles[i:i + 40]
        data = "action=query&prop=pageprops&ppprop=wikibase_item&redirects=1&format=json&titles=" + quote("|".join(chunk), safe="")
        d = curl_json("https://en.wikipedia.org/w/api.php", data=data)
        pages = (d.get("query") or {}).get("pages") or {}
        redirects = (d.get("query") or {}).get("redirects") or []
        norm = (d.get("query") or {}).get("normalized") or []
        back = {}
        for n in norm:
            back[n.get("to")] = n.get("from")
        for r in redirects:
            src = back.get(r.get("from"), r.get("from"))
            back[r.get("to")] = src
        for page in pages.values():
            qid = ((page.get("pageprops") or {}).get("wikibase_item"))
            title = page.get("title")
            if not qid or not title:
                continue
            origin = back.get(title, title)
            found[origin] = qid
            found[title] = qid
        time.sleep(0.2)
    return found


def wd_entities(qids: list[str]) -> dict[str, dict]:
    out = {}
    ids = [q for q in dict.fromkeys(qids) if q]
    for i in range(0, len(ids), 40):
        chunk = "|".join(ids[i:i + 40])
        d = curl_json(
            "https://www.wikidata.org/w/api.php",
            data=f"action=wbgetentities&ids={chunk}&props=labels|claims&languages=fr|en&format=json",
        )
        out.update(d.get("entities") or {})
        time.sleep(0.2)
    return out


def claim_values(entity: dict, pid: str) -> list[str]:
    vals = []
    for c in (entity.get("claims") or {}).get(pid) or []:
        snak = c.get("mainsnak") or {}
        dv = (snak.get("datavalue") or {}).get("value")
        if isinstance(dv, str):
            vals.append(dv)
        elif isinstance(dv, dict):
            if "time" in dv:
                vals.append(dv["time"][1:11])
            elif "id" in dv:
                vals.append(dv["id"])
    return vals


def label_of(entity: dict) -> str:
    labels = entity.get("labels") or {}
    return ((labels.get("fr") or labels.get("en") or {}).get("value")) or ""


def best_website(urls: list[str]) -> str | None:
    if not urls:
        return None
    https = [u for u in urls if u.startswith("https://")]
    pool = https or urls
    # prefer homepages (short path)
    def score(u: str) -> tuple:
        p = urlparse(u)
        path = p.path.rstrip("/")
        return (len(path), len(u))
    return sorted(pool, key=score)[0]


def domain(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
    except ValueError:
        return ""
    if host.startswith("www."):
        host = host[4:]
    return host


def search_qid(name: str) -> list[str]:
    d = curl_json(
        "https://www.wikidata.org/w/api.php?action=wbsearchentities&format=json&language=en&type=item&limit=4&search=" + quote(name)
    )
    return [s.get("id") for s in d.get("search") or [] if s.get("id")]


def feed_ok(body: bytes) -> bool:
    head = body[:2500].lstrip().lower()
    if not (head.startswith(b"<?xml") or b"<rss" in head or b"<feed" in head):
        return False
    return b"<item" in body.lower() or b"<entry" in body.lower()


def sitemap_ok(body: bytes) -> bool:
    head = body[:2500].lstrip().lower()
    return (b"<urlset" in head or b"<sitemapindex" in head or b"<urlset" in body[:8000].lower() or b"<sitemapindex" in body[:8000].lower())


def discover(item: dict) -> dict:
    site = item["website_url"]
    code, ctype, body = curl(site, timeout=15)
    html = body.decode("utf-8", "replace") if body else ""
    feeds: list[str] = []
    candidates: list[str] = []
    if html:
        for m in FEED_LINK_RE.finditer(html[:300_000]):
            h = HREF_RE.search(m.group(0))
            if h:
                candidates.append(urljoin(site, h.group(1)))
    base = site.rstrip("/")
    candidates += [base + p for p in COMMON_FEEDS]
    seen = set()
    for u in candidates:
        u = u.split("#")[0]
        if u in seen or len(feeds) >= 3:
            continue
        seen.add(u)
        c, _, b = curl(u, timeout=12)
        if c == 200 and feed_ok(b):
            feeds.append(u)
    # sitemap via robots then common paths
    sitemaps: list[str] = []
    rcode, _, rbody = curl(urljoin(site, "/robots.txt"), timeout=10)
    if rcode == 200 and rbody:
        for line in rbody.decode("utf-8", "replace").splitlines():
            if line.lower().startswith("sitemap:"):
                sitemaps.append(line.split(":", 1)[1].strip())
    if not sitemaps:
        for p in SITEMAP_PATHS:
            u = base + p
            c, _, b = curl(u, timeout=10)
            if c == 200 and sitemap_ok(b):
                sitemaps.append(u)
                break
    else:
        # confirm the first
        c, _, b = curl(sitemaps[0], timeout=12)
        if not (c == 200 and sitemap_ok(b)):
            sitemaps = []
    status = "unreachable"
    if code == 200 and html:
        status = "verified" if feeds else "site_only"
    elif code in (401, 403, 429):
        status = "verified" if feeds else "robot_blocked"
    elif feeds:
        status = "verified"
    elif code:
        status = "http_error"
    item = dict(item)
    item["http_status"] = code
    item["feeds"] = feeds
    item["rss_url"] = feeds[0] if feeds else ""
    item["sitemap"] = sitemaps[0] if sitemaps else ""
    item["sitemaps"] = sitemaps[:3]
    item["collect_status"] = status
    return item


def google_news_rss(item: dict) -> str:
    host = domain(item["website_url"])
    lang = item.get("language") or "en"
    iso = item.get("country") or "US"
    q = quote(f"site:{host}")
    return f"https://news.google.com/rss/search?q={q}&hl={lang}&gl={iso}&ceid={iso}:{lang}"


def gdelt_sample(domains: list[str]) -> list[dict]:
    rows = []
    for host in domains:
        url = f"https://api.gdeltproject.org/api/v2/doc/doc?query=domain:{quote(host)}&mode=artlist&maxrecords=5&format=json&timespan=7d"
        code, _, body = curl(url, timeout=25, ua=UA_WD)
        n = 0
        sample = ""
        if code == 200 and body:
            try:
                data = json.loads(body.decode("utf-8", "replace"))
                arts = data.get("articles") or []
                n = len(arts)
                if arts:
                    sample = arts[0].get("title") or ""
            except json.JSONDecodeError:
                n = -1
        rows.append({"domain": host, "http": code, "articles": n, "sample_title": sample[:180]})
        time.sleep(6)
    return rows


def main() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    countries = json.loads(COUNTRIES.read_text())
    by_name = {c["name_en"].casefold(): c for c in countries}
    by_code = {c["code"]: c for c in countries}

    wiki_rows = parse_wiki()
    print(f"wikipedia rows {len(wiki_rows)}")
    titles = [r["wikipedia"] for r in wiki_rows if r.get("wikipedia")]
    qmap = wiki_qids(titles)
    print(f"qids {len(set(qmap.values()))}")
    entities = wd_entities(list(qmap.values()))

    # ideology / owner labels
    extra_ids = []
    for e in entities.values():
        extra_ids += claim_values(e, "P1142")[:2]
        extra_ids += claim_values(e, "P127")[:1]
    extra = wd_entities(extra_ids)
    entities.update(extra)

    catalog = []
    excluded = []
    for r in wiki_rows:
        if r["name"] in EXCLUSIONS or (r.get("wikipedia") in EXCLUSIONS):
            excluded.append({"name": r["name"], "country_name": r["country_name"], "reason": EXCLUSIONS.get(r["name"]) or EXCLUSIONS.get(r["wikipedia"]), "source": "wikipedia_record"})
            continue
        qid = qmap.get(r["wikipedia"]) or qmap.get(r["name"])
        ent = entities.get(qid) or {}
        sites = claim_values(ent, "P856")
        website = best_website(sites)
        inception = (claim_values(ent, "P571") or [None])[0]
        founded = (inception or "")[:4] or r.get("founded")
        ideo = [label_of(entities.get(i) or {}) for i in claim_values(ent, "P1142")[:2]]
        ideo = [x for x in ideo if x]
        owner = [label_of(entities.get(i) or {}) for i in claim_values(ent, "P127")[:1]]
        owner = [x for x in owner if x]
        iso = iso_of(r["country_name"] or "", by_name)
        key = r["name"].casefold()
        cname = (r["country_name"] or "").casefold()
        if key == "la nación" and "costa" in cname:
            key = "la nación (costa rica)"
        if key == "the guardian" and "nigeria" in cname:
            key = "the guardian (nigeria)"
        orientation, ligne = LINES.get(key, ("Référence nationale", ""))
        if not ligne:
            ligne = "Cité comme newspaper of record dans l'article Wikipédia « Newspaper of record » (exemples sourcés). Le positionnement partisan n'est pas déduit ici."
        if ideo:
            ligne = ligne.rstrip(".") + ". Idéologie renseignée sur Wikidata : " + ", ".join(ideo) + "."
        lang = LANG.get(r.get("lang_name") or "", "")
        catalog.append({
            "name": r["name"],
            "country": iso,
            "country_name": r["country_name"],
            "region": region_of(iso, by_code),
            "language": lang,
            "website_url": website or "",
            "type": "quotidien",
            "famille": FAMILLE_BY_NAME.get(key, "reference"),
            "declared_orientation": orientation,
            "ligne_editoriale": ligne,
            "note": "",
            "founded": founded or "",
            "longevity_score": longevity(founded),
            "wikidata": f"https://www.wikidata.org/wiki/{qid}" if qid else "",
            "wikipedia": "https://en.wikipedia.org/wiki/" + quote(r["wikipedia"].replace(" ", "_")) if r.get("wikipedia") else "",
            "owner": ", ".join(owner),
            "source": "wikipedia_record",
        })

    for s in SUPPLEMENTS:
        catalog.append({
            "name": s["name"],
            "country": s["iso"],
            "country_name": (by_code.get(s["iso"]) or {}).get("name_en") or s["iso"],
            "region": region_of(s["iso"], by_code),
            "language": s["lang"],
            "website_url": s["url"],
            "type": s["type"],
            "famille": s["famille"],
            "declared_orientation": s["orientation"],
            "ligne_editoriale": s["ligne"],
            "note": s.get("note") or "",
            "founded": "",
            "longevity_score": None,
            "wikidata": "",
            "wikipedia": "",
            "owner": "",
            "source": "complement",
        })

    # dedupe by domain, prefer wikipedia_record name if both
    by_dom = {}
    no_site = []
    for item in catalog:
        host = domain(item["website_url"])
        if not host:
            no_site.append(item)
            continue
        prev = by_dom.get(host)
        if prev is None or (prev["source"] != "wikipedia_record" and item["source"] == "wikipedia_record"):
            by_dom[host] = item
        elif prev and item["source"] == "complement" and prev["source"] == "wikipedia_record":
            # keep wiki row but fill orientation from complement if wiki line is generic
            if prev["declared_orientation"] == "Référence nationale" and item["declared_orientation"] != "Référence nationale":
                prev["declared_orientation"] = item["declared_orientation"]
                prev["ligne_editoriale"] = item["ligne_editoriale"]
                prev["famille"] = item["famille"]
                prev["type"] = item["type"]
    items = list(by_dom.values())
    print(f"catalog {len(items)} no_site {len(no_site)} excluded {len(excluded)}")
    unmapped = [i["name"] for i in items if not i["country"]]
    print("unmapped", unmapped)

    # probe
    done = []
    with ThreadPoolExecutor(max_workers=12) as pool:
        futs = {pool.submit(discover, it): it["name"] for it in items if it["website_url"]}
        for n, fut in enumerate(as_completed(futs), 1):
            try:
                done.append(fut.result())
            except Exception as e:  # noqa: BLE001
                print("probe fail", futs[fut], e)
            if n % 40 == 0:
                print(f"probed {n}/{len(futs)}")
    print("probe statuses", Counter(d["collect_status"] for d in done))

    verified = []
    held = []
    for d in done:
        d["gdelt_domain"] = domain(d["website_url"])
        d["google_news_rss"] = google_news_rss(d)
        d["gdelt_query"] = f"domain:{d['gdelt_domain']}"
        if d["collect_status"] in ("verified", "site_only", "robot_blocked") and d["website_url"]:
            verified.append(d)
        else:
            held.append(d)

    verified.sort(key=lambda x: (x["region"], x["country"] or "", x["name"]))
    # GDELT sample: a spread of regions
    sample_domains = []
    seen_reg = set()
    for d in verified:
        if d["collect_status"] != "verified":
            continue
        if d["region"] in seen_reg:
            continue
        seen_reg.add(d["region"])
        sample_domains.append(d["gdelt_domain"])
        if len(sample_domains) >= 6:
            break
    # ensure a few flagships
    for host in ["lemonde.fr", "nytimes.com", "theguardian.com", "asahi.com"]:
        if host not in sample_domains:
            sample_domains.append(host)
    print("gdelt sample", sample_domains)
    gdelt = gdelt_sample(sample_domains[:8])

    # google news spot check
    gn = []
    for d in verified:
        if d["rss_url"]:
            continue
        if len(gn) >= 3:
            break
    for d in verified[:3]:
        c, _, b = curl(d["google_news_rss"], timeout=15)
        gn.append({"name": d["name"], "http": c, "feed_ok": feed_ok(b)})
        time.sleep(1)

    payload = {
        "generated": "2026-10-29",
        "criteria": "Reconnaissance au moins nationale, rédaction professionnelle, indépendance non contestée de façon structurelle. Socle : Wikipédia, article Newspaper of record, exemples sourcés. Compléments : pairs nationaux, services publics à mandat d'indépendance, agences à site public, rédactions indépendantes.",
        "longevity_score": "Prior dérivé de l'année de fondation uniquement (avant 1850 → 98, puis 92, 85, 75, 62, 48, 35). Ce n'est pas une mesure d'audience.",
        "axes": "Pas de scores d'axes (−1..+1). La ligne déclarée est qualitative. Tacite estime official_classification à l'import via _complete_outlet.",
        "count": len(verified),
        "by_status": dict(Counter(d["collect_status"] for d in verified)),
        "by_region": dict(Counter(d["region"] for d in verified)),
        "by_famille": dict(Counter(d["famille"] for d in verified)),
        "countries": len({d["country"] for d in verified if d["country"]}),
        "media": verified,
        "unverifiable": [{"name": d["name"], "country": d["country"], "website_url": d["website_url"], "http_status": d["http_status"], "source": d["source"]} for d in held],
        "excluded": excluded,
        "considered_and_excluded": CONSIDERED,
        "no_website_on_wikidata": [{"name": i["name"], "country_name": i["country_name"]} for i in no_site],
        "gdelt_sample": gdelt,
        "google_news_sample": gn,
        "unmapped_country": unmapped,
    }
    (OUT / "reference_media.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1))

    fields = ["name", "country", "language", "website_url", "rss_url", "declared_orientation", "longevity_score",
              "sitemap", "gdelt_domain", "google_news_rss", "famille", "type", "ligne_editoriale", "wikidata", "founded", "owner", "source", "collect_status", "note"]
    with (OUT / "reference_media.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for d in verified:
            row = dict(d)
            row["longevity_score"] = "" if row.get("longevity_score") is None else row["longevity_score"]
            w.writerow(row)
    with (OUT / "reference_media_feeds.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["name", "country", "feed_url", "position"])
        w.writeheader()
        for d in verified:
            for i, u in enumerate(d.get("feeds") or []):
                w.writerow({"name": d["name"], "country": d["country"], "feed_url": u, "position": i})
    print("wrote", len(verified), "held", len(held))


if __name__ == "__main__":
    main()
