"""Live run events: one replayable stream per run, fanned out to subscribers (the server's SSE).

In memory only. A finished run's stream stays replayable until `retain` newer runs finish;
after that, clients read the run from the data API.
"""

import asyncio
import json
from collections import OrderedDict
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler

MAX_TEXT = 1000  # chars of tool input/output per event; full data is in the run record


@dataclass(frozen=True)
class Event:
    id: int  # 1-based position in the run's stream; SSE `id` for Last-Event-ID replay
    type: str
    data: dict


class RunStream:
    def __init__(self):
        self.history: list[Event] = []
        self.closed = False
        self._subscribers: set[asyncio.Queue] = set()

    def emit(self, type: str, **data: Any) -> None:
        if self.closed:
            return
        event = Event(len(self.history) + 1, type, data)
        self.history.append(event)
        for queue in self._subscribers:
            queue.put_nowait(event)


class EventHub:
    """Event streams by run_id. Use from the event loop thread only."""

    def __init__(self, retain: int = 100):
        self.retain = retain
        self._streams: OrderedDict[str, RunStream] = OrderedDict()

    def open(self, run_id: str) -> RunStream:
        stream = self._streams[run_id] = RunStream()
        return stream

    def get(self, run_id: str) -> RunStream | None:
        return self._streams.get(run_id)

    def close(self, run_id: str) -> None:
        stream = self._streams.get(run_id)
        if stream is None or stream.closed:
            return
        stream.closed = True
        for queue in stream._subscribers:
            queue.put_nowait(None)
        self._streams.move_to_end(run_id)
        finished = [k for k, s in self._streams.items() if s.closed]
        for k in finished[: max(0, len(finished) - self.retain)]:
            del self._streams[k]

    async def subscribe(
        self, run_id: str, after: int = 0, keepalive: float = 15.0
    ) -> AsyncIterator[Event | None]:
        """Events with id > `after`, then live ones until the run ends. Yields None after
        `keepalive` seconds of silence so the caller can ping. KeyError if unknown."""
        stream = self._streams[run_id]
        backlog = stream.history[after:]
        queue: asyncio.Queue = asyncio.Queue()
        # Decide now, not after the backlog: if the run ends while the backlog is being sent,
        # the queue already holds the rest of its events and must be drained.
        live = not stream.closed
        if live:
            stream._subscribers.add(queue)
        try:
            for event in backlog:
                yield event
            if not live:
                return
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), keepalive)
                except TimeoutError:
                    yield None
                    continue
                if event is None:
                    return
                yield event
        finally:
            stream._subscribers.discard(queue)


def token_usage(response) -> tuple[int, int, int]:
    """(input, output, cache_read) tokens summed over an LLMResult's generations."""
    i = o = c = 0
    for generations in response.generations:
        for gen in generations:
            usage = getattr(getattr(gen, "message", None), "usage_metadata", None)
            if usage:
                i += usage.get("input_tokens", 0)
                o += usage.get("output_tokens", 0)
                c += (usage.get("input_token_details") or {}).get("cache_read", 0)
    return i, o, c


def _clip(value: Any) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return text if len(text) <= MAX_TEXT else text[:MAX_TEXT] + "…"


def _path(metadata: dict | None) -> str:
    """Enclosing nodes without task ids: 'screen:<id>|agent:<id>' -> 'screen/agent'. '' = top."""
    ns = (metadata or {}).get("checkpoint_ns") or ""
    return "/".join(part.split(":")[0] for part in ns.split("|") if part)


class EventPublisher(BaseCallbackHandler):
    """LangChain callbacks -> run events for graph nodes, model calls and tool calls.

    Each event carries `span` (its id) and `parent` (span of the nearest published ancestor,
    or None), so a client can draw a tree and tell parallel fan-out branches apart.
    """

    run_inline = True  # called on the event loop thread, so emitting needs no locking

    def __init__(self, stream: RunStream):
        self.stream = stream
        self._parents: dict[UUID, UUID | None] = {}  # every started LangChain run
        self._open: dict[UUID, dict] = {}  # published runs -> data repeated on their end

    def _span(self, run_id: UUID | None) -> str | None:
        return run_id.hex[-12:] if run_id else None  # random tail; LangChain ids lead with time

    def _published_parent(self, parent: UUID | None) -> str | None:
        while parent is not None and parent not in self._open:
            parent = self._parents.get(parent)
        return self._span(parent)

    def _start(self, run_id: UUID, parent: UUID | None, type: str, metadata, **data: Any) -> None:
        self._parents[run_id] = parent
        md = metadata or {}
        data = {"node": md.get("langgraph_node"), "path": _path(md), **data}
        self._open[run_id] = {"span": self._span(run_id), **data}
        self.stream.emit(type, **self._open[run_id], parent=self._published_parent(parent))

    def _end(self, run_id: UUID, type: str, **extra: Any) -> None:
        self._parents.pop(run_id, None)
        if (data := self._open.pop(run_id, None)) is not None:
            self.stream.emit(type, **data, **extra)

    @staticmethod
    def _error(error: BaseException) -> str:
        return _clip(f"{type(error).__name__}: {error}")

    # Graph nodes: LangGraph names each node's chain after the node; `__x__` nodes are internal.
    def on_chain_start(
        self, serialized, inputs, *, run_id, parent_run_id=None, metadata=None, **kw
    ):
        node = (metadata or {}).get("langgraph_node")
        if node and kw.get("name") == node and not node.startswith("__"):
            self._start(run_id, parent_run_id, "node_start", metadata)
        else:
            self._parents[run_id] = parent_run_id

    def on_chain_end(self, outputs, *, run_id, **kwargs):
        self._end(run_id, "node_end")

    def on_chain_error(self, error, *, run_id, **kwargs):
        self._end(run_id, "node_error", error=self._error(error))

    def on_chat_model_start(
        self, serialized, messages, *, run_id, parent_run_id=None, metadata=None, **kwargs
    ):
        model = (metadata or {}).get("ls_model_name")
        self._start(run_id, parent_run_id, "llm_start", metadata, model=model)

    def on_llm_end(self, response, *, run_id, **kwargs):
        i, o, c = token_usage(response)
        self._end(run_id, "llm_end", input_tokens=i, output_tokens=o, cache_read_tokens=c)

    def on_llm_error(self, error, *, run_id, **kwargs):
        self._end(run_id, "llm_error", error=self._error(error))

    def on_tool_start(
        self, serialized, input_str, *, run_id, parent_run_id=None, metadata=None, inputs=None, **kw
    ):
        tool = kw.get("name") or (serialized or {}).get("name") or "tool"
        self._start(run_id, parent_run_id, "tool_start", metadata, tool=tool)
        # Input only on the start event; it is not repeated on the end event.
        self.stream.history[-1].data["input"] = _clip(inputs if inputs else input_str)

    def on_tool_end(self, output, *, run_id, **kwargs):
        self._end(run_id, "tool_end", output=_clip(getattr(output, "content", output)))

    def on_tool_error(self, error, *, run_id, **kwargs):
        self._end(run_id, "tool_error", error=self._error(error))
