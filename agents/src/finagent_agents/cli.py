"""finagent-agents list | run <workflow> --input k=v | run-many <workflow> --inputs-file f.jsonl | serve"""

import argparse
import asyncio
import json
import sys

import httpx
from dotenv import load_dotenv

from finagent_agents.config import AgentSettings
from finagent_agents.context import MakeLLM
from finagent_agents.data import DataLayer, HttpDataLayer, MemoryDataLayer, RunRecord
from finagent_agents.registry import InputError, Workflow, WorkflowError, load_workflows
from finagent_agents.runner import Runner


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="finagent-agents")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="show workflows")
    run = sub.add_parser("run", help="run one workflow")
    run.add_argument("workflow")
    run.add_argument(
        "--input",
        "-i",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="JSON value, or plain text for str inputs; repeatable",
    )
    many = sub.add_parser("run-many", help="run a workflow once per JSONL line, concurrently")
    many.add_argument("workflow")
    many.add_argument("--inputs-file", required=True)
    serve = sub.add_parser("serve", help="run the HTTP API server")
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    return parser


def _parse_pairs(wf: Workflow | None, pairs: list[str]) -> dict:
    inputs = {}
    for pair in pairs:
        key, sep, raw = pair.partition("=")
        if not sep:
            raise InputError(f"--input {pair!r} must be KEY=VALUE")
        if wf is not None and wf.input.get(key) == "str":
            inputs[key] = raw
            continue
        try:
            inputs[key] = json.loads(raw)
        except json.JSONDecodeError:
            inputs[key] = raw
    return inputs


def _print_list(workflows: dict[str, Workflow]) -> None:
    for wf in workflows.values():
        print(f"{wf.name}  graph={wf.graph}  input={wf.input}  timeout={wf.timeout_s}s")
        for node, b in wf.nodes.items():
            print(
                f"    {node}: {b.model} effort={b.effort} prompt={b.prompt} tools={list(b.tools)}"
            )


def _print_run(run: RunRecord) -> None:
    print(
        f"[{run.status}] {run.workflow} {run.run_id} "
        f"tokens in={run.input_tokens} out={run.output_tokens} cache_read={run.cache_read_tokens}"
    )
    print(run.output if run.status == "ok" else run.error)


async def _run(
    cmd: str,
    workflow: str,
    batch: list[dict],
    settings: AgentSettings,
    workflows: dict[str, Workflow],
    make_llm: MakeLLM | None,
    data: DataLayer | None,
) -> list[RunRecord]:
    """Owns the data layer it creates, so its HTTP client lives and closes on this loop."""
    owned = None
    if data is None:
        if settings.data_url:
            data = owned = HttpDataLayer(settings.data_url, settings.data_token)
        else:
            data = MemoryDataLayer()
        print(f"store: {settings.data_url or 'memory (FINAGENT_AGENTS_DATA_URL unset)'}",
              file=sys.stderr)  # fmt: skip
    try:
        runner = Runner(
            workflows,
            data,
            make_llm=make_llm,
            max_runs=settings.max_runs,
            requests_per_second=settings.requests_per_second,
        )
        if cmd == "run":
            return [await runner.run(workflow, batch[0])]
        return await runner.run_many(workflow, batch)
    finally:
        if owned is not None:
            await owned.aclose()


def main(
    argv: list[str] | None = None,
    make_llm: MakeLLM | None = None,
    data: DataLayer | None = None,
) -> int:
    load_dotenv()
    args = _parser().parse_args(argv)
    settings = AgentSettings()
    workflows = load_workflows(settings.workflows_file, settings.prompts_dir)
    if args.cmd == "list":
        _print_list(workflows)
        return 0
    if args.cmd == "serve":
        import uvicorn

        from finagent_agents.server import create_app

        app = create_app(settings, workflows, data=data, make_llm=make_llm)
        uvicorn.run(app, host=args.host or settings.api_host, port=args.port or settings.api_port)
        return 0

    try:
        if args.cmd == "run":
            batch = [_parse_pairs(workflows.get(args.workflow), args.input)]
        else:
            with open(args.inputs_file, encoding="utf-8") as f:
                batch = [json.loads(line) for line in f if line.strip()]
        runs = asyncio.run(
            _run(args.cmd, args.workflow, batch, settings, workflows, make_llm, data)
        )
    except (InputError, WorkflowError) as e:
        print(e)
        return 2
    except httpx.HTTPError as e:
        print(f"data API error: {e}")
        return 1
    for run in runs:
        _print_run(run)
    return 0 if all(r.status == "ok" for r in runs) else 1


if __name__ == "__main__":
    raise SystemExit(main())
