"""
Application d'Analyse Statistiques KBO (Korea Baseball Organization)
===================================================================
Application Streamlit pour analyser les runs, les sluggers récurrents et les tendances W/L
de la ligue sud-coréenne de baseball (KBO League - 10 équipes).

--- Choix de la source de données (investigation détaillée) ---
Comme pour la NPB, il n'existe PAS d'équivalent officiel de "MLB StatsAPI" pour la KBO :
aucune API publique documentée et gratuite n'est proposée par la ligue. Plusieurs pistes ont
été testées avant de retenir la solution actuelle :

1. mykbo.net (site anglophone communautaire) : la page d'accueil est surtout un flux de
   type blog/réseaux sociaux, et les URLs "propres" (/schedule, /standings, /stats, ...) qui
   existeraient sur un site classique renvoient toutes une 404 - la seule vraie donnée
   structurée exploitable trouvée sur ce site est un lien "Google Sheets Version" (calendrier
   de la saison par stade, publié via Google Sheets/export CSV). Ce tableau donne le
   calendrier des rencontres par stade, mais AUCUN score, AUCUNE heure de match, et AUCUN
   détail joueur par joueur : insuffisant à lui seul pour les boxscores demandés.
2. koreabaseball.com (site officiel) : un simple `requests.get` sur les pages "/eng/..."
   renvoie une redirection vers une page d'erreur générique. La version coréenne du site
   (schedule non-"/eng/") se charge, elle, normalement (HTTP 200) et révèle dans son code
   source les véritables endpoints AJAX internes utilisés par le calendrier JS du site
   (fichiers ASP.NET "*.asmx", ex: /ws/Schedule.asmx/GetScheduleList). Cependant, appeler ces
   endpoints directement (même avec une session persistante, des en-têtes de navigateur
   réalistes, un Referer et les bons paramètres JSON) renvoie systématiquement une erreur
   HTTP 401 avec un message générique - signe d'une protection anti-bot (WAF) au niveau de
   ces endpoints spécifiquement, indépendante du rendu HTML classique. Cette piste reste
   donc BLOQUÉE depuis cet environnement ; c'est une limitation documentée, pas un blocage
   de conception de cette application.
3. Naver Sports (m.sports.naver.com) : Naver, principal portail web coréen, publie une
   couverture complète de la KBO alimentée par une API JSON interne non officielle
   (`api-gw.sports.naver.com`), largement utilisée par des projets KBO open-source existants
   (ex: kbo-cli, kbobar, kbo_pbp_naver_sports - trouvés via une recherche GitHub dédiée pour
   s'inspirer d'une approche qui fonctionne réellement plutôt que réinventer une solution
   fragile). Testée manuellement, cette API répond en JSON structuré, sans authentification,
   pour :
     - le calendrier + scores + lanceurs annoncés + décisions (V/D) : `/schedule/games`
     - le boxscore détaillé (runs/HR par frappeur) d'un match : `/schedule/games/{id}/record`
     - les statistiques de saison par joueur, y compris ERA/WHIP calculés pour les lanceurs :
       `/statistics/categories/kbo/seasons/{annee}/players`
   C'est donc cette API qui est utilisée ici comme source principale. Comme il s'agit d'un
   usage de type "scraping" d'un endpoint non documenté publiquement (même s'il répond en
   JSON propre plutôt qu'en HTML à parser), le même esprit de robustesse que pour npb.jp est
   appliqué : session persistante, retry/backoff, dégradation gracieuse sur toute erreur
   réseau, sans jamais faire planter l'app.

--- Noms de joueurs en alphabet latin : méthode retenue (différente de la NPB, et pourquoi) ---
Contrairement au japonais (où les kanji ont plusieurs lectures possibles, ce qui rendait
nécessaire l'appariement PAR ORDRE avec une page anglaise séparée dans l'app NPB), le coréen
s'écrit en hangul, un alphabet PHONÉTIQUE : chaque syllabe hangul se décompose de façon
déterministe en (consonne initiale, voyelle, consonne finale optionnelle) et se transcrit
donc en alphabet latin de façon non ambiguë via la romanisation révisée du coréen (RR,
norme officielle sud-coréenne). Ce n'est PAS une "transcription phonétique automatique
hasardeuse" comme pourrait l'être une conversion katakana -> anglais : c'est un algorithme
standard et déterministe, implémenté ici directement (voir `_romaniser_syllabe`), avec une
table de correspondance pour les noms de famille coréens les plus courants (ex: 김 -> "Kim"
plutôt que la forme mécanique "Gim", 이 -> "Lee" plutôt que "I", 박 -> "Park" plutôt que
"Bak"), car l'usage réel (maillots, médias) suit ces graphies "historiques" plutôt que la
romanisation strictement mécanique.
Ceci dit, cette romanisation ne fonctionne bien QUE pour les noms d'origine coréenne : pour
les joueurs étrangers (import players), le nom hangul affiché par les sources coréennes est
lui-même une transcription PHONÉTIQUE de leur nom d'origine (ex: "데이비슨" pour "Davidson"),
et romaniser cette transcription donnerait un résultat absurde ("Deibiseun"). C'est
l'équivalent exact du problème katakana rencontré côté NPB. La solution retenue est
meilleure que le simple appariement par ordre de la NPB : l'API Naver Sports utilise un
IDENTIFIANT NUMÉRIQUE DE JOUEUR ("playerId"/"playerCode") COMMUN entre le boxscore d'un
match et la page de statistiques de saison, et cette dernière page contient parfois un champ
"viewName" (nom anglais officiel, renseigné surtout pour les joueurs étrangers et certains
internationaux) directement associable par identifiant exact - PAS par ordre de frappe, donc
plus robuste que la technique NPB. Quand ce nom anglais n'existe pas pour un joueur donné
(cas de la majorité des joueurs coréens "de rôle"), on retombe sur la romanisation
algorithmique décrite plus haut, qui reste fiable pour un nom d'origine coréenne.
Limites connues (documentées ici comme le fait l'app NPB pour les siennes) :
  - un joueur étranger sans "viewName" connu de Naver Sports sera affiché avec une
    romanisation phonétique de sa transcription coréenne, qui peut différer sensiblement de
    l'orthographe anglaise réelle de son nom ;
  - les prénoms coréens composés de 2 syllabes sont concaténés sans séparateur ni tiret
    (ex: "하성" -> "Haseong") : certains médias utilisent plutôt "Ha-Seong" ou "Ha Seong" ;
  - les rares noms de famille coréens à 2 syllabes (ex: 남궁, 황보) ne sont pas gérés
    spécifiquement et seront coupés après la première syllabe.

Auteur: Généré via MAMMOUTH AI (adaptation KBO, version API interne Naver Sports)
"""

# ============================================================
# 1. IMPORTS - On importe les bibliothèques nécessaires
# ============================================================
import streamlit as st          # Framework pour créer l'interface web
import pandas as pd             # Manipulation de données (tableaux)
import altair as alt            # Graphiques avancés (ligne de moyenne annotée)
import re                       # Extraction des runs/manches lancées dans les champs texte
import time                     # Délais/backoff entre les appels réseau
import json                     # Le champ "profile" de l'API Naver Sports est lui-même une
                                 # chaîne JSON imbriquée dans la réponse JSON - il faut donc
                                 # la reparser explicitement (voir `_charger_effectifs_saison`)
import calendar                 # calendar.monthrange : calcule le dernier jour d'un mois
                                 # donné, nécessaire pour interroger l'API par plage de dates
import requests                 # Appels HTTP vers l'API interne Naver Sports
from datetime import datetime   # Gestion des dates
from zoneinfo import ZoneInfo   # Gestion des fuseaux horaires (KST <-> heure française)

# Remarque technique : contrairement à l'app NPB, `BeautifulSoup` n'est PAS utilisée ici.
# La source de données retenue pour la KBO (API interne Naver Sports, voir docstring
# ci-dessus) répond directement en JSON structuré : il n'y a donc aucune page HTML à
# parser. Ajouter une dépendance à `beautifulsoup4` dans `requirements.txt` serait donc
# inutile pour cette application (voir section correspondante du fichier requirements).

# ============================================================
# Fuseaux horaires : les matchs KBO sont annoncés et joués en heure de Séoul (KST, UTC+9,
# comme le Japon, SANS heure d'été). Un match "du soir" à 18h30 KST correspond à 11h30 ou
# 10h30 du matin en France selon l'heure d'été/hiver française. Toute la logique
# "quel est le match d'aujourd'hui ?" doit donc se baser sur la date/l'heure EN CORÉE,
# jamais sur la date/l'heure française ou celle du serveur.
# ============================================================
TZ_SEOUL = ZoneInfo("Asia/Seoul")
TZ_PARIS = ZoneInfo("Europe/Paris")

# Année KBO courante, basée sur la date du jour EN CORÉE (fuseau KST)
ANNEE_COURANTE = datetime.now(TZ_SEOUL).year

# Mois couverts par la saison régulière + les séries éliminatoires (Wild Card, Semi-Playoff,
# Playoff) + la Korean Series. Vérifié empiriquement sur l'API Naver Sports : la saison
# régulière 2026 débute le 28 mars (roundCode "kbo_r"), et la Korean Series se termine
# généralement fin octobre / début novembre (roundCode "kbo_ps_ks"). Mars est donc inclus
# bien qu'il contienne aussi des matchs de pré-saison ("kbo_e", exclus explicitement dans
# `charger_calendrier_mensuel`).
MOIS_SAISON = list(range(3, 12))

# En-tête HTTP "réaliste" : un simple User-Agent générique suffit pour l'API Naver Sports
# (testé et validé), mais on ajoute tout de même un Referer cohérent et un Accept-Language,
# par robustesse et par bonne pratique si Naver venait à renforcer ses vérifications.
HEADERS_HTTP = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7,fr;q=0.6",
    "Referer": "https://m.sports.naver.com/kbaseball/schedule/index",
    "Accept": "application/json, text/plain, */*",
}

_SESSION = requests.Session()
_SESSION.headers.update(HEADERS_HTTP)

# URL de base de l'API interne (non officielle) Naver Sports pour la KBO
BASE_NAVER = "https://api-gw.sports.naver.com"


def appeler_avec_retry(fonction, *args, tentatives: int = 3, delai_base: float = 0.5, **kwargs):
    """
    Exécute `fonction(*args, **kwargs)` avec un système de retry + backoff exponentiel.

    Objectif : éviter que l'API Naver Sports fasse "disparaître" silencieusement des
    équipes/joueurs/matchs à cause d'une erreur réseau transitoire ou d'un rejet temporaire
    (timeout, erreur 429/5xx, etc.). Sans cela, un simple `except: continue` avalerait
    l'erreur et sauterait l'équipe/le match sans aucune nouvelle tentative ni message - c'est
    une des causes classiques du bug "certaines équipes ne se mettent pas à jour".

    Le délai n'intervient qu'EN CAS D'ÉCHEC (pas avant chaque appel), donc les appels
    réussis (le cas normal) ne sont pas ralentis. Comme la plupart des fonctions qui
    utilisent cet appel sont elles-mêmes mises en cache par Streamlit, ce délai ne
    s'applique de toute façon qu'au premier chargement (cache miss), pas aux reruns.
    """
    derniere_erreur = None
    for tentative in range(1, tentatives + 1):
        try:
            return fonction(*args, **kwargs)
        except Exception as e:
            derniere_erreur = e
            if tentative < tentatives:
                time.sleep(delai_base * (2 ** (tentative - 1)))  # 0.5s, 1s, 2s, ...
    raise derniere_erreur


def _get_json(url: str, params: dict = None, timeout: float = 10.0) -> dict:
    """
    Appelle un endpoint JSON de l'API interne Naver Sports et retourne la réponse décodée.
    Équivalent, pour cette source de données, de `_get_soup` dans l'app NPB (mais on
    retourne un dict JSON déjà parsé plutôt qu'un arbre HTML, puisqu'il n'y a pas de HTML
    à analyser ici).
    """
    reponse = _SESSION.get(url, params=params, timeout=timeout)
    reponse.raise_for_status()
    return reponse.json()


# ============================================================
# 2. CONFIGURATION DE LA PAGE - Paramètres de l'application
# ============================================================
st.set_page_config(
    page_title="Analyse KBO - Runs & Sluggers",
    page_icon="⚾",
    layout="wide"
)

# ============================================================
# 3. LISTE DES ÉQUIPES KBO (10 équipes, codes utilisés par l'API Naver Sports)
# ============================================================
# Les codes (clés) sont ceux renvoyés tels quels par l'API Naver Sports dans les champs
# "homeTeamCode"/"awayTeamCode"/"teamCode" (vérifiés empiriquement, PAS supposés) : certains
# codes sont hérités des anciens noms de franchise (ex: "HT" pour KIA Tigers vient de
# l'ancien nom "Haitai Tigers" ; "SK" pour SSG Landers vient de l'ancien nom "SK Wyverns" ;
# "OB" pour Doosan Bears vient de l'ancien nom "OB Bears") - la KBO a conservé ces codes
# historiques dans ses systèmes internes malgré les changements de nom/propriétaire.
TEAMS_KBO = {
    "LG": "LG Twins",
    "KT": "KT Wiz",
    "SS": "Samsung Lions",
    "HH": "Hanwha Eagles",
    "LT": "Lotte Giants",
    "SK": "SSG Landers",
    "HT": "KIA Tigers",
    "OB": "Doosan Bears",
    "WO": "Kiwoom Heroes",
    "NC": "NC Dinos",
}

# Certains champs de l'API Naver Sports renvoient le nom d'équipe en HANGUL plutôt qu'en
# code (notamment "homeTeamName"/"awayTeamName" pour les équipes historiquement coréennes -
# Lotte, Hanwha, Doosan, Samsung, Kiwoom - alors que LG/NC/KIA/SSG/KT sont déjà affichés en
# lettres latines par Naver lui-même). Cette table de repli permet de retrouver le code à
# partir du nom, un peu comme `NOM_COURT_TO_CODE` dans l'app NPB.
NOM_EQUIPE_VERS_CODE = {
    "롯데": "LT", "한화": "HH", "두산": "OB", "삼성": "SS", "키움": "WO",
    "LG": "LG", "NC": "NC", "KIA": "HT", "기아": "HT", "SSG": "SK", "KT": "KT", "kt wiz": "KT",
}

# Traduction des noms de stades (renvoyés en hangul par l'API Naver Sports) vers leur nom
# anglais usuel. Couvre les 9 stades "domicile" utilisés par les 10 équipes (Jamsil est
# partagé par LG Twins et Doosan Bears) ; quelques stades régionaux utilisés ponctuellement
# pour des matchs "hors les murs" sont ajoutés en complément, sans prétendre à
# l'exhaustivité - dans ce cas, le nom hangul d'origine est affiché en repli.
STADES_KBO = {
    "잠실": "Jamsil Baseball Stadium",
    "고척": "Gocheok Sky Dome",
    "문학": "Incheon SSG Landers Field",
    "수원": "Suwon KT Wiz Park",
    "대전": "Hanwha Life Eagles Park",
    "대구": "Daegu Samsung Lions Park",
    "광주": "Gwangju-Kia Champions Field",
    "사직": "Sajik Baseball Stadium",
    "창원": "Changwon NC Park",
    # Stades régionaux occasionnels ("hors les murs")
    "울산": "Ulsan Munsu Baseball Stadium",
    "포항": "Pohang Baseball Stadium",
    "청주": "Cheongju Baseball Stadium",
}


def traduire_stade(nom_stade: str) -> str:
    """Traduit un nom de stade coréen vers l'anglais si connu, sinon le retourne tel quel."""
    if not nom_stade:
        return nom_stade
    return STADES_KBO.get(nom_stade, nom_stade)


# ============================================================
# 4. ROMANISATION DES NOMS DE JOUEURS (hangul -> alphabet latin)
# ============================================================
# Table de correspondance pour les noms de famille coréens les plus courants, dont
# l'orthographe latine "d'usage" (celle utilisée sur les maillots/dans les médias) diffère
# de la romanisation mécanique syllabe par syllabe (ex: 김 se romanise mécaniquement "Gim"
# mais s'écrit presque toujours "Kim" en pratique). Cette table ne couvre qu'un sous-ensemble
# des noms de famille coréens (les plus fréquents) : un nom de famille absent de cette table
# sera romanisé mécaniquement via `_romaniser_syllabe`, ce qui reste linguistiquement correct
# mais peut différer légèrement de l'usage courant pour des noms plus rares.
SURNOMS_COREENS = {
    "김": "Kim", "이": "Lee", "박": "Park", "최": "Choi", "정": "Jung", "강": "Kang",
    "조": "Cho", "윤": "Yoon", "임": "Lim", "오": "Oh", "신": "Shin", "권": "Kwon",
    "안": "Ahn", "류": "Ryu", "유": "Yoo", "전": "Jeon", "고": "Ko", "문": "Moon",
    "배": "Bae", "백": "Baek", "허": "Heo", "심": "Shim", "노": "Noh", "곽": "Kwak",
    "성": "Sung", "주": "Joo", "우": "Woo", "구": "Koo", "황": "Hwang", "한": "Han",
    "서": "Seo", "송": "Song", "장": "Jang", "양": "Yang", "손": "Son", "남": "Nam",
    "하": "Ha", "차": "Cha", "민": "Min", "진": "Jin", "지": "Ji", "홍": "Hong",
}

# Tables de romanisation révisée du coréen (RR, norme officielle) pour la décomposition
# d'une syllabe hangul en (consonne initiale "cho", voyelle "jung", consonne finale "jong").
# Un caractère hangul syllabique se calcule ainsi (bloc Unicode "Hangul Syllables",
# commençant à U+AC00) :
#   code_point - 0xAC00 = (index_cho * 21 + index_jung) * 28 + index_jong
# Ces tables permettent donc de retrouver algorithmiquement les 3 composantes phonétiques
# de N'IMPORTE QUELLE syllabe hangul, sans avoir besoin d'un dictionnaire de noms complet -
# une transformation déterministe, contrairement à une romanisation "au jugé".
_ROMANISATION_CHO = [
    "g", "kk", "n", "d", "tt", "r", "m", "b", "pp", "s",
    "ss", "", "j", "jj", "ch", "k", "t", "p", "h",
]
_ROMANISATION_JUNG = [
    "a", "ae", "ya", "yae", "eo", "e", "yeo", "ye", "o", "wa",
    "wae", "oe", "yo", "u", "wo", "we", "wi", "yu", "eu", "ui", "i",
]
_ROMANISATION_JONG = [
    "", "k", "k", "k", "n", "n", "n", "t", "l", "k",
    "m", "l", "l", "l", "l", "l", "m", "p", "p", "t",
    "t", "ng", "t", "t", "k", "t", "p", "h",
]


def _romaniser_syllabe(caractere: str) -> str:
    """
    Décompose UNE syllabe hangul en (cho, jung, jong) via son code Unicode et retourne sa
    romanisation révisée. Les caractères hors du bloc "Hangul Syllables" (espaces, tirets,
    lettres latines déjà présentes, etc.) sont retournés tels quels plutôt que de planter.
    """
    code = ord(caractere) - 0xAC00
    if not (0 <= code < 11172):  # 19 * 21 * 28 = 11172 syllabes hangul possibles
        return caractere
    index_jong = code % 28
    index_jung = (code // 28) % 21
    index_cho = code // (28 * 21)
    return _ROMANISATION_CHO[index_cho] + _ROMANISATION_JUNG[index_jung] + _ROMANISATION_JONG[index_jong]


def nom_hangul_vers_romanisation(nom_hangul: str) -> str:
    """
    Romanise un nom coréen complet (ex: "김하성") en "Nom_de_famille Prénom" (ex:
    "Kim Haseong"), en utilisant la table `SURNOMS_COREENS` pour le nom de famille
    (1ère syllabe) si elle le connaît, sinon en romanisant mécaniquement via
    `_romaniser_syllabe`. Le prénom (syllabes restantes) est toujours romanisé
    mécaniquement et concaténé sans séparateur (convention simplifiée - voir les limites
    documentées dans le docstring d'en-tête du fichier).
    Retourne la chaîne d'origine telle quelle si elle est vide ou ne commence pas par un
    caractère hangul (ex: nom déjà en latin, cas rare mais possible en repli).
    """
    if not nom_hangul:
        return nom_hangul
    nom_hangul = nom_hangul.strip()
    if not nom_hangul:
        return nom_hangul

    caractere_famille = nom_hangul[0]
    reste_prenom = nom_hangul[1:]

    nom_famille = SURNOMS_COREENS.get(caractere_famille)
    if nom_famille is None:
        nom_famille = _romaniser_syllabe(caractere_famille).capitalize()

    prenom_brut = "".join(_romaniser_syllabe(c) for c in reste_prenom)
    prenom = prenom_brut.capitalize() if prenom_brut else ""

    return f"{nom_famille} {prenom}".strip()


def _parser_manches_lancees(texte_manches) -> float:
    """
    Convertit le champ "manches lancées" renvoyé par l'API Naver Sports (ex: "160 1/3" ou
    "160 2/3" ou simplement "160") en nombre décimal de manches (ex: 160.333...).
    Retourne None si le texte est vide ou non interprétable, plutôt que de planter.
    """
    if not texte_manches:
        return None
    texte_manches = str(texte_manches).strip()
    correspondance = re.match(r"^(\d+)(?:\s+(\d)/3)?$", texte_manches)
    if not correspondance:
        try:
            return float(texte_manches)
        except ValueError:
            return None
    entier = int(correspondance.group(1))
    tiers = int(correspondance.group(2)) if correspondance.group(2) else 0
    return entier + tiers / 3.0


# ============================================================
# 5. FONCTIONS DE CHARGEMENT DES DONNÉES (avec mise en cache)
# ============================================================

@st.cache_data
def get_teams_kbo(annee: int = None):
    """
    Retourne la liste des 10 équipes KBO. Comme pour la NPB, la liste des franchises est
    stable d'une année sur l'autre (les changements de nom/propriétaire sont rares et déjà
    pris en compte dans `TEAMS_KBO`). Le paramètre `annee` est conservé pour la parité
    d'interface avec le reste du code, mais n'est pas utilisé.
    """
    return dict(TEAMS_KBO)


def extraire_abreviation_equipe(nom_equipe: str) -> str:
    """
    Extrait le code KBO depuis une chaîne 'CODE - Nom complet'.
    Exemple: 'HT - KIA Tigers' -> 'HT'
    """
    return nom_equipe.split(' - ')[0].strip()


@st.cache_data(show_spinner=False, ttl=1800)
def charger_calendrier_mensuel(annee: int, mois: int) -> pd.DataFrame:
    """
    Récupère, en UNE SEULE requête, le calendrier ET les résultats de TOUS les matchs KBO
    (10 équipes confondues) pour un mois donné, via l'API interne Naver Sports :
    GET https://api-gw.sports.naver.com/schedule/games
        ?fields=basic,schedule,baseball&fromDate=AAAA-MM-01&toDate=AAAA-MM-DD
        &upperCategoryId=kbaseball&categoryId=kbo&size=300

    --- CORRECTIF (troncature silencieuse à 10 matchs) ---
    Sans le paramètre "size", cette API renvoie systématiquement 10 matchs MAXIMUM, quelle
    que soit la largeur de la plage fromDate/toDate demandée (vérifié empiriquement : une
    requête sur un mois entier, comportant ~110 matchs, ne renvoyait que les 10 premiers
    sans aucune erreur ni indication de troncature autre que le champ "gameTotalCount", qui
    lui affichait bien le vrai total). "size=300" est largement suffisant pour couvrir un
    mois KBO complet (5 matchs/jour au maximum, soit ~155 matchs pour un mois de 31 jours).

    Cette page renvoie, pour chaque match : équipes domicile/extérieur, score, stade, date
    et heure de début (heure de Corée - KST), lanceurs partants ANNONCÉS des deux côtés,
    lanceur gagnant/perdant si le match est terminé, ainsi que l'identifiant du match
    ("gameId") utilisé plus bas pour récupérer le boxscore détaillé.

    Comme cette fonction ne dépend PAS de l'équipe sélectionnée, Streamlit ne fait cet appel
    réseau qu'UNE SEULE FOIS par (année, mois), quel que soit le nombre d'équipes consultées
    ensuite dans la session.
    """
    dernier_jour = calendar.monthrange(annee, mois)[1]
    params = {
        "fields": "basic,schedule,baseball",
        "fromDate": f"{annee}-{mois:02d}-01",
        "toDate": f"{annee}-{mois:02d}-{dernier_jour:02d}",
        "upperCategoryId": "kbaseball",
        "categoryId": "kbo",
        "size": 300,
    }
    url = f"{BASE_NAVER}/schedule/games"
    try:
        data = appeler_avec_retry(_get_json, url, params=params)
    except Exception:
        return pd.DataFrame()

    lignes = []
    for g in (data.get('result', {}) or {}).get('games', []) or []:
        if g.get('categoryId') != 'kbo':
            continue
        if g.get('cancel'):
            continue

        # On exclut les matchs de pré-saison ("kbo_e" = exhibition), joués avec des
        # compositions d'équipe différentes et qui fausseraient les statistiques. On garde
        # en revanche la saison régulière ("kbo_r") ET les séries éliminatoires + Korean
        # Series ("kbo_ps_wd/sp/po/ks"), par symétrie avec l'app NPB qui inclut la saison
        # régulière ET les Climax Series/Japan Series.
        round_code = g.get('roundCode') or ''
        if not (round_code.startswith('kbo_r') or round_code.startswith('kbo_ps')):
            continue

        code_home = g.get('homeTeamCode')
        code_away = g.get('awayTeamCode')
        # Repli sur le nom d'équipe (parfois en hangul) si le code venait à manquer
        if not code_home:
            code_home = NOM_EQUIPE_VERS_CODE.get(g.get('homeTeamName'))
        if not code_away:
            code_away = NOM_EQUIPE_VERS_CODE.get(g.get('awayTeamName'))

        lignes.append({
            "Date": g.get('gameDate'),
            "game_id": g.get('gameId'),
            "code_home": code_home,
            "code_away": code_away,
            "nom_home": g.get('homeTeamName'),
            "nom_away": g.get('awayTeamName'),
            "score_home": g.get('homeTeamScore'),
            "score_away": g.get('awayTeamScore'),
            "stade": g.get('stadium'),
            "game_datetime": g.get('gameDateTime'),
            "statusCode": g.get('statusCode'),
            "lanceur_annonce_home": (g.get('homeStarterName') or '').strip(),
            "lanceur_annonce_away": (g.get('awayStarterName') or '').strip(),
            "lanceur_gagnant": (g.get('winPitcherName') or '').strip(),
            "lanceur_perdant": (g.get('losePitcherName') or '').strip(),
        })

    return pd.DataFrame(lignes)


@st.cache_data(show_spinner=False, ttl=3600)
def _charger_effectifs_saison(annee: int) -> pd.DataFrame:
    """
    Récupère, pour chacune des 10 équipes KBO et pour les DEUX types de joueurs (frappeurs
    "HITTER" ET lanceurs "PITCHER"), les statistiques de saison ainsi que le nom anglais
    officiel connu de Naver Sports ("viewName", quand disponible), via :
    GET /statistics/categories/kbo/seasons/{annee}/players?playerType=...&teamCode=...

    Cette unique fonction (mise en cache 1h - les stats de saison évoluent au fil des
    matchs, contrairement à la liste des équipes) sert de base à la fois :
      - à la traduction anglaise des noms de joueurs dans les boxscores (jointure par
        "playerId", qui est le MÊME identifiant numérique que le "playerCode"/"pcode"
        utilisé par l'API de boxscore /schedule/games/{gameId}/record - vérifié
        empiriquement en comparant les deux sources sur les mêmes joueurs) ;
      - aux statistiques du lanceur partant adverse annoncé (ERA/WHIP/HR alloués), retrouvé
        par son nom hangul + son équipe dans ce même tableau (voir `obtenir_infos_lanceur`).

    Le champ "profile" de l'API est une chaîne JSON IMBRIQUÉE dans la réponse JSON (une
    particularité de cette API) : il faut donc la re-parser explicitement avec `json.loads`.
    Le champ "viewName" qu'elle contient est parfois formaté "Prénom Nom, Prénom complet Nom
    complet" (ex: "Yonny Chirinos, Yonny Enrique Chirinos") : on ne garde que la première
    partie, plus courte et plus proche du nom affiché sur le maillot/à l'antenne.

    En cas d'échec réseau sur une équipe/un type de joueur donné, on continue simplement
    avec les données déjà récupérées pour les autres équipes (dégradation gracieuse) plutôt
    que de faire échouer tout le chargement.
    """
    lignes = []
    for code_equipe in TEAMS_KBO:
        for type_joueur in ("HITTER", "PITCHER"):
            params = {
                "playerType": type_joueur,
                "field": "hra" if type_joueur == "HITTER" else "era",
                "direction": "DESC" if type_joueur == "HITTER" else "ASC",
                "teamCode": code_equipe,
                "pageSize": 150,
                "page": 1,
            }
            url = f"{BASE_NAVER}/statistics/categories/kbo/seasons/{annee}/players"
            try:
                data = appeler_avec_retry(_get_json, url, params=params)
            except Exception:
                continue  # on garde les autres équipes déjà chargées, pas de crash global

            for j in (data.get('result', {}) or {}).get('seasonPlayerStats', []) or []:
                nom_anglais = ""
                try:
                    profil = json.loads(j.get('profile') or '{}')
                    nom_anglais = (profil.get('viewName') or '').strip()
                    if ',' in nom_anglais:
                        nom_anglais = nom_anglais.split(',')[0].strip()
                except Exception:
                    nom_anglais = ""

                ligne = {
                    "playerId": str(j.get('playerId') or ''),
                    "nom_hangul": j.get('playerName') or '',
                    "nom_anglais": nom_anglais,
                    "code_equipe": code_equipe,
                    "type": type_joueur,
                }
                if type_joueur == "PITCHER":
                    ligne.update({
                        "era": j.get('pitcherEra'),
                        "whip": j.get('pitcherWhip'),
                        "hr_alloues": j.get('pitcherHr'),
                        "runs_alloues": j.get('pitcherR'),
                        "inning_txt": j.get('pitcherInning'),
                        "apparitions": j.get('pitcherGameCount'),
                    })
                lignes.append(ligne)

    return pd.DataFrame(lignes)


@st.cache_data(show_spinner=False, ttl=3600)
def _dict_noms_anglais(annee: int) -> dict:
    """
    Construit un dictionnaire {playerId: nom_anglais} à partir de `_charger_effectifs_saison`,
    en ne gardant que les joueurs pour lesquels Naver Sports connaît un nom anglais. Utilisé
    pour une recherche rapide (O(1)) depuis `get_stats_offensives_match`, plutôt que de
    filtrer un DataFrame à chaque joueur de chaque match (ce qui serait beaucoup plus lent
    sur une saison complète).
    """
    effectifs = _charger_effectifs_saison(annee)
    if effectifs.empty:
        return {}
    sous_ensemble = effectifs[effectifs['nom_anglais'] != '']
    return dict(zip(sous_ensemble['playerId'], sous_ensemble['nom_anglais']))


@st.cache_data(show_spinner=False, ttl=1800)
def charger_donnees_equipe(annee: int = None, equipe_abbr: str = None) -> pd.DataFrame:
    """
    Charge les données de match TERMINÉS pour une équipe donnée, sur toute la saison, en
    assemblant les calendriers mensuels (mars à novembre) via `charger_calendrier_mensuel`.
    Affiche deux colonnes distinctes : 'Équipe Domicile' et 'Équipe Extérieur' (comme la
    version MLB/NPB d'origine).
    """
    if annee is None:
        annee = ANNEE_COURANTE
    if not equipe_abbr:
        return pd.DataFrame()

    code_equipe = equipe_abbr.upper()

    frames = [charger_calendrier_mensuel(annee, mois) for mois in MOIS_SAISON]
    frames = [f for f in frames if not f.empty]
    if not frames:
        return pd.DataFrame()

    df_tout = pd.concat(frames, ignore_index=True)
    masque = (df_tout['code_home'] == code_equipe) | (df_tout['code_away'] == code_equipe)
    df_equipe = df_tout[masque].copy()

    # On ne garde que les matchs dont le score est connu des deux côtés...
    df_equipe = df_equipe.dropna(subset=['score_home', 'score_away'])
    if df_equipe.empty:
        return pd.DataFrame()

    # ...ET qui sont réellement terminés : un match du jour (heure de Corée) peut être EN
    # COURS avec un score partiel déjà présent dans l'API. On ne le considère "terminé" que
    # si son statut Naver Sports vaut "RESULT", ou s'il a eu lieu un jour STRICTEMENT
    # antérieur à aujourd'hui (KST), ou si une décision (lanceur gagnant/perdant) est déjà
    # publiée (ce qui n'arrive qu'en fin de match).
    aujourdhui_kst = datetime.now(TZ_SEOUL).strftime('%Y-%m-%d')
    est_termine = (
        (df_equipe['statusCode'] == 'RESULT')
        | (df_equipe['Date'] < aujourdhui_kst)
        | (df_equipe['lanceur_gagnant'] != '')
        | (df_equipe['lanceur_perdant'] != '')
    )
    df_equipe = df_equipe[est_termine]
    if df_equipe.empty:
        return pd.DataFrame()

    try:
        matchs = []
        for _, g in df_equipe.iterrows():
            est_dom = (g['code_home'] == code_equipe)
            nom_home_aff = TEAMS_KBO.get(g['code_home'], g['nom_home'])
            nom_away_aff = TEAMS_KBO.get(g['code_away'], g['nom_away'])

            if est_dom:
                runs, runs_adverses = int(g['score_home']), int(g['score_away'])
            else:
                runs, runs_adverses = int(g['score_away']), int(g['score_home'])

            if runs > runs_adverses:
                wl = "W"
            elif runs < runs_adverses:
                wl = "L"
            else:
                wl = "T"

            matchs.append({
                "Date": g['Date'],
                "Équipe Domicile": nom_home_aff,
                "Équipe Extérieur": nom_away_aff,
                "R": runs,
                "RA": runs_adverses,
                "W/L": wl,
                "game_id": g['game_id'],
                "Est_Domicile": est_dom,
                # Colonnes internes (non affichées) : nécessaires pour retrouver le
                # boxscore détaillé du match plus tard.
                "code_home": g['code_home'],
                "code_away": g['code_away'],
            })
        df = pd.DataFrame(matchs).sort_values('Date').reset_index(drop=True)
        return df
    except Exception as e:
        st.error(f"Erreur lors du chargement des données pour {equipe_abbr} ({annee}): {e}")
        return pd.DataFrame()


@st.cache_data(show_spinner=False)
def get_stats_offensives_match(game_id: str, est_domicile: bool, dict_noms_anglais: dict = None):
    """
    Récupère, via le boxscore Naver Sports d'un match (endpoint "/record"), les runs ET les
    home runs marqués par chaque joueur de l'équipe (domicile ou extérieur) lors de ce
    match. Retourne une liste de dicts {'name': str, 'runs': int, 'hr': int}.

    Détail technique de l'API : la réponse contient un bloc "battersBoxscore" avec deux
    listes "home" et "away" (une entrée par frappeur ayant joué, PAS de ligne "total équipe"
    mélangée dedans - contrairement à npb.jp, aucun filtrage de ligne n'est donc nécessaire
    ici). Chaque entrée contient directement "run" (runs marqués), "hr" (home runs),
    "name" (nom en hangul) et "playerCode" (identifiant numérique du joueur, le même que
    "playerId" dans les statistiques de saison - voir `_charger_effectifs_saison`).

    --- Noms de joueurs en anglais/romanisés ---
    Pour chaque joueur, on cherche d'abord son nom anglais officiel dans
    `dict_noms_anglais` (construit à partir de la fiche de saison Naver Sports, fiable
    surtout pour les joueurs étrangers). S'il n'existe pas, on romanise algorithmiquement
    son nom hangul via `nom_hangul_vers_romanisation` (fiable pour les noms d'origine
    coréenne - voir le docstring d'en-tête du fichier pour le détail de cette méthode et
    ses limites).
    """
    if not game_id:
        return []
    dict_noms_anglais = dict_noms_anglais or {}

    url = f"{BASE_NAVER}/schedule/games/{game_id}/record"
    try:
        data = appeler_avec_retry(_get_json, url)
    except Exception:
        return []

    record_data = (data.get('result', {}) or {}).get('recordData', {}) or {}
    batters_boxscore = record_data.get('battersBoxscore', {}) or {}
    liste_joueurs = batters_boxscore.get('home' if est_domicile else 'away', []) or []

    lignes_brutes = []
    for j in liste_joueurs:
        nom_hangul = j.get('name', '') or ''
        player_id = str(j.get('playerCode') or '')
        nom_anglais = dict_noms_anglais.get(player_id)
        nom_final = nom_anglais if nom_anglais else nom_hangul_vers_romanisation(nom_hangul)

        try:
            runs = int(j.get('run') or 0)
        except (ValueError, TypeError):
            runs = 0
        try:
            hr = int(j.get('hr') or 0)
        except (ValueError, TypeError):
            hr = 0

        if runs <= 0 and hr <= 0:
            continue
        lignes_brutes.append({'name': nom_final, 'runs': runs, 'hr': hr})

    # Fusion des statistiques par nom final, au cas où un même joueur apparaîtrait sur
    # plusieurs lignes (remplacement puis retour en jeu, etc.)
    stats_par_joueur = {}
    for ligne in lignes_brutes:
        cle = ligne['name']
        if cle not in stats_par_joueur:
            stats_par_joueur[cle] = {'runs': 0, 'hr': 0}
        stats_par_joueur[cle]['runs'] += ligne['runs']
        stats_par_joueur[cle]['hr'] += ligne['hr']

    return [{'name': nom, 'runs': s['runs'], 'hr': s['hr']} for nom, s in stats_par_joueur.items()]


@st.cache_data(show_spinner=False, ttl=1800)
def get_matchs_avec_scoreurs(annee: int, equipe_abbr: str):
    """
    Enrichit les données de match avec la liste des scoreurs de runs ET de home runs par
    match, et calcule le cumul de runs / home runs marqués par joueur sur toute la période
    chargée.
    Retourne (df_matchs_enrichi, df_meilleurs_scoreurs_runs, df_meilleurs_scoreurs_hr).
    """
    df = charger_donnees_equipe(annee, equipe_abbr)
    if df.empty or 'game_id' not in df.columns:
        return df, pd.DataFrame(), pd.DataFrame()

    dict_noms_anglais = _dict_noms_anglais(annee)

    df = df.copy()
    colonne_joueurs_runs = []
    colonne_joueurs_hr = []
    colonne_stats_brutes = []
    cumul_runs = {}
    cumul_hr = {}

    for _, ligne in df.iterrows():
        stats_batteurs = get_stats_offensives_match(
            ligne['game_id'], bool(ligne['Est_Domicile']), dict_noms_anglais,
        )

        # On conserve les données BRUTES (liste de dicts {name, runs, hr}) dans une colonne
        # cachée, en plus de la version texte formatée pour l'affichage. Toute agrégation
        # ultérieure (ex: résumé des 10 derniers matchs) doit additionner ces valeurs brutes
        # directement, et NE PAS reparser le texte formaté ci-dessous : reparser une chaîne
        # comme "Kim (2), Choi (1)" est fragile (suffixe de désambiguïsation qui peut varier
        # d'un match à l'autre pour un même joueur, etc.).
        colonne_stats_brutes.append(stats_batteurs)

        entrees_runs = [f"{s['name']} ({s['runs']})" for s in stats_batteurs if s['runs'] > 0]
        colonne_joueurs_runs.append(", ".join(entrees_runs) if entrees_runs else "—")

        entrees_hr = [f"{s['name']} ({s['hr']})" for s in stats_batteurs if s['hr'] > 0]
        colonne_joueurs_hr.append(", ".join(entrees_hr) if entrees_hr else "—")

        for s in stats_batteurs:
            if s['runs'] > 0:
                cumul_runs[s['name']] = cumul_runs.get(s['name'], 0) + s['runs']
            if s['hr'] > 0:
                cumul_hr[s['name']] = cumul_hr.get(s['name'], 0) + s['hr']

    df['Joueurs (Runs)'] = colonne_joueurs_runs
    df['Joueurs (HR)'] = colonne_joueurs_hr
    df['_offensive_stats'] = colonne_stats_brutes  # colonne interne (non affichée)

    df_meilleurs_runs = pd.DataFrame(
        [{'Joueur': nom, 'Runs Marqués': total} for nom, total in cumul_runs.items()]
    )
    if not df_meilleurs_runs.empty:
        df_meilleurs_runs = df_meilleurs_runs.sort_values('Runs Marqués', ascending=False).reset_index(drop=True)

    df_meilleurs_hr = pd.DataFrame(
        [{'Joueur': nom, 'Home Runs': total} for nom, total in cumul_hr.items()]
    )
    if not df_meilleurs_hr.empty:
        df_meilleurs_hr = df_meilleurs_hr.sort_values('Home Runs', ascending=False).reset_index(drop=True)

    return df, df_meilleurs_runs, df_meilleurs_hr


def parser_cellule_joueurs(cellule: str) -> dict:
    """
    Parse une cellule du type "Nom (N), Nom2 (N2), ..." et retourne un dict {nom: total}.

    Une cellule peut contenir plusieurs joueurs séparés par des virgules. Certains noms
    romanisés peuvent en théorie contenir eux-mêmes une virgule, donc on ne découpe pas
    simplement sur toutes les virgules : on découpe plutôt sur chaque entrée complète
    "... (N)" (recherche non-gourmande jusqu'à la prochaine parenthèse de valeur).
    """
    cumul = {}
    if not cellule or cellule == "—":
        return cumul

    entrees = re.findall(r'(.+?\(\d+\))(?:,\s*|$)', cellule)
    for entree in entrees:
        entree = entree.strip()
        if not entree:
            continue
        correspondance = re.match(r'^(.*)\((\d+)\)$', entree)
        if correspondance:
            nom = correspondance.group(1).strip()
            valeur = int(correspondance.group(2))
        else:
            nom = entree
            valeur = 1
        cumul[nom] = cumul.get(nom, 0) + valeur

    return cumul


def calculer_resume_10_derniers_matchs(df_derniers: pd.DataFrame):
    """
    À partir des données des 10 derniers matchs, calcule, pour les runs ET pour les home
    runs : la moyenne marquée sur ces matchs, le cumul EXACT par joueur, et le top 3 des
    joueurs les plus récurrents.

    La fonction additionne les statistiques brutes par match (colonne interne
    '_offensive_stats', une liste de dicts {name, runs, hr} par match - la même source que
    celle utilisée pour construire les colonnes affichées), sans repasser par aucun texte
    formaté, pour garantir que le total obtenu correspond toujours exactement à la somme des
    valeurs visibles dans le tableau des 10 derniers matchs. Le parsing par regex
    (`parser_cellule_joueurs`) n'est conservé qu'en repli, si jamais la colonne brute n'est
    pas disponible.

    Retourne (moyenne_runs, top3_runs, moyenne_hr, top3_hr, cumul_runs, cumul_hr) :
      - top3_* est une liste de tuples (nom, total) limitée aux 3 plus hauts totaux.
      - cumul_runs / cumul_hr sont les dictionnaires COMPLETS {nom: total} (non tronqués),
        à utiliser dès qu'on a besoin du total exact d'un joueur qui n'est pas forcément
        dans le top 3 de l'AUTRE catégorie.
    """
    if df_derniers.empty or 'R' not in df_derniers.columns:
        return None, [], None, [], {}, {}

    moyenne_runs = pd.to_numeric(df_derniers['R'], errors='coerce').mean()

    a_stats_brutes = '_offensive_stats' in df_derniers.columns
    a_colonne_hr = 'Joueurs (HR)' in df_derniers.columns

    cumul_runs = {}
    cumul_hr = {}

    if a_stats_brutes:
        for stats_match in df_derniers['_offensive_stats']:
            for s in (stats_match or []):
                if s.get('runs', 0) > 0:
                    cumul_runs[s['name']] = cumul_runs.get(s['name'], 0) + s['runs']
                if s.get('hr', 0) > 0:
                    cumul_hr[s['name']] = cumul_hr.get(s['name'], 0) + s['hr']
    else:
        # Repli (rétro-compatibilité) : si la colonne brute n'existe pas, on retombe sur
        # le parsing texte, moins fiable mais fonctionnel.
        for cellule in df_derniers.get('Joueurs (Runs)', []):
            for nom, valeur in parser_cellule_joueurs(cellule).items():
                cumul_runs[nom] = cumul_runs.get(nom, 0) + valeur
        if a_colonne_hr:
            for cellule in df_derniers['Joueurs (HR)']:
                for nom, valeur in parser_cellule_joueurs(cellule).items():
                    cumul_hr[nom] = cumul_hr.get(nom, 0) + valeur

    top3_runs = sorted(cumul_runs.items(), key=lambda x: x[1], reverse=True)[:3]

    moyenne_hr = None
    top3_hr = []
    if a_stats_brutes or a_colonne_hr:
        nb_matchs = len(df_derniers)
        moyenne_hr = (sum(cumul_hr.values()) / nb_matchs) if nb_matchs else 0.0
        top3_hr = sorted(cumul_hr.items(), key=lambda x: x[1], reverse=True)[:3]

    return moyenne_runs, top3_runs, moyenne_hr, top3_hr, cumul_runs, cumul_hr


@st.cache_data(show_spinner=False, ttl=300)
def obtenir_calendrier_du_jour_kst():
    """
    Récupère le calendrier KBO de la date du jour EN CORÉE (fuseau KST), pas la date
    française. C'est le cœur de l'adaptation du fuseau horaire : au moment où un
    utilisateur français ouvre l'application le matin, il est déjà "cet après-midi/ce soir"
    en Corée la plupart du temps, donc interroger le calendrier KBO avec la date française
    donnerait très souvent le mauvais jour de match (voire aucun match).
    """
    maintenant_kst = datetime.now(TZ_SEOUL)
    df_mois = charger_calendrier_mensuel(maintenant_kst.year, maintenant_kst.month)
    if df_mois.empty:
        return pd.DataFrame(), maintenant_kst
    date_str = maintenant_kst.strftime('%Y-%m-%d')
    return df_mois[df_mois['Date'] == date_str].copy(), maintenant_kst


def obtenir_infos_lanceur(nom_hangul: str, code_equipe: str, effectifs: pd.DataFrame):
    """
    Retrouve un lanceur (par son nom hangul ANNONCÉ + son équipe) dans le tableau des
    effectifs de saison (`_charger_effectifs_saison`), et retourne ses statistiques de la
    saison en cours (ERA, WHIP - directement fournis par l'API Naver Sports, pas besoin de
    les recalculer comme pour la NPB -, runs/HR alloués, HR/9, nombre d'apparitions).

    Contrairement à l'app NPB (qui retrouve le lanceur annoncé via une page dédiée aux
    identifiants npb.jp), l'API Naver Sports ne fournit que le NOM (hangul) du lanceur
    annoncé directement dans le calendrier, sans identifiant numérique associé : on le
    retrouve donc par correspondance EXACTE de nom hangul + équipe dans le tableau des
    effectifs de saison, une jointure fiable en pratique (deux lanceurs partants du même
    nom hangul dans le même effectif sont extrêmement improbables).

    Retourne un dict {'nom', 'era', 'whip', 'runs_alloues', 'hr_alloues', 'hr_par_9',
    'matchs_titulaire'} dès que le joueur est trouvé dans les effectifs (le nom est alors
    toujours renseigné), avec les champs statistiques à None si aucune ligne ERA exploitable
    n'existe (ex: lanceur tout juste rappelé, sans historique de saison). Retourne None si
    le nom est vide ou introuvable dans les effectifs (dégradation gracieuse : l'app
    continue avec le seul nom romanisé algorithmiquement, sans planter).
    """
    if not nom_hangul or effectifs is None or effectifs.empty:
        return None

    sous_ensemble = effectifs[
        (effectifs['type'] == 'PITCHER')
        & (effectifs['code_equipe'] == code_equipe)
        & (effectifs['nom_hangul'] == nom_hangul)
    ]
    if sous_ensemble.empty:
        return None

    ligne = sous_ensemble.iloc[0]
    nom_anglais = (ligne.get('nom_anglais') or '').strip()
    nom_affiche = nom_anglais if nom_anglais else nom_hangul_vers_romanisation(nom_hangul)

    resultat = {
        'nom': nom_affiche,
        'era': None,
        'whip': None,
        'runs_alloues': None,
        'hr_alloues': None,
        'hr_par_9': None,
        'matchs_titulaire': None,
    }

    era = ligne.get('era')
    if era is None or (isinstance(era, float) and pd.isna(era)) or not era:
        return resultat

    innings = _parser_manches_lancees(ligne.get('inning_txt'))
    hr_alloues = int(ligne.get('hr_alloues') or 0)
    whip = ligne.get('whip')

    resultat.update({
        'era': float(era),
        'whip': float(whip) if whip is not None and not (isinstance(whip, float) and pd.isna(whip)) else None,
        'runs_alloues': int(ligne.get('runs_alloues') or 0),
        'hr_alloues': hr_alloues,
        'hr_par_9': (hr_alloues / innings * 9) if innings else None,
        'matchs_titulaire': int(ligne.get('apparitions') or 0),
    })
    return resultat


@st.cache_data(show_spinner=False, ttl=300)
def obtenir_match_du_jour(code_equipe: str, annee: int):
    """
    Cherche, dans le calendrier KBO du jour (date système EN CORÉE, cf.
    `obtenir_calendrier_du_jour_kst`), un match impliquant l'équipe donnée. Retourne un dict
    avec l'adversaire, le statut domicile/extérieur, les lanceurs partants annoncés (des
    deux côtés), le stade, l'heure KST ET l'heure française équivalente, ou None si aucun
    match n'est prévu aujourd'hui (KST) pour cette équipe.
    """
    if not code_equipe:
        return None

    df_jour, maintenant_kst = obtenir_calendrier_du_jour_kst()
    if df_jour.empty:
        return None

    code_equipe = code_equipe.upper()
    ligne = None
    for _, g in df_jour.iterrows():
        if g['code_home'] == code_equipe or g['code_away'] == code_equipe:
            ligne = g
            break
    if ligne is None:
        return None

    est_domicile = (ligne['code_home'] == code_equipe)
    code_adverse = ligne['code_away'] if est_domicile else ligne['code_home']
    nom_adverse = TEAMS_KBO.get(
        code_adverse,
        ligne['nom_away'] if est_domicile else ligne['nom_home'],
    )

    # --- Conversion KST -> heure française (Europe/Paris) ---
    # "gameDateTime" est renvoyé par l'API Naver Sports comme une date/heure LOCALE (heure
    # de Corée), sans indication explicite de fuseau dans la chaîne elle-même (ex:
    # "2026-07-31T18:30:00") : on lui attache donc nous-mêmes le fuseau KST avant de
    # convertir vers l'heure française, exactement comme le fait l'app NPB pour le Japon.
    heure_kst_str = "—"
    heure_paris_str = None
    game_datetime_str = ligne.get('game_datetime')
    if game_datetime_str:
        try:
            dt_kst = datetime.fromisoformat(game_datetime_str).replace(tzinfo=TZ_SEOUL)
            heure_kst_str = dt_kst.strftime('%H:%M')
            dt_paris = dt_kst.astimezone(TZ_PARIS)
            # On affiche systématiquement la date française complète (et pas seulement
            # l'heure) : "31/07 à 11:30" lève toute ambiguïté sur le jour civil français
            # correspondant, même si l'heure locale coréenne tombe tard le soir.
            heure_paris_str = dt_paris.strftime('%d/%m à %H:%M')
        except Exception:
            heure_paris_str = None

    effectifs = _charger_effectifs_saison(annee)

    lanceur_annonce_nous_hangul = ligne['lanceur_annonce_home'] if est_domicile else ligne['lanceur_annonce_away']
    lanceur_annonce_adv_hangul = ligne['lanceur_annonce_away'] if est_domicile else ligne['lanceur_annonce_home']

    infos_notre_lanceur = (
        obtenir_infos_lanceur(lanceur_annonce_nous_hangul, code_equipe, effectifs)
        if lanceur_annonce_nous_hangul else None
    )
    infos_lanceur_adverse = (
        obtenir_infos_lanceur(lanceur_annonce_adv_hangul, code_adverse, effectifs)
        if lanceur_annonce_adv_hangul else None
    )

    # Si le lanceur annoncé n'a pas été retrouvé dans les effectifs de saison (dégradation
    # gracieuse), on affiche au moins son nom romanisé algorithmiquement plutôt que rien.
    lanceur_notre_equipe = (
        infos_notre_lanceur['nom'] if infos_notre_lanceur
        else (nom_hangul_vers_romanisation(lanceur_annonce_nous_hangul) if lanceur_annonce_nous_hangul else None)
    )
    lanceur_adverse = (
        infos_lanceur_adverse['nom'] if infos_lanceur_adverse
        else (nom_hangul_vers_romanisation(lanceur_annonce_adv_hangul) if lanceur_annonce_adv_hangul else None)
    )

    statut_code = ligne.get('statusCode')
    if statut_code == 'RESULT':
        statut = "Terminé"
    elif statut_code in ('STARTED', 'LIVE'):
        statut = "En cours"
    elif statut_code == 'CANCELLED':
        statut = "Annulé"
    elif statut_code == 'SUSPENDED':
        statut = "Suspendu"
    else:
        statut = "Programmé"

    return {
        'adversaire': nom_adverse,
        'est_domicile': est_domicile,
        'lanceur_notre_equipe': lanceur_notre_equipe,
        'lanceur_adverse': lanceur_adverse,
        'stats_lanceur_adverse': infos_lanceur_adverse,
        'heure_kst': heure_kst_str,
        'heure_paris': heure_paris_str or "—",
        'statut': statut,
        'venue': traduire_stade(ligne.get('stade')) or "—",
    }


def predire_runs_match(moyenne_runs_equipe, moyenne_ra_equipe, stats_lanceur_adverse):
    """
    Estimation heuristique (PAS un modèle statistique validé) du nombre de runs que
    l'équipe sélectionnée pourrait marquer aujourd'hui, ainsi que du total de runs du
    match, en croisant :
      - la moyenne de runs marqués par l'équipe sur ses 10 derniers matchs,
      - les stats du lanceur partant adverse (ERA, WHIP) - un ERA/WHIP élevé indique un
        lanceur plus "battable", donc on augmente l'estimation,
      - la moyenne de runs concédés par l'équipe sur ses 10 derniers matchs, utilisée comme
        proxy raisonnable de l'attaque adverse (faute de connaître le lanceur partant de
        notre propre équipe, hors périmètre de la demande).
    Si les stats du lanceur adverse ne sont pas disponibles (dégradation gracieuse - cas
    fréquent en KBO pour un lanceur sans historique ERA exploitable cette saison, ou si le
    nom annoncé n'a pas pu être retrouvé dans les effectifs), on se base uniquement sur la
    forme offensive récente de l'équipe, exactement comme le fait l'app NPB dans ce cas.
    Retourne un dict {'runs_equipe', 'total_match', 'confiance'} ou None si aucune donnée
    de forme récente n'est disponible pour l'équipe.
    """
    if moyenne_runs_equipe is None:
        return None

    if stats_lanceur_adverse is not None and (stats_lanceur_adverse.get('era') or 0) > 0:
        era = stats_lanceur_adverse['era']
        whip = stats_lanceur_adverse.get('whip')
        # Moyenne pondérée entre la forme offensive de l'équipe et la vulnérabilité du lanceur adverse
        runs_estimes_equipe = (moyenne_runs_equipe * 0.55) + (era * 0.45)
        # Un WHIP élevé (plus de coureurs sur les buts) augmente l'estimation, un WHIP très bas la réduit
        if whip is not None:
            if whip >= 1.35:
                runs_estimes_equipe *= 1.12
            elif whip <= 1.05:
                runs_estimes_equipe *= 0.90
        confiance = "Élevée" if (stats_lanceur_adverse.get('matchs_titulaire') or 0) >= 8 else "Moyenne"
    else:
        # Pas de stats fiables sur le lanceur adverse -> on se base uniquement sur la forme offensive de l'équipe
        runs_estimes_equipe = moyenne_runs_equipe
        confiance = "Faible"

    runs_estimes_adverse = moyenne_ra_equipe if moyenne_ra_equipe is not None and pd.notna(moyenne_ra_equipe) else moyenne_runs_equipe
    total_runs_estime = runs_estimes_equipe + runs_estimes_adverse

    return {
        'runs_equipe': round(runs_estimes_equipe, 1),
        'total_match': round(total_runs_estime, 1),
        'confiance': confiance,
    }


def predire_joueurs_du_jour(cumul_runs_10, cumul_hr_10, stats_lanceur_adverse, top_n: int = 3):
    """
    Construit une liste de joueurs "en forme" et calcule pour chacun un indice de confiance
    (0-100) croisant leur activité récente avec les faiblesses du lanceur adverse du jour
    (ERA, WHIP, HR/9 encaissés).

    La fonction prend `cumul_runs_10` / `cumul_hr_10`, les dictionnaires COMPLETS (non
    tronqués) de tous les joueurs sur les 10 derniers matchs. On sélectionne les candidats
    "en forme" via le top 3 de chaque catégorie (runs / HR), mais leur total affiché est
    toujours le total EXACT (les deux dictionnaires complets), jamais une valeur tronquée à
    0 pour un joueur présent dans le top 3 d'une seule des deux catégories.

    Retourne une liste de dicts triée par indice décroissant, limitée à `top_n`.
    """
    cumul_runs_10 = cumul_runs_10 or {}
    cumul_hr_10 = cumul_hr_10 or {}

    if not cumul_runs_10 and not cumul_hr_10:
        return []

    top3_noms_runs = {nom for nom, _ in sorted(cumul_runs_10.items(), key=lambda x: x[1], reverse=True)[:3]}
    top3_noms_hr = {nom for nom, _ in sorted(cumul_hr_10.items(), key=lambda x: x[1], reverse=True)[:3]}
    candidats = top3_noms_runs | top3_noms_hr

    if not candidats:
        return []

    # Facteur de vulnérabilité du lanceur adverse : plus son ERA/WHIP/HR-par-9 sont élevés,
    # plus il est jugé "battable" (facteur > 1) ; un lanceur dominant réduit le facteur
    # (< 1). Le facteur est borné pour rester réaliste (pas d'emballement).
    facteur_adverse = 1.0
    if stats_lanceur_adverse is not None and (stats_lanceur_adverse.get('era') or 0) > 0:
        era = stats_lanceur_adverse['era']
        whip = stats_lanceur_adverse.get('whip') or 1.20
        hr9 = stats_lanceur_adverse.get('hr_par_9') or 1.0
        facteur_adverse += max(0, (era - 4.0)) * 0.08
        facteur_adverse += max(0, (whip - 1.20)) * 0.5
        facteur_adverse += max(0, (hr9 - 1.0)) * 0.15
        facteur_adverse = max(0.7, min(facteur_adverse, 1.6))

    resultats = []
    for nom in candidats:
        runs_10 = cumul_runs_10.get(nom, 0)
        hr_10 = cumul_hr_10.get(nom, 0)
        indice_brut = (runs_10 * 8) + (hr_10 * 20)  # le HR pèse plus car plus rare qu'un run
        indice = min(95, round(indice_brut * facteur_adverse))
        if indice <= 0:
            continue
        if indice >= 65:
            confiance = "Élevée"
        elif indice >= 35:
            confiance = "Moyenne"
        else:
            confiance = "Faible"
        resultats.append({
            'nom': nom,
            'runs_10': runs_10,
            'hr_10': hr_10,
            'indice': indice,
            'confiance': confiance,
        })

    resultats = sorted(resultats, key=lambda x: x['indice'], reverse=True)
    return resultats[:top_n]


# ============================================================
# 6. INTERFACE PRINCIPALE
# ============================================================

st.title("⚾ Analyse Statistiques KBO (Korea Baseball Organization)")
st.markdown("### Explorez les runs, les prédictions du jour et les tendances W/L")

# Sidebar pour les paramètres globaux
with st.sidebar:
    st.header("⚙️ Paramètres")
    saison_options = list(range(ANNEE_COURANTE, ANNEE_COURANTE - 5, -1))
    annee = int(st.selectbox(
        "Sélectionnez la saison:",
        options=saison_options,
        index=0
    ))
    st.markdown("---")
    st.markdown("**Légende des abréviations:**")
    st.markdown("""
    - **R** : Runs (Points marqués)
    - **RA** : Runs Against (Points concédés)
    - **HR** : Home Runs (Coup de circuit)
    - **W** : Wins (Victoires)
    - **L** : Losses (Défaites)
    """)
    st.markdown("---")
    st.caption(
        "🕒 Les dates/heures de match sont gérées en heure de Corée (KST, UTC+9, sans "
        "heure d'été) puis converties en heure française dans l'onglet Prédictions du jour, "
        "car les matchs KBO se jouent tôt en heure française (fin de matinée/après-midi)."
    )
    st.caption(
        "📡 Données récupérées via l'API interne (non officielle) de Naver Sports, "
        "utilisée par de nombreux outils KBO open-source : le site officiel "
        "koreabaseball.com bloque les requêtes automatisées vers ses propres endpoints "
        "internes (HTTP 401), même avec des en-têtes de navigateur réalistes."
    )
    st.caption(
        "🈺 Les noms de joueurs coréens sont romanisés automatiquement (algorithme de "
        "romanisation révisée du coréen) ; le nom anglais officiel est utilisé à la place "
        "quand Naver Sports le connaît (surtout pour les joueurs étrangers). Limite connue : "
        "un joueur étranger sans nom anglais connu peut être affiché avec une romanisation "
        "approximative de sa transcription coréenne."
    )

# Récupération de la liste des équipes KBO
EQUIPES_KBO = get_teams_kbo(annee)

# ============================================================
# 7. ONGLETS PRINCIPAUX
# ============================================================
onglets = st.tabs([
    "📊 Analyse par Équipe",
    "🔮 Prédictions du jour"
])

# --------------------------------------------------------------
# ONGLET 1: ANALYSE PAR ÉQUIPE
# --------------------------------------------------------------
with onglets[0]:
    st.header("📊 Analyse des Runs par Équipe")

    col1, col2 = st.columns([1, 3])

    with col1:
        options_equipes = [f"{abbr} - {nom}" for abbr, nom in EQUIPES_KBO.items()]
        equipe_selectionnee = st.selectbox(
            "Choisissez une équipe:",
            options=options_equipes
        )

    equipe_abbr = extraire_abreviation_equipe(equipe_selectionnee)

    # Chargement des données de matchs, enrichies avec les scoreurs de runs et de HR
    # (boxscores Naver Sports) - premier chargement potentiellement long (un appel réseau
    # par match de la saison), les chargements suivants sont quasi instantanés grâce au
    # cache Streamlit.
    with st.spinner(f"Chargement des données et des boxscores pour les {EQUIPES_KBO[equipe_abbr]} ({annee})... (peut prendre un moment)"):
        df_matchs, df_meilleurs_scoreurs, df_meilleurs_hr = get_matchs_avec_scoreurs(annee, equipe_abbr)

    # Valeurs par défaut du résumé des 10 derniers matchs : elles sont réaffectées plus bas
    # si les données sont disponibles, mais doivent exister dès maintenant car l'onglet
    # "Prédictions du jour" (exécuté après celui-ci) les réutilise.
    moyenne_runs_10, top3_runs_10, moyenne_hr_10, top3_hr_10 = None, [], None, []
    cumul_runs_10, cumul_hr_10 = {}, {}

    st.markdown("---")
    st.subheader("🔝 Classement Home Runs dans l'équipe")

    # -------- Top 3 frappeurs de Home Runs, calculé à partir des boxscores Naver Sports --------
    # On réutilise directement `df_meilleurs_hr`, déjà calculé ci-dessus à partir de TOUS
    # les boxscores de la saison chargée - c'est la même source de vérité que la colonne
    # "Joueurs (HR)" plus bas, plutôt que d'interroger une seconde fois une API de
    # statistiques agrégées qui pourrait diverger légèrement de ce qui est affiché.
    top_batteurs_hr = []
    if not df_meilleurs_hr.empty:
        top_batteurs_hr = df_meilleurs_hr.head(3).to_dict('records')

    if not top_batteurs_hr:
        st.info("Aucun joueur avec Home Runs enregistré pour cette équipe/saison.")
    else:
        slugger_cols = st.columns(len(top_batteurs_hr))
        for idx, row in enumerate(top_batteurs_hr):
            with slugger_cols[idx]:
                st.metric(label=row['Joueur'], value=f"{int(row['Home Runs'])} HR")
    # ----- Fin du classement Home Runs équipe ------

    st.markdown("---")
    st.subheader("📈 Tendance des Runs par match (score équipe)")
    # 2. Graphique tendance Runs, avec ligne de moyenne annotée
    try:
        if not df_matchs.empty and "R" in df_matchs.columns:
            df_matchs = df_matchs.copy()
            df_matchs['Runs'] = pd.to_numeric(df_matchs['R'], errors='coerce')
            df_matchs = df_matchs.dropna(subset=['Runs'])
            # Ajouter un numéro de match croissant
            df_matchs = df_matchs.reset_index(drop=True)
            df_matchs['Match_Num'] = df_matchs.index + 1

            if not df_matchs.empty:
                moyenne_runs = df_matchs['Runs'].mean()

                ligne_runs = alt.Chart(df_matchs).mark_line(
                    point=True, color='#1f77b4'
                ).encode(
                    x=alt.X('Match_Num:Q', title='Numéro du match'),
                    y=alt.Y('Runs:Q', title='Runs marqués'),
                    tooltip=[
                        alt.Tooltip('Match_Num:Q', title='Match #'),
                        alt.Tooltip('Runs:Q', title='Runs')
                    ]
                )

                ligne_moyenne = alt.Chart(pd.DataFrame({'moyenne': [moyenne_runs]})).mark_rule(
                    color='red', strokeDash=[6, 4], size=2
                ).encode(
                    y=alt.Y('moyenne:Q'),
                    tooltip=[alt.Tooltip('moyenne:Q', title='Moyenne', format='.2f')]
                )

                annotation_moyenne = alt.Chart(pd.DataFrame({
                    'moyenne': [moyenne_runs],
                    'x': [df_matchs['Match_Num'].max()]
                })).mark_text(
                    text=f"Moyenne : {moyenne_runs:.2f}",
                    align='right',
                    baseline='bottom',
                    dx=-4,
                    dy=-6,
                    color='red',
                    fontWeight='bold'
                ).encode(
                    x=alt.X('x:Q'),
                    y=alt.Y('moyenne:Q')
                )

                st.altair_chart(ligne_runs + ligne_moyenne + annotation_moyenne)
            else:
                st.info("Pas de données de runs disponibles pour cette équipe/saison.")
        else:
            st.info("Pas de données de runs disponibles pour cette équipe/saison.")
    except Exception as e:
        st.info(f"Erreur lors de l'affichage des tendances de runs : {e}")

    # Statistiques synthétiques en haut
    if not df_matchs.empty and 'R' in df_matchs.columns:
        runs_total = df_matchs['R'].sum()
        runs_moyen = df_matchs['R'].mean()
        matchs_joues = len(df_matchs[df_matchs['R'].notna()])

        st.markdown(f"### Statistiques des Runs - {EQUIPES_KBO[equipe_abbr]} ({annee})")
        col_stat1, col_stat2, col_stat3 = st.columns(3)
        with col_stat1:
            st.metric(
                label="Runs Totaux",
                value=f"{int(runs_total)}",
                help="Nombre total de runs marqués cette saison")
        with col_stat2:
            st.metric(
                label="Moyenne par Match",
                value=f"{runs_moyen:.2f}",
                help="Moyenne de runs marqués par match"
            )
        with col_stat3:
            st.metric(
                label="Matchs Analysés",
                value=f"{matchs_joues}",
                help="Nombre de matchs avec données disponibles"
            )

        st.markdown("---")
        st.subheader("📋 Derniers Matchs")
        st.caption("Dates affichées selon le calendrier coréen (KST), identique à celui de koreabaseball.com.")
        display_columns = ['Date', 'Équipe Domicile', 'Équipe Extérieur', 'R', 'RA', 'W/L', 'Joueurs (Runs)', 'Joueurs (HR)']
        df_recents = df_matchs.tail(10)
        df_recents = df_recents[display_columns] if all(c in df_recents.columns for c in display_columns) else df_recents

        # Renommer les colonnes pour la présentation
        df_recents = df_recents.rename(columns={
            'R': 'Runs',
            'RA': 'Runs_Adverses',
            'W/L': 'Résultat'
        })

        # --- Ajout du surlignage sur l'équipe sélectionnée dans le tableau des matchs ---

        # Nom de l'équipe sélectionnée (utilisé pour la surbrillance)
        nom_equipe_sel = EQUIPES_KBO.get(equipe_abbr, "")

        def highlight_team(cell):
            if cell == nom_equipe_sel:
                # On utilise un bleu claire qui convient sur clair comme foncé
                return 'background-color: #bdd7ee; font-weight: bold;'
            return ''

        # Affichage du DataFrame stylé
        try:
            st.dataframe(
                df_recents.style.applymap(
                    highlight_team,
                    subset=['Équipe Domicile', 'Équipe Extérieur']
                ),
                use_container_width=True,
                hide_index=True
            )
        except Exception:
            st.dataframe(df_recents, use_container_width=True, hide_index=True)

        # --- Résumé permanent des 10 derniers matchs (se met à jour automatiquement) ---
        moyenne_runs_10, top3_runs_10, moyenne_hr_10, top3_hr_10, cumul_runs_10, cumul_hr_10 = calculer_resume_10_derniers_matchs(
            df_matchs.tail(10)
        )
        if moyenne_runs_10 is not None:
            texte_top3_runs = (
                ", ".join(f"{nom} ({runs} runs)" for nom, runs in top3_runs_10)
                if top3_runs_10 else "Aucun joueur enregistré"
            )
            texte_top3_hr = (
                ", ".join(f"{nom} ({hr} HR)" for nom, hr in top3_hr_10)
                if top3_hr_10 else "Aucun joueur enregistré"
            )

            st.markdown(f"**Moyenne de runs sur les 10 derniers matchs : {moyenne_runs_10:.2f}**")
            st.markdown(f"**Top 3 des joueurs les plus récurrents (runs marqués) : {texte_top3_runs}**")
            st.markdown(f"**Moyenne de home runs sur les 10 derniers matchs : {moyenne_hr_10:.2f}**")
            st.markdown(f"**Top 3 des joueurs les plus récurrents (home runs) : {texte_top3_hr}**")
        else:
            st.markdown("**Résumé indisponible : pas assez de données sur les 10 derniers matchs.**")

        st.markdown("---")
        col_runs, col_hr = st.columns(2)
        with col_runs:
            st.subheader("🏅 Meilleurs scoreurs de Runs")
            st.markdown(f"Cumul des runs marqués par joueur sur la saison {annee}")
            if not df_meilleurs_scoreurs.empty:
                st.dataframe(
                    df_meilleurs_scoreurs,
                    use_container_width=True,
                    hide_index=True
                )
            else:
                st.info("Aucune donnée de scoreurs disponible pour cette équipe/saison.")
        with col_hr:
            st.subheader("🏆 Meilleurs frappeurs de Home Runs")
            st.markdown(f"Cumul des home runs marqués par joueur sur la saison {annee}")
            if not df_meilleurs_hr.empty:
                st.dataframe(
                    df_meilleurs_hr,
                    use_container_width=True,
                    hide_index=True
                )
            else:
                st.info("Aucune donnée de home runs disponible pour cette équipe/saison.")
    elif not df_matchs.empty:
        st.warning("Données de runs non disponibles pour cette équipe.")
    else:
        st.error("Impossible de charger les données. Vérifiez le code de l'équipe, ou réessayez : l'API Naver Sports peut être temporairement indisponible.")

# --------------------------------------------------------------
# ONGLET 2: PRÉDICTIONS DU JOUR
# --------------------------------------------------------------
with onglets[1]:
    st.header("🔮 Prédictions du jour")
    st.markdown(f"Prédiction du match du jour pour les **{EQUIPES_KBO.get(equipe_abbr, equipe_abbr)}**")
    st.caption(
        "⚠️ Estimations statistiques basées sur les tendances récentes de l'équipe et les stats du "
        "lanceur adverse. Ce ne sont pas des garanties de résultat : à utiliser uniquement à titre "
        "informatif, avec discernement si vous vous en servez pour parier."
    )

    if annee != ANNEE_COURANTE:
        st.info(
            f"Les prédictions du jour ne sont disponibles que pour la saison en cours "
            f"({ANNEE_COURANTE}). Sélectionnez {ANNEE_COURANTE} dans le menu de gauche pour "
            f"voir la prédiction du match d'aujourd'hui (heure de Corée)."
        )
    else:
        maintenant_kst_aff = datetime.now(TZ_SEOUL)
        maintenant_paris_aff = maintenant_kst_aff.astimezone(TZ_PARIS)
        st.caption(
            f"📅 Aujourd'hui en Corée : {maintenant_kst_aff.strftime('%A %d %B %Y, %H:%M')} (KST) "
            f"— soit {maintenant_paris_aff.strftime('%A %d %B %Y, %H:%M')} en France."
        )

        with st.spinner("Recherche du match du jour (calendrier KBO, heure de Corée)..."):
            match_du_jour = obtenir_match_du_jour(equipe_abbr, annee)

        if not match_du_jour:
            st.info(f"Aucun match n'est prévu aujourd'hui (heure de Corée) pour les {EQUIPES_KBO.get(equipe_abbr, equipe_abbr)}.")
        else:
            lieu = "à domicile" if match_du_jour['est_domicile'] else "à l'extérieur"
            st.subheader(
                f"🆚 {EQUIPES_KBO.get(equipe_abbr, equipe_abbr)} {lieu} contre {match_du_jour['adversaire']}"
            )

            col_venue, col_heure_kst, col_heure_paris, col_statut = st.columns(4)
            with col_venue:
                st.metric("Stade", match_du_jour['venue'] or "—")
            with col_heure_kst:
                st.metric("Heure (Corée, KST)", match_du_jour['heure_kst'])
            with col_heure_paris:
                st.metric("Heure (France)", match_du_jour['heure_paris'])
            with col_statut:
                st.metric("Statut", match_du_jour['statut'] or "—")

            st.markdown("#### ⚾ Lanceurs partants annoncés")
            col_p1, col_p2 = st.columns(2)
            with col_p1:
                st.markdown(f"**{EQUIPES_KBO.get(equipe_abbr, equipe_abbr)}**")
                st.markdown(f"### {match_du_jour['lanceur_notre_equipe'] or 'Non annoncé'}")
            with col_p2:
                st.markdown(f"**{match_du_jour['adversaire']}**")
                st.markdown(f"### {match_du_jour['lanceur_adverse'] or 'Non annoncé'}")

            # Les stats du lanceur adverse (saison en cours) ont déjà été récupérées par
            # `obtenir_match_du_jour` (en même temps que son nom anglais/romanisé), il n'y
            # a donc plus besoin d'un second appel réseau séparé ici.
            stats_lanceur_adverse = match_du_jour['stats_lanceur_adverse']

            if stats_lanceur_adverse and stats_lanceur_adverse.get('era'):
                whip_txt = f"{stats_lanceur_adverse['whip']:.2f}" if stats_lanceur_adverse.get('whip') is not None else "—"
                st.caption(
                    f"Stats saison {annee} de {stats_lanceur_adverse['nom']} : "
                    f"ERA {stats_lanceur_adverse['era']:.2f} · WHIP {whip_txt} · "
                    f"{stats_lanceur_adverse['hr_alloues']} HR alloués · "
                    f"{stats_lanceur_adverse['matchs_titulaire']} apparitions"
                )
            elif match_du_jour['lanceur_adverse']:
                st.caption("Statistiques du lanceur adverse indisponibles pour le moment.")

            st.markdown("---")
            st.subheader("📊 Module de prédiction des Runs")

            if moyenne_runs_10 is None:
                st.info("Pas assez de données récentes pour estimer les runs de cette équipe.")
            else:
                moyenne_ra_10 = pd.to_numeric(
                    df_matchs.tail(10).get('RA', pd.Series(dtype=float)), errors='coerce'
                ).mean()
                prediction_runs = predire_runs_match(moyenne_runs_10, moyenne_ra_10, stats_lanceur_adverse)

                col_pred1, col_pred2, col_pred3 = st.columns(3)
                with col_pred1:
                    st.metric(
                        f"Runs estimés — {equipe_abbr}",
                        f"{prediction_runs['runs_equipe']}"
                    )
                with col_pred2:
                    st.metric("Total de runs estimé (match)", f"{prediction_runs['total_match']}")
                with col_pred3:
                    st.metric("Indice de confiance", prediction_runs['confiance'])

                st.caption(
                    f"Basé sur une moyenne de {moyenne_runs_10:.2f} runs/match et "
                    f"{moyenne_ra_10:.2f} runs concédés/match sur les 10 derniers matchs, "
                    + (
                        f"croisée avec les stats du lanceur adverse ({stats_lanceur_adverse['nom']})."
                        if stats_lanceur_adverse and stats_lanceur_adverse.get('era')
                        else "en l'absence de stats fiables sur le lanceur adverse."
                    )
                )

            st.markdown("---")
            st.subheader("🎯 Module de prédiction des Joueurs (HR / Runs)")

            joueurs_a_surveiller = predire_joueurs_du_jour(
                cumul_runs_10, cumul_hr_10, stats_lanceur_adverse, top_n=3
            )

            if not joueurs_a_surveiller:
                st.info(
                    "Pas assez de données de forme récente (runs/HR sur les 10 derniers matchs) "
                    "pour identifier des joueurs à surveiller aujourd'hui."
                )
            else:
                cols_joueurs = st.columns(len(joueurs_a_surveiller))
                for idx, joueur in enumerate(joueurs_a_surveiller):
                    with cols_joueurs[idx]:
                        st.markdown(f"**{joueur['nom']}**")
                        st.progress(joueur['indice'] / 100)
                        st.markdown(f"Indice de confiance : **{joueur['confiance']}** ({joueur['indice']}/100)")
                        st.caption(
                            f"{joueur['runs_10']} run(s) et {joueur['hr_10']} HR sur les 10 derniers matchs"
                        )

# ============================================================
# 7bis. PIED DE PAGE
# ============================================================
st.markdown("---")
st.markdown(
    f"<div style='text-align: center; color: gray;'>"
    f"⚾ Application KBO Analytics | Données : API Naver Sports (non officielle) | Mise à jour: "
    f"{datetime.now(TZ_SEOUL).strftime('%Y-%m-%d %H:%M')} KST"
    f"</div>",
    unsafe_allow_html=True
)
