from pathlib import Path

import pytest

from testbench import demo


@pytest.fixture
def demo_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    project = tmp_path / "project"
    demo.create_example_project(project)
    monkeypatch.chdir(project)
    return project
