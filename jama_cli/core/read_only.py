"""Read-only mode: the switch and the HTTP methods it lets through.

Read-only mode is turned on by ``read_only: true`` in a profile, by the
``JAMA_READ_ONLY`` environment variable or by ``jama serve --read-only``. Any
one of them is enough; none of them can turn it off again once another one has
turned it on.
"""

from __future__ import annotations

import os

from loguru import logger

READ_ONLY_ENV = "JAMA_READ_ONLY"

# HTTP methods that cannot change anything on the Jama server.
SAFE_METHODS: frozenset[str] = frozenset({"GET", "HEAD", "OPTIONS"})

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"", "0", "false", "no", "off"}


def parse_flag(value: str | None) -> bool:
    """Parse an on/off setting. An unrecognised value counts as on (fail closed)."""
    normalized = (value or "").strip().lower()
    if normalized in _TRUE:
        return True
    if normalized in _FALSE:
        return False
    logger.warning(f"Unrecognised value {value!r} for {READ_ONLY_ENV}; treating it as on")
    return True


def read_only_from_env() -> bool:
    """Whether ``JAMA_READ_ONLY`` turns read-only mode on."""
    return parse_flag(os.environ.get(READ_ONLY_ENV))


def refusal_message(what: str) -> str:
    """The message of a refused write."""
    return (
        f"Read-only mode is on: {what} would change Jama and was not sent. "
        f"Turn read-only mode off (profile 'read_only', {READ_ONLY_ENV}, "
        "'jama serve --read-only') to allow changes."
    )
