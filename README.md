# BLB (Banga-Luru Bytes)

AI-powered restaurant recommendations for Bangalore. A diner picks an area, budget, cuisines, dishes and a minimum rating, and adds anything else in their own words. The app shortlists matching restaurants from a Zomato dataset, and an LLM ranks the shortlist and explains each pick. Facts on each card always come from the dataset, never from the LLM.

There are two ways to use it:

| | What it is | Where it runs |
| --- | --- | --- |
| **Web app** | A FastAPI backend (`src/recommender/api.py`) and a static frontend (`frontend/`) | Railway and Vercel, or locally |
| **Streamlit app** | `app.py`, the original single-program version | Locally |

Both use the same search code in `src/recommender/`.

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
| `POST /recommend` | Display-ready results for a search. 422 for an invalid search, 429 over the rate limit, 503 without data. |

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
| `VITE_API_BASE_URL` | Frontend build | | The API's address. Built into the page, so not secret. |
