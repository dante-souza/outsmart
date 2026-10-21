import pytest
from tests.fakes import by_name, move


def no_progress(fraction: float, text: str) -> None:
    pass


def coins(arena) -> dict:
    return {name: player.coins for name, player in by_name(arena).items()}


def test_alliance_takes_extra_coins_from_the_victim(arena, scripts):
    scripts.script(
        Alex=[move(give="Blake", take="Charlie")],
        Blake=[move(give="Alex", take="Charlie")],
        Charlie=[move(give="Drew", take="Alex")],
        Drew=[move(give="Charlie", take="Blake")],
    )
    arena.do_turn(no_progress)
    players = by_name(arena)
    assert coins(arena) == {"Alex": 13, "Blake": 13, "Charlie": 9, "Drew": 13}
    assert players["Alex"].records[-1].alliances_with == ["Blake"]
    assert sorted(players["Charlie"].records[-1].alliances_against) == ["Alex", "Blake"]
    assert players["Drew"].records[-1].alliances_with == []


def test_private_messages_are_delivered(arena, scripts):
    arena.do_turn(no_progress)
    received = by_name(arena)["Blake"].records[-1].messages
    assert received == {
        sender: f"Hello Blake, from {sender}" for sender in ["Alex", "Charlie", "Drew"]
    }


def test_invalid_response_forfeits_the_move_and_costs_a_coin(arena, scripts):
    scripts.script(
        Alex=["I would rather not play"],
        Blake=[move(give="Charlie", take="Drew")],
        Charlie=[move(give="Drew", take="Blake")],
        Drew=[move(give="Blake", take="Charlie")],
    )
    arena.do_turn(no_progress)
    assert by_name(arena)["Alex"].records[-1].is_invalid_move
    assert coins(arena) == {"Alex": 11, "Blake": 12, "Charlie": 12, "Drew": 12}


@pytest.mark.parametrize("stray_recipient", ["Zed", "Alex"])
def test_messages_to_non_players_are_dropped(arena, scripts, stray_recipient):
    """
    Bug: a message addressed to someone who isn't another player crashed the whole turn with a KeyError,
    or, when players addressed themselves, showed up as a message received from themselves
    """
    messages = {other: f"Hi {other}" for other in ["Blake", "Charlie", "Drew"]}
    messages[stray_recipient] = "Is anyone there?"
    scripts.script(Alex=[move(give="Blake", take="Charlie", messages=messages)])
    arena.do_turn(no_progress)
    players = by_name(arena)
    assert players["Blake"].records[-1].messages["Alex"] == "Hi Blake"
    assert "Alex" not in players["Alex"].records[-1].messages


@pytest.mark.parametrize("give, take", [("Alex", "Charlie"), ("Blake", "Alex")])
def test_players_cannot_give_to_or_take_from_themselves(arena, scripts, give, take):
    """
    Bug: a player could give a coin to themselves, which also counted as an alliance with themselves,
    gaining 3 coins in one turn
    """
    scripts.script(
        Alex=[move(give=give, take=take)],
        Blake=[move(give="Charlie", take="Drew")],
        Charlie=[move(give="Drew", take="Blake")],
        Drew=[move(give="Blake", take="Charlie")],
    )
    arena.do_turn(no_progress)
    players = by_name(arena)
    assert players["Alex"].records[-1].is_invalid_move
    assert players["Alex"].coins == 11
    assert all(not player.records[-1].alliances_with for player in players.values())


def test_giving_and_taking_from_the_same_player_is_invalid(arena, scripts):
    scripts.script(Alex=[move(give="Blake", take="Blake")])
    arena.do_turn(no_progress)
    assert by_name(arena)["Alex"].records[-1].is_invalid_move


def test_each_player_is_asked_for_a_move_naming_only_the_others(arena, scripts):
    arena.do_turn(no_progress)
    request = next(
        r
        for r in scripts.requests
        if "Your player name is Alex" in r["messages"][1]["content"]
    )
    schema = request["response_format"].model_json_schema()
    assert sorted(schema["properties"]["give_coin_to"]["enum"]) == [
        "Blake",
        "Charlie",
        "Drew",
    ]
    assert sorted(schema["properties"]["take_coin_from"]["enum"]) == [
        "Blake",
        "Charlie",
        "Drew",
    ]
    assert sorted(schema["$defs"]["PrivateMessages"]["required"]) == [
        "Blake",
        "Charlie",
        "Drew",
    ]
