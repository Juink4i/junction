"""A stand-in for Gemini that plays a fixed script, so the ADK wiring can be tested offline.

Each step is a function of the last tool response (a dict) that returns either
("call", tool_name, args) or ("text", "final words").
"""

from __future__ import annotations

from typing import Any, AsyncGenerator, Callable

from google.adk.models import BaseLlm, LlmRequest, LlmResponse
from google.genai import types

Step = Callable[[dict[str, Any]], tuple]


class ScriptedLlm(BaseLlm):
    model: str = "scripted"
    steps: list[Any] = []
    position: int = 0

    async def generate_content_async(self, llm_request: LlmRequest,
                                     stream: bool = False) -> AsyncGenerator[LlmResponse, None]:
        last: dict[str, Any] = {}
        for content in reversed(llm_request.contents or []):
            responses = [p.function_response for p in content.parts or [] if p.function_response]
            if responses:
                last = dict(responses[-1].response or {})
                break
        kind, *rest = self.steps[self.position](last)
        self.position += 1
        if kind == "call":
            name, args = rest
            part = types.Part(function_call=types.FunctionCall(name=name, args=args))
        else:
            part = types.Part(text=rest[0])
        yield LlmResponse(content=types.Content(role="model", parts=[part]), turn_complete=True)
