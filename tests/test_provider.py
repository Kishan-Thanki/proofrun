# Note: This test suite was generated and curated with the assistance of
# AI/agent tooling.

"""Unit tests for the Proofrun configuration manager."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from proofrun.config.compiler import ConfigCompilerError, load_and_compile_config
from proofrun.config.provider import ConfigProvider

VALID_CONFIG = """
version: "1.0"

global:
  base_url: "https://example.com"

scenarios:
  - name: "Test Scenario"
    interval_seconds: 30
    steps:
      - name: "Health Check"
        request:
          method: "GET"
          path: "/health"
        expect:
          status: 200
"""


def test_config_manager_loads_configuration(tmp_path: Path) -> None:
    """Verifies the configuration is loaded successfully."""
    config_file = tmp_path / "proofrun.yaml"
    config_file.write_text(VALID_CONFIG, encoding="utf-8")

    manager = ConfigProvider(config_file)

    config, error = manager.load()

    assert error is None
    assert config is not None
    assert config.scenarios[0].name == "Test Scenario"


def test_config_manager_returns_cached_configuration(
    tmp_path: Path,
) -> None:
    """Verifies repeated loads return the cached configuration."""
    config_file = tmp_path / "proofrun.yaml"
    config_file.write_text(VALID_CONFIG, encoding="utf-8")

    manager = ConfigProvider(config_file)

    first_config, first_error = manager.load()
    second_config, second_error = manager.load()

    assert first_error is None
    assert second_error is None
    assert first_config is second_config


def test_config_manager_reloads_modified_configuration(
    tmp_path: Path,
) -> None:
    """Verifies a modified configuration is recompiled."""
    config_file = tmp_path / "proofrun.yaml"
    config_file.write_text(VALID_CONFIG, encoding="utf-8")

    manager = ConfigProvider(config_file)

    first_config, error = manager.load()

    assert error is None
    assert first_config is not None

    original_stat = config_file.stat()

    updated_config = VALID_CONFIG.replace(
        'name: "Test Scenario"',
        'name: "Updated Scenario"',
    )
    config_file.write_text(updated_config, encoding="utf-8")

    modified_stat = type(original_stat)(
        list(original_stat[:8])
        + [original_stat.st_atime_ns, original_stat.st_mtime_ns + 1]
    )

    with patch.object(
        Path,
        "stat",
        return_value=modified_stat,
    ):
        second_config, second_error = manager.load()

    assert second_error is None
    assert second_config is not None
    assert second_config.scenarios[0].name == "Updated Scenario"


def test_config_manager_retains_last_known_good_configuration(
    tmp_path: Path,
) -> None:
    """Verifies an invalid update retains the previous valid configuration."""
    config_file = tmp_path / "proofrun.yaml"
    config_file.write_text(VALID_CONFIG, encoding="utf-8")

    manager = ConfigProvider(config_file)

    config, error = manager.load()

    assert error is None
    assert config is not None

    invalid_config = """
version: "1.0"

global:
  base_url: "https://example.com"

scenarios:
  - invalid configuration
"""
    config_file.write_text(invalid_config, encoding="utf-8")

    stat_result = config_file.stat()
    modified_stat = type(stat_result)(
        list(stat_result[:8])
        + [
            stat_result.st_atime_ns,
            stat_result.st_mtime_ns + 1,
        ]
    )

    with patch.object(
        Path,
        "stat",
        return_value=modified_stat,
    ):
        cached_config, compile_error = manager.load()

    assert cached_config is config
    assert compile_error is not None
    assert isinstance(compile_error, ConfigCompilerError)


def test_config_manager_handles_missing_file(tmp_path: Path) -> None:
    """Verifies a missing configuration file returns an error."""
    config_file = tmp_path / "missing.yaml"

    manager = ConfigProvider(config_file)

    config, error = manager.load()

    assert config is None
    assert error is not None
    assert isinstance(error, ConfigCompilerError)
    assert "Unable to access configuration file" in str(error)


def test_config_manager_handles_file_access_error(
    tmp_path: Path,
) -> None:
    """Verifies filesystem errors preserve the cached configuration."""
    config_file = tmp_path / "proofrun.yaml"
    config_file.write_text(VALID_CONFIG, encoding="utf-8")

    manager = ConfigProvider(config_file)

    config, error = manager.load()

    assert error is None
    assert config is not None

    with patch.object(
        Path,
        "stat",
        side_effect=PermissionError("Permission denied"),
    ):
        cached_config, stat_error = manager.load()

    assert cached_config is config
    assert stat_error is not None
    assert isinstance(stat_error, ConfigCompilerError)
    assert "PermissionError" in str(stat_error)


def test_unchanged_invalid_configuration_is_not_parsed_again(
    tmp_path: Path,
) -> None:
    config_file = tmp_path / "proofrun.yaml"
    config_file.write_text("version: '1.0'\nscenarios: nope\n", encoding="utf-8")
    manager = ConfigProvider(config_file)

    with patch(
        "proofrun.config.provider.load_and_compile_config",
        wraps=load_and_compile_config,
    ) as compile_config:
        _, first_error = manager.load()
        _, second_error = manager.load()
        _, third_error = manager.load()

    assert first_error is not None
    assert second_error is first_error
    assert third_error is first_error
    assert compile_config.call_count == 1


def test_fixing_an_invalid_configuration_recovers(tmp_path: Path) -> None:
    config_file = tmp_path / "proofrun.yaml"
    config_file.write_text("version: '1.0'\nscenarios: nope\n", encoding="utf-8")
    manager = ConfigProvider(config_file)

    config, error = manager.load()

    assert config is None
    assert error is not None

    config_file.write_text(VALID_CONFIG, encoding="utf-8")
    stat = config_file.stat()
    os.utime(config_file, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))

    config, error = manager.load()

    assert error is None
    assert config is not None

    config, error = manager.load()

    assert error is None
    assert config is not None


def test_file_access_error_does_not_expose_path_or_exception_details(
    tmp_path: Path,
) -> None:
    """Filesystem errors must not expose sensitive paths or raw error text."""
    secret = "PROOFRUN-TEST-SECRET-CANARY-PATH-3f8a"
    config_file = tmp_path / f"{secret}.yaml"
    manager = ConfigProvider(config_file)

    with patch.object(
        Path,
        "stat",
        side_effect=OSError(f"Permission denied: {secret}"),
    ):
        _, error = manager.load()

    assert error is not None
    assert "Unable to access configuration file" in str(error)
    assert secret not in str(error)
