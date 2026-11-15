# Hosting the demo

The hosted demo is one container: the trade server on `127.0.0.1:8000` (inside only) and the
screens on `$PORT`, started by `deploy/start.sh`. Each boot makes fresh demo kitchens, keys,
mandates and order history (`server.make_mandate`), because the host keeps no disk.

## Hugging Face Spaces (free)

```bash
hf auth login                      # once, with a write token
git commit ...                     # the Space gets HEAD, not your working tree
uv run --with huggingface_hub python deploy/publish_space.py /tmp/space-staging
```

The script copies HEAD, encrypts `data/raw/` into `deploy/data.enc` with a fresh key, sets the
Space secrets `DATA_KEY`, `GEMINI_API_KEY` and `VALIO_API_KEY` from `.env`, and uploads. The
Space builds the `Dockerfile`; the build opens the data with `DATA_KEY` and builds
`data/catalog.db`. The Valio Aimo files are never committed or readable in the Space.

Judges open `https://<user>-valio-aimo-trade.hf.space/app/`. On the buyer chat page they type an
order; the agent runs on the server (one run per kitchen, two at once). `ASK_AGENT=off` (a Space
variable) turns the order box off.

## Railway (what the judges' link uses)

Hugging Face now needs a PRO plan for Docker Spaces, so the live demo runs on Railway's Free
plan. Railway builds the same `Dockerfile` from a local upload, so `data/raw/` goes up without
being committed (`.railwayignore` keeps out keys, `.env` and local state):

```bash
railway up --no-gitignore --detach           # from the repo root, linked to the project
railway variables --set GEMINI_API_KEY=... --set VALIO_API_KEY=...   # once
railway domain                                # once: the public *.up.railway.app link
```
