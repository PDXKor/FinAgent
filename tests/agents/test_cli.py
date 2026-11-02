import json

import pytest

from finagent_agents.cli import main

from .conftest import ai, first_human

pytestmark = pytest.mark.component


@pytest.fixture(autouse=True)
def no_dotenv(monkeypatch, tmp_path):
    # Keep the repo .env out: load_dotenv searches upward from the package, not the cwd.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("finagent_agents.cli.load_dotenv", lambda: None)
    monkeypatch.delenv("FINAGENT_AGENTS_DATA_URL", raising=False)


def test_list_prints_workflows(capsys):
    assert main(["list"]) == 0
    out = capsys.readouterr().out
    assert "ping" in out and "company_brief" in out and "screen_then_brief" in out


def test_run_prints_output(capsys, scripted):
    llm = scripted(lambda msgs: ai("pong " + first_human(msgs)))
    assert main(["run", "ping", "--input", "text=hi"], make_llm=lambda b: llm) == 0
    out = capsys.readouterr().out
    assert "ok" in out and "pong text: hi" in out


def test_run_parses_json_input_values(capsys, scripted):
    seen = []
    llm = scripted(lambda msgs: (seen.append(first_human(msgs)), ai("x"))[1])
    argv = ["run", "screen_then_brief", "--input", 'tickers=["AAPL","TSLA"]']
    assert main(argv, make_llm=lambda b: llm) == 0
    assert "ticker: AAPL" in seen and "ticker: TSLA" in seen


def test_failed_run_returns_1(capsys, scripted):
    def boom(msgs):
        raise RuntimeError("boom")

    assert main(["run", "ping", "--input", "text=hi"], make_llm=lambda b: scripted(boom)) == 1
    assert "boom" in capsys.readouterr().out


def test_bad_input_returns_2(capsys, scripted):
    assert main(["run", "ping"], make_llm=lambda b: scripted(lambda m: ai("x"))) == 2
    assert "text" in capsys.readouterr().out


def test_run_many_reads_jsonl(tmp_path, capsys, scripted):
    path = tmp_path / "in.jsonl"
    path.write_text("\n".join(json.dumps({"text": t}) for t in ["a", "b"]) + "\n\n")
    llm = scripted(lambda msgs: ai("pong " + first_human(msgs)))
    assert main(["run-many", "ping", "--inputs-file", str(path)], make_llm=lambda b: llm) == 0
    out = capsys.readouterr().out
    assert "pong text: a" in out and "pong text: b" in out
