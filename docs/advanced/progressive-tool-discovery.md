# Progressive tool discovery

This page is part of the **SystemOne Harness** docs:

- [Jev Integration](systemone.md) - SystemOne harness, packs, tool gates, evals
- **Progressive Tool Discovery** - this page
- [SystemOne Tune (GEPA)](systemone-tune.md) - improve packs from examples


SuperQode can search native and MCP capabilities without loading every tool
schema into the model context. The discovery pipeline is configurable: the
harness supplies lifecycle, activation, permission, execution, and traces, but
does not require a particular retrieval implementation.

The pipeline is:

```text
catalogue → search → rank → Jev → activate → permission → execute
```

Search never grants permission and never executes a tool. Activation only makes
the selected schema visible on the next model step.

!!! warning "Experimental"

    Unified discovery is opt-in. The existing native `tool_search` and MCP
    `mcp_search` / `mcp_execute` paths remain available in `legacy` mode.

## Configure discovery

The built-in `systemone` harness ships with unified BM25 discovery, an
eight-candidate shortlist, Jev shadow judging, and deferred MCP tools already
enabled. Launch it without knowing any repository paths:

```sh
uv run superqode --tui --harness systemone
```

In the TUI, `:systemone` shows the embedded discovery summary and
`:systemone discovery` opens the detailed lifecycle. `:discovery` remains a
short alias. The explicit configuration below is for projects that want to
change those defaults or bring their own search implementation.

Add `tool_discovery` to a harness specification:

```yaml
name: portable-discovery

tool_discovery:
  enabled: true
  mode: unified
  trace_dir: .superqode/traces

  search:
    backend: bm25
    limit: 20
    on_error: fallback
    fallback_chain: [bm25, lexical]

  rank:
    candidate_limit: 8
    exact_name_boost: 4.0

  judge:
    backend: jev
    mode: shadow

  activation:
    limit: 3

  mcp:
    mode: deferred_tools

systemone:
  enabled: true
  client: live
  mode: shadow
```

Modes are:

| Mode | Behaviour |
| --- | --- |
| `legacy` | Preserve the existing native and MCP search surfaces. |
| `shadow` | Run configured retrieval and record its candidates while legacy activation remains authoritative. |
| `unified` | Use the configured retrieval shortlist for native and MCP activation. |

Built-in search backends are `bm25` and `lexical`. Both include deterministic
normalized exact-name boosting. `on_error` accepts `fallback`, `empty`, or
`fail`; fallback attempts are included in result metadata and traces.

## Bring your own search

A project can own retrieval while keeping the SuperQode pipeline:

```yaml
tool_discovery:
  enabled: true
  mode: unified
  search:
    backend: custom
    handler: company.discovery:search_tools
    on_error: fallback
    fallback_chain: [bm25, lexical]
```

The backend label may describe the implementation (`semantic`, `hybrid`, or a
company-specific name) when `handler` is supplied; `custom` is only the generic
label.

The callable may be synchronous or asynchronous:

```python
def search_tools(query, catalogue, *, limit):
    # Return stable descriptor ids, result mappings, or ToolCandidate objects.
    return [
        {"id": "mcp:github:create_issue", "score": 0.94},
        {"id": "native:web_fetch", "score": 0.72},
    ][:limit]
```

Candidate mappings can include a `signals` mapping for backend-specific score
provenance. This supports external semantic search, hybrid retrieval, or an
MCP server's domain-specific search without making it a SuperQode dependency.

Search and ranking are separate extension points. To preserve an existing
retriever and apply a company-owned reranker afterward:

```yaml
tool_discovery:
  search:
    backend: bm25
    limit: 20
  rank:
    backend: semantic-reranker
    handler: company.discovery:rerank_tools
    candidate_limit: 8
```

The rank callable receives `(query, candidates, limit=...)` and returns
candidate ids, mappings, or `ToolCandidate` objects in the desired order.

## MCP execution modes

`mcp.mode: deferred_tools` presents a selected MCP capability as a real tool.
The capability retains its server and original tool identity and passes through
the standard hooks, permission manager, Jev tool gate, and audit path.

Use `mcp.mode: meta_tools` to retain the existing `mcp_search` and
`mcp_execute` compatibility surface. This is useful for models that require a
stable, fixed tool list.

## Jev

Jev is an optional judge over the bounded retrieval shortlist. It does not
search the catalogue. Configure `judge.backend: jev` and use `shadow` until
thresholds have been evaluated on labelled discovery traces. Existing System
One client, model, timeout, and credential settings still apply; the
`systemone` block must be enabled independently so selecting a ranker never
silently initiates an external decision call.

## Traces

When `trace_dir` is set, sanitized JSON records are written below
`tool-discovery/`. Each record includes the query, catalogue size, selected
retrieval backend, fallback errors, ranked candidates, component scores, Jev
decision, activated tools, and a `discoveryId`. Executed tool results retain the
activation origin so retrieval and execution can be evaluated separately.

Environment overrides are available for rollout and diagnostics:

```sh
export SUPERQODE_TOOL_DISCOVERY=unified
export SUPERQODE_TOOL_SEARCH_BACKEND=bm25
export SUPERQODE_TOOL_DISCOVERY_TRACE_DIR=.superqode/traces
```

## Inspect it in the TUI

Run `:systemone discovery` (or its `:discovery` alias) after a tool search to see the active backend, ranked
shortlist, Jev selection or abstention, activated schemas, and the later
execution outcome. The view is intentionally sanitized: it does not display
tool arguments, output, or secrets. This makes the complete retrieve → rank →
judge → activate → permission → execute lifecycle suitable for a terminal-only
demo.
