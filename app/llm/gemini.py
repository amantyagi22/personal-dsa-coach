"""The Gemini implementation of LLMProvider.

This is the only module in the project that imports the Gemini SDK.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from google import genai
from google.genai import errors, types
from pydantic import BaseModel, ValidationError

from app.config import Config, ModelRole
from app.llm.base import (
    LLMError,
    LLMProvider,
    RateLimitError,
    ToolCall,
    ToolSpec,
    ToolTurn,
)

logger = logging.getLogger(__name__)

_RATE_LIMIT_STATUS = 429

_ENV_VAR_FOR_ROLE: dict[ModelRole, str] = {
    "reasoning": "GEMINI_MODEL_REASONING",
    "fast": "GEMINI_MODEL_FAST",
}

# Message roles the agent may use. Gemini has no "tool" role of its own - tool
# results are sent as user-role parts carrying a function_response.
_AGENT_ROLES = frozenset({"user", "model", "tool"})


class GeminiProvider(LLMProvider):
    def __init__(self, config: Config, client: Any | None = None) -> None:
        self.config = config
        self.client = client or genai.Client(api_key=config.gemini_api_key)

    def _call(self, role: ModelRole, contents: Any, config: types.GenerateContentConfig) -> Any:
        """Make one Gemini call, translating SDK failures into LLMError.

        Takes the role rather than the model name so the error message can name
        the environment variable to change. Deriving the role back from the model
        gets it wrong whenever both roles point at the same model.
        """
        model = self.config.model_for(role)
        # The SDK runs the tool loop itself unless told not to. This project's
        # whole point is that the loop is hand-written, so disable it everywhere -
        # one choke point rather than one flag per call site.
        config.automatic_function_calling = types.AutomaticFunctionCallingConfig(disable=True)
        logger.info("Calling Gemini model %s", model)
        try:
            return self.client.models.generate_content(
                model=model, contents=contents, config=config
            )
        except errors.ClientError as exc:
            # Deliberately no retry. Free-tier limits are per-day, so retrying
            # cannot succeed and only spends what is left.
            if getattr(exc, "code", None) == _RATE_LIMIT_STATUS:
                raise RateLimitError(
                    f"Rate limit reached for model {model}. "
                    f"The free tier's daily quota for this model is used up.\n"
                    f"Try again tomorrow, or point {_ENV_VAR_FOR_ROLE[role]} "
                    f"at a different model."
                ) from exc
            if _is_invalid_key(exc):
                raise LLMError(
                    "Gemini rejected your API key.\n"
                    "\n"
                    "Check GEMINI_API_KEY in your .env. You can get a fresh key at\n"
                    "https://aistudio.google.com/apikey"
                ) from exc
            raise LLMError(f"Gemini rejected the request to {model}: {exc}") from exc
        except errors.APIError as exc:
            raise LLMError(f"Gemini call to {model} failed: {exc}") from exc
        except Exception as exc:
            # Transport failures - no network, DNS, timeouts - are not APIErrors.
            # Without this the user gets a raw traceback instead of a message.
            raise LLMError(
                f"Could not reach Gemini to call {model}: {exc}\n"
                f"Check your internet connection and try again."
            ) from exc

    def generate(
        self,
        prompt: str,
        *,
        role: ModelRole = "fast",
        system: str | None = None,
    ) -> str:
        response = self._call(role, prompt, types.GenerateContentConfig(system_instruction=system))
        text = getattr(response, "text", None)
        if not text:
            raise LLMError(f"Model {self.config.model_for(role)} returned an empty response.")
        return str(text)

    def generate_structured[T: BaseModel](
        self,
        prompt: str,
        schema: type[T],
        *,
        role: ModelRole = "fast",
        system: str | None = None,
    ) -> T:
        model = self.config.model_for(role)
        response = self._call(
            role,
            prompt,
            types.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
                response_schema=schema,
            ),
        )

        parsed = getattr(response, "parsed", None)
        if isinstance(parsed, schema):
            return parsed

        # Native enforcement is the normal path; this covers the case where the
        # SDK hands back JSON text without populating .parsed.
        text = getattr(response, "text", None)
        if not text:
            raise LLMError(f"Model {model} returned no {schema.__name__}.")
        try:
            return schema.model_validate(json.loads(text))
        except (json.JSONDecodeError, ValidationError) as exc:
            raise LLMError(
                f"Model {model} did not return a valid {schema.__name__}: {exc}"
            ) from exc

    def generate_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[ToolSpec],
        *,
        role: ModelRole = "fast",
        system: str | None = None,
    ) -> ToolTurn:
        config = types.GenerateContentConfig(
            system_instruction=system,
            tools=[_to_gemini_tool(tools)] if tools else None,
        )
        response = self._call(role, _to_gemini_contents(messages), config)

        calls = [
            ToolCall(name=call.name, arguments=dict(call.args or {}))
            for call in (getattr(response, "function_calls", None) or [])
        ]
        return ToolTurn(text=getattr(response, "text", None) or "", tool_calls=calls)


def _is_invalid_key(exc: errors.ClientError) -> bool:
    """Whether a 400 is really "your key is wrong".

    Matched on the reason string rather than the status, because Gemini returns a
    generic 400 INVALID_ARGUMENT for a bad key - the same status as a malformed
    request, which needs a completely different message.
    """
    return "API_KEY_INVALID" in str(exc)


def _to_gemini_tool(tools: list[ToolSpec]) -> types.Tool:
    return types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name=tool.name,
                description=tool.description,
                parameters_json_schema=tool.parameters,
            )
            for tool in tools
        ]
    )


def _to_gemini_contents(messages: list[dict[str, Any]]) -> list[types.Content]:
    """Translate the agent's message history into Gemini's Content format.

    Roles the agent uses: "user", "model", and "tool". Gemini has no "tool" role -
    tool results are user-role parts carrying a function_response.
    """
    contents: list[types.Content] = []
    for index, message in enumerate(messages):
        role = message.get("role", "user")
        if role not in _AGENT_ROLES:
            # Coercing an unknown role would silently misattribute a turn - the
            # model would act on it and no test would notice. "assistant" is the
            # most likely typo, since most other SDKs use it for "model".
            raise LLMError(
                f"Message {index} has role {role!r}. Expected one of {sorted(_AGENT_ROLES)}."
            )

        if role == "tool":
            contents.append(
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_function_response(
                            name=message["name"],
                            response={"result": message["content"]},
                        )
                    ],
                )
            )
            continue

        parts: list[types.Part] = []
        if message.get("content"):
            parts.append(types.Part(text=str(message["content"])))
        for call in message.get("tool_calls", []):
            parts.append(
                types.Part(function_call=types.FunctionCall(name=call.name, args=call.arguments))
            )
        if not parts:
            raise LLMError(
                f"Message {index} (role {role!r}) has neither content nor tool calls. "
                f"Dropping it would silently change the conversation."
            )
        contents.append(types.Content(role=role, parts=parts))
    return contents
