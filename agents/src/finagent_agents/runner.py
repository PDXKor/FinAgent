"""Async executor: one event loop, many concurrent runs, each isolated."""

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.rate_limiters import InMemoryRateLimiter
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph.state import CompiledStateGraph

from finagent_agents.context import GraphContext, MakeLLM
from finagent_agents.data import DataLayer, RunRecord
from finagent_agents.graphs import GRAPHS
from finagent_agents.llm import make_llm as default_make_llm
from finagent_agents.registry import Workflow, WorkflowError

RECURSION_LIMIT = 25  # LangGraph steps per run; stops runaway tool loops


class UsageCounter(BaseCallbackHandler):
    """Sums token usage over every LLM call in a run, including nested graphs."""

    run_inline = True

    def __init__(self):
        self.input_tokens = self.output_tokens = self.cache_read_tokens = 0

    def on_llm_end(self, response, **kwargs):
        for generations in response.generations:
            for gen in generations:
                usage = getattr(getattr(gen, "message", None), "usage_metadata", None)
                if not usage:
                    continue
                self.input_tokens += usage.get("input_tokens", 0)
                self.output_tokens += usage.get("output_tokens", 0)
                self.cache_read_tokens += (usage.get("input_token_details") or {}).get(
                    "cache_read", 0
                )


class Runner:
    """Runs workflows. Limits, outer to inner: per-workflow cap, `max_runs`, model rate limit."""

    def __init__(
        self,
        workflows: dict[str, Workflow],
        data: DataLayer,
        make_llm: MakeLLM | None = None,
        max_runs: int = 4,
        checkpointer: BaseCheckpointSaver | None = None,
        requests_per_second: float = 5.0,
    ):
        self.workflows = workflows
        self.data = data
        if make_llm is None:
            limiter = InMemoryRateLimiter(requests_per_second=requests_per_second)
            make_llm = lambda binding: default_make_llm(binding, rate_limiter=limiter)
        self.make_llm = make_llm
        self.checkpointer = checkpointer or InMemorySaver()
        self._global = asyncio.Semaphore(max_runs)
        self._caps: dict[str, asyncio.Semaphore] = {}
        self._graphs: dict[str, CompiledStateGraph] = {}

    def workflow(self, name: str) -> Workflow:
        try:
            return self.workflows[name]
        except KeyError:
            raise WorkflowError(f"unknown workflow {name!r}; known: {sorted(self.workflows)}") from None

    async def run(self, name: str, inputs: dict) -> RunRecord:
        wf = self.workflow(name)
        return await self._execute(wf, wf.validate(inputs))

    async def run_many(self, name: str, inputs_list: list[dict]) -> list[RunRecord]:
        """Run all concurrently. Inputs are validated first, so a typo starts nothing."""
        wf = self.workflow(name)
        validated = [wf.validate(i) for i in inputs_list]
        return list(await asyncio.gather(*(self._execute(wf, i) for i in validated)))

    def _graph(self, wf: Workflow) -> CompiledStateGraph:
        """Compiled once per workflow and shared by its runs."""
        if wf.name not in self._graphs:
            ctx = GraphContext(wf, self.data, self.make_llm)
            graph = GRAPHS[wf.graph].build(ctx)
            self._graphs[wf.name] = graph.compile(checkpointer=self.checkpointer)
        return self._graphs[wf.name]

    async def _execute(self, wf: Workflow, inputs: dict) -> RunRecord:
        run = RunRecord(
            run_id=uuid4().hex,
            workflow=wf.name,
            inputs=inputs,
            status="running",
            started_at=datetime.now(UTC),
            bindings=wf.describe(),
        )
        await self.data.save_run(run)
        usage = UsageCounter()
        config = {
            "configurable": {"thread_id": run.run_id},
            "callbacks": [usage],
            "max_concurrency": wf.max_concurrency,
            "recursion_limit": RECURSION_LIMIT,
        }
        cap = self._caps.setdefault(wf.name, asyncio.Semaphore(wf.max_concurrency))
        try:
            async with cap, self._global:
                graph = self._graph(wf)
                out = await asyncio.wait_for(graph.ainvoke({"inputs": inputs}, config), wf.timeout_s)
            run.status, run.output = "ok", out.get("result")
        except TimeoutError:
            run.status, run.error = "timeout", f"timed out after {wf.timeout_s}s"
        except Exception as e:  # noqa: BLE001 - one run's failure must not reach the others
            run.status, run.error = "failed", f"{type(e).__name__}: {e}"
        run.input_tokens = usage.input_tokens
        run.output_tokens = usage.output_tokens
        run.cache_read_tokens = usage.cache_read_tokens
        run.finished_at = datetime.now(UTC)
        await self.data.save_run(run)
        return run
