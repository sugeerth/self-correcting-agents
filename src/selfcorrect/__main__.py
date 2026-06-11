"""``python -m selfcorrect`` — delegates to the CLI."""

from selfcorrect.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
