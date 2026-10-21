"""
Run the Streamlit app headless with scripted LLMs, and click through a game
"""

import dotenv
import pytest
from streamlit.testing.v1 import AppTest


@pytest.fixture
def app(monkeypatch, scripts) -> AppTest:
    # The app loads .env on every run, which would bring back the real keys and database
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *args, **kwargs: False)
    app = AppTest.from_file("../app.py", default_timeout=60)
    app.run()
    return app


def button(app: AppTest, label: str):
    return next(b for b in app.button if b.label == label)


def test_page_shows_four_players_and_the_buttons(app):
    assert not app.exception
    assert [b.label for b in app.button] == ["Run Turn 1", "Run Game", "Restart Game"]
    assert [m.label for m in app.metric] == ["Coins"] * 4


def test_run_turn(app):
    button(app, "Run Turn 1").click().run()
    assert not app.exception
    assert app.session_state["arena"].turn == 2
    assert button(app, "Run Turn 2")
    assert not any(
        record.is_invalid_move
        for p in app.session_state["arena"].players
        for record in p.records
    )


def test_run_game_plays_to_the_end(app):
    button(app, "Run Game").click().run()
    assert not app.exception
    arena = app.session_state["arena"]
    assert arena.is_game_over
    assert all(b.disabled for b in app.button if b.label != "Restart Game")


def test_restart_game(app):
    button(app, "Run Turn 1").click().run()
    button(app, "Restart Game").click().run()
    assert not app.exception
    assert app.session_state["arena"].turn == 1
    assert button(app, "Run Turn 1")
