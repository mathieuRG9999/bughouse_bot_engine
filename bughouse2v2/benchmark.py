"""Tournoi apparié : deux minimax contre deux random, couleurs inversées.

python -m bughouse2v2.benchmark --games 200 --output results
Le temps virtuel ne dépend PAS du temps de calcul. Voir BENCHMARK.md.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from dataclasses import asdict, dataclass
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import platform
import random
import statistics
import time

from .clock import ManualTime, TimeControl
from .game import Game
from .minimax import MinimaxPlayer, VALUES
from .players import RandomPlayer
from .seat import ALL_SEATS, Seat


@dataclass(frozen=True)
class Config:
    games: int = 200
    seed: int = 42
    base: float = 180.0
    increment: float = 0.0
    think_min: float = 0.3
    think_max: float = 3.0
    max_plies: int = 2000  # coups individuels, les deux planches confondues
    max_virtual_seconds: float = 3600.0
    max_depth: int = 6
    min_time: float = 0.05
    max_time: float = 1.0
    gamma: float = 0.9
    hand_bonus: float = 0.5
    moves_to_go: int = 40
    f_pawn_weight: float = 40.0

    def validate(self):
        if self.games <= 0 or self.games % 2:
            raise ValueError('games doit être un entier positif pair (100 paires = 200 parties).')
        if self.max_plies <= 0 or self.max_depth <= 0 or self.moves_to_go <= 0:
            raise ValueError('max_plies, max_depth et moves_to_go doivent être positifs.')
        floats = (self.base, self.increment, self.think_min, self.think_max,
                  self.max_virtual_seconds, self.min_time, self.max_time,
                  self.gamma, self.hand_bonus, self.f_pawn_weight)
        if not all(math.isfinite(v) for v in floats):
            raise ValueError('Les paramètres numériques doivent être finis.')
        if self.base <= 0 or self.increment < 0 or self.max_virtual_seconds <= 0:
            raise ValueError('base/durée max > 0, increment >= 0 requis.')
        if not 0 < self.think_min <= self.think_max:
            raise ValueError('0 < think_min <= think_max requis.')
        if not 0 < self.min_time <= self.max_time or not 0 < self.gamma <= 1:
            raise ValueError('0 < min_time <= max_time et 0 < gamma <= 1 requis.')


def make_players(config: Config, pair: int, minimax_team: int):
    # Graines par bot et couleur. Le même bot/couleur garde sa graine dans
    # les deux parties d'une paire ; les quatre joueurs restent indépendants.
    players = {}
    for seat in ALL_SEATS:
        kind = 'minimax' if seat.team == minimax_team else 'random'
        seed = config.seed + pair * 100_003 + (0 if kind == 'minimax' else 10_000) + int(seat.color)
        if kind == 'minimax':
            players[seat] = MinimaxPlayer(
                seed=seed, max_depth=config.max_depth, gamma=config.gamma,
                hand_bonus=config.hand_bonus, moves_to_go=config.moves_to_go,
                min_time=config.min_time, max_time=config.max_time,
                f_pawn_weight=config.f_pawn_weight)
        else:
            players[seat] = RandomPlayer(seed=seed)
    return players


def play_game(config: Config, game_index: int, move_sink=None):
    """Retourne (ligne de résultat, mesures des choix de coups).

    Deux délais de jeu peuvent courir simultanément. Les appels des bots sont
    exécutés séquentiellement, sur l'état courant à l'instant virtuel du coup.
    Aucun sleep ; un drapeau interrompt l'attente exactement à son échéance.
    """
    pair, minimax_team = game_index // 2, game_index % 2
    players = make_players(config, pair, minimax_team)
    rngs = {s: random.Random(config.seed + pair * 100_003 + 50_000 + i)
            for i, s in enumerate(ALL_SEATS)}
    clock = ManualTime()
    game = Game(TimeControl(config.base, config.increment), now=clock)
    ready = {0: None, 1: None}
    decisions = []
    wall_start = time.perf_counter()
    game.start()
    cutoff = None
    while not game.is_over:
        if len(game.history) >= config.max_plies:
            cutoff = 'max_plies'
            break
        for b in (0, 1):
            if ready[b] is None and not game.is_blocked(b):
                seat = Seat(b, game.turn(b))
                ready[b] = clock() + rngs[seat].uniform(config.think_min, config.think_max)
        pending = [(t, b) for b, t in ready.items() if t is not None]
        target, board = min(pending) if pending else (math.inf, None)
        flag_at = clock() + max(0.0, min(game.time_left(s) for s in game.active_seats))
        next_time = min(target, flag_at, config.max_virtual_seconds)
        clock.advance(max(0.0, next_time - clock()))
        # En cas d'égalité, le drapeau prime sur le coup.
        if next_time >= flag_at:
            game.check_time()
            if not game.is_over:  # protège les arrondis au voisinage de zéro
                clock.advance(1e-9)
                game.check_time()
            continue
        if next_time >= config.max_virtual_seconds:
            cutoff = 'max_virtual_seconds'
            break
        seat = Seat(board, game.turn(board))
        bot = players[seat]
        kind = 'minimax' if seat.team == minimax_team else 'random'
        # Le bot d'origine ne remet pas ses compteurs à zéro lorsqu'un seul
        # coup est légal ; éviter d'attribuer ses anciennes mesures à ce coup.
        if kind == 'minimax':
            bot.nodes = 0
            bot.last_depth = 0
        started = time.perf_counter()
        move = bot.choose_move(game, board)
        choice_seconds = time.perf_counter() - started
        gives_check = game.boards[board].gives_check(move)
        entry = game.push(board, move)
        row = dict(game=game_index + 1, pair=pair + 1, ply=entry.ply,
                   virtual_seconds=clock(), bot=kind, seat=str(seat),
                   move=move.uci(), san=entry.san, choice_seconds=choice_seconds,
                   nodes=bot.nodes if kind == 'minimax' else None,
                   depth=bot.last_depth if kind == 'minimax' else None,
                   capture=entry.captured or 0, capture_value=VALUES.get(entry.captured, 0),
                   drop=move.drop or 0, promotion=move.promotion or 0,
                   check=int(gives_check))
        decisions.append(row)
        if move_sink:
            move_sink(row)
        ready[board] = None
    wall_seconds = time.perf_counter() - wall_start
    result = game.result
    row = dict(game=game_index + 1, pair=pair + 1, pair_seed=config.seed + pair * 100_003,
               minimax_team=minimax_team,
               minimax_seats='AW+BB' if minimax_team == 0 else 'AB+BW',
               winner=('minimax' if result.winner == minimax_team else 'random') if result else '',
               winner_team=result.winner if result else '',
               reason=result.reason.value if result else cutoff,
               loser_seat=str(result.loser) if result else '',
               terminal_board='AB'[result.loser.board] if result else '',
               virtual_seconds=clock(), wall_seconds=wall_seconds, plies=len(game.history),
               plies_A=sum(e.seat.board == 0 for e in game.history),
               plies_B=sum(e.seat.board == 1 for e in game.history))
    for seat in ALL_SEATS:
        row[f'clock_{seat}'] = max(0.0, game.time_left(seat))
    for kind in ('minimax', 'random'):
        ds = [d for d in decisions if d['bot'] == kind]
        row[f'{kind}_moves'] = len(ds)
        row[f'{kind}_choice_seconds'] = sum(d['choice_seconds'] for d in ds)
        for metric in ('capture', 'drop', 'promotion', 'check'):
            row[f'{kind}_{metric}s'] = sum(bool(d[metric]) for d in ds)
        row[f'{kind}_capture_value'] = sum(d['capture_value'] for d in ds)
    return row, decisions


def describe(values):
    xs = sorted(values)
    if not xs:
        return dict(n=0, mean=None, median=None, p95=None, stdev=None)
    return dict(n=len(xs), mean=statistics.mean(xs), median=statistics.median(xs),
                p95=xs[max(0, math.ceil(0.95 * len(xs)) - 1)],
                stdev=statistics.stdev(xs) if len(xs) > 1 else 0.0)


def summarize(config, games, decisions):
    completed = [g for g in games if g['winner']]
    wins = Counter(g['winner'] for g in completed)
    # Incertitude sur le score d'une paire (0, 0.5 ou 1), les parties appariées
    # ne sont pas considérées comme deux observations indépendantes.
    pairs = []
    for p in sorted({g['pair'] for g in games}):
        pair_games = [g for g in games if g['pair'] == p]
        if len(pair_games) == 2 and all(g['winner'] for g in pair_games):
            pairs.append(sum(g['winner'] == 'minimax' for g in pair_games) / 2)
    ci = None
    if len(pairs) >= 2:
        rng = random.Random(config.seed)
        scores = sorted(statistics.mean(rng.choices(pairs, k=len(pairs))) for _ in range(3000))
        ci = [scores[74], scores[2924]]
    bots = {}
    for kind in ('minimax', 'random'):
        ds = [d for d in decisions if d['bot'] == kind]
        won = [g for g in completed if g['winner'] == kind]
        bots[kind] = dict(
            wins=wins[kind], win_rate_completed=wins[kind] / len(completed) if completed else None,
            win_virtual_seconds=describe([g['virtual_seconds'] for g in won]),
            win_wall_seconds=describe([g['wall_seconds'] for g in won]),
            win_plies=describe([g['plies'] for g in won]),
            choice_seconds=describe([d['choice_seconds'] for d in ds]),
            nodes=describe([d['nodes'] for d in ds if d['nodes'] is not None]),
            completed_depth=describe([d['depth'] for d in ds if d['depth'] is not None]),
            captures=sum(bool(d['capture']) for d in ds),
            capture_value=sum(d['capture_value'] for d in ds),
            drops=sum(bool(d['drop']) for d in ds),
            checks=sum(d['check'] for d in ds), promotions=sum(bool(d['promotion']) for d in ds),
            captures_per_100_moves=100 * sum(bool(d['capture']) for d in ds) / len(ds) if ds else None,
            drops_per_100_moves=100 * sum(bool(d['drop']) for d in ds) / len(ds) if ds else None,
            wins_by_reason=dict(Counter(g['reason'] for g in won)))
    by_seats = {}
    for seats in ('AW+BB', 'AB+BW'):
        subset = [g for g in games if g['minimax_seats'] == seats]
        ended = [g for g in subset if g['winner']]
        by_seats[seats] = dict(games=len(subset), completed=len(ended),
                              minimax_wins=sum(g['winner'] == 'minimax' for g in ended),
                              random_wins=sum(g['winner'] == 'random' for g in ended),
                              unfinished=len(subset) - len(ended))
    return dict(config=asdict(config), games_recorded=len(games), completed=len(completed),
                unfinished=len(games) - len(completed),
                unfinished_reasons=dict(Counter(g['reason'] for g in games if not g['winner'])),
                bots=bots, by_minimax_seats=by_seats,
                complete_pairs=len(pairs), paired_minimax_score=statistics.mean(pairs) if pairs else None,
                paired_bootstrap_95_percent=ci,
                pair_outcomes=dict(Counter(str(p) for p in pairs)),
                virtual_seconds=describe([g['virtual_seconds'] for g in games]),
                wall_seconds=describe([g['wall_seconds'] for g in games]),
                total_game_wall_seconds=sum(g['wall_seconds'] for g in games),
                environment=dict(python=platform.python_version(), platform=platform.platform(),
                                 chess=importlib.metadata.version('chess')),
                source_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                               for p in Path(__file__).parent.glob('*.py')},
                notes=[
                    'Horloges virtuelles : mêmes distributions de délai pour les deux bots.',
                    'Temps de calcul réel mesuré, mais non déduit des horloges virtuelles.',
                    'Les victoires suivent les règles du Game fourni, y compris les mats différés.',
                    'Une limite atteinte est une partie inachevée, jamais une nulle ou une défaite.',
                    'Les moyennes de victoire concernent uniquement les parties gagnées.',
                    'Bootstrap des paires complètes : exploratoire, peut dégénérer à 100 % de victoires.',
                    'Les graines ne garantissent pas les mêmes coups avec une recherche limitée en temps.',
                    'Ce tournoi contre random ne mesure pas un Elo.'])


MOVE_FIELDS = ['game', 'pair', 'ply', 'virtual_seconds', 'bot', 'seat', 'move', 'san',
               'choice_seconds', 'nodes', 'depth', 'capture', 'capture_value', 'drop', 'promotion', 'check']


def run(config: Config, output: Path):
    config.validate()
    output.mkdir(parents=True, exist_ok=True)
    # Pas d'écrasement silencieux d'un précédent tournoi.
    if any((output / f).exists() for f in ('games.csv', 'moves.csv', 'summary.json')):
        raise ValueError('Ce dossier contient déjà un tournoi : choisir un autre --output.')
    games, decisions = [], []
    interrupted = False
    with (output / 'games.csv').open('w', newline='', encoding='utf-8') as gf, \
         (output / 'moves.csv').open('w', newline='', encoding='utf-8') as mf:
        move_writer = csv.DictWriter(mf, fieldnames=MOVE_FIELDS)
        move_writer.writeheader()
        game_writer = None
        try:
            for i in range(config.games):
                # Export des coups d'une partie seulement après sa fin, pour
                # que le CSV et les agrégats portent sur les mêmes parties.
                row, ds = play_game(config, i)
                games.append(row)
                decisions.extend(ds)
                if game_writer is None:
                    game_writer = csv.DictWriter(gf, fieldnames=list(row))
                    game_writer.writeheader()
                game_writer.writerow(row)
                move_writer.writerows(ds)
                gf.flush()
                mf.flush()
                print(f"[{i+1}/{config.games}] minimax={row['minimax_seats']} "
                      f"gagnant={row['winner'] or 'inachevée'} ({row['reason']}) "
                      f"virtuel={row['virtual_seconds']:.2f}s réel={row['wall_seconds']:.2f}s "
                      f"coups={row['plies']}", flush=True)
        except KeyboardInterrupt:
            interrupted = True
            print('\nInterruption : bilan des parties déjà terminées.', flush=True)
    summary = summarize(config, games, decisions)
    summary['interrupted'] = interrupted
    (output / 'summary.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    print(f"\nTerminées : {summary['completed']}, inachevées : {summary['unfinished']}")
    for name, bot in summary['bots'].items():
        rate = bot['win_rate_completed']
        print(f"{name}: {bot['wins']} victoires, " + (f'{rate:.1%}' if rate is not None else 'taux indisponible'))
        w = bot['win_virtual_seconds']['mean']
        c = bot['choice_seconds']['mean']
        if w is not None:
            print(f'  Durée virtuelle moyenne des victoires : {w:.3f}s')
        if c is not None:
            print(f'  Temps réel moyen par choix de coup : {1000*c:.3f}ms')
    print(f"Fichiers : {output.resolve()}")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    defaults = Config()
    for field, value in asdict(defaults).items():
        parser.add_argument('--' + field.replace('_', '-'), type=type(value), default=value)
    parser.add_argument('--output', type=Path, default=Path('benchmark_results'))
    args = vars(parser.parse_args())
    output = args.pop('output')
    try:
        run(Config(**args), output)
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    main()
