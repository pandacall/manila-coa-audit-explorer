"""Gemini on Vertex AI behind the model-adapter interface.

Credentials are Application Default Credentials locally and the service account on Cloud Run; there
are no API keys. The model name comes from configuration.
"""

from __future__ import annotations

from google import genai
from google.genai import types

from coa_explorer.models import Message, ModelTurn, ToolCall, ToolSpec, Usage

MAX_OUTPUT_TOKENS = 8192


class GeminiAdapter:
    def __init__(self, *, project: str, location: str, model: str):
        self._client = genai.Client(vertexai=True, project=project, location=location)
        self._model = model

    def generate(self, system: str, messages: list[Message], tools: list[ToolSpec]) -> ModelTurn:
        response = self._client.models.generate_content(
            model=self._model,
            contents=[to_content(message) for message in messages],
            config=types.GenerateContentConfig(
                system_instruction=system,
                tools=[types.Tool(function_declarations=[declaration(tool) for tool in tools])],
                # When only one tool is offered (the engine's last round) the model must call it.
                tool_config=types.ToolConfig(
                    function_calling_config=types.FunctionCallingConfig(
                        mode=types.FunctionCallingConfigMode.ANY,
                        allowed_function_names=[tool.name for tool in tools],
                    )
                )
                if len(tools) == 1
                else None,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
                max_output_tokens=MAX_OUTPUT_TOKENS,
            ),
        )
        content = response.candidates[0].content if response.candidates else None
        parts = (content.parts if content else None) or []
        calls = [
            ToolCall(
                part.function_call.name, dict(part.function_call.args or {}), part.function_call.id
            )
            for part in parts
            if part.function_call
        ]
        text = "".join(part.text for part in parts if part.text and not part.thought) or None
        return ModelTurn(text=text, tool_calls=calls, raw=content, usage=usage_of(response))


def usage_of(response: types.GenerateContentResponse) -> Usage | None:
    metadata = response.usage_metadata
    if metadata is None:
        return None
    # Thinking tokens are billed as output.
    output = (metadata.candidates_token_count or 0) + (metadata.thoughts_token_count or 0)
    return Usage(input_tokens=metadata.prompt_token_count or 0, output_tokens=output)


def declaration(tool: ToolSpec) -> types.FunctionDeclaration:
    return types.FunctionDeclaration(
        name=tool.name, description=tool.description, parameters_json_schema=tool.parameters
    )


def to_content(message: Message) -> types.Content:
    if message.role == "model" and message.raw is not None:
        return message.raw  # replayed as received, thought signatures included
    if message.role == "tool":
        return types.Content(
            role="user",
            parts=[
                types.Part(
                    function_response=types.FunctionResponse(
                        id=result.call.id,
                        name=result.call.name,
                        response={"result": result.content},
                    )
                )
                for result in message.tool_results
            ],
        )
    return types.Content(
        role="model" if message.role == "model" else "user",
        parts=[types.Part(text=message.text or "(no response)")],
    )
