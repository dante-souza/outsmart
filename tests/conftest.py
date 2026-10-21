import litellm
import pymongo
import pytest
from game.arenas import Arena
from game.players import Player
from tests.fakes import NAMES, Scripts


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    """
    Keep every test away from the real leaderboard database, LLM APIs and local settings
    """
    monkeypatch.delenv("MONGO_URI", raising=False)
    monkeypatch.delenv("ARENA", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    def no_database(*args, **kwargs):
        raise RuntimeError("Tests must not connect to MongoDB")

    monkeypatch.setattr(pymongo, "MongoClient", no_database)


@pytest.fixture
def scripts(monkeypatch) -> Scripts:
    """
    Replace LLM calls with scripted replies; tests add moves with scripts.script(Alex=[...])
    """
    scripts = Scripts(litellm.completion)
    monkeypatch.setattr(litellm, "completion", scripts.completion)
    return scripts


@pytest.fixture
def arena(scripts) -> Arena:
    return Arena([Player(name, "gpt-5-nano") for name in NAMES])


@pytest.fixture
def saved_games(monkeypatch) -> list:
    """
    Capture games that would be saved to the database
    """
    saved = []
    monkeypatch.setenv("MONGO_URI", "mongodb://tests-never-connect")
    monkeypatch.setattr(Arena, "do_save_game", lambda self, *args: saved.append(args))
    return saved
