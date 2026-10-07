from monke.sim.cli import run_game


def test_fuzz_200_games():
    for seed in range(200):
        run_game(seed)
