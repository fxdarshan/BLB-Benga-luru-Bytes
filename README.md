# BLB (Banga-Luru Bytes)

AI-powered restaurant recommendations for Bangalore. A diner picks an area, budget, cuisines, dishes and a minimum rating, and adds anything else in their own words. The app shortlists matching restaurants from a Zomato dataset, and an LLM ranks the shortlist and explains each pick. Facts on each card always come from the dataset, never from the LLM.

It's a web app: a FastAPI backend (`src/recommender/api.py`) on Railway and a static frontend (`frontend/`) on Vercel, both of which also run locally. The search code is in `src/recommender/`. The first version was a single Streamlit program, `app.py`; it was removed on 2026-11-14, once the web app did everything it did and more.

**Live:** https://blb-frontend.vercel.app (API: https://blb-benga-luru-bytes-production-f4839515.up.railway.app)

## Web App Features

| Feature | How it works |
| --- | --- |
| **Search in your own words** | Type "pocket-friendly biryani in BTM, rated 4+" and press Go. `frontend/src/parse.js` matches the sentence against the real lists of areas, cuisines and dishes, fills in the form, and searches. It runs in the browser, so it's instant and makes no AI call. Words it doesn't recognise go to "Anything else?", which also matches related words: "quiet" finds reviews saying "peaceful" or "cozy", and "work" finds "laptop" or "wifi". |
| **Dropdowns** | Area, cuisine and dish open a list on click, narrow as you type, and work with the arrow keys and Enter. The item under the cursor grows and turns bold. |
| **Home** | Clicking the BLB logo or name starts over: the form returns to its defaults, the own-words box, page address and remembered search are cleared, any search still running is ignored, and the welcome screen returns. The shortlist and theme are kept. Ctrl or Cmd-click still opens a new tab. |
| **Example searches** | The empty page offers one-tap searches, such as "Biryani in BTM under ₹500". |
| **Instant results** | The best matches by rating appear in about 0.2 seconds, from `POST /shortlist`, with a note that the AI is ranking them. The AI's picks and reasons replace them when they arrive, about 2 to 20 seconds later. If the AI request fails, the rating-ranked results stay, with a Try again button. |
| **Clear loading** | Placeholder cards and a line saying what's happening ("Ranking with AI…") until the first results arrive. |
| **Shareable searches** | Each search is kept in the page address (`?area=BTM&dish=Biryani`), so it can be shared or bookmarked, and the browser's Back button returns to the previous search. |
| **Remembers the last search** | The form is filled in with your last search when you come back. Kept in this browser only. |
| **Refine** | One-tap buttons above the results: Pocket friendly (the next budget down), a higher minimum rating, Include new places, and Clear filters. |
| **Phone layout** | After a search on a narrow screen, the form shrinks to a one-line summary with "Edit search", so the results are in view. |
| **Card actions** | Directions (opens Google Maps, no key needed), Share (the phone's share sheet, or copies a link), Save, and More like this (same main cuisine and price band in the same area). |
| **Shortlist** | ♥ Saved in the header opens your saved places side by side: rating, price for two, cuisines and area. Kept in this browser only. |
| **Feedback** | 👍 / 👎 under each "Why this fits". Counted on the API and written to its log, as labelled examples for the evaluation. |
| **Look** | The top result is marked "Top pick" with a crown, ratings are coloured by band (green 4.0+, amber 3.5 to 3.9, grey below), and each card has a small cuisine icon. One set of rounded line icons in the accent colour marks the form labels, budgets (✦, ₹, ₹₹, ₹₹₹), refine buttons, card badges, "Liked for", "Why this fits" and the review quote, and the example searches have food emoji. |
| **Light and dark themes** | Follows the phone or computer's setting, and the sun/moon button in the header switches it. The choice is remembered in this browser. The light theme is a warm cream version of the dark one, for reading outdoors; all text is at least 5:1 contrast in both. |
| **Illustrations** | Small line drawings in the accent colour for the welcome screen (a steaming bowl and skyline), no matches (an empty plate), the AI being busy (a pot on the boil) and errors (an unplugged cable). |
| **Depth and motion** | A warm glow on the header and the top pick, cards that lift on hover, a ring around the chosen budget, lists and the shortlist that slide open, buttons that press in, a heart that pops on Save, and cross-fades when results or the theme change. All motion stops when the device asks for reduced motion. |
| **When the AI is busy** | If Groq's per-minute limit stops the main model, the search is retried once on a smaller model (`openai/gpt-oss-20b`), which Groq limits separately. Only if that is busy too are results ranked by rating, and the page says why, with a Try again button. Identical searches that arrive together share one AI call, and an optional daily token cap pauses the AI until midnight UTC. |

## Documents

- [Problem statement](Doc/problemStatement.md)
- [Architecture](Doc/architecture.md)
- [Implementation plan](Doc/implementation-plan.md)
- [Deployment plan](Doc/deployment-plan.md): Railway and Vercel, step by step
- [Evaluation plan](Doc/eval.md) and [edge cases](Doc/edge-cases.md)

## Set Up

You need [uv](https://docs.astral.sh/uv/) and, for the frontend, Node.js 22.12 or later.

```bash
uv sync
```

```bash
cp .env.example .env
```

Put your Groq key in `.env` as `GROQ_API_KEY`. Without a key the app still works, ranking results by score with no AI explanations.

Build the restaurant data once. The first run downloads the 574 MB dataset from Hugging Face:

```bash
uv run python -m recommender.ingest
```

This writes `data/restaurants.parquet` and `data/metadata.json`. The dataset revision is pinned, so every build gives the same data.

`uv sync` installs every dependency group: the API's own dependencies, plus `ingest` (for building the data) and `dev` (tests). The server image installs only the API's.

## Run Locally

### Web app

Start the API on port 8000:

```bash
uv run uvicorn --factory recommender.api:create_app --port 8000
```

In another terminal, start the frontend on port 5173:

```bash
cd frontend
npm install
cp .env.example .env.local
npm run dev
```

Open http://localhost:5173. `ALLOWED_ORIGINS` in `.env` must include `http://localhost:5173`, as the example does.

## API

| Endpoint | What it returns |
| --- | --- |
| `GET /health` | `{"status": "ok", "build_id": ..., "ai_ranking": true, "last_ai_call": {...}}`, or 503 if the data didn't load. `ai_ranking` means a key is set; `last_ai_call` says whether the AI works: `ok`, the failure `reason` (such as `authentication` for a wrong key), the model and when, or null before the first call. |
| `GET /options` | Areas, cuisines and dishes in menu order, the budget choices, and form defaults |
| `POST /recommend` | Display-ready results for a search. 422 for an invalid search, 429 over the rate limit, 503 without data. `ai_busy` is true when the AI was skipped because the provider's per-minute limit was reached. |
| `POST /shortlist` | The same search ranked by rating alone, at once, with no AI call. Same body as `/recommend`, plus `ai_pending`: true when `/recommend` will have the AI rank it. 60 a minute per client, apart from searches, and not counted in `/stats`. |
| `POST /feedback` | Records a thumbs up or down on one result's explanation: `{"restaurant", "rank", "helpful", "ai_ranked"}`. 204, or 429 over 30 a minute per client. |
| `GET /stats` | Counts since the store was created: searches, AI-ranked searches, cache hits, fallbacks by reason, top areas, cuisines and dishes, budgets, and feedback. Nothing personal. `storage` says whether they're kept in a file (`persistent`, so they survive restarts) or in memory. |

The full contract is in the [deployment plan](Doc/deployment-plan.md#api-contract). All text is plain: the frontend sets it with `textContent`, so dataset, review and LLM text always displays literally.

## Test

```bash
uv run pytest
```

```bash
uv run ruff check .
```

No test calls a paid API. Two live tests run only with `RUN_LIVE_TESTS=1`.

The frontend's rules (the search in the page address, rating bands, refine, More like this and the sentence parser) have unit tests that run with Node's own test runner, with no extra packages:

```bash
cd frontend
```

```bash
npm test
```

The page itself is split into `main.js` (wiring), `dom.js` (icons and element helpers), `pickers.js` (the dropdowns), `search-logic.js` (pure rules) and the smaller modules beside them. Check the whole page in a browser against the local API too.

**Uptime:** [`.github/workflows/uptime.yml`](.github/workflows/uptime.yml) checks the site and `/health` every 15 minutes. If either is down for three tries a minute apart, it opens an issue labelled `uptime`, which GitHub emails you, and closes it once both are back. It never fails, so it can't hold up a deploy. GitHub pauses scheduled workflows in a public repository after 60 days without a commit. For error alerts from inside the API, an error tracker such as Sentry needs an account of your own.

**CI:** [`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs the lint, the formatting check, the tests, the frontend tests and the frontend build on every pull request and every push to `main`. Railway deploys the API only after it passes on the commit.

**Usage counts and feedback** are kept in a SQLite file in `STATE_DIR`, so they survive restarts and deploys (in memory when it's unset, as locally). On Railway, `STATE_DIR` is `/app/state`, where the `blb-state` volume is mounted. The counts are at `GET /stats` on the API. To export the feedback as CSV for the evaluation:

```bash
uv run python -m recommender.usage_store /app/state/blb.sqlite3 > feedback.csv
```

On Railway, run it inside the service with `railway ssh`. Each piece of feedback is also written to the API log as a `feedback {...}` line.

## Evaluate

The evaluation harness is in `tests/eval/`. The preflight and self-check make no API calls:

```bash
uv run python tests/eval/preflight.py
```

```bash
uv run python tests/eval/selfcheck.py
```

Paid runs need a spending cap. See [Phase 6 of the implementation plan](Doc/implementation-plan.md#phase-6-evaluation-and-tuning).

## Deploy

The [deployment plan](Doc/deployment-plan.md) has the full steps. In short:

1. **Railway (API):** deploy from GitHub. The `Dockerfile` builds `data/` during the build. Set `GROQ_API_KEY`, `ALLOWED_ORIGINS` and `TRUSTED_PROXY_HOPS=1` as variables in Railway.
2. **Vercel (frontend):** import the repository with Root Directory `frontend/`, and set `VITE_API_BASE_URL` to the Railway address.
3. Add the Vercel address to `ALLOWED_ORIGINS` on Railway.

**Railway's settings are code**, in [`.railway/railway.ts`](.railway/railway.ts): the Dockerfile builder, the `/health` check that must pass before traffic moves to a new deployment, restart on failure, the watch paths (only changes to `src/`, the Docker files and the Python lock files redeploy the API, so frontend and docs commits don't restart it), "Wait for CI", and the `blb-state` volume at `/app/state`. A service with a volume can't run two deployments at once, so each API redeploy has a short outage. Railway never reads the file during a deploy. To change a setting, edit the file, then from the repository root:

```bash
npm install
```

```bash
npm run iac:plan
```

```bash
npm run iac:apply
```

`iac:plan` only shows what would change. Variables, including the Groq key, stay in Railway's dashboard: the file never holds them.

**Changes go through pull requests:** work on a branch, open a pull request, and merge it once CI passes. Merging to `main` deploys the API (after CI passes again on `main`) and the web page.

**Change the API before the page.** Vercel deploys the page in seconds and Railway the API in minutes, so after a merge the new page briefly talks to the old API. Keep API changes additive (new endpoints and fields only), ship them first, and have the page treat a missing endpoint or field as absent, as it does for `/shortlist` and `/feedback`. Remove something from the API only after the page has stopped using it. Vercel skips builds when nothing in `frontend/` changed since its last deployment (`frontend/scripts/ignore-build.sh`).

**Before making it public:** the dataset states no licence. Keep the deployment private until that is resolved.

## Configuration

| Variable | Used by | Default | Notes |
| --- | --- | --- | --- |
| `LLM_PROVIDER` | API | `groq` | Or `anthropic` |
| `GROQ_API_KEY`, `ANTHROPIC_API_KEY` | API | | Secret. Only the chosen provider's key is needed. |
| `LLM_MODEL` | API | Provider default | `openai/gpt-oss-120b` for Groq |
| `LLM_FALLBACK_MODEL` | API | `openai/gpt-oss-20b` for Groq | Tried once when the main model hits its per-minute limit. `none` turns it off. Groq only: Claude has its own fallback. |
| `LLM_DAILY_TOKEN_LIMIT` | API | `0` (no cap) | AI tokens allowed per UTC day; after that, results are ranked by score until midnight UTC. Counted in memory, so a restart starts the count again. Today's use is in `/stats` as `ai_budget`. |
| `LLM_EFFORT` | API | `low` | |
| `LLM_TIMEOUT_SECONDS` | API | `45` | |
| `MAX_CANDIDATES`, `MAX_RESULTS` | API | `8`, `5` | |
| `DATA_DIR` | All | `./data` | |
| `ALLOWED_ORIGINS` | API | None | Comma-separated web origins allowed to call the API |
| `ALLOWED_ORIGIN_REGEX` | API | None | Optional pattern, for preview deployments |
| `RATE_LIMIT_PER_MINUTE` | API | `10` | Searches per client per minute. 0 turns it off. |
| `TRUSTED_PROXY_HOPS` | API | `0` | `1` behind Railway's proxy, so the limit sees each diner's address |
| `WARM_CACHE_AREAS` | API | None (off) | Comma-separated areas whose default search is kept cached, so it's instant and makes no AI call for diners. Each costs about one AI search an hour, so name only a few on Groq's free plan. |
| `WARM_CACHE_INTERVAL_SECONDS` | API | `60` | Wait between warm-up searches, which leaves most of the per-minute token limit for diners |
| `STATE_DIR` | API | None (in memory) | Directory for the SQLite file of usage counts and feedback. The Docker image sets `/app/state`. |
| `VITE_API_BASE_URL` | Frontend build | | The API's address. Built into the page, so not secret. |
