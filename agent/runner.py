"""Run the buyer agent once: one request in, a summary and the server's decision out."""

from __future__ import annotations

import asyncio
import logging
import sys
from dataclasses import dataclass, field
from typing import Any

from agent.config import Settings
from agent.events import EventSink
from agent.instructions import build_instruction, preference_lines
from agent.mcp_link import MandateRefused, TradeLink
from agent.tools import AskFn, Toolbox

APP_NAME = "valio_buyer"
MAX_LLM_CALLS = 40

# ADK's telemetry warns on every scripted-model turn; keep the demo terminal readable.
logging.getLogger("google_adk.google.adk.telemetry").setLevel(logging.ERROR)


def check_model(model: str) -> str | None:
    """None if the Gemini model can be used with this key, otherwise a plain explanation.

    One tiny generation (a retired model can still be listed but refuse to generate), so a
    wrong model fails before the demo starts instead of in the middle of a scene.
    """
    from google import genai
    from google.genai import types

    client = genai.Client()  # keep a reference: a garbage-collected client closes its connection
    try:
        client.models.generate_content(model=model, contents="Reply with OK.",
                                       config=types.GenerateContentConfig(max_output_tokens=8))
        return None
    except Exception as exc:  # 404 retired model, 403 bad key, network down
        message = str(exc).split("{", 1)[0].strip() or type(exc).__name__
        return (f"Gemini model {model!r} is not usable with this key ({message}). "
                f"Set AGENT_MODEL in .env, for example gemini-3.8-flash.")


@dataclass
class RunResult:
    summary: str = ""
    outcome: str | None = None  # confirmed, needs_clarification, pending_approval, approved, rejected
    request: dict[str, Any] | None = None
    quotes: list[dict[str, Any]] = field(default_factory=list)
    orders: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    mandate_problem: str | None = None  # the server did not accept the mandate; go back to onboarding



def make_ask(replies: list[str], interactive: bool | None = None) -> AskFn:
    """Answers come from scripted replies first, then the terminal if a person is there."""
    queue = list(replies)
    interactive = sys.stdin.isatty() if interactive is None else interactive

    async def ask(question: str) -> str | None:
        if queue:
            return queue.pop(0)
        if interactive:
            return (await asyncio.to_thread(input, "   Your answer: ")).strip() or None
        return None

    return ask


def build_agent(settings: Settings, toolbox: Toolbox):
    from google.adk.agents import LlmAgent
    from google.genai import types

    instruction = build_instruction(settings.buyer_name, settings.today, settings.gullible,
                                    settings.profile)
    retry = types.HttpRetryOptions(attempts=5, initial_delay=2.0, max_delay=30.0,
                                   http_status_codes=[429, 500, 502, 503, 504])
    return LlmAgent(
        name="buyer_agent",
        description="Buys from Valio Aimo for a professional kitchen: Shopper and Substitution.",
        model=settings.model,
        instruction=lambda _ctx: instruction,  # a function, so ADK does not template {braces}
        tools=toolbox.functions(),
        generate_content_config=types.GenerateContentConfig(
            temperature=0.2, http_options=types.HttpOptions(retry_options=retry)),
    )


async def run_buyer(request: str, settings: Settings, sink: EventSink,
                    ask: AskFn | None = None) -> RunResult:
    from google.adk.agents.run_config import RunConfig
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    ask = ask or make_ask(settings.replies)
    sink.add_secret(settings.mandate_token)
    model_name = settings.model if isinstance(settings.model, str) else getattr(settings.model, "model", "?")
    sink.publish("run_start", buyer_name=settings.buyer_name, model=model_name,
                 request=request, gullible=settings.gullible,
                 preferences=preference_lines(settings.profile))
    sink.publish("user", text=request)
    result = RunResult()

    toolbox: Toolbox | None = None
    try:
        async with TradeLink(settings.server_url, settings.mandate_token) as link:
            toolbox = Toolbox(link, settings, sink, ask)
            sessions = InMemorySessionService()
            runner = Runner(app_name=APP_NAME, agent=build_agent(settings, toolbox),
                            session_service=sessions)
            session = await sessions.create_session(app_name=APP_NAME, user_id=settings.buyer)
            message = types.Content(role="user", parts=[types.Part(text=request)])
            try:
                async for event in runner.run_async(user_id=settings.buyer, session_id=session.id,
                                                    new_message=message,
                                                    run_config=RunConfig(max_llm_calls=MAX_LLM_CALLS)):
                    if event.author == "user" or not event.content or not event.content.parts:
                        continue
                    texts = [p.text for p in event.content.parts if p.text and not p.thought]
                    if texts and not event.partial:
                        text = "\n".join(texts).strip()
                        sink.publish("agent", text=text)
                        result.summary = text
            except Exception as exc:  # the model or network failed; report it, never guess
                result.error = f"{type(exc).__name__}: {exc}"
                sink.publish("note", text=f"The agent stopped because of an error: {result.error}")
            finally:
                await runner.close()
    except MandateRefused as refused:
        where = refused.onboarding_url or "the onboarding page"
        result.mandate_problem = f"{refused.message} Sign a new mandate at {where}."
        result.error = f"mandate refused ({refused.code})"
        sink.publish("note", text="Valio Aimo did not accept this kitchen's mandate. "
                                  f"{result.mandate_problem}")

    if toolbox is not None:
        result.outcome = toolbox.outcome
        result.request = toolbox.request
        result.quotes = toolbox.quotes
        result.orders = toolbox.orders
    sink.publish("run_end", outcome=result.outcome, summary=result.summary, error=result.error)
    return result
