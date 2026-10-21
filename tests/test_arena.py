from game.arenas import Arena
from interfaces.llms import LLM
from tests.fakes import by_name, move

GANG_UP_ON_ALEX = dict(
    Alex=[move(give="Drew", take="Blake")],
    Blake=[move(give="Charlie", take="Alex")],
    Charlie=[move(give="Blake", take="Alex")],
    Drew=[move(give="Blake", take="Alex")],
)


def no_progress(fraction: float, text: str) -> None:
    pass


def play(arena) -> None:
    for _ in range(10):
        if arena.is_game_over:
            break
        arena.do_turn(no_progress)


def test_default_arena_has_four_different_supported_models():
    model_names = [player.llm.model_name for player in Arena.default().players]
    assert len(set(model_names)) == 4
    assert set(model_names) <= set(LLM.all_model_names())


def test_full_game_lasts_ten_turns_and_is_saved_once(arena, scripts, saved_games):
    play(arena)
    assert arena.is_game_over
    assert arena.turn == 10
    assert all(player.coins == 12 and player.is_winner for player in arena.players)
    assert len(saved_games) == 1
    names, llms, coins, ranks = saved_games[0]
    assert list(ranks) == [0, 0, 0, 0]
    table = arena.table()
    assert table.shape == (11, 4)
    assert not table.isna().any().any()


def test_bankruptcy_ends_the_game_early(arena, scripts, saved_games):
    scripts.script(**GANG_UP_ON_ALEX)
    play(arena)
    players = by_name(arena)
    assert arena.is_game_over
    assert arena.turn == 3
    assert players["Alex"].is_dead
    assert players["Alex"].coins == 0
    assert {name for name, player in players.items() if player.is_winner} == {
        "Blake",
        "Charlie",
    }
    assert len(saved_games) == 1
    names, llms, coins, ranks = saved_games[0]
    assert dict(zip(names, ranks)) == {"Alex": 3, "Blake": 0, "Charlie": 0, "Drew": 2}
    table = arena.table()
    assert table["Alex"].tolist()[:4] == [12, 7, 2, 0]
    assert table.iloc[4:].isna().all().all()


def test_bankruptcy_on_the_last_turn_saves_the_game_once(arena, scripts, saved_games):
    """
    Bug: when a player went bankrupt on turn 10, game over was handled twice and the game was saved twice
    """
    scripts.script(**GANG_UP_ON_ALEX)
    arena.turn = 10
    by_name(arena)["Alex"].coins = 4
    arena.do_turn(no_progress)
    assert arena.is_game_over
    assert len(saved_games) == 1
