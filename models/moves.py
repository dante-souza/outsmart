from pydantic import BaseModel, Field, create_model
from typing import Dict, List, Literal, Self, Type


class Move(BaseModel):
    """
    A player's move, taken from the structured response that comes back from an LLM
    """

    strategy: str
    give: str
    take: str
    messages: Dict[str, str]

    @staticmethod
    def response_format(other_names: List[str]) -> Type[BaseModel]:
        """
        Create the schema that a player's LLM must respond with, using structured outputs.
        Coins can only be given to and taken from the other players, and each of them must get a private message
        :param other_names: the names of the other players
        :return: a pydantic class describing the response
        """
        other_player = Literal[tuple(other_names)]
        messages = create_model(
            "PrivateMessages",
            **{
                name: (str, Field(description=f"Your private message for {name}"))
                for name in other_names
            },
        )
        return create_model(
            "MoveResponse",
            secret_strategy=(
                str,
                Field(
                    description="Secretly explain your plans, for your own benefit - the other players will not see this"
                ),
            ),
            give_coin_to=(
                other_player,
                Field(description="The player you will give a coin to"),
            ),
            take_coin_from=(
                other_player,
                Field(description="The player you will take a coin from"),
            ),
            private_messages=(
                messages,
                Field(description="A private message for each of the other players"),
            ),
        )

    @classmethod
    def from_response(cls, response: BaseModel) -> Self:
        """
        Create a Move from a response that conforms to the schema from Move.response_format()
        :param response: the structured response from the LLM
        :return: a Move object
        """
        return cls(
            strategy=response.secret_strategy,
            give=response.give_coin_to,
            take=response.take_coin_from,
            messages=response.private_messages.model_dump(),
        )
