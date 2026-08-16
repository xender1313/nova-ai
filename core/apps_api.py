"""API du tableau "App" (onglet de web/chat.html) : gere directement la section
apps: de config.yaml (nom -> chemin/lien), sans passer par la conversation LLM.

Remplir une ligne du tableau EST l'acte de confirmation (contrairement au chat
texte, qui repasse par la confirmation N2 habituelle de tools/apps.ajouter_app) --
choix valide avec l'utilisateur. L'ajout reutilise tools.apps.ajouter_app tel
quel (meme ecriture dans config.yaml), pour ne jamais dupliquer cette logique :
une app ajoutee via le tableau est immediatement utilisable a la voix, et
inversement.

Meme garde-fou "local uniquement" que core/chat_api.py et core/panneau.py :
toute requete avec un en-tete de tunnel (X-Forwarded-For/Host) ou un Host
non-local est refusee (403).
"""
import logging
import os
import re
from pathlib import Path

from core.config import definir, reglage

LOG = logging.getLogger("jarvis")

_HOTES_LOCAUX = {"localhost", "127.0.0.1", "::1", "[::1]"}

# Lettre de lecteur (une seule lettre) suivie de ":" puis "\" ou "/" -> chemin
# Windows reel (C:\..., C:/...), jamais un protocole (les schemas d'URI font
# plus d'une lettre : steam:, spotify:, ms-settings:, http:...).
_RE_CHEMIN_WINDOWS = re.compile(r"^[a-zA-Z]:[\\/]")
# Sinon, "mot:" -> protocole/URI, ni verifiable ni "installe/non installe".
_RE_PROTOCOLE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")

# Extrait le chemin d'executable meme quand des arguments suivent (ex.
# "steam.exe +controller_rate 0") : NE PAS couper sur le premier espace, le
# chemin lui-meme en contient souvent (ex. "C:\Program Files (x86)\...").
# Non-greedy jusqu'a la premiere extension connue suivie d'un espace/fin.
_RE_EXECUTABLE = re.compile(r"^(.*?\.(?:exe|msc|cpl|bat|cmd|py))(?=[\s\"]|$)", re.IGNORECASE)


def _etat_installation(chemin):
    """True/False si le fichier existe/n'existe pas sur le disque, None si le
    chemin n'est pas un fichier verifiable (protocole/URI)."""
    c = (chemin or "").strip()
    if not c:
        return None
    sans_guillemets = c.strip('"')
    if not _RE_CHEMIN_WINDOWS.match(sans_guillemets) and _RE_PROTOCOLE.match(sans_guillemets):
        return None
    candidats = [sans_guillemets]
    trouve = _RE_EXECUTABLE.match(sans_guillemets)
    if trouve:
        candidats.append(trouve.group(1))
    for candidat in candidats:
        if not candidat:
            continue
        try:
            if Path(os.path.expandvars(candidat)).exists():
                return True
        except Exception:
            continue
    return False


def _local_seulement(request):
    """Meme logique que core.chat_api._local_seulement / core.panneau (section
    9.2 / N8) : un en-tete de tunnel indique un passage par ngrok -> refuse."""
    if request.headers.get("x-forwarded-for") or request.headers.get("x-forwarded-host"):
        return False
    host = (request.headers.get("host", "") or "").split(":")[0].strip().lower()
    return host in _HOTES_LOCAUX or host == ""


def monter_routes(app):
    """Monte GET/POST /api/apps et DELETE /api/apps/{nom} sur l'app FastAPI
    unifiee (appelee par core.serveur). LOCAL UNIQUEMENT."""
    from fastapi import Request
    from fastapi.responses import JSONResponse

    def garde(request: Request):
        if not _local_seulement(request):
            return JSONResponse({"ok": False,
                                 "message": "Accessible en local uniquement."},
                                status_code=403)
        return None

    @app.get("/api/apps")
    def api_apps_liste(request: Request):
        refus = garde(request)
        if refus:
            return refus
        apps = reglage("apps", {}) or {}
        return {"ok": True, "apps": [
            {"nom": n, "chemin": c, "installee": _etat_installation(c)}
            for n, c in apps.items()]}

    @app.get("/api/apps/recherche")
    def api_apps_recherche(request: Request):
        refus = garde(request)
        if refus:
            return refus
        from core.recherche_apps import rechercher
        apps = reglage("apps", {}) or {}
        try:
            candidats = rechercher(apps)
        except Exception as e:
            LOG.exception("apps_api: recherche a plante")
            return JSONResponse(
                {"ok": False, "message": f"erreur interne ({type(e).__name__})."},
                status_code=200)
        return {"ok": True, "candidats": candidats}

    @app.post("/api/apps")
    async def api_apps_ajouter(request: Request):
        refus = garde(request)
        if refus:
            return refus
        try:
            data = await request.json()
        except Exception:
            data = {}
        if not isinstance(data, dict):
            data = {}
        nom = str(data.get("nom", "")).strip()
        chemin = str(data.get("chemin", "")).strip()
        if not nom or not chemin:
            return JSONResponse({"ok": False, "message": "nom et chemin requis."},
                                status_code=400)
        try:
            from tools.apps import ajouter_app
            message = ajouter_app(nom, chemin)
        except Exception as e:
            LOG.exception("apps_api: ajout de %r a plante", nom)
            return JSONResponse(
                {"ok": False, "message": f"erreur interne ({type(e).__name__})."},
                status_code=200)
        return {"ok": True, "message": message}

    @app.delete("/api/apps/{nom}")
    def api_apps_supprimer(nom: str, request: Request):
        refus = garde(request)
        if refus:
            return refus
        apps = reglage("apps", {}) or {}
        clef = next((k for k in apps if k.lower() == nom.strip().lower()), None)
        if clef is None:
            return JSONResponse({"ok": False, "message": f"{nom} introuvable."},
                                status_code=404)
        del apps[clef]
        definir("apps", apps)
        return {"ok": True, "message": f"{clef} supprime."}

    LOG.info("apps_api: routes montees (/api/apps) -- local uniquement")
