# Bughouse 2v2 (Python)

Base de moteur de bughouse 2v2 : 4 horloges, annulation des coups, bots branchables, jeu manuel en CLI.

## Arborescence (à respecter)

```
projet/
├── play.py              <- jeu en ligne de commande (bouton « Run » d'un IDE OK)
├── play_gui.py          <- interface graphique
├── requirements.txt
├── pyproject.toml
├── bughouse2v2/         <- le paquet : ces fichiers doivent rester ensemble dans ce dossier
│   ├── __init__.py  __main__.py  cli.py  gui.py  interaction.py
│   └── clock.py  game.py  players.py  seat.py  sim.py
└── tests/
    ├── test_game.py  test_cli.py  test_interaction.py  test_gui_smoke.py
```

Le paquet s'appelle `bughouse2v2` (et non `bughouse`) pour ne pas entrer en collision avec un
éventuel `bughouse.py` déjà présent dans ton dépôt.

## Installation

Linux / macOS :
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```
Windows (PowerShell) :
```powershell
py -m venv .venv ; .venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Jouer à la main

```bash
python play.py                       # tu joues les 4 places   (Windows : py play.py)
python play.py --bots BW,BB          # BW et BB jouées par des bots aléatoires
python play.py --base 60 --increment 1
```
Équivalent : `python -m bughouse2v2 ...`.

Places : `AW`/`AB` = Blancs/Noirs de la planche A, `BW`/`BB` = Blancs/Noirs de la planche B.
Équipe 0 = AW + BB, équipe 1 = AB + BW. Les deux planches tournent en parallèle ; `>` marque les horloges actives.

| Commande | Effet |
|---|---|
| `a e2e4` / `b Nf3` / `a P@e5` | joue sur la planche A / B (UCI ou SAN, drops `N@f3`) |
| `moves a` | liste les coups légaux |
| `undo` | annule le dernier coup (toutes planches), rembobine les horloges |
| `pause` / `resume` | fige / relance les horloges |
| `resign BB` | la place abandonne |
| `show`, `help`, `quit` | affichage, aide, sortie |

## Interface graphique (tkinter)

```bash
python play_gui.py                          # Windows : py play_gui.py
python play_gui.py --bots BW,BB --base 120 --increment 1
```
- **Jouer un coup** : clic sur une de tes pièces, puis sur la case d'arrivée (les coups possibles sont marqués, les captures par un anneau). La promotion ouvre un petit choix.
- **Poser une pièce** (drop) : clic sur la pièce dans ta poche (à côté de l'horloge), puis sur une case libre. Re-clic = désélection.
- **Annuler** : bouton ou Ctrl+Z (remet aussi les horloges). **Pause**, **Abandon**, **Nouvelle partie** (base et incrément modifiables).
- **Bots** : cocher « Bot AW/AB/BW/BB » fait jouer la place par `RandomPlayer` (réglage du délai). Pour tester TON bot : `App(root, players={Seat(...): MonBot(), ...})`.
- Horloges actives en jaune (rouge sous 10 s) ; dernier coup surligné ; roi en échec en rouge ; « bloqué » quand une place n'a aucun coup et attend une pièce de son partenaire.
- La planche B est affichée retournée (Noirs en bas) comme sur les sites de bughouse ; bouton « retourner » par planche.

tkinter est livré avec Python sous Windows/macOS. Sous Linux : `sudo apt install python3-tk`.
Les clics sont gérés par `bughouse2v2/interaction.py` (sans tkinter, donc testable) ; `gui.py` ne fait que dessiner.

## Simulation bot contre bot (temps virtuel)

```bash
python -m bughouse2v2.sim --seed 1 --base 180 --log
```

## Tests

```bash
python -m pytest        # ou simplement : pytest
```
Les tests de la fenêtre sont ignorés automatiquement s'il n'y a ni tkinter ni écran
(Linux sans affichage : `xvfb-run -a python -m pytest`).

## Brancher ton bot

Implémenter `choose_move(game, board) -> chess.Move` (voir `bughouse2v2/players.py`),
puis `simulate(players={Seat(...): MonBot(), ...})` ou `run(game, bots)` dans la CLI.
