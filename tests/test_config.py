"""Settings a run reads from the environment."""

from __future__ import annotations

import pytest

from subcast import config


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("7", 7),
        ("0", 0),
        ("-3", 0),
        (None, config.DEFAULT_LIST_LIMIT),
        ("", config.DEFAULT_LIST_LIMIT),
        ("half a number", config.DEFAULT_LIST_LIMIT),
    ],
)
def test_the_list_limit_can_be_set_and_falls_back(
    monkeypatch,
    value: str | None,
    expected: int,
):
    """
    A setting that cannot be read is the default, not an error: refusing
    to play over an environment variable would be worse than ignoring it.
    """

    if value is None:
        monkeypatch.delenv(
            config.LIST_LIMIT_ENVIRONMENT,
            raising=False,
        )

    else:
        monkeypatch.setenv(
            config.LIST_LIMIT_ENVIRONMENT,
            value,
        )

    assert config.list_limit() == expected
