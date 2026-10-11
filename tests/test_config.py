import pytest

from testbench.config import ConfigError, expand_env


def test_env_vars_are_expanded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DSP_USER", "tester")
    assert expand_env({"user": "${DSP_USER}", "port": "${DSP_PORT:-443}"}) == {
        "user": "tester",
        "port": "443",
    }


def test_missing_env_var_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DSP_PASSWORD", raising=False)
    with pytest.raises(ConfigError, match="DSP_PASSWORD"):
        expand_env("${DSP_PASSWORD}")
