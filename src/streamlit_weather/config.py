"""Environment configuration, loaded from ``.env`` at import time.

All runtime configuration comes from the environment. For local development a
``.env`` file (copied from ``.env.example``) supplies the same keys, so values
live in one place instead of being exported by hand per shell.

The loader is deliberately small and dependency-free:

* It only fills variables that are **not already set**, mirroring
  ``python-dotenv``'s ``load_dotenv(override=False)`` and 12-factor conventions.
  Real environment variables — CI, containers, ``export``, the dev container —
  therefore always win over a stale local file.
* Values may be quoted (``KEY="value"``) or bare; ``#`` starts a comment except
  inside quotes.
"""

import os
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent

# Candidate locations, first match wins: the CWD (where the app is launched,
# matching Streamlit's own config resolution) then the repo root, two levels
# above ``src/streamlit_weather`` in a source checkout.
_ENV_SEARCH_PATHS = (
    Path.cwd() / ".env",
    PACKAGE_DIR.parents[1] / ".env",
)


def _parse_value(raw: str) -> str:
    """Strip inline comments and matching quotes from a ``KEY=value`` right-hand side."""
    value = raw.strip()

    if value[:1] in {'"', "'"}:
        quote = value[0]
        end = value.find(quote, 1)
        if end != -1:
            return value[1:end]

    # Unquoted value: anything after a ``#`` comment marker is ignored.
    return value.split("#", 1)[0].strip()


def load_dotenv(path: Path | None = None) -> Path | None:
    """Populate ``os.environ`` from a ``.env`` file; return the file used, if any.

    Existing environment variables are never overwritten, so explicit exports and
    container configuration take precedence over local defaults.
    """
    candidates = (path,) if path is not None else _ENV_SEARCH_PATHS
    for candidate in candidates:
        if not candidate.is_file():
            continue
        for line in candidate.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, _, raw_value = stripped.partition("=")
            key = key.removeprefix("export ").strip()
            if key:
                os.environ.setdefault(key, _parse_value(raw_value))
        return candidate
    return None


def env(name: str, default: str | None = None) -> str | None:
    """Read a variable, treating an empty string as unset."""
    value = os.environ.get(name)
    return value if value else default


# Load once on import so every module (``llm``, pages, entry point) sees the
# same resolved configuration regardless of which imports first.
load_dotenv()
