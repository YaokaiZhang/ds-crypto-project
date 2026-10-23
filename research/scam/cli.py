"""Compatibility import for installed launchers; all public commands use the pipeline."""
from .pipeline import main

if __name__ == "__main__":
    raise SystemExit(main())
