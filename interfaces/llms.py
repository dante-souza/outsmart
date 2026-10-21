"""
This module contains the interface to external LLMs. Every model is reached through OpenRouter using LiteLLM,
and responses use structured outputs so that they always conform to a pydantic schema.
Create an LLM with one of the names from LLM.all_model_names(), then communicate with send().
This module should have no knowledge of the game itself.
"""

import logging
import os
from typing import Dict, List, Type, TypeVar

# Use the model map bundled with LiteLLM, rather than downloading the latest one on import
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

import litellm
from pydantic import BaseModel

litellm.suppress_debug_info = True
logging.getLogger("LiteLLM").setLevel(logging.WARNING)

Response = TypeVar("Response", bound=BaseModel)

# The model names used in the game and stored with past results, mapped to their ids on OpenRouter.
# Each of these supports structured outputs on OpenRouter
OPENROUTER_MODELS: Dict[str, str] = {
    "openai/gpt-6-luna": "openai/gpt-6-luna",
    "anthropic/claude-haiku-5.5": "anthropic/claude-haiku-5.5",
    "deepseek/deepseek-v4.1-flash-1017": "deepseek/deepseek-v4.1-flash-1017",
    "xiaomi/mimo-v2.6-flash": "xiaomi/mimo-v2.6-flash",
    "gpt-5.4": "openai/gpt-5.4",
    "gpt-5.2": "openai/gpt-5.2",
    "gpt-5.1": "openai/gpt-5.1",
    "gpt-5": "openai/gpt-5",
    "gpt-5-nano": "openai/gpt-5-nano",
    "gpt-5-mini": "openai/gpt-5-mini",
    "claude-opus-4-6": "anthropic/claude-opus-4.6",
    "claude-sonnet-4-5": "anthropic/claude-sonnet-4.5",
    "claude-haiku-4-5": "anthropic/claude-haiku-4.5",
    "claude-opus-4-5": "anthropic/claude-opus-4.5",
    "grok-4.20-0309-reasoning": "x-ai/grok-4.20",
    "gemini-2.5-flash": "google/gemini-2.5-flash",
    "gemini-2.5-pro": "google/gemini-2.5-pro",
    "gemini-3.1-pro-preview": "google/gemini-3.1-pro-preview",
    "openai/gpt-oss-120b": "openai/gpt-oss-120b",
}

# Only route requests to providers that support every parameter we send, including structured outputs
PROVIDER_ROUTING = {"require_parameters": True}

# Models reason with low effort, set with OpenRouter's own reasoning parameter, which all the models support;
# some providers don't support the top level reasoning_effort that LiteLLM would send instead
DEFAULT_REASONING_EFFORT = "low"

# These models reason far longer than the others at low effort, which slows down every turn, so reasoning is off.
# DeepSeek still reasoned for thousands of tokens at minimal, and MiMo can only switch reasoning on or off
REASONING_EFFORT: Dict[str, str] = {
    "deepseek/deepseek-v4.1-flash-1017": "none",
    "xiaomi/mimo-v2.6-flash": "none",
}


class LLM:
    """
    A model that is called through OpenRouter
    """

    model_name: str

    def __init__(self, model_name: str):
        """
        :param model_name: one of the names from LLM.all_model_names()
        """
        if model_name not in OPENROUTER_MODELS:
            raise ValueError(f"Unsupported model: {model_name}")
        self.model_name = model_name

    def __repr__(self) -> str:
        """
        :return: A string version of the receiver
        """
        return f"<LLM {self.model_name}>"

    def reasoning(self) -> Dict[str, str]:
        """
        :return: OpenRouter's reasoning parameter for this model
        """
        effort = REASONING_EFFORT.get(self.model_name, DEFAULT_REASONING_EFFORT)
        return {"effort": effort}

    def send(
        self, system_prompt: str, user_prompt: str, response_format: Type[Response]
    ) -> Response:
        """
        Send the prompts to the model, which must respond with JSON that conforms to the schema
        :param system_prompt: The system prompt passed to the LLM
        :param user_prompt: The user prompt passed to the LLM
        :param response_format: The pydantic class that the response must conform to
        :return: an instance of response_format, populated from the LLM's response
        """
        response = litellm.completion(
            model=f"openrouter/{OPENROUTER_MODELS[self.model_name]}",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format=response_format,
            extra_body={"provider": PROVIDER_ROUTING, "reasoning": self.reasoning()},
        )
        return response_format.model_validate_json(response.choices[0].message.content)

    @staticmethod
    def all_model_names() -> List[str]:
        """
        :return: a list of names of all the models supported
        """
        return list(OPENROUTER_MODELS.keys())
