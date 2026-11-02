"""Async executor: one event loop, many concurrent runs, each isolated."""

import asyncio
import logging
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.rate_limiters import InMemoryRateLimiter
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph.state import CompiledStateGraph

from finagent_agents.context import GraphContext, MakeLLM
from finagent_agents.data import DataLayer, RunRecord
from finagent_agents.events import EventHub, EventPublisher, RunStream, token_usage
from finagent_agents.graphs import GRAPHS
from finagent_agents.llm import make_llm as default_make_llm
from finagent_agents.registry import Workflow, WorkflowError

log = logging.getLogger(__name__)

RECURSION_LIMIT = 25  # LangGraph steps per run; stops runaway tool loops
INTERRUPTED = "interrupted: the agents process stopped before the run finished"
SAVE_ATTEMPTS = 3  # final-result saves, on top of the data layer's own retries
SAVE_BACKOFF_S = 1.0  # doubled per attempt


class UsageCounter(BaseCallbackHandler):
    """Sums token usage over every LLM call in a run, including nested graphs."""

    run_inline = True

    def __init__(self):
        self.input_tokens = self.output_tokens = self.cache_read_tokens = 0

    def on_llm_end(self, response, **kwargs):
        i, o, c = token_usage(response)
        self.input_tokens += i
        self.output_tokens += o
        self.cache_read_tokens += c


class Runner:
    """Runs workflows. Limits, outer to inner: per-workflow cap, `max_runs`, model rate limit.

    `run`/`run_many` await results (CLI). `start` returns at once and runs in the background
    (server); `cancel` stops such a run. With `events`, each run publishes a live stream.
    """

    def __init__(
        self,
        workflows: dict[str, Workflow],
        data: DataLayer,
        make_llm: MakeLLM | None = None,
        max_runs: int = 4,
        checkpointer: BaseCheckpointSaver | None = None,
        requests_per_second: float = 5.0,
        events: EventHub | None = None,
    ):
        self.workflows = workflows
        self.data = data
        if make_llm is None:
            limiter = InMemoryRateLimiter(requests_per_second=requests_per_second)
            make_llm = lambda binding: default_make_llm(binding, rate_limiter=limiter)
        self.make_llm = make_llm
        self.checkpointer = checkpointer or InMemorySaver()
        self.events = events
        self._global = asyncio.Semaphore(max_runs)
        self._caps: dict[str, asyncio.Semaphore] = {}
        self._graphs: dict[str, CompiledStateGraph] = {}
        self._tasks: dict[str, asyncio.Task] = {}  # background runs by run_id

    def workflow(self, name: str) -> Workflow:
        try:
            return self.workflows[name]
        except KeyError:
            raise WorkflowError(
                f"unknown workflow {name!r}; known: {sorted(self.workflows)}"
            ) from None

    async def run(self, name: str, inputs: dict) -> RunRecord:
        wf = self.workflow(name)
        return await self._execute(wf, await self._begin(wf, wf.validate(inputs)))

    async def run_many(self, name: str, inputs_list: list[dict]) -> list[RunRecord]:
        """Run all concurrently. Inputs are validated first, so a typo starts nothing."""
        wf = self.workflow(name)
        validated = [wf.validate(i) for i in inputs_list]

        async def one(inputs: dict) -> RunRecord:
            return await self._execute(wf, await self._begin(wf, inputs))

        return list(await asyncio.gather(*(one(i) for i in validated)))

    async def start(self, name: str, inputs: dict) -> RunRecord:
        """Validate, save as queued, execute in the background. Returns the queued record."""
        wf = self.workflow(name)
        run = await self._begin(wf, wf.validate(inputs))
        task = asyncio.create_task(self._execute(wf, run), name=f"run-{run.run_id}")
        self._tasks[run.run_id] = task
        task.add_done_callback(lambda t: self._done(run.run_id, t))
        return replace(run)

    def cancel(self, run_id: str) -> bool:
        """Cancel a background run; it saves itself as `cancelled`. False if not active."""
        task = self._tasks.get(run_id)
        if task is None or task.done():
            return False
        task.cancel()
        return True

    @property
    def active(self) -> list[str]:
        return list(self._tasks)

    async def shutdown(self) -> None:
        """Cancel background runs and wait until each has saved its final state."""
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _save_final(self, run: RunRecord) -> None:
        """The result exists only in memory until saved: retry, then log it before giving up."""
        for attempt in range(SAVE_ATTEMPTS):
            try:
                await self.data.save_run(run)
                return
            except Exception:
                if attempt == SAVE_ATTEMPTS - 1:
                    log.error(
                        "run %s not saved: status=%s error=%s output=%.2000r",
                        run.run_id, run.status, run.error, run.output,
                    )  # fmt: skip
                    raise
                await asyncio.sleep(SAVE_BACKOFF_S * 2**attempt)

    def _done(self, run_id: str, task: asyncio.Task) -> None:
        self._tasks.pop(run_id, None)
        if not task.cancelled() and (e := task.exception()) is not None:
            log.error("run %s could not save its result: %r", run_id, e)

    def _graph(self, wf: Workflow) -> CompiledStateGraph:
        """Compiled once per workflow and shared by its runs."""
        if wf.name not in self._graphs:
            ctx = GraphContext(wf, self.data, self.make_llm)
            graph = GRAPHS[wf.graph].build(ctx)
            self._graphs[wf.name] = graph.compile(checkpointer=self.checkpointer)
        return self._graphs[wf.name]

    async def _begin(self, wf: Workflow, inputs: dict) -> RunRecord:
        run = RunRecord(
            run_id=uuid4().hex,
            workflow=wf.name,
            inputs=inputs,
            status="queued",
            started_at=datetime.now(UTC),
            bindings=wf.describe(),
        )
        await self.data.save_run(run)
        if self.events is not None:
            self.events.open(run.run_id).emit("run_start", workflow=wf.name, inputs=inputs)
        return run

    async def _execute(self, wf: Workflow, run: RunRecord) -> RunRecord:
        stream = self.events.get(run.run_id) if self.events is not None else None
        usage = UsageCounter()
        config = {
            "configurable": {"thread_id": run.run_id},
            "callbacks": [usage] + ([EventPublisher(stream)] if stream else []),
            "max_concurrency": wf.max_concurrency,
            "recursion_limit": RECURSION_LIMIT,
        }
        cap = self._caps.setdefault(wf.name, asyncio.Semaphore(wf.max_concurrency))
        try:
            async with cap, self._global:
                run.status = "running"  # past the concurrency limits
                await self.data.save_run(run)
                if stream is not None:
                    stream.emit("running")
                graph = self._graph(wf)
                invocation = graph.ainvoke({"inputs": run.inputs}, config)
                out = await asyncio.wait_for(invocation, wf.timeout_s)
            run.status, run.output = "ok", out.get("result")
        except TimeoutError:
            run.status, run.error = "timeout", f"timed out after {wf.timeout_s}s"
        except asyncio.CancelledError:
            run.status, run.error = "cancelled", "cancelled"
            await self._finish(run, usage, stream)
            raise
        except Exception as e:  # noqa: BLE001 - one run's failure must not reach the others
            run.status, run.error = "failed", f"{type(e).__name__}: {e}"
        await self._finish(run, usage, stream)
        return run

    async def _finish(self, run: RunRecord, usage: UsageCounter, stream: RunStream | None) -> None:
        run.input_tokens = usage.input_tokens
        run.output_tokens = usage.output_tokens
        run.cache_read_tokens = usage.cache_read_tokens
        run.finished_at = datetime.now(UTC)
        try:
            await self._save_final(run)
        finally:
            if stream is not None:
                stream.emit(
                    "done",
                    status=run.status,
                    error=run.error,
                    input_tokens=run.input_tokens,
                    output_tokens=run.output_tokens,
                    cache_read_tokens=run.cache_read_tokens,
                )
                self.events.close(run.run_id)


async def mark_interrupted(data: DataLayer) -> int:
    """Save runs a previous process left `queued` or `running` as failed. Call at server start,
    before any run begins; assumes one agents process per data store. Returns how many."""
    stale = [r for s in ("queued", "running") for r in await data.list_runs(status=s)]
    now = datetime.now(UTC)
    for run in stale:
        await data.save_run(replace(run, status="failed", error=INTERRUPTED, finished_at=now))
    return len(stale)
