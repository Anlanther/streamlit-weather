# 🌧️ Hong Kong Weather Dashboard

A Streamlit dashboard powered by the **Hong Kong Observatory (HKO) Open Data API**, plus a **grounded chat assistant** that answers questions using _only_ the data the app has fetched.

![Python](https://img.shields.io/badge/python-3.14-blue)
![uv](https://img.shields.io/badge/managed%20by-uv-DE5FE9)
![Streamlit](https://img.shields.io/badge/streamlit-1.67-FF4B4B)

## Features

The app has two pages, reachable from the sidebar navigation.

### 📅 Forecast (default page)

| Section                      | What it does                                                                                                                                                                                                            |
| ---------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Weather warnings banner**  | Shows every active warning (Rainstorm, Tropical Cyclone, Very Hot, …) as a red/amber block with the first sentence of the official text, plus the last update time. Falls back to a quiet "No active weather warnings." |
| **7-day forecast dashboard** | Temperature, humidity, and Probability of Significant Rain (PSR) charts in tabs, with a compact summary table underneath.                                                                                               |

### 💬 Ask About the Forecast

Ask questions about the forecast. The model is instructed to answer _only_ from the injected
JSON, and each reply exposes a "Show retrieved context" expander so you can verify the answer.

## Data sources

- **9-day forecast** — `https://data.weather.gov.hk/weatherAPI/opendata/weather.php?dataType=fnd&lang=en`
- **Weather warnings** — `https://data.weather.gov.hk/weatherAPI/opendata/weather.php?dataType=warningInfo&lang=en`

No API key is required for HKO data. Chat runs against a **local LLM served by
[LM Studio](https://lmstudio.ai/)** — see below.

## Project structure

```
.
├── pyproject.toml      # Single source of dependency truth (PEP 621)
├── uv.lock             # Reproducible, hash-pinned resolution
├── .python-version     # Pinned interpreter for uv
└── src/streamlit_weather/
    ├── app.py            # entry point: st.navigation sidebar + page registration
    ├── pages/
    │   ├── dashboard.py  # forecast page: warnings, charts, table
    │   └── chat.py       # "Ask About the Forecast" page
    ├── data.py           # shared, cached data loading for every page
    ├── helpers.py        # page icon shared by the shell and pages
    ├── fetch.py          # API calls, @st.cache_data caching, fallback data
    ├── transform.py      # Cleaning, PSR scoring, warning summaries, prompt context
    ├── llm.py            # Grounded chat call to local LM Studio (testable, Streamlit-free)
    ├── __main__.py       # `hk-weather` entry point
    └── tests/
        ├── test_pipeline.py  # Parsing, fallback, validation, grounding
        └── test_app.py       # End-to-end UI smoke tests via streamlit.testing
```

Each layer only depends on the one below it (`pages → data → llm → transform → fetch`), so any
layer can be unit-tested or swapped without touching the others. The two pages share a single
cached fetch, so switching between them never re-hits the API.

## Setup

Requires [uv](https://docs.astral.sh/uv/). All dependencies live in `pyproject.toml`; there is no
`requirements.txt` to drift out of sync with it.

```bash
git clone <your-repo-url>
cd streamlit-weather
uv sync          # creates .venv, installs the locked environment + dev tools
```

### Connect to your local LM Studio model

The chat talks to LM Studio's OpenAI-compatible server, so everything stays on your
machine — no API key, and no data leaves the host.

1. In LM Studio, load a model (an instruction-tuned one works best).
2. Open **Developer** (or the server tab) and click **Start Server**. It listens on
   `http://localhost:1234` by default.
3. Nothing else is required: the app auto-detects the loaded model.

Configuration is optional and read from the environment:

| Variable             | Default                    | Purpose                                                            |
| -------------------- | -------------------------- | ------------------------------------------------------------------ |
| `LM_STUDIO_BASE_URL` | `http://localhost:1234/v1` | API root, if LM Studio listens elsewhere (another port or machine) |
| `LM_STUDIO_MODEL`    | _(auto-detected)_          | Model id to request; only needed when several models are loaded    |
| `LM_STUDIO_API_KEY`  | `lm-studio`                | Key sent to LM Studio; set only if your server validates keys      |

### Configuration via `.env`

Copy the example file once; it is git-ignored, so local values never get committed:

```bash
cp .env.example .env
```

Edit `.env` to point at another host/port or to pin a model, then just run the app —
`streamlit_weather.config` loads it automatically on startup:

```dotenv
LM_STUDIO_BASE_URL=http://192.168.1.50:1234/v1
LM_STUDIO_MODEL=lmstudio-community/qwen2.5-7b-instruct
```

Real environment variables always win over `.env` (the loader never overwrites an
already-set variable), so `export`, CI, and container configuration — including the
dev container's `LM_STUDIO_BASE_URL` — take precedence over the local file.

Verify the server is up before starting the app:

```bash
curl http://localhost:1234/v1/models
```

### Running inside the dev container

When the app runs in the provided dev container, LM Studio is on your **host**, so
`localhost` will not reach it. The container is preconfigured for this
(`.devcontainer/devcontainer.json`):

- `LM_STUDIO_BASE_URL` is set to `http://host.docker.internal:1234/v1`.
- `host.docker.internal:host-gateway` is mapped so that hostname resolves on
  Linux/OrbStack as well as Docker Desktop.
- Port `8501` is forwarded so the dashboard opens in your host browser.

By default LM Studio only listens on the host's loopback interface, which is **not**
reachable from inside a container. If you see `Connection refused`:

1. In LM Studio's server settings, enable **Serve on Local Network** (or
   "Listen on all interfaces") and keep the port at `1234`.
2. Restart the server, then check from the container shell:

    ```bash
    curl http://host.docker.internal:1234/v1/models
    ```

    If that still fails, allow incoming connections to LM Studio (port 1234) in your
    host firewall.

## Run

```bash
uv run hk-weather
```

The dashboard opens at <http://localhost:8501>. Equivalent invocations:

```bash
uv run streamlit run src/streamlit_weather/app.py
uv run python -m streamlit_weather
```

> **Tip:** If LM Studio is not running the dashboard still renders fully — the chat replies
> with a notice telling you to start the server, rather than failing silently.

## Development

```bash
uv run pytest          # 43 tests, no network required
uv run ruff check .    # lint
uv run ruff format .   # format
```

## Design notes

- **Caching** — both fetches use `@st.cache_data(ttl="10m")`, matching HKO's update cadence
  (forecast a few times daily, warnings on change) while avoiding a request on every rerun.
- **Graceful degradation** — network errors, non-2xx responses, invalid JSON, and structurally
  unexpected payloads all fall back to generated sample data with an
  `st.info("Showing cached sample data due to API unavailability.")` notice.
- **"No warnings" vs. "API down"** — HKO returns a bare `{}` when nothing is active. That is treated
  as a genuine all-clear, _not_ as a failure, so fake warnings never appear during calm weather.
  Covered by `test_fetch_warnings_all_clear_is_not_fallback`.
- **Schema tolerance** — the live API uses `PSR` (uppercase) while some documentation describes
  `psr`; the parser accepts either, plus `YYYYMMDD` or `YYYY-MM-DD` dates, and tolerates missing or
  null `forecastMaxrh`/`psr` fields.
- **Grounding** — the exact same string is sent to the model and shown in the context expander, so
  what you inspect is precisely what the model saw.
