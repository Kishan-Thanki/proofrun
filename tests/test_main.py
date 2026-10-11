"""Unit tests for the Proofrun CLI entrypoint."""

from __future__ import annotations

import runpy
from unittest.mock import patch


def test_main_execution() -> None:
    """Verifies that the module entrypoint starts the CLI."""
    with patch("proofrun.cli.commands.app") as mock_app:
        runpy.run_module(
            "proofrun.__main__",
            run_name="__main__",
        )

    mock_app.assert_called_once_with()


def test_main_import_does_not_start_cli() -> None:
    """Verifies importing the module does not start the CLI."""
    with patch("proofrun.cli.commands.app") as mock_app:
        runpy.run_module(
            "proofrun.__main__",
            run_name="proofrun.__main__",
        )

    mock_app.assert_not_called()
