"""Launch the Streamlit UI.

Equivalent to `streamlit run app.py` but lets us use `python -m scripts.run_streamlit`
for consistency with the other scripts.
"""
import subprocess
import sys
from pathlib import Path


def main() -> None:
    project_root = Path(__file__).parent.parent
    app_path = project_root / "app.py"
    subprocess.run(
        [sys.executable, "-m", "streamlit", "run", str(app_path)],
        check=True,
    )


if __name__ == "__main__":
    main()