# BLB (Banga-Luru Bytes)

AI-powered restaurant recommendations for Bangalore. A diner picks an area, budget, cuisines, dishes and a minimum rating, and adds anything else in their own words. The app shortlists matching restaurants from a Zomato dataset, and an LLM ranks the shortlist and explains each pick. Facts on each card always come from the dataset, never from the LLM.

There are two ways to use it:

| | What it is | Where it runs |
| --- | --- | --- |
| **Web app** | A FastAPI backend (`src/recommender/api.py`) and a static frontend (`frontend/`) | Railway and Vercel, or locally |
| **Streamlit app** | `app.py`, the original single-program version | Locally |

Both use the same search code in `src/recommender/`.

**Live:** https://blb-frontend.vercel.app (API: https://blb-benga-luru-bytes-production-f4839515.up.railway.app)

## Web App Features

| Feature | How it works |
| --- | --- |
| **Search in your own words** | Type "pocket-friendly biryani in BTM, rated 4+" and press Go. `frontend/src/parse.js` matches the sentence against the real lists of areas, cuisines and dishes, fills in the form, and searches. It runs in the browser, so it's instant and makes no AI call. Words it doesn't recognise go to "Anything else?". |
| **Dropdowns** | Area, cuisine and dish open a list on click, narrow as you type, and work with the arrow keys and Enter. The item under the cursor grows and turns bold. |
| **Example searches** | The empty page offers one-tap searches, such as "Biryani in BTM under ₹500". |
| **Clear loading** | Placeholder cards and a line saying what's happening ("Ranking with AI…") while a search runs. |
| **Shareable searches** | Each search is kept in the page address (`?area=BTM&dish=Biryani`), so it can be shared or bookmarked, and the browser's Back button returns to the previous search. |
| **Remembers the last search** | The form is filled in with your last search when you come back. Kept in this browser only. |
| **Refine** | One-tap buttons above the results: Pocket friendly (the next budget down), a higher minimum rating, Include new places, and Clear filters. |
| **Phone layout** | After a search on a narrow screen, the form shrinks to a one-line summary with "Edit search", so the results are in view. |
| **Card actions** | Directions (opens Google Maps, no key needed), Share (the phone's share sheet, or copies a link), Save, and More like this (same main cuisine and price band in the same area). |
| **Shortlist** | ♥ Saved in the header opens your saved places side by side: rating, price for two, cuisines and area. Kept in this browser only. |
| **Feedback** | 👍 / 👎 under each "Why this fits". Counted on the API and written to its log, as labelled examples for the evaluation. |
| **Look** | The top result is marked "Top pick" with a crown, ratings are coloured by band (green 4.0+, amber 3.5 to 3.9, grey below), and each card has a small cuisine icon. One set of rounded line icons in the accent colour marks the form labels, budgets (✦, ₹, ₹₹, ₹₹₹), refine buttons, card badges, "Liked for", "Why this fits" and the review quote, and the example searches have food emoji. |
| **When the AI is busy** | If Groq's per-minute limit is reached, results are ranked by rating and the page says why, with a Try again button. |

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

`uv sync` installs every dependency group: the API's own dependencies, plus `ingest` (for building the data), `ui` (Streamlit) and `dev` (tests). The server image installs only the API's.

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

### Streamlit app

```bash
uv run streamlit run app.py
```

## API

| Endpoint | What it returns |
| --- | --- |
| `GET /health` | `{"status": "ok", "build_id": ..., "ai_ranking": true}`, or 503 if the data didn't load |
| `GET /options` | Areas, cuisines and dishes in menu order, the budget choices, and form defaults |
| `POST /recommend` | Display-ready results for a search. 422 for an invalid search, 429 over the rate limit, 503 without data. `ai_busy` is true when the AI was skipped because the provider's per-minute limit was reached. |
| `POST /feedback` | Records a thumbs up or down on one result's explanation: `{"restaurant", "rank", "helpful", "ai_ranked"}`. 204, or 429 over 30 a minute per client. |
| `GET /stats` | Counts since the server started: searches, AI-ranked searches, cache hits, fallbacks by reason, top areas, cuisines and dishes, budgets, and feedback. Nothing personal. |

The full contract is in the [deployment plan](Doc/deployment-plan.md#api-contract). All text is plain: the frontend sets it with `textContent`, so dataset, review and LLM text always displays literally.

## Test

```bash
uv run pytest
```

```bash
uv run ruff check .
```

No test calls a paid API. Two live tests run only with `RUN_LIVE_TESTS=1`.

The frontend has no test suite. Check it with `npm run build` and in a browser against the local API.

Usage counts are at `GET /stats` on the API. Feedback lines are in the API log; on Railway, run `railway logs` and look for `feedback`.

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

1. **Railway (API):** deploy from GitHub. `railway.json` builds the `Dockerfile`, which builds `data/` during the build and checks `/health` before switching traffic. Set `GROQ_API_KEY`, `ALLOWED_ORIGINS` and `TRUSTED_PROXY_HOPS=1`.
2. **Vercel (frontend):** import the repository with Root Directory `frontend/`, and set `VITE_API_BASE_URL` to the Railway address.
3. Add the Vercel address to `ALLOWED_ORIGINS` on Railway.

**Before making it public:** the dataset states no licence. Keep the deployment private until that is resolved.

## Configuration

| Variable | Used by | Default | Notes |
| --- | --- | --- | --- |
| `LLM_PROVIDER` | API, Streamlit | `groq` | Or `anthropic` |
| `GROQ_API_KEY`, `ANTHROPIC_API_KEY` | API, Streamlit | | Secret. Only the chosen provider's key is needed. |
| `LLM_MODEL` | API, Streamlit | Provider default | `openai/gpt-oss-120b` for Groq |
| `LLM_EFFORT` | API, Streamlit | `low` | |
| `LLM_TIMEOUT_SECONDS` | API, Streamlit | `45` | |
| `MAX_CANDIDATES`, `MAX_RESULTS` | API, Streamlit | `8`, `5` | |
| `DATA_DIR` | All | `./data` | |
| `ALLOWED_ORIGINS` | API | None | Comma-separated web origins allowed to call the API |
| `ALLOWED_ORIGIN_REGEX` | API | None | Optional pattern, for preview deployments |
| `RATE_LIMIT_PER_MINUTE` | API | `10` | Searches per client per minute. 0 turns it off. |
| `TRUSTED_PROXY_HOPS` | API | `0` | `1` behind Railway's proxy, so the limit sees each diner's address |
| `WARM_CACHE_AREAS` | API | None (off) | Comma-separated areas whose default search is kept cached, so it's instant and makes no AI call for diners. Each costs about one AI search an hour, so name only a few on Groq's free plan. |
| `WARM_CACHE_INTERVAL_SECONDS` | API | `60` | Wait between warm-up searches, which leaves most of the per-minute token limit for diners |
| `VITE_API_BASE_URL` | Frontend build | | The API's address. Built into the page, so not secret. |
