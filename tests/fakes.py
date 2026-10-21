"""
Stand-ins for the LLMs, so that games can be played in tests without calling any APIs.
Each player follows a script of moves; players without a script pass coins around in a circle.
"""

import json
import re
from collections import defaultdict
from typing import Callable, Dict, List, Optional, Tuple, Union

NAMES = ["Alex", "Blake", "Charlie", "Drew"]

PROMPT_NAMES = re.compile(
    r"Your player name is (\w+) and the other players are ([\w, ]+)\."
)

Step = Union[dict, str]


def move(give: str, take: str, messages: Optional[Dict[str, str]] = None) -> dict:
    """
    Describe one scripted move
    :param give: who to give a coin to
    :param take: who to take a coin from
    :param messages: private messages by recipient; by default, a greeting to each of the other players
    :return: a step for a script
    """
    return {"give": give, "take": take, "messages": messages}


def rotation(name: str) -> dict:
    """
    Give to the next player and take from the one after; if everyone does this, nobody's coins change
    """
    index = NAMES.index(name)
    return move(give=NAMES[(index + 1) % 4], take=NAMES[(index + 2) % 4])


def names_from_prompt(user_prompt: str) -> Tuple[str, List[str]]:
    """
    Work out which player is being prompted, and who the others are
    """
    name, others = PROMPT_NAMES.search(user_prompt).groups()
    return name, others.split(", ")


def render(step: Step, name: str, others: List[str]) -> str:
    """
    Turn a step into the text an LLM would reply with; a string step is returned as-is
    """
    if isinstance(step, str):
        return step
    messages = step["messages"]
    if messages is None:
        messages = {other: f"Hello {other}, from {name}" for other in others}
    return json.dumps(
        {
            "secret_strategy": f"{name} is following a script",
            "give_coin_to": step["give"],
            "take_coin_from": step["take"],
            "private_messages": messages,
        }
    )


def by_name(arena) -> Dict:
    """
    :return: the arena's players keyed by name
    """
    return {player.name: player for player in arena.players}


class Scripts:
    """
    The moves for each player, in order; the last step of a script repeats
    """

    def __init__(self, completion: Callable):
        """
        :param completion: the real litellm.completion, used to build responses with its mock_response option
        """
        self.real_completion = completion
        self.steps: Dict[str, List[Step]] = {}
        self.turns = defaultdict(int)
        self.requests: List[dict] = []

    def script(self, **steps: List[Step]) -> None:
        self.steps.update(steps)

    def reply(self, user_prompt: str) -> str:
        name, others = names_from_prompt(user_prompt)
        steps = self.steps.get(name) or [rotation(name)]
        step = steps[min(self.turns[name], len(steps) - 1)]
        self.turns[name] += 1
        return render(step, name, others)

    def completion(self, model: str, messages: List[dict], **kwargs):
        """
        Takes the place of litellm.completion, replying from the scripts without calling any API
        """
        self.requests.append({"model": model, "messages": messages, **kwargs})
        content = self.reply(messages[1]["content"])
        return self.real_completion(
            model=model, messages=messages, mock_response=content
        )
