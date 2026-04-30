"""Authentication helpers."""

import os

from dotenv import load_dotenv

load_dotenv()


def get_app_token() -> str | None:
    """Return the Socrata app token from the environment, or None."""
    return os.environ.get("SOCRATA_APP_TOKEN")
