#!/usr/bin/env python3
"""Ajoute la presse nationale hors Occident et les titres auparavant écartés."""

from __future__ import annotations

import csv
import json
import re
import subprocess
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse

ROOT = Path("/Users/mp/press analysis")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
FEED_RE = re.compile(r'<link\b[^>]*type=["\']application/(?:rss|atom)\+xml["\'][^>]*>', re.I)
HREF_RE = re.compile(r'href=["\']([^"\']+)["\']', re.I)
PATHS = ["/rss", "/feed", "/feed/", "/rss.xml", "/feed.xml", "/atom.xml", "/index.rss"]
SITEMAPS = ["/sitemap.xml", "/sitemap_index.xml", "/news-sitemap.xml", "/sitemap-news.xml"]


def A(name, iso, lang, url, typ, famille, orientation, ligne, founded="", force=False):
    return dict(name=name, iso=iso, lang=lang, url=url, typ=typ, famille=famille,
                orientation=orientation, ligne=ligne, founded=founded, force=force)


# force=True : entrer même si le site ne répond pas (organe demandé explicitement).
ADD = [
    # --- auparavant hors de la barre ---
    A("Al Jazeera English", "QA", "en", "https://www.aljazeera.com", "television", "international", "État du Qatar, régional", "Chaîne qatarie d'information internationale. Financement de l'État, ligne très suivie hors du Golfe.", "1996", True),
    A("Al Jazeera Arabic", "QA", "ar", "https://www.aljazeera.net", "television", "international", "État du Qatar, régional", "Rédaction arabe d'Al Jazeera, audience majeure dans le monde arabe.", "1996", True),
    A("RT", "RU", "en", "https://www.rt.com", "television", "international", "Organe d'État", "Chaîne internationale de l'État russe.", "2005", True),
    A("Sputnik", "RU", "en", "https://sputnikglobe.com", "agence", "international", "Organe d'État", "Agence internationale de l'État russe.", "2014", True),
    A("TASS", "RU", "en", "https://tass.com", "agence", "agence", "Organe d'État", "Agence de presse de l'État russe.", "1904", True),
    A("RIA Novosti", "RU", "ru", "https://ria.ru", "agence", "agence", "Organe d'État", "Agence nationale russe, groupe Rossiya Segodnya.", "1941", True),
    A("Xinhua", "CN", "en", "https://english.news.cn", "agence", "agence", "Organe d'État", "Agence de presse de l'État chinois, édition anglaise.", "1931", True),
    A("People's Daily", "CN", "en", "https://en.people.cn", "quotidien", "reference", "Organe du Parti", "Organe du Comité central du Parti communiste chinois, édition anglaise.", "1948", True),
    A("Global Times", "CN", "en", "https://www.globaltimes.cn", "quotidien", "reference", "Organe du Parti", "Quotidien du groupe People's Daily, ligne nationaliste à destination de l'étranger.", "1993", True),
    A("CGTN", "CN", "en", "https://www.cgtn.com", "television", "international", "Organe d'État", "Chaîne internationale de la télévision centrale chinoise.", "2016", True),
    A("China Daily", "CN", "en", "https://www.chinadaily.com.cn", "quotidien", "reference", "Organe d'État", "Quotidien anglophone de l'État chinois.", "1981", True),
    A("South China Morning Post", "HK", "en", "https://www.scmp.com", "quotidien", "reference", "Centre, libéral sous contrainte", "Quotidien historique de Hong Kong, détenu par Alibaba. Marge d'indépendance réduite depuis 2020.", "1903", True),
    A("The Straits Times", "SG", "en", "https://www.straitstimes.com", "quotidien", "reference", "Aligné sur le gouvernement", "Quotidien national, groupe SPH, ligne proche du gouvernement.", "1845", True),
    A("Channel NewsAsia", "SG", "en", "https://www.channelnewsasia.com", "television", "reference", "Aligné sur le gouvernement", "Chaîne d'information de Mediacorp, groupe public singapourien.", "1999", True),
    A("New Straits Times", "MY", "en", "https://www.nst.com.my", "quotidien", "reference", "Droite, proche de l'UMNO", "Quotidien anglophone historiquement lié à l'UMNO.", "1965", True),
    A("Granma", "CU", "es", "https://www.granma.cu", "quotidien", "reference", "Organe du Parti", "Organe du Parti communiste de Cuba.", "1965", True),
    A("Rodong Sinmun", "KP", "ko", "http://www.rodong.rep.kp/en/", "quotidien", "reference", "Organe du Parti", "Organe du Parti du travail de Corée.", "1945", True),
    A("KCNA", "KP", "en", "http://www.kcna.kp/en", "agence", "agence", "Organe d'État", "Agence centrale de presse coréenne.", "1946", True),
    A("Press TV", "IR", "en", "https://www.presstv.ir", "television", "international", "Organe d'État", "Chaîne internationale de la télévision d'État iranienne.", "2007", True),
    A("IRNA", "IR", "en", "https://en.irna.ir", "agence", "agence", "Organe d'État", "Agence de presse de la République islamique.", "1934", True),
    A("Ettela'at", "IR", "fa", "https://www.ettelaat.com", "quotidien", "reference", "Organe d'État", "Plus ancien quotidien iranien encore publié, sous contrôle de l'État.", "1926", True),
    A("Al-Ahram", "EG", "en", "https://english.ahram.org.eg", "quotidien", "reference", "Organe d'État", "Quotidien d'État égyptien, édition anglaise.", "1875", True),
    A("Al-Masry Al-Youm", "EG", "ar", "https://www.almasryalyoum.com", "quotidien", "reference", "Centre, privé sous contrainte", "Quotidien privé. Autocensure structurelle depuis 2013.", "2004", True),
    A("Al Rai", "JO", "ar", "https://alrai.com", "quotidien", "reference", "Semi-officiel", "Quotidien jordanien semi-officiel.", "1971", True),
    A("Akhbar Al Khaleej", "BH", "ar", "https://www.akhbar-alkhaleej.com", "quotidien", "reference", "Proche du pouvoir", "Quotidien bahreïni de référence locale.", "1976", True),
    A("Gulf Daily News", "BH", "en", "https://www.gdnonline.com", "quotidien", "reference", "Proche du pouvoir", "Quotidien anglophone bahreïni.", "1978", True),
    A("L'Union", "GA", "fr", "https://www.union.sonapresse.com", "quotidien", "reference", "Proche du pouvoir", "Quotidien dominant au Gabon.", "1973", True),
    A("L'Osservatore Romano", "VA", "it", "https://www.osservatoreromano.va", "quotidien", "reference", "Organe du Saint-Siège", "Quotidien du Vatican.", "1861", True),
    A("The London Gazette", "GB", "en", "https://www.thegazette.co.uk", "quotidien", "reference", "Journal officiel", "Journal officiel britannique : avis légaux, pas une rédaction d'information.", "1665", True),
    # Golfe et Levant
    A("Al Arabiya", "SA", "en", "https://english.alarabiya.net", "television", "international", "État saoudien, régional", "Chaîne saoudienne d'information, groupe MBC. Édition anglaise.", "2003"),
    A("Al Arabiya Arabic", "SA", "ar", "https://www.alarabiya.net", "television", "international", "État saoudien, régional", "Rédaction arabe d'Al Arabiya.", "2003"),
    A("Asharq Al-Awsat", "GB", "ar", "https://aawsat.com", "quotidien", "international", "Proche de Riyad", "Quotidien panarabe publié à Londres, proche de l'Arabie saoudite.", "1978"),
    A("Arab News", "SA", "en", "https://www.arabnews.com", "quotidien", "reference", "Proche du pouvoir", "Quotidien anglophone saoudien, groupe Saudi Research and Media.", "1975"),
    A("Saudi Gazette", "SA", "en", "https://www.saudigazette.com.sa", "quotidien", "reference", "Proche du pouvoir", "Second quotidien anglophone saoudien.", "1976"),
    A("The National", "AE", "en", "https://www.thenationalnews.com", "quotidien", "reference", "Proche du pouvoir", "Quotidien anglophone d'Abu Dhabi.", "2008"),
    A("Gulf News", "AE", "en", "https://gulfnews.com", "quotidien", "reference", "Proche du pouvoir", "Quotidien anglophone de Dubaï.", "1978"),
    A("Khaleej Times", "AE", "en", "https://www.khaleejtimes.com", "quotidien", "reference", "Proche du pouvoir", "Quotidien anglophone de Dubaï.", "1978"),
    A("The Peninsula", "QA", "en", "https://thepeninsulaqatar.com", "quotidien", "reference", "Proche du pouvoir", "Quotidien anglophone qatari.", "1996"),
    A("Gulf Times", "QA", "en", "https://www.gulf-times.com", "quotidien", "reference", "Proche du pouvoir", "Quotidien anglophone qatari.", "1978"),
    A("Kuwait Times", "KW", "en", "https://kuwaittimes.com", "quotidien", "reference", "Proche du pouvoir", "Quotidien anglophone koweïtien.", "1961"),
    A("Times of Oman", "OM", "en", "https://timesofoman.com", "quotidien", "reference", "Proche du pouvoir", "Quotidien anglophone omanais.", "1975"),
    A("Jordan Times", "JO", "en", "https://jordantimes.com", "quotidien", "reference", "Semi-officiel", "Quotidien anglophone jordanien.", "1975"),
    A("Al-Akhbar", "LB", "ar", "https://al-akhbar.com", "quotidien", "reference", "Proche du Hezbollah", "Quotidien libanais, ligne de gauche proche du Hezbollah.", "2006"),
    A("Tehran Times", "IR", "en", "https://www.tehrantimes.com", "quotidien", "reference", "Organe d'État", "Quotidien anglophone iranien.", "1979"),
    A("Iran International", "GB", "fa", "https://www.iranintl.com", "television", "international", "Opposition en exil", "Chaîne persanophone basée à Londres, ligne d'opposition à la République islamique.", "2017"),
    A("Rudaw", "IQ", "en", "https://www.rudaw.net", "television", "reference", "Kurde, proche du PDK", "Chaîne et site kurdes d'Erbil.", "2006"),
    A("Al-Sumaria", "IQ", "ar", "https://www.alsumaria.tv", "television", "reference", "Centre, généraliste", "Chaîne irakienne privée d'information.", "2004"),
    A("SANA", "SY", "en", "https://sana.sy/en", "agence", "agence", "Organe d'État", "Agence de presse de l'État syrien.", "1965", True),
    A("WAFA", "PS", "en", "https://english.wafa.ps", "agence", "agence", "Organe de l'Autorité", "Agence de presse de l'Autorité palestinienne.", "1972"),
    A("Ma'an News", "PS", "en", "https://www.maannews.net", "agence", "reference", "Indépendant", "Agence palestinienne indépendante.", "2005"),
    # Maghreb, Égypte, Afrique
    A("El Watan", "DZ", "fr", "https://elwatan.dz", "quotidien", "reference", "Centre, indépendant sous contrainte", "Quotidien francophone algérien, une des dernières rédactions critiques.", "1990"),
    A("TSA", "DZ", "fr", "https://www.tsa-algerie.com", "pure_player", "reference", "Centre", "Pure player algérien à forte audience.", "2007"),
    A("APS", "DZ", "fr", "https://www.aps.dz", "agence", "agence", "Organe d'État", "Agence de presse algérienne.", "1961"),
    A("Hespress", "MA", "ar", "https://www.hespress.com", "pure_player", "reference", "Centre, populaire", "Premier site d'information marocain.", "2007"),
    A("Le360", "MA", "fr", "https://fr.le360.ma", "pure_player", "reference", "Proche du pouvoir", "Site national francophone à forte audience.", "2014"),
    A("La Presse de Tunisie", "TN", "fr", "https://lapresse.tn", "quotidien", "reference", "Organe d'État", "Quotidien francophone de l'État tunisien.", "1936"),
    A("Business News", "TN", "fr", "https://www.businessnews.com.tn", "pure_player", "economique", "Économique", "Site économique tunisien.", "2008"),
    A("Mosaique FM", "TN", "fr", "https://www.mosaiquefm.net", "radio", "reference", "Centre, populaire", "Radio privée la plus écoutée, site d'information national.", "2003"),
    A("Youm7", "EG", "ar", "https://www.youm7.com", "pure_player", "reference", "Proche du pouvoir", "Plus gros site d'information égyptien.", "2008"),
    A("Le Soleil", "SN", "fr", "https://lesoleil.sn", "quotidien", "reference", "Organe d'État", "Quotidien de l'État sénégalais.", "1970"),
    A("Dakaractu", "SN", "fr", "https://www.dakaractu.com", "pure_player", "reference", "Centre, populaire", "Site d'information sénégalais à forte audience.", "2010"),
    A("Fraternité Matin", "CI", "fr", "https://www.fratmat.info", "quotidien", "reference", "Organe d'État", "Quotidien de l'État ivoirien.", "1964"),
    A("Abidjan.net", "CI", "fr", "https://news.abidjan.net", "pure_player", "reference", "Centre, populaire", "Principal portail d'information ivoirien.", "1998"),
    A("Journal du Cameroun", "CM", "fr", "https://www.journalducameroun.com", "pure_player", "reference", "Centre", "Site national camerounais.", "2008"),
    A("Cameroon Tribune", "CM", "fr", "https://www.cameroon-tribune.cm", "quotidien", "reference", "Organe d'État", "Quotidien de l'État camerounais.", "1974"),
    A("Sidwaya", "BF", "fr", "https://www.sidwaya.info", "quotidien", "reference", "Organe d'État", "Quotidien de l'État burkinabè.", "1984"),
    A("Lefaso.net", "BF", "fr", "https://lefaso.net", "pure_player", "reference", "Centre, indépendant", "Premier site d'information burkinabè.", "2003"),
    A("Maliweb", "ML", "fr", "https://www.maliweb.net", "pure_player", "reference", "Centre", "Portail d'information malien.", "2000"),
    A("Daily Graphic", "GH", "en", "https://www.graphic.com.gh", "quotidien", "reference", "Organe d'État", "Quotidien de l'État ghanéen, plus fort tirage.", "1950"),
    A("The Reporter", "ET", "en", "https://www.thereporterethiopia.com", "hebdo", "reference", "Centre, indépendant", "Hebdomadaire anglophone éthiopien.", "1995"),
    A("The New Times", "RW", "en", "https://www.newtimes.co.rw", "quotidien", "reference", "Proche du pouvoir", "Quotidien national rwandais.", "1995"),
    A("New Vision", "UG", "en", "https://www.newvision.co.ug", "quotidien", "reference", "Organe d'État", "Quotidien de l'État ougandais.", "1955"),
    A("The Guardian", "TZ", "en", "https://www.ippmedia.com", "quotidien", "reference", "Centre, généraliste", "Groupe IPP Media, un des deux pôles de la presse tanzanienne avec Nation.", "1990"),
    A("Iwacu", "BI", "fr", "https://www.iwacu-burundi.org", "hebdo", "reference", "Indépendant", "Principal média indépendant burundais.", "2008"),
    A("Actualite.cd", "CD", "fr", "https://actualite.cd", "pure_player", "reference", "Centre", "Site d'information national congolais.", "2016"),
    A("7sur7.cd", "CD", "fr", "https://www.7sur7.cd", "pure_player", "reference", "Centre, populaire", "Site d'information à forte audience en RDC.", "2005"),
    A("The Herald", "ZW", "en", "https://www.herald.co.zw", "quotidien", "reference", "Organe d'État", "Quotidien de l'État zimbabwéen.", "1891"),
    A("News Diggers", "ZM", "en", "https://diggers.news", "pure_player", "investigation", "Indépendant", "Pure player d'enquête zambien.", "2017"),
    A("Jornal de Angola", "AO", "pt", "https://www.jornaldeangola.ao", "quotidien", "reference", "Organe d'État", "Quotidien de l'État angolais.", "1923"),
    A("Novo Jornal", "AO", "pt", "https://www.novojornal.co.ao", "hebdo", "reference", "Centre, indépendant", "Hebdomadaire angolais privé.", "2008"),
    A("Carta de Moçambique", "MZ", "pt", "https://www.cartamz.com", "hebdo", "reference", "Indépendant", "Hebdomadaire mozambicain indépendant.", "2016"),
    A("L'Express de Madagascar", "MG", "fr", "https://lexpress.mg", "quotidien", "reference", "Centre", "Quotidien malgache. Homonyme des Express français et mauricien.", "1973"),
    A("Midi Madagasikara", "MG", "fr", "https://www.midi-madagasikara.mg", "quotidien", "reference", "Centre", "Quotidien malgache.", "1983"),
    A("FrontPage Africa", "LR", "en", "https://frontpageafricaonline.com", "quotidien", "reference", "Indépendant", "Quotidien libérien d'enquête.", "2005"),
    A("Sahara Reporters", "NG", "en", "https://saharareporters.com", "pure_player", "investigation", "Opposition, investigation", "Pure player d'enquête nigérian, basé aux États-Unis.", "2006"),
    A("Daily Trust", "NG", "en", "https://dailytrust.com", "quotidien", "reference", "Centre, nord", "Quotidien du nord du Nigeria, audience nationale.", "2001"),
    A("Sudan Tribune", "SD", "en", "https://sudantribune.com", "pure_player", "reference", "Indépendant", "Site de référence sur le Soudan, rédaction en exil.", "2003"),
    A("Dabanga", "SD", "en", "https://www.dabangasudan.org", "radio", "reference", "Indépendant", "Radio et site soudanais indépendants, basés aux Pays-Bas.", "2008"),
    # Asie
    A("The Star", "MY", "en", "https://www.thestar.com.my", "quotidien", "reference", "Centre, généraliste", "Quotidien anglophone malaisien le plus lu.", "1971"),
    A("Bernama", "MY", "en", "https://www.bernama.com", "agence", "agence", "Organe d'État", "Agence de presse malaisienne.", "1967"),
    A("VnExpress", "VN", "vi", "https://vnexpress.net", "pure_player", "reference", "Organe d'État, populaire", "Premier site d'information vietnamien, groupe FPT sous régulation d'État.", "2001"),
    A("Tuổi Trẻ", "VN", "vi", "https://tuoitre.vn", "quotidien", "reference", "Organe de l'Union de la jeunesse", "Quotidien d'Hô Chi Minh-Ville, très lu.", "1975"),
    A("Nhân Dân", "VN", "vi", "https://nhandan.vn", "quotidien", "reference", "Organe du Parti", "Organe du Parti communiste vietnamien.", "1951"),
    A("Vietnam News", "VN", "en", "https://vietnamnews.vn", "quotidien", "reference", "Organe d'État", "Quotidien anglophone de l'agence Vietnam News.", "1991"),
    A("Detik", "ID", "id", "https://www.detik.com", "pure_player", "reference", "Centre, populaire", "Premier site d'information indonésien.", "1998"),
    A("Antara", "ID", "en", "https://en.antaranews.com", "agence", "agence", "Organe d'État", "Agence de presse indonésienne.", "1937"),
    A("Thai Rath", "TH", "th", "https://www.thairath.co.th", "quotidien", "reference", "Centre, populaire", "Quotidien le plus lu de Thaïlande.", "1950"),
    A("The Nation", "TH", "en", "https://www.nationthailand.com", "quotidien", "reference", "Centre, libéral", "Quotidien anglophone thaïlandais.", "1971"),
    A("Khmer Times", "KH", "en", "https://www.khmertimeskh.com", "quotidien", "reference", "Proche du pouvoir", "Quotidien anglophone cambodgien.", "2014"),
    A("Vientiane Times", "LA", "en", "https://www.vientianetimes.org.la", "quotidien", "reference", "Organe d'État", "Quotidien anglophone laotien.", "1994"),
    A("Global New Light of Myanmar", "MM", "en", "https://www.gnlm.com.mm", "quotidien", "reference", "Organe d'État", "Quotidien de la junte birmane.", "1914", True),
    A("Dhaka Tribune", "BD", "en", "https://www.dhakatribune.com", "quotidien", "reference", "Centre, libéral", "Quotidien anglophone bangladais.", "2013"),
    A("The Business Standard", "BD", "en", "https://www.tbsnews.net", "quotidien", "economique", "Économique", "Quotidien économique bangladais.", "2019"),
    A("Daily Mirror", "LK", "en", "https://www.dailymirror.lk", "quotidien", "reference", "Centre", "Quotidien anglophone sri-lankais. Homonyme du Mirror britannique.", "1999"),
    A("Ekantipur", "NP", "ne", "https://ekantipur.com", "quotidien", "reference", "Centre", "Site du groupe Kantipur, premier quotidien népalais.", "1993"),
    A("Tengri News", "KZ", "ru", "https://tengrinews.kz", "pure_player", "reference", "Centre, populaire", "Premier site d'information kazakh.", "2010"),
    A("Informburo", "KZ", "ru", "https://informburo.kz", "pure_player", "reference", "Centre", "Site d'information kazakh.", "2014"),
    A("The Astana Times", "KZ", "en", "https://astanatimes.com", "hebdo", "reference", "Proche du pouvoir", "Hebdomadaire anglophone officiel d'Astana.", "2010"),
    A("Gazeta.uz", "UZ", "ru", "https://www.gazeta.uz", "pure_player", "reference", "Centre", "Principal site d'information ouzbek.", "2005"),
    A("Kun.uz", "UZ", "uz", "https://kun.uz", "pure_player", "reference", "Centre, populaire", "Site d'information ouzbek à forte audience.", "2012"),
    A("24.kg", "KG", "ru", "https://24.kg", "pure_player", "reference", "Centre", "Agence et site kirghizes.", "2006"),
    A("Asia-Plus", "TJ", "ru", "https://asiaplustj.info", "pure_player", "reference", "Indépendant", "Principal média indépendant tadjik.", "1996"),
    A("UB Post", "MN", "en", "https://theubpost.mn", "hebdo", "reference", "Centre", "Hebdomadaire anglophone mongol.", "1996"),
    A("Montsame", "MN", "en", "https://montsame.mn/en", "agence", "agence", "Organe d'État", "Agence de presse mongole.", "1921"),
    A("TOLO News", "AF", "en", "https://tolonews.com", "television", "reference", "Indépendant sous contrainte", "Principale rédaction afghane encore identifiable, groupe Moby.", "2010"),
    A("Pajhwok", "AF", "en", "https://pajhwok.com", "agence", "agence", "Indépendant", "Agence afghane indépendante.", "2003"),
    A("GMA News", "PH", "en", "https://www.gmanetwork.com/news", "television", "reference", "Centre, généraliste", "Rédaction du réseau GMA, un des deux pôles télévisés avec ABS-CBN.", "1950"),
    # Amérique latine mince + téléSud
    A("Diario Libre", "DO", "es", "https://www.diariolibre.com", "quotidien", "reference", "Centre", "Quotidien national dominicain.", "2001"),
    A("CRHoy", "CR", "es", "https://www.crhoy.com", "pure_player", "reference", "Centre", "Principal pure player costaricain.", "2012"),
    A("La Prensa", "HN", "es", "https://www.laprensa.hn", "quotidien", "reference", "Centre-droit", "Quotidien de San Pedro Sula, un des deux titres nationaux.", "1964"),
    A("El Heraldo", "HN", "es", "https://www.elheraldo.hn", "quotidien", "reference", "Centre-droit", "Quotidien de Tegucigalpa.", "1979"),
    A("La Prensa Gráfica", "SV", "es", "https://www.laprensagrafica.com", "quotidien", "reference", "Centre-droit", "Quotidien national salvadorien.", "1915"),
    A("El Diario de Hoy", "SV", "es", "https://www.elsalvador.com", "quotidien", "reference", "Centre-droit", "Quotidien national salvadorien.", "1936"),
    A("Los Tiempos", "BO", "es", "https://www.lostiempos.com", "quotidien", "reference", "Centre", "Quotidien de Cochabamba, audience nationale.", "1943"),
    A("Búsqueda", "UY", "es", "https://www.busqueda.com.uy", "hebdo", "reference", "Centre, libéral", "Hebdomadaire de politique et d'économie.", "1972"),
    A("Cubadebate", "CU", "es", "https://www.cubadebate.cu", "pure_player", "reference", "Organe d'État", "Site officiel cubain, ligne du pouvoir.", "2003", True),
    A("teleSUR", "VE", "es", "https://www.telesurtv.net", "television", "international", "Organe d'État, régional", "Chaîne régionale basée à Caracas, financée par plusieurs États latino-américains.", "2005", True),
    A("Últimas Noticias", "VE", "es", "https://ultimasnoticias.com.ve", "quotidien", "reference", "Proche du pouvoir", "Quotidien vénézuélien à fort tirage, passé sous contrôle gouvernemental.", "1941"),
    # Balkans et Baltique encore minces
    A("Večernji list", "HR", "hr", "https://www.vecernji.hr", "quotidien", "reference", "Centre-droit", "Quotidien national croate.", "1959"),
    A("Index.hr", "HR", "hr", "https://www.index.hr", "pure_player", "reference", "Centre, populaire", "Principal pure player croate.", "2002"),
    A("Dnevnik", "SI", "sl", "https://www.dnevnik.si", "quotidien", "reference", "Centre-gauche", "Quotidien slovène. Homonyme du Dnevnik bulgare.", "1951"),
    A("RTV Slovenija", "SI", "sl", "https://www.rtvslo.si", "service_public", "service_public", "Centre, service public", "Service public slovène.", "1928"),
    A("Politika", "RS", "sr", "https://www.politika.rs", "quotidien", "reference", "Centre, historique", "Plus ancien quotidien des Balkans, ligne de centre.", "1904"),
    A("Blic", "RS", "sr", "https://www.blic.rs", "quotidien", "reference", "Centre, populaire", "Quotidien populaire serbe.", "1996"),
    A("15min", "LT", "lt", "https://www.15min.lt", "pure_player", "reference", "Centre", "Principal pure player lituanien.", "2005"),
    A("Lietuvos rytas", "LT", "lt", "https://www.lrytas.lt", "quotidien", "reference", "Centre", "Quotidien national lituanien.", "1990"),
    A("Delfi", "LV", "lv", "https://www.delfi.lv", "pure_player", "reference", "Centre, populaire", "Principal portail letton.", "1999"),
    A("Delfi", "EE", "et", "https://www.delfi.ee", "pure_player", "reference", "Centre, populaire", "Principal portail estonien. Même groupe que Delfi Lettonie.", "1999"),
    A("24 Chasa", "BG", "bg", "https://www.24chasa.bg", "quotidien", "reference", "Centre, populaire", "Quotidien populaire bulgare.", "1991"),
    A("Mediapool", "BG", "bg", "https://www.mediapool.bg", "pure_player", "reference", "Centre, indépendant", "Pure player bulgare indépendant.", "2001"),
    A("Klix", "BA", "bs", "https://www.klix.ba", "pure_player", "reference", "Centre, populaire", "Principal site d'information de Bosnie-Herzégovine.", "2000"),
    A("Top Channel", "AL", "sq", "https://top-channel.tv", "television", "reference", "Centre, populaire", "Première chaîne privée albanaise.", "2001"),
    A("Panorama", "AL", "sq", "https://www.panorama.com.al", "quotidien", "reference", "Centre", "Quotidien albanais. Homonyme du magazine italien.", "1995"),
    A("Sloboden Pečat", "MK", "mk", "https://www.slobodenpecat.mk", "quotidien", "reference", "Centre", "Quotidien nord-macédonien.", "2012"),
    A("Pravda", "SK", "sk", "https://www.pravda.sk", "quotidien", "reference", "Centre-gauche", "Quotidien slovaque, ligne de centre-gauche. Homonyme de la Pravda russe.", "1920"),
    A("LB.ua", "UA", "uk", "https://lb.ua", "pure_player", "reference", "Centre", "Site politique ukrainien, groupe du magazine Lévyi Bereh.", "2009"),
    A("NV", "UA", "uk", "https://nv.ua", "hebdo", "reference", "Centre, libéral", "News magazine ukrainien, ancienne Novoe Vremia.", "2014"),
]


def curl(url, timeout=12):
    try:
        p = subprocess.run(
            ["curl", "-sS", "-L", "--http1.1", "--compressed", "--max-time", str(timeout), "-A", UA, "-w", "\n%{http_code}", "-o", "-", url],
            capture_output=True, timeout=timeout + 5,
        )
    except subprocess.TimeoutExpired:
        return 0, b""
    raw = p.stdout or b""
    if b"\n" not in raw:
        return 0, raw
    body, _, code_b = raw.rpartition(b"\n")
    try:
        code = int((code_b or b"0").strip() or b"0")
    except ValueError:
        code = 0
    return code, body


def feed_ok(body: bytes) -> bool:
    head = body[:500].lstrip().lower()
    if head.startswith(b"<!doctype") or head.startswith(b"<html"):
        return False
    if not (head.startswith(b"<?xml") or head.startswith(b"<rss") or head.startswith(b"<feed") or head.startswith(b"<rdf")):
        return False
    low = body[:12000].lower()
    return b"<item" in low or b"<entry" in low


def sitemap_ok(body: bytes) -> bool:
    low = body[:8000].lower()
    return b"<urlset" in low or b"<sitemapindex" in low


def discover(item):
    site = item["url"]
    code, body = curl(site, 14)
    html = body.decode("utf-8", "replace") if body else ""
    htmlish = "<html" in html[:2500].lower() or html[:200].lstrip().lower().startswith("<!doctype")
    cands = []
    if html:
        for m in FEED_RE.finditer(html[:350000]):
            h = HREF_RE.search(m.group(0))
            if h:
                cands.append(urljoin(site, h.group(1)))
    base = site.rstrip("/")
    cands += [base + p for p in PATHS]
    feeds, seen = [], set()
    for u in cands:
        u = u.split("#")[0]
        if u in seen or len(feeds) >= 2:
            continue
        seen.add(u)
        c, b = curl(u, 10)
        if c == 200 and feed_ok(b):
            feeds.append(u)
    sitemaps = []
    rc, rb = curl(urljoin(site if site.startswith("http") else "https://" + site, "/robots.txt"), 8)
    if rc == 200 and rb:
        for line in rb.decode("utf-8", "replace").splitlines():
            if line.lower().startswith("sitemap:"):
                sitemaps.append(line.split(":", 1)[1].strip())
    if sitemaps:
        c, b = curl(sitemaps[0], 10)
        if not (c == 200 and sitemap_ok(b)):
            sitemaps = []
    else:
        origin = f"{urlparse(site).scheme}://{urlparse(site).netloc}"
        for pth in SITEMAPS:
            u = origin + pth
            c, b = curl(u, 8)
            if c == 200 and sitemap_ok(b):
                sitemaps.append(u)
                break
    if feeds:
        status = "verified"
    elif code in (401, 403, 429) or (code == 200 and not htmlish):
        status = "robot_blocked" if code in (401, 403, 429) else ("site_only" if htmlish else "unreachable")
    elif code == 200 and htmlish:
        status = "site_only"
    else:
        status = "unreachable"
    out = dict(item)
    out.update(http=code, feeds=feeds, rss=feeds[0] if feeds else "", sitemap=sitemaps[0] if sitemaps else "", status=status)
    return out


def longevity(year):
    if not year or not str(year).isdigit():
        return None
    y = int(year)
    if y < 1850: return 98
    if y < 1900: return 92
    if y < 1945: return 85
    if y < 1980: return 75
    if y < 2000: return 62
    if y < 2015: return 48
    return 35


def main():
    print("probe", len(ADD), flush=True)
    done = []
    with ThreadPoolExecutor(10) as pool:
        futs = [pool.submit(discover, it) for it in ADD]
        for i, fut in enumerate(as_completed(futs), 1):
            done.append(fut.result())
            if i % 25 == 0:
                print("probed", i, flush=True)
    print(Counter(d["status"] for d in done), flush=True)

    payload = json.loads((ROOT / "data/reference_media.json").read_text())
    countries = {c["code"]: c for c in json.loads((ROOT / "backend/app/data/countries.json").read_text())}
    hosts = {urlparse(m["website_url"]).netloc.lower().removeprefix("www.") for m in payload["media"]}
    names = {(m["name"], m["country"]) for m in payload["media"]}
    added, skipped = [], []
    for d in done:
        if d["status"] == "unreachable" and not d["force"]:
            skipped.append((d["name"], d["iso"], d["http"], d["url"]))
            continue
        iso = d["iso"]
        if iso not in countries:
            skipped.append((d["name"], iso, "bad-iso", d["url"]))
            continue
        h = urlparse(d["url"]).netloc.lower().removeprefix("www.")
        if (d["name"], iso) in names or h in hosts:
            skipped.append((d["name"], iso, "dup", h))
            continue
        if d["status"] == "unreachable":
            d["status"] = "unreachable"
        rec = {
            "name": d["name"], "country": iso,
            "country_name": countries[iso]["name_en"],
            "region": countries[iso]["region"] or "—",
            "language": d["lang"], "website_url": d["url"],
            "type": d["typ"], "famille": d["famille"],
            "declared_orientation": d["orientation"], "ligne_editoriale": d["ligne"],
            "note": "Ancien hors-barre, réintégré." if d["force"] else "",
            "founded": d.get("founded") or "", "longevity_score": longevity(d.get("founded")),
            "wikidata": "", "wikipedia": "", "owner": "", "source": "complement",
            "http_status": d.get("http"),
            "feeds": d.get("feeds") or ([d["rss"]] if d.get("rss") else []),
            "rss_url": d.get("rss") or "",
            "sitemap": d.get("sitemap") or "",
            "sitemaps": [d["sitemap"]] if d.get("sitemap") else [],
            "collect_status": d["status"], "importable": True,
            "gdelt_domain": h,
            "google_news_rss": f"https://news.google.com/rss/search?q={quote('site:'+h)}&hl={d['lang']}&gl={iso}&ceid={iso}:{d['lang']}",
            "gdelt_query": "domain:" + h,
        }
        payload["media"].append(rec)
        hosts.add(h)
        names.add((d["name"], iso))
        added.append(f"{d['status']:14} {iso} {d['name']}")

    payload["excluded"] = []
    payload["considered_and_excluded"] = []
    payload["criteria"] = (
        "Presse nationale mondiale, y compris les organes d'État, la presse du Golfe et les titres auparavant écartés. "
        "La ligne déclarée dit si le média est un organe de pouvoir. Sites, flux et sitemaps vérifiés le 29 octobre 2026."
    )
    payload["media"].sort(key=lambda x: (x.get("region") or "", x.get("country") or "", x["name"]))
    payload["count"] = len(payload["media"])
    payload["by_status"] = dict(Counter(m["collect_status"] for m in payload["media"]))
    payload["by_region"] = dict(Counter(m["region"] for m in payload["media"]))
    payload["by_famille"] = dict(Counter(m["famille"] for m in payload["media"]))
    payload["countries"] = len({m["country"] for m in payload["media"] if m.get("country")})
    payload["with_rss"] = sum(1 for m in payload["media"] if m.get("rss_url"))
    payload["with_sitemap"] = sum(1 for m in payload["media"] if m.get("sitemap"))
    (ROOT / "data/reference_media.json").write_text(json.dumps(payload, ensure_ascii=False, indent=1))
    fields = ["name","country","language","website_url","rss_url","declared_orientation","longevity_score","sitemap","gdelt_domain","google_news_rss","famille","type","ligne_editoriale","wikidata","founded","owner","source","collect_status","note"]
    with (ROOT / "data/reference_media.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for row0 in payload["media"]:
            row = dict(row0)
            row["longevity_score"] = "" if row.get("longevity_score") is None else row["longevity_score"]
            w.writerow(row)
    with (ROOT / "data/reference_media_feeds.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["name", "country", "feed_url", "position"])
        w.writeheader()
        for row0 in payload["media"]:
            for i, u in enumerate(row0.get("feeds") or []):
                if u:
                    w.writerow({"name": row0["name"], "country": row0["country"], "feed_url": u, "position": i})
    print("ADDED", len(added))
    for line in sorted(added):
        print(" ", line)
    print("SKIPPED", len(skipped))
    for s in skipped:
        print(" ", s)
    print("TOTAL", payload["count"], "countries", payload["countries"], "rss", payload["with_rss"], "region", payload["by_region"])


if __name__ == "__main__":
    main()
