from datetime import datetime, timedelta
from typing import List
import pytest
from game.arenas import Arena
from interfaces.llms import LLM
from models.games import Game, Result

FIRST, SECOND, THIRD, FOURTH, FIFTH = LLM.all_model_names()[:5]
RETIRED = "retired-model"
START = datetime(2026, 10, 1)


def game(when: datetime, *llm_ranks) -> Game:
    results = [
        Result(name=f"Player {index}", llm=llm, coins=12, rank=rank)
        for index, (llm, rank) in enumerate(llm_ranks)
    ]
    return Game(run_date=when, results=results)


def use_database(monkeypatch, games: List[Game]) -> List[int]:
    """
    Stand in for the DB with this list of games, which tests can add to
    :return: a list that gets an entry each time all the games are fetched
    """
    fetches = []

    def all_games(cls):
        fetches.append(len(games))
        return games

    monkeypatch.setattr(Game, "all", classmethod(all_games))
    monkeypatch.setattr(Game, "count", classmethod(lambda cls: len(games)))
    monkeypatch.setattr(
        Game,
        "latest",
        classmethod(
            lambda cls, k: sorted(games, key=lambda g: g.run_date, reverse=True)[:k]
        ),
    )
    Game.leaderboard.clear()
    return fetches


@pytest.fixture
def history(monkeypatch) -> List[Game]:
    """
    20 games, alternating between 2 results, so that every model has played at least 10 games
    """
    games = []
    for index in range(10):
        games.append(
            game(
                START + timedelta(hours=2 * index),
                (FIRST, 0),
                (SECOND, 1),
                (THIRD, 2),
                (FOURTH, 3),
            )
        )
        games.append(
            game(
                START + timedelta(hours=2 * index + 1),
                (FIRST, 0),
                (SECOND, 0),
                (THIRD, 2),
                (RETIRED, 3),
            )
        )
    use_database(monkeypatch, games)
    return games


def test_rankings_sorted_by_win_percentage(history):
    rankings = Arena.rankings()
    assert rankings["LLM"].tolist()[:2] == [FIRST, SECOND]
    rows = rankings.set_index("LLM")
    assert rows.loc[FIRST, "Games"] == 20
    assert rows.loc[FIRST, "Win %"] == 100
    assert rows.loc[SECOND, "Win %"] == 50
    assert rows.loc[THIRD, "Win %"] == 0
    assert rows.loc[FIRST, "Skill"] > rows.loc[FOURTH, "Skill"]


def test_rankings_only_show_models_still_supported(history):
    assert RETIRED not in Arena.rankings()["LLM"].tolist()


def test_rankings_only_show_models_with_at_least_ten_games(monkeypatch):
    games = [
        game(
            START + timedelta(hours=index),
            (FIRST, 0),
            (SECOND, 1),
            (THIRD, 2),
            (FOURTH, 3),
        )
        for index in range(9)
    ]
    games.append(
        game(
            START + timedelta(hours=9), (FIRST, 0), (SECOND, 1), (THIRD, 2), (FIFTH, 3)
        )
    )
    use_database(monkeypatch, games)
    assert set(Arena.rankings()["LLM"]) == {FIRST, SECOND, THIRD}


def test_rankings_are_only_recalculated_when_a_game_is_added(monkeypatch):
    games = [
        game(
            START + timedelta(hours=index),
            (FIRST, 0),
            (SECOND, 1),
            (THIRD, 2),
            (FOURTH, 3),
        )
        for index in range(10)
    ]
    fetches = use_database(monkeypatch, games)
    Arena.rankings()
    Arena.rankings()
    assert len(fetches) == 1
    games.append(
        game(
            START + timedelta(hours=10),
            (FOURTH, 0),
            (THIRD, 1),
            (SECOND, 2),
            (FIRST, 3),
        )
    )
    rows = Arena.rankings().set_index("LLM")
    assert len(fetches) == 2
    assert rows.loc[FOURTH, "Games"] == 11
    assert rows.loc[FOURTH, "Win %"] == pytest.approx(100 / 11)


def test_rankings_with_no_games(monkeypatch):
    use_database(monkeypatch, [])
    rankings = Arena.rankings()
    assert rankings.empty
    assert rankings.columns.tolist() == ["LLM", "Games", "Win %", "Skill"]


def test_latest_games_show_winners(history):
    both, first = f"{FIRST}, {SECOND}", FIRST
    assert Arena.latest()["Winner(s)"].tolist() == [both, first, both, first, both]
