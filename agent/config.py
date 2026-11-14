"""Settings for one buyer-agent run.

The agent process only ever loads the Gemini key. The Valio Aimo key belongs to the
server, so it is never read here, even though it sits in the same .env file.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent
MANDATE_DIR = ROOT / "data" / "mandates"

BUYERS = {
    "hotel": "Hotel Chain Oy / Helsinki Central",
    "cafe": "Café Aalto",
    "school": "Espoo School Kitchens",
}

DEFAULT_MODEL = "gemini-2.5-flash"


@dataclass
class Settings:
    buyer: str = "hotel"
    server_url: str = "http://localhost:8000/mcp"
    web_url: str | None = "http://localhost:8080"
    model: str = DEFAULT_MODEL
    mandate_token: str = ""
    mandate_source: str = ""
    approval_wait_s: float = 300.0
    poll_every_s: float = 3.0
    gullible: bool = False
    replies: list[str] = field(default_factory=list)
    today: date = field(default_factory=date.today)

    @property
    def buyer_name(self) -> str:
        return BUYERS.get(self.buyer, self.buyer)


def load_mandate(buyer: str, explicit: str | None = None) -> tuple[str, str]:
    """Return (token, where it came from).

    Order: an explicit file, $MANDATE_TOKEN, data/mandates/<buyer>.(jws|jwt|txt), and finally
    the fake server's demo token. The real server rejects the demo token, which is correct.
    """
    if explicit:
        return Path(explicit).read_text().strip(), explicit
    if os.environ.get("MANDATE_TOKEN"):
        return os.environ["MANDATE_TOKEN"].strip(), "$MANDATE_TOKEN"
    for ext in ("jws", "jwt", "txt"):
        path = MANDATE_DIR / f"{buyer}.{ext}"
        if path.exists():
            return path.read_text().strip(), str(path.relative_to(ROOT))
    return f"demo-{buyer}", "demo token (fake server only)"


def load_gemini_key(env_file: Path = ROOT / ".env") -> bool:
    """Put only the Gemini key into the environment. Returns whether one is available."""
    if os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY"):
        return True
    values = dotenv_values(env_file) if env_file.exists() else {}
    key = values.get("GEMINI_API_KEY") or values.get("GOOGLE_API_KEY")
    if key:
        os.environ["GEMINI_API_KEY"] = key
    model = values.get("AGENT_MODEL")
    if model and not os.environ.get("AGENT_MODEL"):
        os.environ["AGENT_MODEL"] = model
    return bool(key)


def secret_values() -> list[str]:
    """Values that must never be shown: used to scrub everything the agent prints or sends."""
    names = ("GEMINI_API_KEY", "GOOGLE_API_KEY", "VALIO_API_KEY", "MANDATE_TOKEN")
    return [v for n in names if (v := os.environ.get(n)) and len(v) >= 8]
