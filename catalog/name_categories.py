"""One-off: name every product category with Gemini and write catalog/category_names.json.

The product file has category codes only. Gemini reads a sample of each category's product
names and suggests a short English name. Review the file before committing it; names.py
prefers its own hand-written names over these.

    uv run python -m catalog.name_categories
"""

import json
import sqlite3
from pathlib import Path

from catalog.load import DB_PATH

OUT = Path(__file__).resolve().parent / "category_names.json"
MODEL = "gemini-3.8-flash"
BATCH = 40
SAMPLE = 12

PROMPT = """You name product categories for Valio Aimo, a Finnish food-service wholesaler.
Each category below has a code and sample product names from it. Give each a short English
name, 1 to 4 words, sentence case, that a kitchen manager would recognise, for example
"Milk and sour milk", "Tomatoes", "Frozen fish fillets", "Disposable cups".
Base the name only on the sample products. Names must be different from each other: when two
categories are close, make the difference clear (e.g. "Frozen berries" and "Fresh berries").
Answer with one entry per code.

{rows}"""

SCHEMA = {
    "type": "array",
    "items": {"type": "object", "properties": {"code": {"type": "string"}, "name": {"type": "string"}},
              "required": ["code", "name"]},
}


def samples(conn: sqlite3.Connection) -> dict[str, list[str]]:
    by_category: dict[str, list[str]] = {}
    for category, name_en, name_fi in conn.execute(
            "SELECT category, name_en, name_fi FROM products ORDER BY category, id"):
        by_category.setdefault(category, []).append(name_en or name_fi)
    # Spread the sample over the whole category, not just its first ids.
    return {c: names[:: max(1, len(names) // SAMPLE)][:SAMPLE] for c, names in by_category.items()}


def main() -> None:
    import truststore
    from dotenv import load_dotenv
    from google import genai
    from google.genai import types

    from server.unusual import _env_key

    truststore.inject_into_ssl()
    load_dotenv()
    client = genai.Client(api_key=_env_key())
    found = samples(sqlite3.connect(DB_PATH))
    names = json.loads(OUT.read_text()) if OUT.exists() else {}
    todo = [c for c in sorted(found) if c not in names]
    for start in range(0, len(todo), BATCH):
        batch = todo[start:start + BATCH]
        rows = "\n".join(f"{c}: {' | '.join(found[c])}" for c in batch)
        response = client.models.generate_content(
            model=MODEL, contents=PROMPT.format(rows=rows),
            config=types.GenerateContentConfig(
                temperature=0, response_mime_type="application/json", response_json_schema=SCHEMA,
                thinking_config=types.ThinkingConfig(thinking_budget=0)))
        for entry in json.loads(response.text or "[]"):
            if entry.get("code") in batch and str(entry.get("name") or "").strip():
                names[entry["code"]] = entry["name"].strip()
        # Saved after every batch, so a failed run picks up where it stopped.
        OUT.write_text(json.dumps(dict(sorted(names.items())), ensure_ascii=False, indent=1) + "\n")
        print(f"{len(names)}/{len(found)} named")
    missing = sorted(set(found) - set(names))
    print("Missing:", ", ".join(missing) if missing else "none")


if __name__ == "__main__":
    main()
