"""Recherche des jeux/apps deja installes sur le PC (Steam, Epic Games, menu
Demarrer) pour proposer leur ajout au registre apps: de config.yaml.

Reutilise par deux points d'entree :
  - scripts/setup_recherche.py (CLI)
  - core/apps_api.py, route GET /api/apps/recherche (onglet Scripts du chat web)

Aucune ecriture ici : rechercher() renvoie une liste de candidats, l'ajout
reel passe par tools.apps.ajouter_app (comme partout ailleurs).
"""
import logging
import re
import winreg
from pathlib import Path

LOG = logging.getLogger("jarvis")


def _sans_accents_simple(s):
    return (s or "").strip().lower()


def _deja_enregistree(nom, chemin, apps_existantes):
    """True si `nom` ou `chemin` correspond deja a une entree de config.yaml
    apps: (comparaison insensible a la casse)."""
    nom_c = _sans_accents_simple(nom)
    chemin_c = _sans_accents_simple(chemin)
    for n, c in apps_existantes.items():
        if _sans_accents_simple(n) == nom_c:
            return True
        if _sans_accents_simple(c) == chemin_c:
            return True
    return False


# ---------------------------------------------------------------- Steam

def _steam_racine():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as cle:
            chemin, _ = winreg.QueryValueEx(cle, "SteamPath")
            return Path(chemin)
    except OSError:
        pass
    for defaut in (r"C:\Program Files (x86)\Steam", r"C:\Program Files\Steam"):
        if Path(defaut).exists():
            return Path(defaut)
    return None


def _steam_bibliotheques(racine):
    """Chemins des bibliotheques Steam (dossiers steamapps), via
    steamapps/libraryfolders.vdf. Format simple cle/valeur, pas besoin d'un
    vrai parseur VDF -- une regex sur les lignes "path" suffit."""
    bibs = [racine / "steamapps"]
    fichier = racine / "steamapps" / "libraryfolders.vdf"
    if not fichier.exists():
        return bibs
    try:
        texte = fichier.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return bibs
    for m in re.finditer(r'"path"\s*"([^"]+)"', texte):
        chemin = Path(m.group(1).replace("\\\\", "\\")) / "steamapps"
        if chemin not in bibs and chemin.exists():
            bibs.append(chemin)
    return bibs


def _steam_jeux():
    racine = _steam_racine()
    if racine is None:
        return []
    resultats = []
    for bib in _steam_bibliotheques(racine):
        if not bib.exists():
            continue
        for manifeste in bib.glob("appmanifest_*.acf"):
            try:
                texte = manifeste.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            m_id = re.search(r'"appid"\s*"(\d+)"', texte)
            m_nom = re.search(r'"name"\s*"([^"]+)"', texte)
            if not (m_id and m_nom):
                continue
            resultats.append({
                "nom": m_nom.group(1),
                "chemin": f"steam://rungameid/{m_id.group(1)}",
                "source": "Steam",
            })
    return resultats


# ---------------------------------------------------------- Epic Games

def _epic_jeux():
    dossier = Path(r"C:\ProgramData\Epic\EpicGamesLauncher\Data\Manifests")
    if not dossier.exists():
        return []
    import json
    resultats = []
    for fichier in dossier.glob("*.item"):
        try:
            data = json.loads(fichier.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        nom = data.get("DisplayName")
        install_dir = data.get("InstallLocation")
        exe = data.get("LaunchExecutable")
        if not (nom and install_dir and exe):
            continue
        chemin = str(Path(install_dir) / exe)
        if not Path(chemin).exists():
            continue
        resultats.append({"nom": nom, "chemin": chemin, "source": "Epic Games"})
    return resultats


# ------------------------------------------------------ Menu Demarrer

# Sous-chaines (pas une correspondance exacte) : "Uninstall Adobe Photoshop",
# "AbacusAI Desktop Uninstall"... doivent etre exclus quelle que soit leur
# position dans le nom.
_IGNORER_CONTIENT = (
    "uninstall", "desinstall", "unins0", "read me", "readme", "site web",
    "website", "licence", "license", "changelog",
)


def _menu_demarrer_dossiers():
    import os
    dossiers = []
    programdata = os.environ.get("PROGRAMDATA")
    appdata = os.environ.get("APPDATA")
    if programdata:
        dossiers.append(Path(programdata) / "Microsoft/Windows/Start Menu/Programs")
    if appdata:
        dossiers.append(Path(appdata) / "Microsoft/Windows/Start Menu/Programs")
    return [d for d in dossiers if d.exists()]


def _menu_demarrer_raccourcis():
    try:
        import win32com.client
    except ImportError:
        LOG.warning("recherche_apps: pywin32 absent, menu Demarrer ignore")
        return []

    shell = win32com.client.Dispatch("WScript.Shell")
    resultats = []
    for dossier in _menu_demarrer_dossiers():
        for lnk in dossier.rglob("*.lnk"):
            nom = lnk.stem
            try:
                raccourci = shell.CreateShortCut(str(lnk))
                cible = (raccourci.Targetpath or "").strip()
            except Exception:
                continue
            if not cible.lower().endswith(".exe"):
                continue
            if not Path(cible).exists():
                continue
            resultats.append({"nom": nom, "chemin": cible, "source": "Menu Demarrer"})
    return resultats


# ------------------------------------------------------------- combinaison

def rechercher(apps_existantes):
    """Renvoie la liste dedupliquee des jeux/apps trouves, deja filtree pour
    exclure ceux presents dans apps_existantes (config.yaml apps:)."""
    trouves = []
    for fonction in (_steam_jeux, _epic_jeux, _menu_demarrer_raccourcis):
        try:
            trouves.extend(fonction())
        except Exception:
            LOG.exception("recherche_apps: %s a echoue", fonction.__name__)

    vus = set()
    resultats = []
    for c in trouves:
        nom_c = _sans_accents_simple(c["nom"])
        chemin_c = _sans_accents_simple(c["chemin"])
        if any(m in nom_c or m in chemin_c for m in _IGNORER_CONTIENT):
            continue
        if _deja_enregistree(c["nom"], c["chemin"], apps_existantes):
            continue
        if nom_c in vus:
            continue
        vus.add(nom_c)
        resultats.append(c)

    resultats.sort(key=lambda c: c["nom"].lower())
    return resultats
