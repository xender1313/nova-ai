"""Recherche les jeux/apps deja installes sur le PC (Steam, Epic Games, menu
Demarrer) et propose de les ajouter au registre apps: de config.yaml.

    python scripts/setup_recherche.py

Reutilise core/recherche_apps.py (meme logique que l'onglet Scripts du chat
web, voir web/chat.html) et tools/apps.py:ajouter_app pour l'ecriture.
"""
import sys
from pathlib import Path

for _f in (sys.stdout, sys.stderr):          # console Windows cp1252 -> UTF-8
    try:
        _f.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))


def main():
    from core.config import reglage
    from core.recherche_apps import rechercher
    from tools.apps import ajouter_app

    print("Recherche en cours (Steam, Epic Games, menu Demarrer)...\n")
    apps_existantes = reglage("apps", {}) or {}
    candidats = rechercher(apps_existantes)

    if not candidats:
        print("Rien de nouveau trouve -- tout est deja enregistre, ou aucune "
              "source detectee sur cette machine.")
        return

    print(f"{len(candidats)} candidat(s) trouve(s) :\n")
    for i, c in enumerate(candidats, 1):
        print(f"  {i:3}. [{c['source']:12}] {c['nom']}")

    print("\nNumeros a ajouter (ex. 1,3,5), 'tous', ou Entree pour ne rien faire :")
    choix = input("> ").strip().lower()
    if not choix:
        print("Rien ajoute.")
        return

    if choix == "tous":
        selection = candidats
    else:
        indices = set()
        for morceau in choix.split(","):
            morceau = morceau.strip()
            if morceau.isdigit():
                indices.add(int(morceau))
        selection = [c for i, c in enumerate(candidats, 1) if i in indices]

    if not selection:
        print("Aucune selection valide, rien ajoute.")
        return

    for c in selection:
        print(ajouter_app(c["nom"], c["chemin"]))


if __name__ == "__main__":
    main()
