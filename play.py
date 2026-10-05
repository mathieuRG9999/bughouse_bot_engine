"""Point d'entrée à la racine du projet : fonctionne avec le bouton « Run » d'un IDE.

    python play.py                    # tu joues les 4 places
    python play.py --bots BW,BB       # BW et BB jouées par des bots aléatoires
    python play.py --base 60 --increment 1
"""
try:
    from bughouse2v2.cli import main
except ModuleNotFoundError as exc:
    if exc.name == "chess":
        raise SystemExit("Il manque la bibliothèque chess : pip install -r requirements.txt")
    if exc.name == "bughouse2v2":
        raise SystemExit(
            "Dossier bughouse2v2/ introuvable : play.py doit être placé à côté du dossier "
            "bughouse2v2/ (qui contient __init__.py, game.py, clock.py, ...)."
        )
    raise

if __name__ == "__main__":
    main()
