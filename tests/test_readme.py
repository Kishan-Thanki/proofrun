"""Keep the README's YAML examples valid against the real schema."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from proofrun.config.compiler import load_and_compile_config

README = Path(__file__).resolve().parent.parent / "README.md"


def _config_examples() -> list[str]:
    if not README.exists():  # pragma: no cover - e.g. tests run from an sdist
        return []

    blocks = re.findall(r"```yaml\n(.*?)```", README.read_text(), re.S)

    return [block for block in blocks if 'version: "1.0"' in block]


EXAMPLES = _config_examples()


def test_readme_has_complete_config_examples() -> None:
    assert len(EXAMPLES) >= 3


@pytest.mark.parametrize("index", range(len(EXAMPLES)))
def test_readme_config_examples_are_valid(index: int, tmp_path: Path) -> None:
    config_file = tmp_path / "example.yaml"
    config_file.write_text(EXAMPLES[index], encoding="utf-8")

    config = load_and_compile_config(config_file)

    assert config.scenarios
