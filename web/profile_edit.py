"""The buyer changes its preferences in data/buyers/<id>/profile.json.

Preferences only steer which fitting product the buyer's own agent picks; the trade server
never sees them. So, unlike the mandate, a change is not signed and not logged.
Usual orders are changed through the mandate (web.mandate_edit), which keeps both files in step.
"""

from __future__ import annotations

import json
from typing import Any

from onboarding.options import PACK_SIZES, PRIORITIES
from web.accounts import MandateFiles
from web.mandate_edit import EditError, write_profile

EDITABLE = {"priorities", "pack_size"}


def read_profile(files: MandateFiles, buyer_id: str) -> dict:
    path = files.profile(buyer_id)
    if path is None:
        raise EditError("profile_not_found", "This account has no preferences. Only a kitchen that "
                        "signed up on the onboarding page has them.")
    return json.loads(path.read_text(encoding="utf-8"))


def problems(profile: dict) -> list[str]:
    found = []
    priorities = profile.get("priorities")
    if not isinstance(priorities, list) or sorted(map(str, priorities)) != sorted(PRIORITIES):
        found.append("Rank each of the four priorities once: price, reliable delivery, "
                     "Finnish origin, sustainability.")
    if profile.get("pack_size") not in PACK_SIZES:
        found.append("Pack size must be small or large.")
    return found


def update_profile(*, buyer_id: str, change: Any, files: MandateFiles) -> dict:
    """The profile with the change saved. Raises EditError."""
    if not isinstance(change, dict):
        raise EditError("bad_field", "Send a JSON object with only the fields to change.")
    for key in change:
        if key == "usual_orders":
            raise EditError("bad_field", "Usual orders are changed with the mandate, which keeps "
                            "both files in step.")
        if key not in EDITABLE:
            raise EditError("bad_field", f"{key} cannot be changed here.")
    current = read_profile(files, buyer_id)
    new = {**current, **change}
    found = problems(new)
    if found:
        raise EditError("bad_profile", " ".join(found))
    if new != current:
        write_profile(files.profile(buyer_id), new)
    return new
