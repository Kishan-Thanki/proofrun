"""Configuration loading and caching for Proofrun."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from proofrun.core.compiler import (
    ConfigCompilerError,
    load_and_compile_config,
)
from proofrun.core.config import ProofrunConfig


@dataclass
class ConfigProvider:
    """Manage a cached, compiled Proofrun configuration."""

    config_path: Path
    _config: ProofrunConfig | None = None
    _last_modified_ns: int | None = None
    _failed_modified_ns: int | None = None
    _failed_error: ConfigCompilerError | None = None

    def load(self) -> tuple[ProofrunConfig | None, ConfigCompilerError | None]:
        """Load the configuration when needed.

        The configuration is compiled on the first call and whenever the
        configuration file modification time changes.

        If a changed configuration is invalid, the last known-good
        configuration is retained and the compiler error is returned. A file
        that is still unchanged and still invalid is not parsed again; the
        same error is returned until the file is modified.

        Returns:
            A tuple containing the current configuration and an optional
            compilation error.
        """
        try:
            modified_ns = self.config_path.stat().st_mtime_ns
        except OSError as err:
            error = ConfigCompilerError(
                f"Unable to access configuration file '{self.config_path}': {err}"
            )
            return self._config, error

        if self._config is not None and self._last_modified_ns == modified_ns:
            return self._config, None

        if self._failed_error is not None and self._failed_modified_ns == modified_ns:
            return self._config, self._failed_error

        try:
            config = load_and_compile_config(self.config_path)
        except ConfigCompilerError as err:
            self._failed_modified_ns = modified_ns
            self._failed_error = err
            return self._config, err

        self._config = config
        self._last_modified_ns = modified_ns
        self._failed_modified_ns = None
        self._failed_error = None

        return self._config, None
