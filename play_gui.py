"""Lance l'interface graphique : python play_gui.py [--bots BW,BB] [--base 180] [--increment 0]"""
try:
    from bughouse2v2.gui import main
except ModuleNotFoundError as exc:
    if exc.name == "chess":
        raise SystemExit("Il manque la bibliothèque chess : pip install -r requirements.txt")
    if exc.name == "bughouse2v2":
        raise SystemExit("play_gui.py doit être placé à côté du dossier bughouse2v2/.")
    raise

if __name__ == "__main__":
    main()
