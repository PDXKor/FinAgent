# Agents — Overall Design

## Purpose
Run LLM agent graphs (LangGraph + Claude) as named, configurable **workflows** over data produced by `recon`. Many workflows and many runs execute concurrently in one process.

## Concepts

| Concept | What it is | Defined in |
|---|---|---|
| **Tool** | Typed function the LLM can call. No LLM inside. Read-only by default. | `tools/` (code) |
| **Prompt** | Versioned system-prompt file. Immutable once used. | `prompts/<name>.v<N>.md` |
| **Agent** | One LLM node = model + prompt + tool set. | binding in `workflows.yaml` |
| **Graph** | LangGraph `StateGraph` wiring agent, tool, and plain nodes. Holds no config literals. | `graphs/` (code) |
| **Workflow** | Graph + per-node bindings (model, prompt, tools) + input schema + limits + schedule. Unit of execution. | `workflows.yaml` |
| **Run** | One execution of a workflow with inputs. `thread_id = run_id`. | `RunRecord` via `DataLayer` |

Rule: **code defines shapes (graphs, tools); config binds them (workflows).** Same graph serves many workflows; changing a model or prompt is a config change.

## Layout

```
src/finagent_agents/
  design/overall-design.md
  config.py          # AgentSettings (FINAGENT_AGENTS_* env)
  llm.py             # make_llm(binding) -> ChatAnthropic
  registry.py        # load workflows.yaml + prompts; resolve GRAPHS/TOOLS by name
  context.py         # GraphContext handed to graph builders
  runner.py          # async executor: concurrency, timeouts, run log
  data.py            # DataLayer protocol, RunRecord, HttpDataLayer, MemoryDataLayer
  cli.py             # finagent-agents list | run | run-many
  workflows.yaml
  prompts/
    ping.v1.md  company_brief.v1.md  screener.v1.md  brief_writer.v1.md
  tools/
    __init__.py      # TOOLS = {name: factory(data) -> BaseTool}
    company.py       # get_company, get_financials (async, via DataLayer)
  graphs/
    __init__.py      # GRAPHS = {name: GraphSpec(nodes, build)}
    agent.py         # agent_graph(): one agent <-> ToolNode loop, shared by all graphs
    single.py        # one LLM call, no tools
    react.py         # one agent with its tool loop
    multi/           # several agents wired together; one file per graph
      screen_then_brief.py  # screener fan-out, then writer
tests/agents/
```

Mirrors `recon`: `workflows.yaml` ≈ `jobs.yaml`, `GRAPHS`/`TOOLS` ≈ `jobs.REGISTRY`, run records ≈ `ingest_runs`.

## Architecture

```
workflows.yaml ──► Registry ──► Runner (asyncio, one event loop)
prompts/*.md  ──┘     │           ├─ per-workflow cap          max_concurrency
                      │           ├─ Semaphore(max_runs)      global cap
                      │           ├─ per-run timeout, isolated failure
                      │           └─ RunRecord ──► DataLayer.save_run
                      ▼
       GRAPHS[name](GraphContext) ──► compiled graph (cached per workflow, shared by runs)
                      │
        nodes: agent (LLM+prompt+tools) │ ToolNode │ plain fn
             │                                │
   ChatAnthropic + RateLimiter          TOOLS ──► DataLayer (async, read-only)
             │
         Claude API
```

## Workflow Config

```yaml
# workflows.yaml
defaults:
  model: claude-opus-5-5
  effort: medium
  timeout_s: 120
  max_concurrency: 4

workflows:
  ping:                         # smoke test, no tools
    graph: single
    input: { text: str }
    nodes:
      agent: { prompt: ping@1 }

  company_brief:
    graph: react
    input: { ticker: str }
    nodes:
      agent: { prompt: company_brief@1, tools: [get_company, get_financials] }
    schedule: null              # cron later, same as jobs.yaml

  screen_then_brief:            # multi-agent example
    graph: screen_then_brief
    input: { tickers: "list[str]" }   # quote: YAML flow maps reject [ ]
    nodes:
      screener: { model: claude-haiku-5-5, effort: low, prompt: screener@1, tools: [get_financials] }
      writer:   { prompt: brief_writer@1, tools: [get_company] }
```

- `nodes` keys must match the node names the graph builder asks for. Validated at load.
- Unknown graph, tool, prompt, or node → load-time error, not run-time.

## Graph Contract

```python
def build(ctx: GraphContext) -> StateGraph: ...
```

Registered as `GRAPHS[name] = GraphSpec(nodes, build)`; `nodes` lists the node names a workflow must bind. Every agent is built by `agent_graph(ctx, node)`: an agent <-> `ToolNode` loop with a static, cache-marked system prompt. Graphs call it as a subgraph from their own nodes, so one agent and a multi-agent graph share the same code.

`GraphContext` gives the builder resolved, per-node dependencies:
- `ctx.llm("writer")` → `ChatAnthropic` bound to that node's tools
- `ctx.prompt("writer")` → system prompt text
- `ctx.tools("writer")` → `list[BaseTool]` (for `ToolNode`)

State: `TypedDict` with `messages: Annotated[list, add_messages]` plus workflow fields. Final answer goes in `result`.

Fan-out (e.g. one sub-run per ticker) uses LangGraph `Send`; bounded by `max_concurrency` in the run config.

Builders get every dependency from `ctx` → tests swap in fake LLMs and temp DBs without patching.

## Tools
- `TOOLS = {name: factory(data: DataLayer) -> BaseTool}`.
- **Async tools** that `await` the `DataLayer`. No sync tools, so nothing runs in threads and a timeout cancels cleanly.
- Read-only. No tool writes through the `DataLayer`.
- Return small JSON: cap rows, round numbers. Big results waste tokens.
- Typed args via Pydantic so schema errors fail before the query runs.

## Prompts
- File per version: `prompts/company_brief.v1.md`; referenced as `company_brief@1`.
- Never edit a used version; add `v2`. The run log stores which versions ran.
- **System prompt is static** (no dates, tickers, IDs) so prompt caching hits. Run inputs go in the first user message.

## Claude Connection
- `langchain-anthropic` `ChatAnthropic`; key from `ANTHROPIC_API_KEY`.
- Default model `claude-opus-5-5`; per-node override (e.g. `claude-haiku-5-5` for bulk screening).
- Opus 5.5 specifics:
  - Thinking is always on and cannot be disabled. Set `effort` per node instead; it defaults to `medium`.
  - Forced `tool_choice` (`any` / named tool) returns a 400. Use `auto` and say in the prompt when to call a tool.
  - For structured output use the `json_schema` method (`output_config.format`), not the function-calling method, which forces a tool.
- Rate: `InMemoryRateLimiter` on the model (req/s) + SDK `max_retries` for 429/5xx.
- Caching: `cache_control` on the system prompt. Check `cache_read_input_tokens` in the run log.
- Later: server-side refusal fallback (`fallbacks: "default"`) once `langchain-anthropic` passes it through.
- **Verify** the installed `langchain-anthropic` version passes `effort`, `output_config`, and `cache_control` through.

## Concurrency Model
- One process, one asyncio loop. All runs use `graph.ainvoke(...)`.
- Compiled graphs are immutable and shared; per-run state is keyed by `thread_id`.
- No module-level mutable state in graphs or tools.
- Limits, outer to inner:
  1. `max_concurrency` per workflow: semaphore + LangGraph `config["max_concurrency"]` for fan-out. Taken first so a saturated workflow never holds global slots.
  2. `max_runs`: global semaphore on concurrent runs.
  3. Model rate limiter: requests/sec to Claude.
- Each run: `asyncio.wait_for(timeout_s)`; `gather(return_exceptions=True)` so one failure never cancels others.
- Checkpointer: `Runner` takes a `checkpointer` argument, default `InMemorySaver`. Graphs never construct one, so a persistent saver drops in without touching graphs.

## Storage
FinAgentData owns storage and serves it over HTTP (`/v1`). This repo imports none of its code; the API is the contract (FinAgentData `src/finagent/data/design.md`, Consumer API).

```
tools / Runner ─► DataLayer ─► HttpDataLayer ──HTTP /v1──► finagent-data serve ─► SQLite
```

- Agents depend only on the async `DataLayer` protocol in `data.py`: `get_company`, `get_financials`, `save_run`.
- `HttpDataLayer`: `httpx.AsyncClient`, native async. 404 → `None`/`[]`. 503 (DB busy) → 3 retries with backoff. Connect errors → 2 transport retries. `save_run` → `PUT /v1/agent-runs/{run_id}` at run start and end.
- `MemoryDataLayer`: tests and local runs.
- CLI picks the store: `FINAGENT_AGENTS_DATA_URL` set → HTTP (+ `FINAGENT_AGENTS_DATA_TOKEN`), else memory. It prints which to stderr.
- `get_financials` returns annual rows (one per fiscal year, newest first).
- New tool needing new data → FinAgentData adds query + endpoint first, then a `DataLayer` method here.

### Deferred
| Capability | Until then |
|---|---|
| Checkpoint persistence | `InMemorySaver`; runs cannot resume after a restart |
| Human-in-the-loop pause/resume | Not supported (needs a persistent checkpointer) |
| Prompt storage | Prompt files in this repo |

## Test Plan
Existing pytest markers apply. All but the last test use fakes, so CI never calls Claude.

| # | Test | Marker | Setup | Asserts |
|---|---|---|---|---|
| 1 | Registry load | unit | sample `workflows.yaml` | resolves graphs, tools, prompts; bad names raise at load |
| 2 | `ping` run | component | fake chat model returns fixed text | `result` set; run saved via `DataLayer` as `ok`, bindings recorded |
| 3 | `company_brief` tool loop | component | fake model emits `tool_call get_company(ticker)`, then final text; `MemoryDataLayer` with fixture rows | tool called with right args, tool result in messages, final `result` |
| 4 | Concurrency | component | 10 runs, fake model sleeps 0.2s, `max_runs=5`, one run forced to fail | peak in-flight == 5; wall time ≈ 2 batches; each output matches its own ticker; 9 `ok` + 1 `failed` |
| 5 | Timeout | component | fake model sleeps past `timeout_s` | status `timeout`; other runs unaffected |
| 6 | Live smoke | contract | real Claude, skip if no `ANTHROPIC_API_KEY` | `company_brief` for one fixture ticker calls a tool and returns non-empty `result` |

Fake model: `langchain_core` `GenericFakeChatModel` subclass whose `bind_tools` returns itself, fed a scripted list of `AIMessage`s (with `tool_calls` where needed). Injected via `GraphContext`.

## Milestones
- **A0:** package skeleton, `make_llm`, registry, `single` graph, `ping` workflow. Tests 1–2.
- **A1:** async `DataLayer` tools, `react` graph, `company_brief`. Test 3, then test 6.
- **A2:** async runner, limits, timeouts, run log via `DataLayer.save_run`, CLI `run` / `run-many`. Tests 4–5.
- **A3:** multi-agent `screen_then_brief` with `Send` fan-out over the watchlist.
- **A4:** schedules via APScheduler (reuse recon scheduler).
- **A5:** data via FinAgentData HTTP API (done). Next: persistent checkpointer, resume, human-in-the-loop.

Setup changes: add `langchain-anthropic` to core dependencies, add `src/finagent_agents` to wheel packages, add an `agents` console script.

## Open Questions
- Human-in-the-loop approval for any future write-capable tool.
