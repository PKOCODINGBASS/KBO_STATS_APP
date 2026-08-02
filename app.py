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
import re                       # Extraction des runs/manches lancées dans les champs texte
import time                     # Délais/backoff entre les appels réseau
import json                     # Le champ "profile" de l'API Naver Sports est lui-même une
                                 # chaîne JSON imbriquée dans la réponse JSON - il faut donc
                                 # la reparser explicitement (voir `_charger_effectifs_saison`)
import calendar                 # calendar.monthrange : calcule le dernier jour d'un mois
                                 # donné, nécessaire pour interroger l'API par plage de dates
import os                       # Chemin du fichier d'historique des prédictions (bilan de la veille)
import requests                 # Appels HTTP vers l'API interne Naver Sports et The-Odds-API (Value Bet)
import unicodedata              # Normalisation des noms d'équipe (Value Bet Detector)
from datetime import datetime, timedelta  # Gestion des dates (timedelta : calcul de "hier")
from zoneinfo import ZoneInfo   # Gestion des fuseaux horaires (KST <-> heure française)

# Design system partagé (monorepo PARIS SPORTIFS) — cherche shared/ local puis parent
import sys
from pathlib import Path as _Path
for _base in (_Path(__file__).resolve().parent, _Path(__file__).resolve().parent.parent):
    if (_base / "shared" / "theme.py").is_file():
        if str(_base) not in sys.path:
            sys.path.insert(0, str(_base))
        break
from shared.theme import (  # noqa: E402
    apply_theme,
    render_page_header,
    render_section_title,
    afficher_cartes_matchs,
    afficher_badge_value_bet,
    render_footer,
    render_prediction_match_banner,
)

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


# ------------------------------------------------------------------------------
# Persistance de l'historique des prédictions (pour le "Bilan des Prédictions" de la
# veille, onglet Résumé) : un instantané des prédictions du jour ("Hot Pronostics")
# est archivé chaque jour, pour pouvoir être comparé au résultat réel le lendemain.
#
# Streamlit Community Cloud utilise un système de fichiers ÉPHÉMÈRE : tout fichier
# écrit localement pendant l'exécution est PERDU à chaque redéploiement (déclenché par
# un `git push`) ou "réveil" de l'app après une période d'inactivité. Un simple fichier
# local ne suffit donc pas à conserver l'historique dans la durée sur cet hébergement.
#
# La source de vérité est donc un Gist GitHub PRIVÉ (persiste indéfiniment, quel que
# soit le nombre de redéploiements), configuré via `st.secrets` :
#
#     [github]
#     token = "ghp_..."   # Personal Access Token GitHub, scope "gist" UNIQUEMENT
#     gist_id = "..."     # ID du Gist privé contenant historique_predictions_kbo.json
#
# à renseigner dans `.streamlit/secrets.toml` en local, et dans les "Secrets" de l'app
# sur share.streamlit.io en production (jamais commités : `.streamlit/secrets.toml`
# est listé dans `.gitignore`).
#
# Si ces secrets ne sont pas configurés (ex: tout premier lancement, développement
# local sans Gist créé), l'application se rabat silencieusement sur le fichier local
# ci-dessous - fonctionnel, mais non persistant sur Streamlit Cloud. Ce fichier local
# sert aussi de cache accessoire même quand le Gist est configuré (repli en cas de
# panne réseau GitHub ponctuelle). Portage à l'identique de la fonctionnalité
# équivalente de NPB_Stats_App (voir son en-tête de fichier), adapté au fuseau horaire
# coréen (KST) et au nom de fichier propre à la KBO.
# ------------------------------------------------------------------------------
NOM_FICHIER_HISTORIQUE_PREDICTIONS = "historique_predictions_kbo.json"
CHEMIN_HISTORIQUE_PREDICTIONS = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), NOM_FICHIER_HISTORIQUE_PREDICTIONS
)


def _obtenir_config_github():
    """
    Lit la configuration GitHub (token + ID du Gist privé) dans `st.secrets`, utilisée
    pour la persistance durable de l'historique des prédictions (cf. commentaire au-
    dessus de `CHEMIN_HISTORIQUE_PREDICTIONS`). Retourne (token, gist_id), ou
    (None, None) si non configuré - jamais d'exception : accéder à `st.secrets` lève
    une erreur s'il n'existe AUCUN fichier `secrets.toml` du tout (cas du tout premier
    lancement / développement local sans Gist configuré), qu'il faut absorber ici pour
    retomber sur le fichier local en toute transparence.
    """
    try:
        conf = st.secrets.get("github", {})
        return conf.get("token"), conf.get("gist_id")
    except Exception:
        return None, None


def _charger_historique_predictions() -> dict:
    """
    Charge l'historique des prédictions archivées (un instantané par date, au format
    {'AAAA-MM-JJ': {'sauvegarde_le': ..., 'matches': [...]}}) - en PRIORITÉ depuis le
    Gist GitHub privé configuré (`_obtenir_config_github`), seule source qui survit aux
    redéploiements sur Streamlit Community Cloud. Repli sur le fichier local
    `CHEMIN_HISTORIQUE_PREDICTIONS` si le Gist n'est pas configuré, ou si l'appel à
    l'API GitHub échoue (panne réseau ponctuelle, token invalide, etc.).

    Retourne un dict vide si aucune des deux sources n'est disponible (ex: tout premier
    lancement de l'application) - ne doit jamais faire planter l'application.
    """
    token, gist_id = _obtenir_config_github()
    if token and gist_id:
        try:
            reponse = requests.get(
                f"https://api.github.com/gists/{gist_id}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                },
                timeout=10,
            )
            reponse.raise_for_status()
            fichier = reponse.json().get("files", {}).get(NOM_FICHIER_HISTORIQUE_PREDICTIONS)
            if fichier and fichier.get("content"):
                return json.loads(fichier["content"])
            return {}
        except Exception:
            pass  # repli silencieux sur le fichier local ci-dessous

    try:
        with open(CHEMIN_HISTORIQUE_PREDICTIONS, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _sauvegarder_predictions_du_jour(date_str: str, matches_snapshot: list) -> None:
    """
    Archive l'instantané des prédictions du jour (`matches_snapshot`) sous la clé
    `date_str`, à la fois dans le Gist GitHub privé configuré (source durable, cf.
    `_obtenir_config_github`) ET dans le fichier local (repli/cache accessoire).
    Appelée depuis `construire_donnees_hot_pronostics_kbo` (donc au maximum une fois
    toutes les 30 min, son propre `ttl` de cache) : écrire à chaque appel écrase
    simplement l'instantané du jour par la version la plus à jour (utile si les
    lanceurs annoncés changent en cours de journée), ce qui est le comportement
    recherché.

    Purge au passage les entrées de plus de 30 jours, pour que l'historique ne
    grossisse pas indéfiniment au fil des mois. Ne lève jamais d'exception : la
    sauvegarde de l'historique est un "bonus" (bilan de la veille) qui ne doit jamais
    faire planter le calcul des prédictions du jour lui-même en cas de souci réseau ou
    d'écriture disque (permissions, disque plein, filesystem éphémère, etc.).
    """
    try:
        historique = _charger_historique_predictions()
        historique[date_str] = {
            'sauvegarde_le': datetime.now(TZ_SEOUL).isoformat(),
            'matches': matches_snapshot,
        }
        date_limite = (datetime.now(TZ_SEOUL) - timedelta(days=30)).strftime('%Y-%m-%d')
        historique = {d: v for d, v in historique.items() if d >= date_limite}
        contenu_json = json.dumps(historique, ensure_ascii=False, indent=2)

        token, gist_id = _obtenir_config_github()
        if token and gist_id:
            try:
                reponse = requests.patch(
                    f"https://api.github.com/gists/{gist_id}",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/vnd.github+json",
                    },
                    json={"files": {NOM_FICHIER_HISTORIQUE_PREDICTIONS: {"content": contenu_json}}},
                    timeout=10,
                )
                reponse.raise_for_status()
            except Exception:
                pass  # au pire, le fichier local ci-dessous prend seul le relais

        with open(CHEMIN_HISTORIQUE_PREDICTIONS, "w", encoding="utf-8") as f:
            f.write(contenu_json)
    except Exception:
        pass


# ============================================================
# 2. CONFIGURATION DE LA PAGE - Paramètres de l'application
# ============================================================
st.set_page_config(
    page_title="Analyse KBO - Runs & Sluggers",
    page_icon="⚾",
    layout="wide"
)
# Thème visuel KBO (bleu roi / blanc / argent + touche rouge) — n'altère aucune logique métier
apply_theme("kbo")

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
            "suspended": g.get('suspended'),
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
        # Les stats du lanceur de NOTRE équipe sont récupérées EXACTEMENT de la même façon
        # (symétrique) que celles du lanceur adverse ci-dessus (voir `infos_notre_lanceur`
        # plus haut dans cette fonction) : elles étaient déjà calculées mais pas exposées
        # dans ce dict avant l'ajout du module "Probabilité de Victoire", qui en a besoin
        # pour comparer les DEUX lanceurs partants annoncés.
        'stats_lanceur_nous': infos_notre_lanceur,
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


def predire_probabilite_victoire(
    moyenne_runs_nous,
    moyenne_offense_adverse,
    stats_lanceur_nous,
    stats_lanceur_adverse,
    est_domicile: bool,
):
    """
    Estimation heuristique (PAS un modèle statistique validé - aucune régression logistique
    entraînée sur des données historiques ici, juste une pondération "de bon sens") de la
    probabilité de victoire de l'équipe sélectionnée ("nous") face à son adversaire du jour,
    exprimée en pourcentage pour CHAQUE équipe (les deux valeurs retournées somment à 100%).

    --- Les 3 facteurs retenus, et leur pondération ---
    1. LANCEURS PARTANTS ANNONCÉS (poids 60% dans le score combiné - facteur jugé le PLUS
       déterminant, comme demandé : à l'échelle d'UN match de baseball, un lanceur partant
       influence directement 5 à 7 manches sur 9, un poids qu'aucun frappeur isolé n'a à
       lui seul). Pour chaque lanceur, on calcule un "indice de qualité" =
       (1/ERA) * 0.7 + (1/WHIP) * 0.3 : l'ERA pèse plus car c'est la statistique la plus
       lisible/suivie, le WHIP vient l'affiner (il capture aussi les coureurs laissés sur
       les buts, pas seulement les points encaissés). Plus l'indice est élevé (ERA/WHIP
       BAS), plus la probabilité penche vers l'équipe de ce lanceur. La part de chaque
       équipe dans ce facteur est simplement son indice rapporté à la somme des deux
       indices (ex: si notre lanceur a un indice deux fois plus élevé que l'adverse, on
       obtient 2/3 - 1/3, PAS 100% - 0%, pour rester réaliste).
    2. DYNAMIQUE OFFENSIVE RÉCENTE (poids 40% dans le score combiné) : moyenne de runs
       marqués sur les 10 derniers matchs de CHAQUE équipe. Pour notre équipe, on réutilise
       directement `moyenne_runs_10` (déjà calculé ailleurs dans l'onglet). Pour l'attaque
       ADVERSE, faute de recharger séparément ses 10 derniers matchs (appel réseau
       supplémentaire non indispensable dans le temps imparti), on réutilise EXACTEMENT le
       même proxy que `predire_runs_match` juste au-dessus : la moyenne de runs CONCÉDÉS
       par NOTRE équipe sur ses 10 derniers matchs (`moyenne_ra_10`), un indicateur
       indirect mais raisonnable de la force offensive à laquelle notre équipe a été
       récemment confrontée. Ce choix est documenté ici explicitement plutôt que caché.
    3. AVANTAGE DU TERRAIN (bonus fixe de +3 points de pourcentage, PAS un facteur pondéré
       avec les deux précédents - appliqué APRÈS le score combiné) pour l'équipe qui reçoit.
       Valeur choisie par prudence : les études sabermétriques MLB situent le taux de
       victoires à domicile autour de 53-54% en moyenne sur longue période (soit un
       avantage net d'environ 3 à 4 points par rapport à un match parfaitement équilibré à
       50/50) ; on retient ici la borne basse (+3) faute d'étude équivalente publiée
       spécifiquement sur la KBO, pour ne pas sur-pondérer un facteur secondaire.

    --- Dégradation gracieuse (données manquantes) ---
    - Lanceur sans ERA exploitable (`stats_lanceur_nous`/`stats_lanceur_adverse` vaut None,
      ou n'a pas de champ 'era' renseigné - cas fréquent en KBO pour un lanceur sans
      historique cette saison) : ce lanceur reçoit un ERA/WHIP "neutres" (`ERA_NEUTRE`/
      `WHIP_NEUTRE`, des moyennes de ligue approximatives), ce qui revient à neutraliser sa
      contribution individuelle SANS jamais planter ni fausser l'estimation vers un 0%/100%
      trompeur. Si les DEUX lanceurs manquent, le facteur 1 devient entièrement neutre
      (50/50), et seuls les facteurs 2 et 3 continuent à jouer.
    - Moyenne de runs manquante (`None`/`NaN`, ex: moins de 10 matchs joués cette saison) :
      remplacée par une moyenne "neutre" (`RUNS_NEUTRE`), pour la même raison.
    - Aucune combinaison de données manquantes ne peut faire planter cette fonction : au
      pire (aucune donnée du tout), elle retombe sur un 50/50 + bonus domicile.

    Retourne un tuple (pct_nous, pct_adverse) de deux flottants arrondis à 1 décimale dont
    la SOMME vaut exactement 100.0, chacun bornée entre 5.0 et 95.0 : une simple heuristique
    ne doit jamais afficher une fausse "certitude absolue" à 0% ou 100%.
    """
    # Valeurs "neutres" de repli (moyennes de ligue approximatives), utilisées uniquement
    # quand une donnée réelle manque, pour neutraliser proprement le facteur concerné.
    ERA_NEUTRE = 4.50    # ERA moyen approximatif toutes équipes KBO confondues
    WHIP_NEUTRE = 1.35   # WHIP moyen approximatif toutes équipes KBO confondues
    RUNS_NEUTRE = 4.50   # Runs/match moyens approximatifs en KBO
    BONUS_DOMICILE = 3.0  # Points de pourcentage (voir justification ci-dessus)

    def _indice_qualite_lanceur(stats_lanceur):
        """Indice de qualité d'un lanceur (plus haut = meilleur), avec repli neutre."""
        if stats_lanceur is not None and stats_lanceur.get('era'):
            era = stats_lanceur['era']
            whip = stats_lanceur.get('whip') or WHIP_NEUTRE
        else:
            era, whip = ERA_NEUTRE, WHIP_NEUTRE
        return (1.0 / era) * 0.7 + (1.0 / whip) * 0.3

    # --- Facteur 1 : lanceurs partants (poids 60%) ---
    qualite_nous = _indice_qualite_lanceur(stats_lanceur_nous)
    qualite_adverse = _indice_qualite_lanceur(stats_lanceur_adverse)
    part_lanceurs_nous = qualite_nous / (qualite_nous + qualite_adverse)

    # --- Facteur 2 : dynamique offensive récente (poids 40%) ---
    runs_nous = (
        moyenne_runs_nous if moyenne_runs_nous is not None and pd.notna(moyenne_runs_nous)
        else RUNS_NEUTRE
    )
    runs_adverse = (
        moyenne_offense_adverse if moyenne_offense_adverse is not None and pd.notna(moyenne_offense_adverse)
        else RUNS_NEUTRE
    )
    somme_runs = runs_nous + runs_adverse
    part_offense_nous = (runs_nous / somme_runs) if somme_runs > 0 else 0.5

    # --- Score combiné (facteurs 1 + 2), puis conversion en pourcentage ---
    part_combinee_nous = (part_lanceurs_nous * 0.6) + (part_offense_nous * 0.4)
    pct_nous = part_combinee_nous * 100.0

    # --- Facteur 3 : avantage du terrain (bonus fixe, appliqué après coup) ---
    pct_nous += BONUS_DOMICILE if est_domicile else -BONUS_DOMICILE

    # Bornes de sécurité (jamais 0%/100% avec une simple heuristique) + normalisation
    # stricte à 100% (l'adversaire récupère exactement le complément).
    pct_nous = max(5.0, min(95.0, pct_nous))
    pct_adverse = 100.0 - pct_nous

    return round(pct_nous, 1), round(pct_adverse, 1)


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


# --------------------------------------------------------------
# SEUILS DE PRÉDICTION PAR LIGUE ("Recommandation de Pari Optimisée")
# --------------------------------------------------------------
# Les moyennes offensives et l'ERA "normal" diffèrent fortement d'une ligue à l'autre
# (la KBO est réputée TRÈS offensive/haut-scoring, davantage encore que la MLB ou la
# NPB - terrains plus petits, saison plus longue de matchs à forte intensité).
# Centraliser ces seuils dans un dictionnaire clé = code ligue permet à
# `generer_recommandation_pari` de s'adapter automatiquement à la ligue du match en
# cours (voir `detecter_ligue_match`), sans jamais coder les seuils KBO "en dur" dans
# la logique elle-même.
LIGUE_PAR_DEFAUT = 'KBO'

SEUILS_PARIS_PAR_LIGUE = {
    'KBO': {
        # ERA d'un lanceur partant jugé "battable" (favorise un pari Over)
        'era_mauvais': 5.00,
        # ERA d'un lanceur partant jugé dominant (favorise un pari Under)
        'era_excellent': 4.00,
        # Total de runs (des deux équipes cumulé) au-delà duquel on considère la
        # tendance du match comme offensive (KBO = ligue TRÈS offensive, seuil
        # plus haut qu'en MLB/NPB par exemple)
        'runs_total_haut': 10.5,
    },
}


def detecter_ligue_match(match_du_jour: dict = None) -> str:
    """
    Détecte la ligue du match en cours à partir des infos du match (`obtenir_match_du_jour`),
    afin que `generer_recommandation_pari` applique les bons seuils ERA/Runs (voir
    `SEUILS_PARIS_PAR_LIGUE`). Cette application ne couvre aujourd'hui que la KBO
    (source de données unique : API Naver Sports), donc le résultat vaut toujours 'KBO'
    en pratique - mais la détection passe bien par le champ `ligue` du match (plutôt
    qu'un `LIGUE_PAR_DEFAUT` codé en dur dans l'appelant), pour que la logique reste
    correcte sans modification si l'app venait à couvrir plusieurs ligues.
    """
    if match_du_jour and match_du_jour.get('ligue'):
        return match_du_jour['ligue']
    return LIGUE_PAR_DEFAUT


def generer_recommandation_pari(
    pct_nous,
    pct_adverse,
    stats_lanceur_nous,
    stats_lanceur_adverse,
    prediction_runs,
    joueurs_a_surveiller,
    ligue: str = None,
    vent_defavorable: bool = False,
):
    """
    Génère la "Recommandation de Pari Optimisée" affichée sous la ligne principale de
    prédiction (probabilité de victoire) de l'onglet "Prédictions du jour", via un petit
    arbre de décision qui croise plusieurs facteurs déjà calculés ailleurs dans l'onglet.
    Objectif affiché à l'utilisateur : minimiser le risque, pas maximiser le gain.

    --- Étape 1 : Risque sur le résultat (Win/Loss) - universel, toutes ligues ---
    Évalue systématiquement la "qualité" du match du point de vue du pari vainqueur
    (une phrase est TOUJOURS générée à cette étape, contrairement aux étapes 2 et 3) :
      - Si l'écart entre les deux probabilités de victoire est inférieur à 10 points, le
        match est jugé "à Haut Risque" sur le vainqueur : on recommande de préférer un
        pari sur les runs plutôt que sur le résultat (moins dépendant d'un seul évènement).
      - Sinon (écart >= 10 points, un favori se dégage nettement), le match est jugé
        "à Faible Risque" sur le vainqueur : un pari sur le résultat est alors présenté
        comme une option plus fiable qu'un pari sur les runs.

    --- Étape 2 : Total de runs (Over/Under) - seuils spécifiques à la ligue ---
    Seuils lus dans `SEUILS_PARIS_PAR_LIGUE[ligue]` (repli sur `LIGUE_PAR_DEFAUT` si la
    ligue est inconnue) :
      - Condition "tendance haute" (Over) : les DEUX lanceurs partants annoncés ont un
        ERA supérieur au seuil "mauvais ERA" de la ligue, OU le total de runs estimé du
        match dépasse le seuil "runs haut" de la ligue.
      - Condition "tendance basse" (Under) : les DEUX lanceurs ont un ERA inférieur au
        seuil "excellent ERA" de la ligue, OU le vent est défavorable aux frappeurs
        (facteur météo optionnel, non disponible aujourd'hui côté API Naver Sports -
        prévu pour une future intégration, `vent_defavorable=False` par défaut).
      La ligne de total proposée est décalée de 1.5 run (arrondi au 0,5 le plus proche)
      DANS LE SENS QUI RÉDUIT LE RISQUE : en dessous de l'estimation pour un Over, au-dessus
      pour un Under, pour se laisser une marge plutôt que de parier pile sur l'estimation brute.
      Une phrase Over/Under est TOUJOURS générée dès que le total estimé est disponible
      (repli : Over si projection >= seuil haut de ligue, sinon Under), y compris quand
      l'étape 1 privilégie déjà un pari sur le vainqueur.

    --- Étape 3 : Option joueur (HR/Run) - universel ---
    Si un joueur du module "Prédiction des Joueurs" (nos sluggers en forme du jour,
    `joueurs_a_surveiller`) ressort avec une confiance au moins "Moyenne", il est proposé
    comme option alternative de pari.

    Retourne une liste de phrases (str), dans l'ordre ci-dessus, prête à être jointe et
    affichée dans un seul encart (ex: `st.info`). Liste vide si aucune recommandation
    n'a pu être formulée (données insuffisantes).
    """
    ligue = ligue or LIGUE_PAR_DEFAUT
    seuils = SEUILS_PARIS_PAR_LIGUE.get(ligue, SEUILS_PARIS_PAR_LIGUE[LIGUE_PAR_DEFAUT])

    def _arrondir_au_demi(valeur: float) -> float:
        """Arrondit au 0,5 le plus proche (ex: 8.2 -> 8.0, 8.3 -> 8.5)."""
        return round(valeur * 2) / 2

    def _era(stats):
        return stats['era'] if stats and stats.get('era') else None

    conseils = []

    # --- Étape 1 : risque Win/Loss (universel) - toujours une phrase, dans un sens ou l'autre ---
    if pct_nous is not None and pct_adverse is not None:
        if abs(pct_nous - pct_adverse) < 10:
            conseils.append(
                "⚠️ Match serré (Haut Risque sur la victoire). Privilégiez un pari sur "
                "les Runs plutôt que sur le vainqueur."
            )
        else:
            favori = "notre équipe" if pct_nous > pct_adverse else "l'équipe adverse"
            conseils.append(
                f"✅ Écart de probabilité net en faveur de {favori} (Faible Risque sur la "
                "victoire). Un pari sur le vainqueur est ici plus fiable qu'un pari sur les Runs."
            )

    # --- Étape 2 : total de runs Over/Under (spécifique à la ligue) ---
    # Toujours une phrase Over/Under dès que le total estimé est disponible, y compris
    # quand l'étape 1 privilégie déjà un pari sur le vainqueur (favori net) : le conseil
    # runs reste alors une option complémentaire utile.
    era_nous = _era(stats_lanceur_nous)
    era_adverse = _era(stats_lanceur_adverse)
    deux_lanceurs_connus = era_nous is not None and era_adverse is not None

    deux_mauvais_era = deux_lanceurs_connus and era_nous > seuils['era_mauvais'] and era_adverse > seuils['era_mauvais']
    deux_excellents_era = deux_lanceurs_connus and era_nous < seuils['era_excellent'] and era_adverse < seuils['era_excellent']

    total_runs_estime = prediction_runs.get('total_match') if prediction_runs else None
    tendance_offensive_runs = total_runs_estime is not None and total_runs_estime > seuils['runs_total_haut']

    if total_runs_estime is not None:
        if deux_mauvais_era or tendance_offensive_runs:
            ligne_over = _arrondir_au_demi(total_runs_estime - 1.5)
            conseils.append(
                f"📈 Tendance offensive forte. Conseil : Jouer 'Over {ligne_over} runs'."
            )
        elif deux_excellents_era or vent_defavorable:
            ligne_under = _arrondir_au_demi(total_runs_estime + 1.5)
            conseils.append(
                f"📉 Match très défensif anticipé. Conseil : Jouer 'Under {ligne_under} runs'."
            )
        elif total_runs_estime >= seuils['runs_total_haut']:
            ligne_over = _arrondir_au_demi(total_runs_estime - 1.5)
            conseils.append(
                f"📈 Projection de runs au seuil haut de la ligue. Conseil : Jouer "
                f"'Over {ligne_over} runs'."
            )
        else:
            ligne_under = _arrondir_au_demi(total_runs_estime + 1.5)
            conseils.append(
                f"📉 Projection de runs contenue. Conseil : Jouer 'Under {ligne_under} runs'."
            )

    # --- Étape 3 : option joueur (universel) ---
    if joueurs_a_surveiller:
        meilleur_joueur = joueurs_a_surveiller[0]
        if meilleur_joueur.get('confiance') in ('Élevée', 'Moyenne'):
            conseils.append(
                f"🎯 Option alternative : {meilleur_joueur['nom']} a une forte probabilité "
                "de marquer un Run/HR aujourd'hui."
            )

    return conseils


# --------------------------------------------------------------
# VALUE BET DETECTOR (comparaison avec les cotes Winamax / marché)
# --------------------------------------------------------------
# Source de cotes : The-Odds-API (https://the-odds-api.com), qui agrège de nombreux
# bookmakers dont Winamax (clé bookmaker 'winamax_fr', région 'eu') - Winamax n'ayant
# pas d'API publique/officielle, passer par cet agrégateur évite le scraping direct de
# leur site (fragile et probablement contraire à leurs CGU) tout en donnant accès à
# leurs cotes réelles quand ce bookmaker couvre le match.
#
# ⚠️ Contrairement à la MLB, la couverture KBO de The-Odds-API/Winamax dépend fortement
# du calendrier/de la popularité du match : il est normal que certains matchs KBO
# n'aient AUCUNE cote disponible (le detector l'affiche alors clairement, sans planter).
ODDS_API_BASE_URL = 'https://api.the-odds-api.com/v4'
ODDS_API_SPORT_KEY = 'baseball_kbo'
ODDS_API_BOOKMAKER_PRINCIPAL = 'winamax_fr'
# Région de repli si Winamax ne propose pas (encore) de cote sur ce match précis -
# on retombe alors sur le 1er bookmaker EU disponible plutôt que d'afficher
# "indisponible" alors qu'une cote de marché existe ailleurs.
ODDS_API_REGION = 'eu'


def _lire_cle_odds_api():
    """
    Lit la clé API The-Odds-API dans `st.secrets` (section [odds_api], clé `api_key`),
    utilisée par le "Value Bet Detector". Retourne None si non configurée - jamais
    d'exception : accéder à `st.secrets` lève une erreur si le fichier secrets.toml
    n'existe pas du tout, d'où le `try/except` (même pattern que la config GitHub
    utilisée pour la persistance de l'historique des prédictions).
    """
    try:
        conf = st.secrets.get("odds_api", {})
        return conf.get("api_key")
    except Exception:
        return None


@st.cache_data(show_spinner=False, ttl=1800)
def obtenir_cotes_moneyline_du_jour(sport_key: str, api_key: str):
    """
    Récupère, via The-Odds-API, les cotes "Moneyline" (marché h2h = vainqueur du
    match, sans handicap) de TOUS les matchs à venir aujourd'hui pour le sport/ligue
    demandé (`sport_key`, ici 'baseball_kbo'), en priorité chez Winamax
    (`ODDS_API_BOOKMAKER_PRINCIPAL`). Si Winamax ne propose pas ce marché pour un
    match donné, on retombe sur le 1er bookmaker EU disponible pour ce match plutôt
    que de le considérer comme "indisponible" alors qu'une cote de marché existe.

    Mise en cache 30 minutes : le quota gratuit de The-Odds-API est limité (500
    requêtes/mois), inutile de rappeler l'API à chaque interaction utilisateur pour
    des cotes qui ne bougent pas d'une minute à l'autre.

    Retourne une liste de dicts {'equipe_domicile', 'equipe_exterieur',
    'cote_domicile', 'cote_exterieur', 'bookmaker'} (une entrée par match), ou []
    si la clé API n'est pas configurée, si la KBO n'est pas couverte aujourd'hui
    (aucun match trouvé côté bookmakers), ou en cas d'erreur réseau/API (ex: quota
    dépassé) - jamais d'exception remontée à l'appelant.
    """
    if not api_key or not sport_key:
        return []
    try:
        reponse = requests.get(
            f"{ODDS_API_BASE_URL}/sports/{sport_key}/odds",
            params={
                'apiKey': api_key,
                'regions': ODDS_API_REGION,
                'markets': 'h2h',
                'oddsFormat': 'decimal',
            },
            timeout=10,
        )
        reponse.raise_for_status()
        matchs_api = reponse.json()
    except Exception:
        return []

    resultats = []
    for match in matchs_api:
        bookmakers = match.get('bookmakers') or []
        bookmaker_retenu = next(
            (b for b in bookmakers if b.get('key') == ODDS_API_BOOKMAKER_PRINCIPAL),
            bookmakers[0] if bookmakers else None,
        )
        if not bookmaker_retenu:
            continue
        marche_h2h = next(
            (m for m in bookmaker_retenu.get('markets', []) if m.get('key') == 'h2h'), None
        )
        if not marche_h2h or len(marche_h2h.get('outcomes', [])) < 2:
            continue
        cotes_par_equipe = {o.get('name'): o.get('price') for o in marche_h2h['outcomes']}
        resultats.append({
            'equipe_domicile': match.get('home_team'),
            'equipe_exterieur': match.get('away_team'),
            'cote_domicile': cotes_par_equipe.get(match.get('home_team')),
            'cote_exterieur': cotes_par_equipe.get(match.get('away_team')),
            'bookmaker': bookmaker_retenu.get('title') or bookmaker_retenu.get('key'),
        })
    return resultats


def _normaliser_nom_equipe(texte: str) -> str:
    """Normalise un nom d'équipe (minuscules, sans accents) pour une comparaison assouplie."""
    return unicodedata.normalize('NFKD', texte or '').encode('ascii', 'ignore').decode().lower().strip()


def trouver_cote_du_match(cotes_du_jour: list, nom_notre_equipe: str, nom_adversaire: str):
    """
    Retrouve, dans la liste retournée par `obtenir_cotes_moneyline_du_jour`, le match
    correspondant à notre équipe/adversaire du jour, et renvoie la cote de CHAQUE
    équipe ainsi que le bookmaker utilisé. La correspondance se fait par comparaison
    "assouplie" (sous-chaîne, insensible à la casse/accents) plutôt qu'une égalité
    stricte : les noms d'équipe fournis par The-Odds-API (ex: "SSG Landers") ne
    correspondent pas toujours mot pour mot aux noms utilisés ailleurs dans l'app
    (`TEAMS_KBO`).

    Retourne un dict {'cote_nous', 'cote_adverse', 'bookmaker'}, ou None si aucun
    match correspondant n'a été trouvé (KBO non couverte pour ce match précis par
    Winamax/les bookmakers EU, ou marché pas encore ouvert aux paris).
    """
    nous = _normaliser_nom_equipe(nom_notre_equipe)
    adverse = _normaliser_nom_equipe(nom_adversaire)
    if not nous or not adverse:
        return None

    def _correspond(a, b):
        return bool(a) and bool(b) and (a in b or b in a)

    for match in cotes_du_jour:
        dom = _normaliser_nom_equipe(match.get('equipe_domicile'))
        ext = _normaliser_nom_equipe(match.get('equipe_exterieur'))

        if _correspond(nous, dom) and _correspond(adverse, ext):
            return {
                'cote_nous': match.get('cote_domicile'),
                'cote_adverse': match.get('cote_exterieur'),
                'bookmaker': match.get('bookmaker'),
            }
        if _correspond(nous, ext) and _correspond(adverse, dom):
            return {
                'cote_nous': match.get('cote_exterieur'),
                'cote_adverse': match.get('cote_domicile'),
                'bookmaker': match.get('bookmaker'),
            }
    return None


def evaluer_value_bet(proba_algo_pct, cote, nom_equipe: str, nom_bookmaker: str = "Winamax"):
    """
    Compare notre probabilité de victoire estimée (`proba_algo_pct`, calculée par
    `predire_probabilite_victoire`) à la probabilité IMPLICITE de la cote de marché
    (`cote`, au format décimal), pour détecter une éventuelle "Value Bet".

    Probabilité implicite = (1 / cote) * 100.
    Value = Proba_Algo - Proba_Implicite.

    Seuils (identiques pour toutes les ligues - écart de probabilité brut, indépendant
    du profil offensif de la ligue) :
      - Value >= +5 points : le marché sous-évalue cette équipe (badge vert 🟢).
      - Value <= -5 points : le marché la sur-évalue par rapport à notre modèle,
        mieux vaut éviter un pari vainqueur sur cette équipe (badge rouge 🔴).
      - Entre les deux : cote jugée "juste" (badge gris ⚪), pas d'avantage
        mathématique net dans un sens ou l'autre.

    --- IMPORTANT : `nom_bookmaker` ---
    Winamax ne couvre PAS tous les matchs de toutes les ligues (constaté : 0% de
    couverture KBO chez The-Odds-API, contre 100% en MLB). `trouver_cote_du_match`
    retombe alors sur un autre bookmaker EU disponible (voir `ODDS_API_BOOKMAKER_PRINCIPAL`)
    - le message doit donc TOUJOURS citer le bookmaker RÉELLEMENT utilisé (`cotes_match
    ['bookmaker']` côté appelant), jamais "Winamax" en dur, pour ne jamais afficher une
    fausse attribution.

    Retourne un tuple (niveau, message) où niveau vaut 'value', 'juste' ou 'evitez',
    ou (None, None) si la cote n'est pas exploitable (absente ou <= 1.0) ou si la
    probabilité de l'algo est inconnue.
    """
    if not cote or cote <= 1.0 or proba_algo_pct is None:
        return None, None

    proba_implicite = (1.0 / cote) * 100.0
    value = proba_algo_pct - proba_implicite

    if value >= 5:
        return 'value', (
            f"🟢 🔥 Value Bet détectée ! {nom_bookmaker} sous-évalue {nom_equipe} "
            f"(Cote : {cote:.2f}, Value : +{value:.1f}%)."
        )
    if value <= -5:
        return 'evitez', (
            f"🔴 ⛔ Ne pas jouer la Win sur {nom_equipe}. La cote de {nom_bookmaker} "
            f"({cote:.2f}) est trop basse par rapport à nos estimations (Value : {value:.1f}%)."
        )
    return 'juste', (
        f"⚪ ⚖️ Cote juste (Fair Value) sur {nom_equipe} (Cote : {cote:.2f}, {nom_bookmaker}). "
        "Pas d'avantage mathématique majeur."
    )


# ============================================================
# 5 bis. "HOT PRONOSTICS" - Scan GLOBAL de tous les matchs du jour
# ============================================================
# Contrairement aux fonctions ci-dessus (centrées sur UNE équipe sélectionnée dans la
# sidebar), ce bloc analyse TOUS les matchs prévus aujourd'hui (heure de Corée), toutes
# équipes confondues, pour en extraire les meilleurs pronostics HR / Runs / Victoire du
# jour - même principe que le module équivalent de l'app MLB, mais l'API Naver Sports
# (source KBO, voir docstring d'en-tête du fichier) n'offre PAS les deux facilités dont
# dispose MLB StatsAPI, ce qui impose deux adaptations documentées ci-dessous :
#
# 1. PAS d'endpoint "lineups" pré-match : `schedule/games/{id}/record` renvoie
#    `recordData: null` tant qu'un match n'a pas commencé (vérifié empiriquement), alors
#    que MLB StatsAPI publie les lineups officielles 1 à 3h avant le match. En repli, la
#    "lineup probable" du jour est estimée à partir des 9 TITULAIRES (champ `batOrder`
#    1-9, en excluant les entrées `substituteIn`) du DERNIER match TERMINÉ de l'équipe -
#    une estimation raisonnable (les entraîneurs KBO changent rarement l'intégralité de
#    leur ordre de frappe d'un match à l'autre) mais PAS une garantie, clairement
#    annoncée comme telle dans l'interface.
# 2. PAS d'endpoint "lastXGames" agrégé côté frappeurs : la forme récente (SLG/OBP sur les
#    10 derniers matchs) est donc calculée manuellement en additionnant les boxscores des
#    10 derniers matchs TERMINÉS de l'équipe (AB, Hits, HR, BB par joueur - mêmes champs
#    que ceux déjà utilisés par `get_stats_offensives_match` pour l'onglet "Analyse par
#    Équipe", mais ici on a aussi besoin de `batOrder`/`ab`/`bb`, d'où une fonction de
#    récupération de boxscore dédiée `obtenir_boxscore_complet_match`). Cette API ne
#    distingue PAS les doubles/triples des simples au niveau d'un boxscore de match (seul
#    le nombre total de coups sûrs "hit" est renvoyé, sans détail par type - contrairement
#    aux statistiques de SAISON qui, elles, exposent `hitterH2`/`hitterH3`) : le SLG récent
#    est donc une ESTIMATION (bases totales ≈ hits + 3×HR, c.-à-d. tout coup sûr non-HR est
#    traité comme un simple), documentée comme telle dans les libellés de colonnes et la
#    méthodologie affichée sous les tableaux - PAS le vrai SLG (qui compterait les doubles
#    à 2 et les triples à 3).

def _estimer_slg_recent(ab: int, hit: int, hr: int) -> float:
    """
    Estime le SLG (slugging percentage) sur une fenêtre de matchs à partir de AB/Hits/HR
    seuls (sans détail doubles/triples, non disponible match par match dans l'API Naver
    Sports - voir le commentaire de section ci-dessus). Hypothèse simplificatrice : tout
    coup sûr qui n'est pas un HR est traité comme un simple (1 base), un HR valant 4 bases
    (soit +3 bases par rapport au 1 déjà compté dans `hit`) -> bases totales ≈ hit + 3*hr.
    Sous-estime légèrement le vrai SLG dès qu'un joueur a frappé des doubles/triples
    récents, mais reste un indicateur cohérent pour un CLASSEMENT relatif entre joueurs.
    """
    if not ab:
        return 0.0
    bases_totales_estimees = hit + 3 * hr
    return bases_totales_estimees / ab


def _estimer_obp_recent(ab: int, hit: int, bb: int) -> float:
    """
    Estime l'OBP (on-base percentage) sur une fenêtre de matchs à partir de AB/Hits/BB
    seuls. L'API Naver Sports ne fournit pas le nombre de "hit by pitch" (HBP) ni de
    sacrifice flies (SF) au niveau d'un boxscore de match, contrairement à la formule
    officielle OBP = (H+BB+HBP)/(AB+BB+HBP+SF) : l'approximation retenue ici,
    (H+BB)/(AB+BB), ignore ces deux termes généralement marginaux (un joueur atteint très
    rarement la base sur HBP, et un SF ne compte de toute façon pas comme un at-bat).
    """
    denominateur = ab + bb
    if not denominateur:
        return 0.0
    return (hit + bb) / denominateur


@st.cache_data(show_spinner=False, ttl=1800)
def obtenir_moyennes_runs_10_toutes_equipes(annee: int) -> dict:
    """
    Calcule, pour CHACUNE des 10 équipes KBO, la moyenne de runs marqués sur ses 10
    derniers matchs TERMINÉS, en réutilisant directement `charger_donnees_equipe` (déjà
    mis en cache par équipe) - donc SANS appel réseau supplémentaire au-delà des
    calendriers mensuels déjà partagés entre toutes les équipes via `charger_calendrier_
    mensuel`. Retourne un dict {code_equipe: moyenne_runs} (une équipe sans historique
    suffisant cette saison est simplement absente du dict).
    """
    moyennes = {}
    for code_equipe in TEAMS_KBO:
        df_equipe = charger_donnees_equipe(annee, code_equipe)
        if df_equipe.empty or 'R' not in df_equipe.columns:
            continue
        dix_derniers = df_equipe.tail(10)
        moyenne = pd.to_numeric(dix_derniers['R'], errors='coerce').mean()
        if pd.notna(moyenne):
            moyennes[code_equipe] = moyenne
    return moyennes


@st.cache_data(show_spinner=False, ttl=1800)
def obtenir_boxscore_complet_match(game_id: str, est_domicile: bool) -> list:
    """
    Récupère le boxscore batteur-par-batteur COMPLET (pas seulement runs/HR comme
    `get_stats_offensives_match`, utilisée par l'onglet "Analyse par Équipe") d'un match
    terminé, avec en plus les champs `batOrder` (position dans l'ordre de passage, 1-9
    pour un titulaire), `ab`/`bb` (nécessaires pour estimer OBP/SLG récents) et
    `est_titulaire` (True si le joueur a débuté le match dans cet ordre de frappe, False
    s'il s'agit d'un remplaçant entré en cours de match, càd `substituteIn` = True côté
    API). Fonction séparée et mise en cache indépendamment de `get_stats_offensives_match`
    (même endpoint, champs différents) pour ne prendre aucun risque de régression sur
    l'onglet "Analyse par Équipe" existant.
    """
    if not game_id:
        return []
    url = f"{BASE_NAVER}/schedule/games/{game_id}/record"
    try:
        data = appeler_avec_retry(_get_json, url)
    except Exception:
        return []

    record_data = (data.get('result', {}) or {}).get('recordData', {}) or {}
    if not record_data:
        return []
    batters_boxscore = record_data.get('battersBoxscore', {}) or {}
    liste_joueurs = batters_boxscore.get('home' if est_domicile else 'away', []) or []

    resultats = []
    for j in liste_joueurs:
        player_code = str(j.get('playerCode') or '')
        if not player_code:
            continue
        bat_order = j.get('batOrder')
        resultats.append({
            'playerCode': player_code,
            'nom_hangul': j.get('name') or '',
            'batOrder': bat_order if isinstance(bat_order, int) else None,
            'est_titulaire': not bool(j.get('substituteIn')),
            'ab': int(j.get('ab') or 0),
            'hit': int(j.get('hit') or 0),
            'hr': int(j.get('hr') or 0),
            'bb': int(j.get('bb') or 0),
        })
    return resultats


@st.cache_data(show_spinner=False, ttl=1800)
def obtenir_lineup_probable_et_forme_recente(annee: int, code_equipe: str) -> dict:
    """
    Pour une équipe donnée, construit :
      1. une estimation de sa lineup PROBABLE du jour (voir limitation documentée en tête
         de section 5 bis) = les 9 titulaires (`batOrder` 1-9) du match TERMINÉ le plus
         RÉCENT parmi les 10 derniers de l'équipe (avec repli sur le match précédent si le
         boxscore du plus récent est temporairement indisponible - dégradation gracieuse
         plutôt qu'une lineup vide) ;
      2. leur forme offensive CUMULÉE (AB, Hits, HR, BB) sur ces mêmes 10 derniers matchs,
         utilisée ensuite pour estimer leur SLG/OBP récents (`_estimer_slg_recent` /
         `_estimer_obp_recent`).

    Retourne un dict {playerCode: {'nom_hangul', 'position_probable', 'ab_10', 'hit_10',
    'hr_10', 'bb_10'}}, restreint aux 9 joueurs de la lineup probable identifiée (un
    banc/bullpen entier n'a pas d'intérêt ici, seuls les titulaires probables comptent).
    Dict vide si l'équipe n'a aucun historique exploitable cette saison.
    """
    df_equipe = charger_donnees_equipe(annee, code_equipe)
    if df_equipe.empty or 'game_id' not in df_equipe.columns:
        return {}

    dix_derniers = df_equipe.tail(10)
    if dix_derniers.empty:
        return {}

    cumul_par_joueur = {}   # playerCode -> {'nom_hangul', 'ab', 'hit', 'hr', 'bb'}
    boxscores_par_match = []  # dans l'ordre chronologique (le dernier élément = match le + récent)

    for _, ligne in dix_derniers.iterrows():
        boxscore = obtenir_boxscore_complet_match(ligne['game_id'], bool(ligne['Est_Domicile']))
        boxscores_par_match.append(boxscore)
        for j in boxscore:
            entree = cumul_par_joueur.setdefault(
                j['playerCode'], {'nom_hangul': j['nom_hangul'], 'ab': 0, 'hit': 0, 'hr': 0, 'bb': 0}
            )
            entree['ab'] += j['ab']
            entree['hit'] += j['hit']
            entree['hr'] += j['hr']
            entree['bb'] += j['bb']

    # Lineup probable = titulaires du match le plus RÉCENT parmi les 10 pour lequel le
    # boxscore a pu être récupéré avec succès (on parcourt à l'envers, du plus récent au
    # plus ancien, et on s'arrête au premier match exploitable).
    lineup_probable = {}
    for boxscore in reversed(boxscores_par_match):
        candidate = {
            j['playerCode']: j['batOrder']
            for j in boxscore
            if j['est_titulaire'] and j['batOrder'] is not None and 1 <= j['batOrder'] <= 9
        }
        if candidate:
            lineup_probable = candidate
            break

    resultats = {}
    for player_code, position in lineup_probable.items():
        stats = cumul_par_joueur.get(player_code)
        if not stats:
            continue
        resultats[player_code] = {
            'nom_hangul': stats['nom_hangul'],
            'position_probable': position,
            'ab_10': stats['ab'],
            'hit_10': stats['hit'],
            'hr_10': stats['hr'],
            'bb_10': stats['bb'],
        }
    return resultats


def _normaliser_colonne_hp(serie: pd.Series) -> pd.Series:
    """
    Normalisation min-max dans [0, 1] d'une colonne de statistiques, pour pouvoir
    combiner des métriques d'échelles très différentes (ex: SLG ~0.3-0.6, HR sur 10
    matchs 0-6, ERA 2-6) dans un même indice pondéré. Renvoie une série neutre à 0.5
    si la colonne est constante (évite une division par zéro sans fausser le classement).
    Suffixe "_hp" ("Hot Pronostics") pour éviter toute collision de nom si une fonction
    de normalisation similaire existait déjà ailleurs dans le fichier.
    """
    minimum, maximum = serie.min(), serie.max()
    if pd.isna(minimum) or pd.isna(maximum) or maximum == minimum:
        return pd.Series([0.5] * len(serie), index=serie.index)
    return (serie - minimum) / (maximum - minimum)


def _calculer_top5_home_runs_kbo(candidats: list) -> pd.DataFrame:
    """
    Construit le classement "Top 5 Home Runs probables" à partir de la liste de candidats
    (un dict par titulaire probable d'un match du jour). Indice pondéré : SLG récent
    estimé 45% + HR/10 derniers matchs 35% + HR/9 du lanceur adverse 20% (les 3 facteurs
    demandés), chaque métrique étant normalisée (min-max) sur l'ensemble des candidats du
    jour avant pondération.
    """
    if not candidats:
        return pd.DataFrame()
    df = pd.DataFrame(candidats)
    indice = (
        _normaliser_colonne_hp(df['SLG récent (estimé)']) * 0.45
        + _normaliser_colonne_hp(df['HR (10 derniers matchs)']) * 0.35
        + _normaliser_colonne_hp(df['HR/9 lanceur adverse']) * 0.20
    ) * 100
    df['Indice HR (/100)'] = indice.round(1)
    df = df.sort_values('Indice HR (/100)', ascending=False).head(5).reset_index(drop=True)
    return df[[
        'Joueur', 'Équipe', 'Adversaire', 'Lanceur adverse',
        'SLG récent (estimé)', 'HR (10 derniers matchs)', 'HR/9 lanceur adverse', 'Indice HR (/100)'
    ]]


def _calculer_top5_runs_kbo(candidats: list) -> pd.DataFrame:
    """
    Construit le classement "Top 5 joueurs pour marquer un run" à partir de la liste de
    candidats. Indice pondéré : OBP récent estimé 45% + bonus de position dans la lineup
    probable (favorise les positions 1 à 4) 25% + ERA du lanceur adverse 30%, chaque
    métrique étant normalisée (min-max) sur l'ensemble des candidats du jour.
    """
    if not candidats:
        return pd.DataFrame()
    df = pd.DataFrame(candidats)
    # Bonus de position : décroît linéairement de la place 1 (bonus max) à la place 9
    # (bonus nul), pour "privilégier les batteurs 1 à 4" tout en restant continu.
    bonus_position = (9 - df['Position probable']).clip(lower=0)
    indice = (
        _normaliser_colonne_hp(df['OBP récent (estimé)']) * 0.45
        + _normaliser_colonne_hp(bonus_position) * 0.25
        + _normaliser_colonne_hp(df['ERA lanceur adverse']) * 0.30
    ) * 100
    df['Indice Run (/100)'] = indice.round(1)
    df = df.sort_values('Indice Run (/100)', ascending=False).head(5).reset_index(drop=True)
    return df[[
        'Joueur', 'Équipe', 'Adversaire', 'Lanceur adverse',
        'OBP récent (estimé)', 'Position probable', 'ERA lanceur adverse', 'Indice Run (/100)'
    ]]


def _total_runs_predit_kbo(moyenne_home, moyenne_away):
    """
    Somme des moyennes de runs (10 derniers matchs) des deux équipes d'un match : sert de
    projection du total de runs, utilisée par le bilan Over/Under de la veille
    (`_bilan_over_under_kbo`). Retourne None si l'une des deux moyennes est indisponible
    (équipe sans historique suffisant cette saison).
    """
    if moyenne_home is None or moyenne_away is None or pd.isna(moyenne_home) or pd.isna(moyenne_away):
        return None
    return float(moyenne_home) + float(moyenne_away)


def _top_candidats_hr_kbo(lineup_equipe: dict, dict_noms_anglais: dict, n: int = 2) -> list:
    """
    Les `n` joueurs de la lineup probable d'une équipe les plus en forme au HR (10
    derniers matchs, même filtre "au moins 5 AB cumulés" que `construire_donnees_hot_
    pronostics_kbo`, pour écarter le bruit d'un joueur tout juste rappelé). Archivés
    dans l'instantané du jour (historique des prédictions) pour d'éventuelles
    analyses ultérieures.
    """
    if not lineup_equipe:
        return []
    candidats = [
        (
            dict_noms_anglais.get(player_code) or nom_hangul_vers_romanisation(infos['nom_hangul']),
            infos['hr_10'],
        )
        for player_code, infos in lineup_equipe.items()
        if infos.get('ab_10', 0) >= 5
    ]
    candidats.sort(key=lambda x: x[1], reverse=True)
    return [nom for nom, _ in candidats[:n]]


@st.cache_data(show_spinner=False, ttl=1800)
def construire_donnees_hot_pronostics_kbo(annee: int):
    """
    Calcul GLOBAL et coûteux (mis en cache via @st.cache_data, ttl=30min) qui scanne TOUS
    les matchs KBO du jour (heure de Corée) et construit les 3 tableaux de l'onglet
    "Hot Pronostics" : Top 5 Home Runs, Top 5 joueurs pour marquer un run, et le
    récapitulatif Win/Lose de chaque confrontation. Ce calcul est indépendant de l'équipe
    sélectionnée dans la sidebar, donc mis en cache séparément (clé = `annee` uniquement)
    pour ne jamais être relancé inutilement quand l'utilisateur change d'équipe.

    Retourne (matchs_du_jour, df_top5_hr, df_top5_runs, df_victoires).
    """
    if annee != ANNEE_COURANTE:
        return [], pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    df_jour, maintenant_kst = obtenir_calendrier_du_jour_kst()
    if df_jour.empty:
        return [], pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    effectifs = _charger_effectifs_saison(annee)
    dict_noms_anglais = _dict_noms_anglais(annee)
    moyennes_runs_equipes = obtenir_moyennes_runs_10_toutes_equipes(annee)

    matchs_du_jour = []
    codes_du_jour = set()
    for _, g in df_jour.iterrows():
        code_home, code_away = g.get('code_home'), g.get('code_away')
        if not code_home or not code_away:
            continue  # code d'équipe non résolu (cas très rare, voir NOM_EQUIPE_VERS_CODE) -> match ignoré
        codes_du_jour.update([code_home, code_away])

        heure_kst_str, heure_paris_str = "—", "—"
        game_datetime_str = g.get('game_datetime')
        if game_datetime_str:
            try:
                dt_kst = datetime.fromisoformat(game_datetime_str).replace(tzinfo=TZ_SEOUL)
                heure_kst_str = dt_kst.strftime('%H:%M')
                heure_paris_str = dt_kst.astimezone(TZ_PARIS).strftime('%d/%m à %H:%M')
            except Exception:
                pass

        matchs_du_jour.append({
            'game_id': g.get('game_id'),
            'code_home': code_home,
            'code_away': code_away,
            'nom_home': TEAMS_KBO.get(code_home, g.get('nom_home')),
            'nom_away': TEAMS_KBO.get(code_away, g.get('nom_away')),
            'lanceur_home_hangul': (g.get('lanceur_annonce_home') or '').strip(),
            'lanceur_away_hangul': (g.get('lanceur_annonce_away') or '').strip(),
            'stade': traduire_stade(g.get('stade')),
            'heure_kst': heure_kst_str,
            'heure_paris': heure_paris_str,
            'statut': g.get('statusCode'),
        })

    if not matchs_du_jour:
        return [], pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    # Une seule estimation de lineup probable + forme récente par équipe présente
    # aujourd'hui (pas par match), même si une équipe jouait deux fois le même jour.
    lineups_par_equipe = {
        code: obtenir_lineup_probable_et_forme_recente(annee, code) for code in codes_du_jour
    }

    candidats_hr = []
    candidats_runs = []
    lignes_victoire = []

    for m in matchs_du_jour:
        stats_p_home = (
            obtenir_infos_lanceur(m['lanceur_home_hangul'], m['code_home'], effectifs)
            if m['lanceur_home_hangul'] else None
        )
        stats_p_away = (
            obtenir_infos_lanceur(m['lanceur_away_hangul'], m['code_away'], effectifs)
            if m['lanceur_away_hangul'] else None
        )

        # --- Tableau Win/Lose : on réutilise TEL QUEL le modèle heuristique déjà validé
        # dans l'onglet "Prédictions du jour" (`predire_probabilite_victoire`), avec les
        # vraies moyennes de runs des DEUX équipes (au lieu du proxy "runs concédés par
        # notre équipe" utilisé côté mono-équipe, où l'attaque adverse n'est pas
        # directement disponible sans recharger un second historique).
        pct_home, pct_away = predire_probabilite_victoire(
            moyennes_runs_equipes.get(m['code_home']),
            moyennes_runs_equipes.get(m['code_away']),
            stats_p_home,
            stats_p_away,
            est_domicile=True,
        )
        nom_lanceur_home_aff = (
            stats_p_home['nom'] if stats_p_home
            else (nom_hangul_vers_romanisation(m['lanceur_home_hangul']) if m['lanceur_home_hangul'] else 'Non annoncé')
        )
        nom_lanceur_away_aff = (
            stats_p_away['nom'] if stats_p_away
            else (nom_hangul_vers_romanisation(m['lanceur_away_hangul']) if m['lanceur_away_hangul'] else 'Non annoncé')
        )
        lignes_victoire.append({
            'Heure (France)': m['heure_paris'],
            'Équipe Domicile': m['nom_home'],
            'Lanceur Domicile': nom_lanceur_home_aff,
            'Équipe Extérieur': m['nom_away'],
            'Lanceur Extérieur': nom_lanceur_away_aff,
            'Proba Domicile (%)': pct_home,
            'Proba Extérieur (%)': pct_away,
        })

        # --- Candidats HR / Runs : chaque lineup probable est croisée avec le lanceur
        # partant ADVERSE (celui qu'elle affrontera aujourd'hui). On exige au moins 5 AB
        # cumulés sur les 10 derniers matchs pour filtrer le bruit d'un joueur tout juste
        # rappelé (échantillon trop faible pour un OBP/SLG récent significatif).
        for code_equipe, nom_equipe, nom_adverse, stats_lanceur_adverse in (
            (m['code_home'], m['nom_home'], m['nom_away'], stats_p_away),
            (m['code_away'], m['nom_away'], m['nom_home'], stats_p_home),
        ):
            nom_lanceur_adverse_aff = stats_lanceur_adverse['nom'] if stats_lanceur_adverse else 'Non annoncé'
            hr_par_9_adverse = (
                stats_lanceur_adverse['hr_par_9']
                if stats_lanceur_adverse and stats_lanceur_adverse.get('hr_par_9') else 1.0
            )
            era_adverse = (
                stats_lanceur_adverse['era']
                if stats_lanceur_adverse and stats_lanceur_adverse.get('era') else 4.5
            )

            for player_code, infos in lineups_par_equipe.get(code_equipe, {}).items():
                if infos['ab_10'] < 5:
                    continue
                nom_anglais = dict_noms_anglais.get(player_code)
                nom_affiche = nom_anglais if nom_anglais else nom_hangul_vers_romanisation(infos['nom_hangul'])

                candidats_hr.append({
                    'Joueur': nom_affiche,
                    'Équipe': nom_equipe,
                    'Adversaire': nom_adverse,
                    'Lanceur adverse': nom_lanceur_adverse_aff,
                    'SLG récent (estimé)': round(_estimer_slg_recent(infos['ab_10'], infos['hit_10'], infos['hr_10']), 3),
                    'HR (10 derniers matchs)': infos['hr_10'],
                    'HR/9 lanceur adverse': round(hr_par_9_adverse, 2),
                })
                candidats_runs.append({
                    'Joueur': nom_affiche,
                    'Équipe': nom_equipe,
                    'Adversaire': nom_adverse,
                    'Lanceur adverse': nom_lanceur_adverse_aff,
                    'OBP récent (estimé)': round(_estimer_obp_recent(infos['ab_10'], infos['hit_10'], infos['bb_10']), 3),
                    'Position probable': infos['position_probable'],
                    'ERA lanceur adverse': round(era_adverse, 2),
                })

    df_top5_hr = _calculer_top5_home_runs_kbo(candidats_hr)
    df_top5_runs = _calculer_top5_runs_kbo(candidats_runs)
    df_victoires = pd.DataFrame(lignes_victoire)

    # --- Archivage de l'instantané du jour (pour le "Bilan des Prédictions" de la veille,
    # onglet Résumé, cf. `_sauvegarder_predictions_du_jour`) : on ne conserve que ce qui
    # est nécessaire à une comparaison ultérieure avec le résultat réel une fois le match
    # terminé (probabilité de victoire, total de runs projeté pour les deux équipes, et
    # candidats HR les plus en forme de chaque équipe).
    matches_snapshot = [
        {
            'game_id': m.get('game_id'),
            'code_home': m['code_home'],
            'code_away': m['code_away'],
            'home_name': m['nom_home'],
            'away_name': m['nom_away'],
            'proba_home': ligne_victoire.get('Proba Domicile (%)'),
            'proba_away': ligne_victoire.get('Proba Extérieur (%)'),
            'total_runs_predit': _total_runs_predit_kbo(
                moyennes_runs_equipes.get(m['code_home']), moyennes_runs_equipes.get(m['code_away'])
            ),
            'candidats_hr_home': _top_candidats_hr_kbo(lineups_par_equipe.get(m['code_home'], {}), dict_noms_anglais),
            'candidats_hr_away': _top_candidats_hr_kbo(lineups_par_equipe.get(m['code_away'], {}), dict_noms_anglais),
        }
        for m, ligne_victoire in zip(matchs_du_jour, lignes_victoire)
    ]
    _sauvegarder_predictions_du_jour(maintenant_kst.strftime('%Y-%m-%d'), matches_snapshot)

    return matchs_du_jour, df_top5_hr, df_top5_runs, df_victoires


# ============================================================
# 5 ter. ONGLET "RÉSUMÉ" - Scores en direct et terminés du jour
# ============================================================
# Ce bloc alimente le tout premier onglet de l'application : un tableau récapitulatif de
# TOUS les matchs KBO du jour (à venir / en cours / terminés), avec un bouton de
# rafraîchissement manuel qui ne recharge QUE cet onglet (via `st.fragment`), pas toute la
# page. Il réutilise le modèle de prédiction déjà calculé pour "Hot Pronostics"
# (`construire_donnees_hot_pronostics_kbo`) pour la colonne "Comparatif Prédiction", au lieu
# de dupliquer le calcul de probabilité de victoire. Adaptation à l'identique de l'onglet
# "Résumé" de l'app MLB (qui s'appuie sur statsapi), ici branchée sur l'API interne Naver
# Sports (voir docstring d'en-tête du fichier).

def _ordinal_anglais(n) -> str:
    """Formate un entier en ordinal anglais (1 -> '1st', 4 -> '4th', 11 -> '11th', ...)."""
    n = int(n)
    if 10 <= (n % 100) <= 20:
        suffixe = 'th'
    else:
        suffixe = {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')
    return f"{n}{suffixe}"


def _formater_statut_match_kbo(g) -> str:
    """
    Traduit les champs bruts Naver Sports ('statusCode', 'statusInfo', 'suspended') en
    l'une des catégories demandées : 'À venir', 'En cours (Top 4th)' ou 'Terminé' - avec un
    repli explicite pour les statuts rares (suspendu) plutôt que de les faire tomber
    silencieusement dans une mauvaise catégorie.

    'statusCode' vaut 'BEFORE' (avant match), 'STARTED' (en direct) ou 'RESULT' (terminé) -
    valeurs vérifiées empiriquement sur l'API réelle (voir aussi le projet open-source
    hanwha-score, qui compare exactement ces trois chaînes). Les matchs annulés ('cancel')
    sont déjà exclus en amont par `charger_calendrier_mensuel`, donc ce cas n'a normalement
    pas besoin d'être géré ici, mais le repli 'À venir' reste sûr si jamais un tel match
    apparaissait malgré tout.

    Quand le match est en direct, 'statusInfo' contient l'inning courant en coréen (ex:
    '5회말' = demi-manche du bas de la 5e) : on le reformate en 'Top'/'Bot' + ordinal anglais,
    par symétrie avec le format utilisé côté MLB ('Bot 4th').
    """
    if g.get('suspended'):
        return "Suspendu"

    status_code = str(g.get('statusCode') or '').strip().upper()

    if status_code == 'RESULT':
        return "Terminé"

    if status_code == 'STARTED':
        info = str(g.get('statusInfo') or '').strip()
        m = re.match(r'^(\d+)\s*회\s*(초|말)', info)
        if m:
            manche_str = _ordinal_anglais(m.group(1))
            demi = "Top" if m.group(2) == '초' else "Bot"
            return f"En cours ({demi} {manche_str})"
        return "En cours"

    return "À venir"  # 'BEFORE', ou tout statut inconnu


@st.cache_data(show_spinner=False, ttl=3600, max_entries=200)
def obtenir_scoreurs_runs_et_hr_match_resume(game_id: str, est_domicile: bool,
                                              dict_noms_anglais: dict = None, cache_bust: int = 0):
    """
    Récupère, via UN SEUL appel au boxscore Naver Sports d'un match (endpoint "/record"),
    les runs ET les home runs marqués par chaque joueur d'une équipe. Retourne
    (liste_runs, liste_hr) de tuples (nom_joueur, nb). Dédiée à l'onglet "Résumé" /
    bilan de la veille : `cache_bust` invalide le cache à la demande.
    """
    if not game_id:
        return [], []
    dict_noms_anglais = dict_noms_anglais or {}

    url = f"{BASE_NAVER}/schedule/games/{game_id}/record"
    try:
        data = appeler_avec_retry(_get_json, url)
        record_data = (data.get('result', {}) or {}).get('recordData', {}) or {}
        batters_boxscore = record_data.get('battersBoxscore', {}) or {}
        liste_joueurs = batters_boxscore.get('home' if est_domicile else 'away', []) or []

        runs_par_joueur = {}
        hr_par_joueur = {}
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
            if runs > 0:
                runs_par_joueur[nom_final] = runs_par_joueur.get(nom_final, 0) + runs
            if hr > 0:
                hr_par_joueur[nom_final] = hr_par_joueur.get(nom_final, 0) + hr
        return list(runs_par_joueur.items()), list(hr_par_joueur.items())
    except Exception:
        return [], []


def obtenir_hr_joueurs_match_resume(game_id: str, est_domicile: bool, dict_noms_anglais: dict = None, cache_bust: int = 0):
    """
    Compatibilité : retourne uniquement les home runs (liste de tuples (nom, nb_hr))
    d'une équipe pour UN match. Délègue à `obtenir_scoreurs_runs_et_hr_match_resume`.
    """
    _, hrs = obtenir_scoreurs_runs_et_hr_match_resume(
        game_id, est_domicile, dict_noms_anglais, cache_bust
    )
    return hrs


def _formater_segment_scoreurs(abbr: str, scoreurs: list) -> str:
    """Formate les scoreurs d'UNE équipe : 'LG: 2 (Kim, Austin)' ou 'LG: 0' si aucun."""
    total = sum(nb for _, nb in scoreurs)
    if total <= 0:
        return f"{abbr}: 0"
    noms = [nom if nb <= 1 else f"{nom} x{nb}" for nom, nb in scoreurs]
    return f"{abbr}: {total} ({', '.join(noms)})"


def _formater_cellule_hr(away_abbr: str, hr_away: list, home_abbr: str, hr_home: list) -> str:
    """Combine les HR des deux équipes d'un match dans une seule cellule de tableau."""
    return (
        f"{_formater_segment_scoreurs(away_abbr, hr_away)} | "
        f"{_formater_segment_scoreurs(home_abbr, hr_home)}"
    )


def _formater_cellule_total_runs(total: int, away_abbr: str, runs_away: list,
                                 home_abbr: str, runs_home: list) -> str:
    """
    Colonne "Total Runs" du bilan de la veille : total du match + détail des joueurs
    ayant marqué un run. Ex: '11 — LG: 6 (Kim, Austin) | KT: 5 (Rojas)'
    """
    detail = (
        f"{_formater_segment_scoreurs(away_abbr, runs_away)} | "
        f"{_formater_segment_scoreurs(home_abbr, runs_home)}"
    )
    return f"{total} — {detail}"


def _trouver_prediction_match_kbo(predictions_par_cle: dict, cle):
    """Tolère int vs str pour les game_id après sérialisation JSON de l'historique."""
    if cle in predictions_par_cle:
        return predictions_par_cle[cle]
    if cle is None:
        return None
    try:
        return predictions_par_cle.get(int(cle)) or predictions_par_cle.get(str(cle))
    except (TypeError, ValueError):
        return predictions_par_cle.get(str(cle))


def _comparer_prediction_vs_score(pred, home_nom: str, away_nom: str, home_score: int, away_score: int, a_commence: bool):
    """
    Retourne (texte_comparatif, icone_resultat) pour la colonne "Résultat vs Algo".
    - `pred` : ligne (pandas Series) issue de `df_victoires` (Hot Pronostics) pour ce match,
      ou None si aucune prédiction n'est encore disponible (lanceurs partants pas encore
      annoncés) -> ("Non disponible", "⏳").
    - Sinon : l'équipe favorite est celle avec la probabilité de victoire la plus haute. On
      compare cette équipe favorite à l'équipe actuellement en tête (ou gagnante si le match
      est terminé) : ✅ si elle mène/a gagné, ❌ si elle est menée/a perdu, ⏳ si le match n'a
      pas commencé ou si le score est à égalité.
    """
    if pred is None:
        return "Non disponible", "⏳"

    pct_home = pred.get('Proba Domicile (%)')
    pct_away = pred.get('Proba Extérieur (%)')
    if pct_home is None or pct_away is None or pd.isna(pct_home) or pd.isna(pct_away):
        return "Non disponible", "⏳"

    equipe_favorite = home_nom if pct_home >= pct_away else away_nom
    pct_favori = max(pct_home, pct_away)
    comparatif = f"{equipe_favorite} à {pct_favori:.0f}%"

    if not a_commence or home_score == away_score:
        return comparatif, "⏳"

    equipe_en_tete = home_nom if home_score > away_score else away_nom
    icone = "✅" if equipe_en_tete == equipe_favorite else "❌"
    return comparatif, icone


# ------------------------------------------------------------------------------
# BILAN DES PRÉDICTIONS DE LA VEILLE (menu déroulant en tête de l'onglet "Résumé")
# ------------------------------------------------------------------------------
# L'API Naver Sports ne publie aucune ligne de paris officielle (contrairement aux sites
# de paris sportifs) : à défaut, la "ligne" Over/Under utilisée ci-dessous pour qualifier
# un match de "à forte marque" (Over) ou "à faible marque" (Under) est la moyenne réelle
# de runs cumulés (les deux équipes confondues) sur tous les matchs déjà joués cette
# saison - la référence la plus neutre et la plus objective disponible sans source de
# paris tierce. Portage à l'identique de la fonctionnalité équivalente de NPB_Stats_App
# (voir son en-tête de section pour le détail des choix), adapté au fuseau horaire coréen
# (KST) et à l'API Naver Sports (un `game_id` explicite est disponible ici pour apparier
# sans ambiguïté chaque match à sa prédiction archivée, contrairement à npb.jp où seule
# la paire (code_home, code_away) fait office d'identifiant).
@st.cache_data(show_spinner=False, ttl=3600)
def obtenir_ligne_over_under_saison_kbo(annee: int) -> float:
    """
    Moyenne de runs totaux (2 équipes cumulées) sur tous les matchs KBO déjà joués cette
    saison, tous mois confondus - sert de ligne de référence Over/Under pour le bilan des
    prédictions de la veille. Repli à 9.0 (ordre de grandeur usuel en KBO) si aucune
    donnée n'est encore disponible (tout début de saison).
    """
    totaux = []
    for mois in MOIS_SAISON:
        try:
            df_mois = charger_calendrier_mensuel(annee, mois)
        except Exception:
            continue
        if df_mois.empty:
            continue
        df_valides = df_mois.dropna(subset=['score_home', 'score_away'])
        if df_valides.empty:
            continue
        totaux.extend((df_valides['score_home'] + df_valides['score_away']).tolist())

    if not totaux:
        return 9.0
    return round(sum(totaux) / len(totaux), 2)


def _formater_vainqueur_kbo(nom_home: str, nom_away: str, home_score: int, away_score: int) -> str:
    """Nom de l'équipe gagnante, ou 'Match nul' (règle du plafond de manches supplémentaires KBO)."""
    if home_score == away_score:
        return "Match nul"
    return nom_home if home_score > away_score else nom_away


def _bilan_victoire_kbo(proba_home, proba_away, nom_home: str, nom_away: str, home_score: int, away_score: int):
    """Retourne (texte, icône) comparant l'équipe favorite annoncée hier à la gagnante réelle."""
    if proba_home is None or proba_away is None or pd.isna(proba_home) or pd.isna(proba_away):
        return "Prédiction non disponible", "⏳"
    if home_score == away_score:
        return "Match nul (pas de favori confirmé)", "⏳"
    favori = nom_home if proba_home >= proba_away else nom_away
    pct_favori = max(proba_home, proba_away)
    gagnant = nom_home if home_score > away_score else nom_away
    icone = "✅" if favori == gagnant else "❌"
    return f"{favori} favori à {pct_favori:.0f}% → vainqueur : {gagnant}", icone


def _bilan_over_under_kbo(total_runs_predit, total_runs_reel: int, ligne: float):
    """Retourne (texte, icône) comparant la projection Over/Under d'hier au total réel."""
    if total_runs_predit is None:
        return "Prédiction non disponible", "⏳"

    def _direction(total):
        if total > ligne:
            return "Over"
        if total < ligne:
            return "Under"
        return "Push"

    direction_predite = _direction(total_runs_predit)
    direction_reelle = _direction(total_runs_reel)
    if direction_reelle == "Push":
        icone = "⏳"
    else:
        icone = "✅" if direction_predite == direction_reelle else "❌"
    return (
        f"{direction_predite} annoncé (projection {total_runs_predit:.1f}, ligne {ligne:.1f}) "
        f"→ réel {total_runs_reel} ({direction_reelle})"
    ), icone


def formater_recommandation_totaux_over_under(total_projete, ligne):
    """
    Affichage UNIQUEMENT (aucune modification du moteur de prédiction) :
    compare le total de runs DÉJÀ projeté par l'algo (`prediction_runs['total_match']`,
    soit Runs équipe + proxy adverse) à la ligne Over/Under de référence
    (`obtenir_ligne_over_under_saison_kbo`, même cut-off que le bilan de la veille).

    - écart > 1 run au-dessus de la ligne → Over
    - écart > 1 run en dessous de la ligne → Under
    - |écart| ≤ 1 → No Bet (marge trop faible)
    """
    if total_projete is None or ligne is None:
        return None
    try:
        total = float(total_projete)
        cut = float(ligne)
    except (TypeError, ValueError):
        return None
    if pd.isna(total) or pd.isna(cut):
        return None

    ecart = total - cut
    if abs(ecart) <= 1:
        return (
            f"⚠️ **Recommandation Totaux : NO BET sur les runs** "
            f"(Projection : {total:.1f} | Ligne : {cut:.1f} - marge trop faible)."
        )
    if ecart > 1:
        return (
            f"📊 **Recommandation Totaux : Jouer l'OVER** "
            f"(Projection : {total:.1f} | Ligne : {cut:.1f})."
        )
    return (
        f"📊 **Recommandation Totaux : Jouer l'UNDER** "
        f"(Projection : {total:.1f} | Ligne : {cut:.1f})."
    )


@st.cache_data(show_spinner=False, ttl=3600)
def construire_bilan_veille_kbo(annee: int):
    """
    Construit le tableau "Résultats de la veille et Bilan des Prédictions" : reprend la
    structure du tableau des matchs du jour (`construire_resume_matchs_du_jour_kbo`),
    mais pour la date d'HIER (heure de Corée) et avec les matchs forcément terminés,
    enrichi de colonnes de bilan comparant la prédiction sauvegardée hier
    (`_sauvegarder_predictions_du_jour`, appelée automatiquement depuis
    `construire_donnees_hot_pronostics_kbo`) au résultat réel.

    Comme cette fonction n'est appelée QUE lorsque l'utilisateur ouvre le menu déroulant
    (cf. `afficher_bilan_predictions_veille_kbo`), elle n'a aucun coût au chargement
    initial de l'onglet "Résumé".

    Retourne (DataFrame, message_erreur, predictions_disponibles) :
      - `predictions_disponibles` (bool) indique si UN AU MOINS instantané de prédictions
        a été retrouvé pour la date d'hier - utilisé par `afficher_bilan_predictions_
        veille_kbo` pour distinguer "aucune prédiction n'a jamais été archivée pour cette
        date" (cas normal les tout premiers jours après l'ajout de cette fonctionnalité,
        ou si l'app n'a pas été ouverte la veille) du cas où le tableau est simplement
        vide pour une autre raison.
    Sur le même modèle que `construire_resume_matchs_du_jour_kbo`, aucune exception n'est
    jamais remontée à l'appelant.
    """
    hier_kst = datetime.now(TZ_SEOUL) - timedelta(days=1)
    date_hier_str = hier_kst.strftime('%Y-%m-%d')

    if hier_kst.month not in MOIS_SAISON:
        return pd.DataFrame(), None, True  # hors saison (déc./janv./fév.) : pas de match hier

    try:
        df_mois = charger_calendrier_mensuel(hier_kst.year, hier_kst.month)
    except Exception as e:
        return pd.DataFrame(), (
            f"Impossible de récupérer les résultats d'hier pour le moment ({e}). "
            "Réessayez en rouvrant ce menu dans quelques instants."
        ), True

    if df_mois.empty:
        return pd.DataFrame(), None, True

    df_hier = df_mois[df_mois['Date'] == date_hier_str].dropna(subset=['score_home', 'score_away'])
    if df_hier.empty:
        return pd.DataFrame(), None, True

    try:
        dict_noms_anglais = _dict_noms_anglais(annee)
    except Exception:
        dict_noms_anglais = {}

    predictions_hier = _charger_historique_predictions().get(date_hier_str, {}).get('matches', [])
    predictions_disponibles = len(predictions_hier) > 0
    # Indexé à la fois en int et en str pour tolérer la sérialisation JSON.
    predictions_par_game_id = {}
    for p in predictions_hier:
        gid = p.get('game_id')
        if gid is None:
            continue
        predictions_par_game_id[gid] = p
        predictions_par_game_id[str(gid)] = p
        try:
            predictions_par_game_id[int(gid)] = p
        except (TypeError, ValueError):
            pass

    ligne_ou = obtenir_ligne_over_under_saison_kbo(annee)

    lignes = []
    for _, g in df_hier.iterrows():
        game_id = g.get('game_id')
        code_home = g.get('code_home') or '???'
        code_away = g.get('code_away') or '???'
        nom_home = TEAMS_KBO.get(code_home, g.get('nom_home') or '?')
        nom_away = TEAMS_KBO.get(code_away, g.get('nom_away') or '?')

        try:
            home_score, away_score = int(g['score_home']), int(g['score_away'])
        except (TypeError, ValueError):
            continue
        total_reel = home_score + away_score

        runs_home, hr_home = obtenir_scoreurs_runs_et_hr_match_resume(
            game_id, True, dict_noms_anglais
        )
        runs_away, hr_away = obtenir_scoreurs_runs_et_hr_match_resume(
            game_id, False, dict_noms_anglais
        )

        pred = _trouver_prediction_match_kbo(predictions_par_game_id, game_id)
        proba_home = pred.get('proba_home') if pred else None
        proba_away = pred.get('proba_away') if pred else None
        total_predit = pred.get('total_runs_predit') if pred else None

        texte_victoire, icone_victoire = _bilan_victoire_kbo(
            proba_home, proba_away, nom_home, nom_away, home_score, away_score
        )
        texte_ou, icone_ou = _bilan_over_under_kbo(total_predit, total_reel, ligne_ou)

        lignes.append({
            'Match': f"{nom_away} vs {nom_home}",
            'Score': f"{code_away} {away_score} - {code_home} {home_score}",
            'Total Runs': _formater_cellule_total_runs(
                total_reel, code_away, runs_away, code_home, runs_home
            ),
            'HR marqués': _formater_cellule_hr(code_away, hr_away, code_home, hr_home),
            'Vainqueur': _formater_vainqueur_kbo(nom_home, nom_away, home_score, away_score),
            'Victoire prédite': f"{icone_victoire} {texte_victoire}",
            'Over/Under prédit': f"{icone_ou} {texte_ou}",
        })

    return pd.DataFrame(lignes), None, predictions_disponibles


def afficher_bilan_predictions_veille_kbo(annee: int):
    """
    Corps du menu déroulant "📅 Résultats de la veille et Bilan des Prédictions" : appelé
    uniquement quand ce menu est ouvert (cf. garde `expander.open` dans `afficher_onglet_
    resume_kbo`), donc sans coût réseau tant que l'utilisateur ne l'a pas déplié.
    """
    if annee != ANNEE_COURANTE:
        st.info(
            f"Le bilan de la veille n'est disponible que pour la saison en cours "
            f"({ANNEE_COURANTE})."
        )
        return

    with st.spinner("Récupération des résultats d'hier et calcul du bilan des prédictions..."):
        df_bilan, message_erreur, predictions_disponibles = construire_bilan_veille_kbo(annee)

    if message_erreur:
        st.error(f"⚠️ {message_erreur}")
        return

    if df_bilan.empty:
        st.info("Aucun match KBO terminé hier (heure de Corée).")
        return

    if not predictions_disponibles:
        st.info(
            "ℹ️ Aucune prédiction n'a été archivée hier pour ces matchs, donc les colonnes de "
            "bilan ci-dessous affichent \"Prédiction non disponible\" - les résultats réels, eux, "
            "sont bien à jour. Cela arrive si l'application n'a pas été consultée du tout hier "
            "(l'archivage se fait uniquement à l'ouverture de l'onglet Résumé ou Hot Pronostics), "
            "ou si cette fonctionnalité vient tout juste d'être ajoutée : le bilan se remplira "
            "automatiquement à partir de demain."
        )

    st.dataframe(
        df_bilan,
        column_config={
            "Match": st.column_config.TextColumn("Match", width="medium"),
            "Score": st.column_config.TextColumn("Score", width="small"),
            "Total Runs": st.column_config.TextColumn("Total Runs", width="large"),
            "HR marqués": st.column_config.TextColumn("HR marqués", width="large"),
            "Vainqueur": st.column_config.TextColumn("Vainqueur", width="medium"),
            "Victoire prédite": st.column_config.TextColumn("Victoire prédite", width="large"),
            "Over/Under prédit": st.column_config.TextColumn("Over/Under prédit", width="large"),
        },
        hide_index=True,
    )

    st.caption(
        "**Méthodologie** — Victoire : ✅ si l'équipe favorite (probabilité la plus haute) a "
        "réellement gagné. Over/Under : ligne de référence = moyenne réelle de runs cumulés par "
        "match sur la saison en cours ; ✅ si notre projection (moyenne de runs des 10 derniers "
        "matchs des deux équipes) était du même côté de cette ligne que le résultat réel. "
        "Total Runs / HR marqués : détail des joueurs ayant réellement marqué, issu du "
        "boxscore officiel. ⏳ = aucune prédiction n'avait été archivée pour ce match "
        "(application non consultée la veille) ou match nul. Les prédictions ne sont "
        "archivées qu'au moment où l'onglet Résumé ou Hot Pronostics est consulté ce "
        "jour-là (pas de calcul en tâche de fond)."
    )


@st.cache_data(show_spinner=False, ttl=3600, max_entries=20)
def construire_resume_matchs_du_jour_kbo(annee: int, cache_bust: int = 0):
    """
    Construit le tableau récapitulatif de TOUS les matchs KBO du jour (à venir, en cours,
    terminés) pour l'onglet "Résumé". `cache_bust` sert uniquement à invalider le cache
    Streamlit à la demande (bouton "Rafraîchir les scores en direct") - le calcul du modèle
    de prédiction ("Hot Pronostics") n'est PAS reproduit à chaque rafraîchissement (il a son
    propre cache à `ttl=1800`, car il ne change pas au fil du match), seuls les
    scores/statuts/HR en direct sont re-récupérés.

    Retourne (DataFrame, message_erreur). En cas d'échec réseau, le DataFrame est vide et
    `message_erreur` contient un texte à afficher via `st.error` - aucune exception ne
    remonte jamais à l'appelant (l'application ne doit jamais planter à cause d'un appel
    réseau en direct).
    """
    if annee != ANNEE_COURANTE:
        return pd.DataFrame(), None

    try:
        df_jour, _ = obtenir_calendrier_du_jour_kst()
    except Exception as e:
        return pd.DataFrame(), (
            f"Impossible de récupérer les scores en direct pour le moment ({e}). "
            "Réessayez dans quelques instants avec le bouton de rafraîchissement."
        )

    if df_jour.empty:
        return pd.DataFrame(), None

    try:
        dict_noms_anglais = _dict_noms_anglais(annee)
    except Exception:
        dict_noms_anglais = {}

    # Prédictions déjà calculées pour "Hot Pronostics" (même modèle, même journée),
    # réutilisées ici pour la colonne "Comparatif Prédiction" - alignées par game_id (les
    # deux fonctions parcourent le même calendrier du jour, dans le même ordre, mais on
    # indexe explicitement par game_id pour rester robuste à tout changement d'ordre entre
    # les deux appels).
    try:
        matchs_lineups, _, _, df_victoires = construire_donnees_hot_pronostics_kbo(annee)
    except Exception:
        matchs_lineups, df_victoires = [], pd.DataFrame()

    predictions_par_game_id = {}
    for idx, m in enumerate(matchs_lineups):
        if idx < len(df_victoires):
            predictions_par_game_id[m.get('game_id')] = df_victoires.iloc[idx]

    lignes = []
    for _, g in df_jour.iterrows():
        game_id = g.get('game_id')
        code_home = g.get('code_home') or '???'
        code_away = g.get('code_away') or '???'
        nom_home = TEAMS_KBO.get(code_home, g.get('nom_home') or '?')
        nom_away = TEAMS_KBO.get(code_away, g.get('nom_away') or '?')

        statut_str = _formater_statut_match_kbo(g)
        a_commence = statut_str == "Terminé" or statut_str.startswith("En cours") or statut_str == "Suspendu"

        try:
            home_score = int(g.get('score_home') or 0)
            away_score = int(g.get('score_away') or 0)
        except (TypeError, ValueError):
            home_score, away_score = 0, 0

        if a_commence:
            score_str = f"{code_away} {away_score} - {code_home} {home_score}"
            # Colonne texte (pas numérique) volontairement : elle doit pouvoir afficher "—"
            # pour les matchs pas encore commencés sans faire planter la sérialisation Arrow
            # du tableau (colonne à types mixtes int/str sinon).
            # Runs + HR détaillés (même format que le bilan de la veille) pour le
            # tableau en direct ET la vue cartes.
            runs_home, hr_home = obtenir_scoreurs_runs_et_hr_match_resume(
                game_id, True, dict_noms_anglais, cache_bust
            )
            runs_away, hr_away = obtenir_scoreurs_runs_et_hr_match_resume(
                game_id, False, dict_noms_anglais, cache_bust
            )
            total_runs = _formater_cellule_total_runs(
                home_score + away_score, code_away, runs_away, code_home, runs_home
            )
            hr_str = _formater_cellule_hr(code_away, hr_away, code_home, hr_home)
        else:
            score_str = "—"
            total_runs = "—"
            hr_str = "—"

        pred = predictions_par_game_id.get(game_id)
        comparatif_str, resultat_icone = _comparer_prediction_vs_score(
            pred, nom_home, nom_away, home_score, away_score, a_commence
        )

        lignes.append({
            'Match': f"{nom_away} vs {nom_home}",
            'Statut': statut_str,
            'Score': score_str,
            'Total Runs': total_runs,
            'Home Runs': hr_str,
            'Comparatif Prédiction': comparatif_str,
            'Résultat vs Algo': resultat_icone,
        })

    return pd.DataFrame(lignes), None


@st.fragment
def afficher_onglet_resume_kbo(annee: int):
    """
    Corps de l'onglet "Résumé" (menu déroulant "Bilan de la veille" + bouton de
    rafraîchissement + tableau du jour), encapsulé dans un `st.fragment` : cliquer sur le
    bouton, ou ouvrir/fermer le menu déroulant, ne relance QUE cette fonction (nouvel appel
    réseau + reconstruction du tableau), sans recharger le reste de l'application (sidebar,
    autres onglets) ni la page web entière.
    """
    # --- Menu déroulant "Bilan des Prédictions" de la veille, tout en haut de l'onglet, au-
    # dessus du tableau des matchs du jour. `on_change="rerun"` rend la propriété `.open`
    # dynamique (True/False selon l'état du menu) : le contenu (requête réseau incluse)
    # n'est donc calculé QUE si l'utilisateur a effectivement déplié le menu, jamais au
    # chargement initial de l'onglet.
    expander_veille = st.expander(
        "📅 Résultats de la veille et Bilan des Prédictions", on_change="rerun"
    )
    if expander_veille.open:
        with expander_veille:
            afficher_bilan_predictions_veille_kbo(annee)

    st.markdown("---")

    if 'resume_cache_bust' not in st.session_state:
        st.session_state.resume_cache_bust = 0
    if 'resume_derniere_actualisation' not in st.session_state:
        st.session_state.resume_derniere_actualisation = None

    col_bouton, col_info = st.columns([1, 2])
    with col_bouton:
        if st.button("🔄 Rafraîchir les scores en direct"):
            st.session_state.resume_cache_bust += 1
            st.session_state.resume_derniere_actualisation = datetime.now(TZ_PARIS)

    with col_info:
        if st.session_state.resume_derniere_actualisation:
            st.caption(
                "Dernière actualisation manuelle : "
                f"{st.session_state.resume_derniere_actualisation.strftime('%H:%M:%S')} (heure française)."
            )
        else:
            st.caption("Cliquez sur le bouton pour actualiser les scores en direct.")

    if annee != ANNEE_COURANTE:
        st.info(
            f"Le résumé du jour n'est disponible que pour la saison en cours "
            f"({ANNEE_COURANTE}). Sélectionnez {ANNEE_COURANTE} dans le menu de gauche."
        )
        return

    with st.spinner("Récupération des scores en direct..."):
        df_resume, message_erreur = construire_resume_matchs_du_jour_kbo(
            annee, st.session_state.resume_cache_bust
        )

    if message_erreur:
        st.error(f"⚠️ {message_erreur}")

    if df_resume.empty:
        if message_erreur is None:
            st.info("Aucun match n'est prévu aujourd'hui (heure de Corée).")
        return

    _resume_column_config = {
        "Match": st.column_config.TextColumn("Match", width="medium"),
        "Statut": st.column_config.TextColumn("Statut", width="small"),
        "Score": st.column_config.TextColumn("Score", width="small"),
        "Total Runs": st.column_config.TextColumn("Total Runs", width="large"),
        "Home Runs": st.column_config.TextColumn("Home Runs", width="large"),
        "Comparatif Prédiction": st.column_config.TextColumn("Comparatif Prédiction", width="medium"),
        "Résultat vs Algo": st.column_config.TextColumn("Résultat vs Algo", width="small"),
    }
    afficher_cartes_matchs(
        df_resume,
        show_table_fallback=True,
        column_config=_resume_column_config,
    )

    st.caption(
        "✅ = l'équipe favorite de notre algorithme mène ou a gagné · ❌ = elle est menée ou a "
        "perdu · ⏳ = match pas encore commencé, à égalité, ou prédiction pas encore disponible. "
        "Le score, le total de runs et les home runs ne sont affichés qu'une fois le match "
        "commencé."
    )


# ============================================================
# 6. INTERFACE PRINCIPALE
# ============================================================

render_page_header(
    "Analyse Statistiques KBO",
    "Explorez les runs, les prédictions du jour et les tendances W/L",
    league="kbo",
)

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
    "📊 Résumé",
    "🔥 Hot Pronostics",
    "📊 Analyse par Équipe",
    "🔮 Prédictions du jour"
], on_change="rerun")

# --------------------------------------------------------------
# ONGLET 0: RÉSUMÉ (scores en direct et terminés du jour)
# --------------------------------------------------------------
with onglets[0]:
    if onglets[0].open:
        render_section_title(
            "Résumé du jour",
            "Suivi en direct de toutes les confrontations KBO du jour",
        )
        afficher_onglet_resume_kbo(annee)

# --------------------------------------------------------------
# ONGLET 1: HOT PRONOSTICS (scan global de tous les matchs du jour)
# --------------------------------------------------------------
with onglets[1]:
    if onglets[1].open:
        render_section_title(
            "Hot Pronostics du jour",
            "Les meilleurs pronostics du jour, tous matchs KBO confondus",
        )
        st.caption(
            "⚠️ Estimations statistiques automatiques calculées à partir des lineups PROBABLES "
            "(estimées d'après le dernier match connu de chaque équipe - l'API KBO utilisée par "
            "cette application ne publie pas de lineup officielle avant le début du match, "
            "contrairement à MLB StatsAPI), des lanceurs partants annoncés et de la forme "
            "récente des joueurs. Ce ne sont pas des garanties de résultat : simples "
            "heuristiques, à utiliser uniquement à titre informatif, avec discernement si vous "
            "vous en servez pour parier."
        )

        if annee != ANNEE_COURANTE:
            st.info(
                f"Les Hot Pronostics ne sont disponibles que pour la saison en cours "
                f"({ANNEE_COURANTE}). Sélectionnez {ANNEE_COURANTE} dans le menu de gauche."
            )
        else:
            with st.spinner(
                "Analyse de tous les matchs KBO du jour (lineups probables, lanceurs, forme "
                "récente)... Premier chargement potentiellement long (plusieurs dizaines "
                "d'appels réseau), les suivants seront quasi instantanés grâce au cache."
            ):
                matchs_jour, df_top5_hr, df_top5_runs, df_victoires = construire_donnees_hot_pronostics_kbo(annee)

            if not matchs_jour:
                st.info("Aucun match KBO n'est prévu aujourd'hui (heure de Corée).")
            else:
                st.caption(
                    f"📅 {len(matchs_jour)} match(s) KBO au programme aujourd'hui (heure de Corée)."
                )

                st.markdown("---")
                st.subheader("💣 Top 5 Home Runs probables")
                if df_top5_hr.empty:
                    st.info(
                        "Aucun candidat exploitable pour le moment (historique de match "
                        "insuffisant pour au moins une des équipes du jour)."
                    )
                else:
                    st.dataframe(
                        df_top5_hr,
                        column_config={
                            "SLG récent (estimé)": st.column_config.NumberColumn("SLG récent (estimé)", format="%.3f"),
                            "HR (10 derniers matchs)": st.column_config.NumberColumn("HR (10 derniers matchs)", format="%d"),
                            "HR/9 lanceur adverse": st.column_config.NumberColumn("HR/9 lanceur adverse", format="%.2f"),
                            "Indice HR (/100)": st.column_config.ProgressColumn(
                                "Indice HR (/100)", min_value=0, max_value=100, format="%.0f"
                            ),
                        },
                        hide_index=True,
                    )

                st.markdown("---")
                st.subheader("🏃 Top 5 joueurs pour marquer un run")
                if df_top5_runs.empty:
                    st.info(
                        "Aucun candidat exploitable pour le moment (historique de match "
                        "insuffisant pour au moins une des équipes du jour)."
                    )
                else:
                    st.dataframe(
                        df_top5_runs,
                        column_config={
                            "OBP récent (estimé)": st.column_config.NumberColumn("OBP récent (estimé)", format="%.3f"),
                            "Position probable": st.column_config.NumberColumn("Position probable", format="%d"),
                            "ERA lanceur adverse": st.column_config.NumberColumn("ERA lanceur adverse", format="%.2f"),
                            "Indice Run (/100)": st.column_config.ProgressColumn(
                                "Indice Run (/100)", min_value=0, max_value=100, format="%.0f"
                            ),
                        },
                        hide_index=True,
                    )

                st.markdown("---")
                st.subheader("🎲 Probabilités Win/Lose du jour")
                if df_victoires.empty:
                    st.info("Aucune donnée de probabilité de victoire disponible pour le moment.")
                else:
                    st.dataframe(
                        df_victoires,
                        column_config={
                            "Proba Domicile (%)": st.column_config.ProgressColumn(
                                "Proba Domicile (%)", min_value=0, max_value=100, format="%.1f%%"
                            ),
                            "Proba Extérieur (%)": st.column_config.ProgressColumn(
                                "Proba Extérieur (%)", min_value=0, max_value=100, format="%.1f%%"
                            ),
                        },
                        hide_index=True,
                    )

                st.caption(
                    "**Méthodologie** — Home Runs : SLG récent estimé (45%) + HR sur les 10 "
                    "derniers matchs (35%) + HR/9 du lanceur partant adverse (20%). Runs : OBP "
                    "récent estimé (45%) + position dans la lineup probable (25%, positions 1 à "
                    "4 favorisées) + ERA du lanceur partant adverse (30%). Win/Lose : moyenne de "
                    "runs marqués sur les 10 derniers matchs de chaque équipe + ERA/WHIP des "
                    "lanceurs partants annoncés du jour (même modèle que l'onglet \"Prédictions "
                    "du jour\", détaillé plus bas). Chaque indice est normalisé sur l'ensemble "
                    "des candidats du jour, donc relatif à la journée en cours. **Limite "
                    "spécifique KBO** : à défaut de lineup officielle publiée avant match par "
                    "l'API utilisée, la lineup \"probable\" est estimée à partir du dernier match "
                    "terminé de chaque équipe (position au bâton généralement stable d'un match "
                    "à l'autre, mais pas garantie) ; de même le SLG/OBP récents sont des "
                    "estimations (l'API ne distingue pas doubles/triples/HBP au niveau d'un "
                    "boxscore de match, contrairement aux statistiques de saison)."
                )

# --------------------------------------------------------------
# ONGLET 2: ANALYSE PAR ÉQUIPE
# --------------------------------------------------------------
with onglets[2]:
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
    # --------------------------------------------------------------------
    # NOTE : le graphique "📈 Tendance des Runs par match (score équipe)"
    # (ligne Altair + règle de moyenne annotée) a été retiré pour épurer
    # l'onglet "Analyse par équipe" et gagner de la place. Les autres
    # éléments de l'onglet (classement Home Runs, moyenne de runs par
    # match ci-dessous, derniers matchs, etc.) restent inchangés.
    # --------------------------------------------------------------------

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
# ONGLET 3: PRÉDICTIONS DU JOUR
# --------------------------------------------------------------
with onglets[3]:
    render_section_title(
        "Prédictions du jour",
        f"Prédiction du match du jour pour les {EQUIPES_KBO.get(equipe_abbr, equipe_abbr)}",
    )
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
            render_prediction_match_banner(
                f"{EQUIPES_KBO.get(equipe_abbr, equipe_abbr)} {lieu} contre {match_du_jour['adversaire']}",
                "Fiche match · lanceurs · probabilités · Value Bet",
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

            # Les stats du lanceur adverse ET celles de NOTRE lanceur (saison en cours) ont
            # déjà été récupérées par `obtenir_match_du_jour`, de manière SYMÉTRIQUE (même
            # fonction `obtenir_infos_lanceur` appelée pour les deux lanceurs annoncés), il
            # n'y a donc plus besoin d'appel réseau séparé ici pour aucun des deux camps.
            stats_lanceur_nous = match_du_jour.get('stats_lanceur_nous')
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

            # Moyenne de runs CONCÉDÉS par notre équipe sur ses 10 derniers matchs : calculée
            # UNE SEULE FOIS ici, puis réutilisée à la fois par le module "Probabilité de
            # Victoire" ci-dessous (comme proxy de l'attaque adverse, voir docstring de
            # `predire_probabilite_victoire`) et par le module de prédiction des Runs plus
            # bas (qui l'utilisait déjà comme proxy identique).
            moyenne_ra_10 = pd.to_numeric(
                df_matchs.tail(10).get('RA', pd.Series(dtype=float)), errors='coerce'
            ).mean()

            # --------------------------------------------------------------
            # NOUVEAU MODULE : PROBABILITÉ DE VICTOIRE
            # --------------------------------------------------------------
            st.markdown("---")
            st.subheader("🎲 Probabilité de Victoire")

            pct_nous, pct_adverse = predire_probabilite_victoire(
                moyenne_runs_10,
                moyenne_ra_10,
                stats_lanceur_nous,
                stats_lanceur_adverse,
                match_du_jour['est_domicile'],
            )

            col_proba1, col_proba2 = st.columns(2)
            with col_proba1:
                st.metric(f"{EQUIPES_KBO.get(equipe_abbr, equipe_abbr)}", f"{pct_nous:.0f}%")
            with col_proba2:
                st.metric(f"{match_du_jour['adversaire']}", f"{pct_adverse:.0f}%")
            st.progress(pct_nous / 100)

            # --------------------------------------------------------------
            # RECOMMANDATION DE PARI OPTIMISÉE
            # --------------------------------------------------------------
            # Calculées ici (plutôt que dans leurs modules respectifs plus bas) pour
            # pouvoir alimenter la recommandation juste en dessous de la ligne
            # principale de prédiction (probabilité de victoire) ; les modules
            # "Prédiction des Runs" et "Prédiction des Joueurs" plus bas réutilisent
            # directement ces mêmes résultats (pas de recalcul, ni d'appel réseau
            # supplémentaire - ce sont de simples fonctions locales).
            prediction_runs = (
                predire_runs_match(moyenne_runs_10, moyenne_ra_10, stats_lanceur_adverse)
                if moyenne_runs_10 is not None else None
            )
            joueurs_a_surveiller = predire_joueurs_du_jour(
                cumul_runs_10, cumul_hr_10, stats_lanceur_adverse, top_n=3
            )

            conseils_paris = generer_recommandation_pari(
                pct_nous,
                pct_adverse,
                stats_lanceur_nous,
                stats_lanceur_adverse,
                prediction_runs,
                joueurs_a_surveiller,
                ligue=detecter_ligue_match(match_du_jour),
            )
            # Affichage Over/Under explicite : comparaison finale UNIQUEMENT
            # (projection déjà calculée vs ligne du bilan de la veille).
            # Ne touche ni à predire_runs_match ni à generer_recommandation_pari.
            reco_totaux = formater_recommandation_totaux_over_under(
                prediction_runs.get('total_match') if prediction_runs else None,
                obtenir_ligne_over_under_saison_kbo(annee),
            )
            lignes_reco = list(conseils_paris or [])
            if reco_totaux:
                lignes_reco.append(reco_totaux)
            if lignes_reco:
                st.info(
                    "**💡 Recommandation de Pari Optimisée**\n\n"
                    + "\n\n".join(lignes_reco)
                )

            st.caption(
                "Estimation basée sur (1) l'ERA/WHIP des lanceurs partants annoncés des deux "
                "équipes (facteur principal), (2) la moyenne de runs marqués/concédés sur les "
                "10 derniers matchs (dynamique offensive récente), et (3) un léger bonus de "
                "+3 points de pourcentage pour l'équipe qui joue à domicile (~53-54% de "
                "victoires à domicile en moyenne dans le baseball professionnel). "
                "⚠️ Simple heuristique, PAS un modèle statistique validé : ne reflète pas "
                "tous les facteurs d'un vrai match (composition exacte de l'équipe, bullpen, "
                "météo, blessures de dernière minute, etc.)."
            )

            lanceur_nous_ok = bool(stats_lanceur_nous and stats_lanceur_nous.get('era'))
            lanceur_adv_ok = bool(stats_lanceur_adverse and stats_lanceur_adverse.get('era'))
            if not (lanceur_nous_ok and lanceur_adv_ok):
                st.info(
                    "ℹ️ Stats ERA/WHIP indisponibles pour au moins un des deux lanceurs "
                    "annoncés (facteur neutralisé pour le(s) lanceur(s) concerné(s)) : "
                    "l'estimation ci-dessus est donc moins fiable que d'habitude."
                )

            # --------------------------------------------------------------
            # VALUE BET DETECTOR (cotes de marché vs notre probabilité algorithmique)
            # --------------------------------------------------------------
            # Les cotes sont récupérées AVANT d'afficher le sous-titre, pour que celui-ci
            # cite le bookmaker RÉELLEMENT utilisé (Winamax n'est que le bookmaker
            # prioritaire - voir `ODDS_API_BOOKMAKER_PRINCIPAL` - constaté à 0% de
            # couverture KBO chez The-Odds-API : le detector retombe systématiquement
            # sur un autre bookmaker EU pour cette ligue).
            st.markdown("---")

            cle_odds_api = _lire_cle_odds_api()
            cotes_match = None
            if cle_odds_api:
                cotes_du_jour = obtenir_cotes_moneyline_du_jour(ODDS_API_SPORT_KEY, cle_odds_api)
                nom_notre_equipe = EQUIPES_KBO.get(equipe_abbr, equipe_abbr)
                cotes_match = trouver_cote_du_match(
                    cotes_du_jour, nom_notre_equipe, match_du_jour['adversaire']
                )
                if cotes_match and not (cotes_match.get('cote_nous') and cotes_match.get('cote_adverse')):
                    cotes_match = None

            titre_bookmaker = f"(vs {cotes_match['bookmaker']})" if cotes_match else "(vs Winamax)"
            st.subheader(f"💰 Value Bet Detector {titre_bookmaker}")

            if not cle_odds_api:
                st.info(
                    "ℹ️ Value Bet Detector non configuré : ajoutez votre clé "
                    "[The-Odds-API](https://the-odds-api.com) dans `.streamlit/secrets.toml` "
                    "(`[odds_api]` puis `api_key = \"...\"`) pour comparer nos probabilités "
                    "aux cotes en direct."
                )
            else:
                if not cotes_match:
                    st.info(
                        "Cotes indisponibles pour ce match pour le moment "
                        "(marché pas encore ouvert, ou match non couvert par les bookmakers suivis - "
                        "la couverture KBO est moins complète que la MLB chez la plupart des "
                        "bookmakers, y compris Winamax)."
                    )
                else:
                    col_cote1, col_cote2 = st.columns(2)
                    with col_cote1:
                        st.metric(f"Cote {nom_notre_equipe}", f"{cotes_match['cote_nous']:.2f}")
                    with col_cote2:
                        st.metric(f"Cote {match_du_jour['adversaire']}", f"{cotes_match['cote_adverse']:.2f}")

                    for niveau, message in (
                        evaluer_value_bet(
                            pct_nous, cotes_match['cote_nous'], nom_notre_equipe, cotes_match['bookmaker']
                        ),
                        evaluer_value_bet(
                            pct_adverse, cotes_match['cote_adverse'], match_du_jour['adversaire'], cotes_match['bookmaker']
                        ),
                    ):
                        afficher_badge_value_bet(niveau, message)

                    st.caption(
                        f"Cotes Moneyline (marché h2h) fournies par {cotes_match['bookmaker']} "
                        "via The-Odds-API. Probabilité implicite = (1 / cote) × 100 ; "
                        "Value = notre probabilité algorithmique − probabilité implicite du marché."
                    )

            st.markdown("---")
            st.subheader("📊 Module de prédiction des Runs")

            # `prediction_runs` a déjà été calculé plus haut, avant la
            # "Recommandation de Pari Optimisée" (voir commentaire à cet endroit).
            if prediction_runs is None:
                st.info("Pas assez de données récentes pour estimer les runs de cette équipe.")
            else:
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

            # `joueurs_a_surveiller` a déjà été calculé plus haut, avant la
            # "Recommandation de Pari Optimisée" (voir commentaire à cet endroit).
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
render_footer("KBO", datetime.now(TZ_SEOUL).strftime('%Y-%m-%d %H:%M') + " KST")
