"""Package entry point: ``uv run hk-weather`` launches the Streamlit app.

Keeping this tiny wrapper means the app can be started from anywhere without
depending on the caller's working directory (Streamlit resolves relative script
paths against the CWD).
"""

import sys
from pathlib import Path

APP_PATH = Path(__file__).with_name("app.py")


def main() -> None:
    from streamlit.web import cli as stcli

    sys.argv = ["streamlit", "run", str(APP_PATH), *sys.argv[1:]]
    raise SystemExit(stcli.main())


if __name__ == "__main__":
    main()
