# ADR-0001: Use LangGraph for agent orchestration over LangChain pipelines

**Status:** Accepted
**Date:** 2026-04-15
**Deciders:** Project author

## Context

The system needs to orchestrate six agents (inspection, compliance, risk, work-order, documentation, follow-up) plus pre- and post-processing nodes (memory recall, memory persist). Each agent has distinct inputs, distinct outputs, and may be conditionally skipped depending on the outcome of earlier agents.

Three options were considered:

1. **LangChain sequential chains.** Compose runnables with `|`. Each agent is a runnable. Conditional branching is awkward — requires custom routing logic outside the chain.
2. **Direct Python function composition.** Write a `def run_workflow(state)` that calls each agent in sequence. Conditional skipping is trivial. But: no built-in support for state immutability, no introspection of the graph structure, no checkpointing.
3. **LangGraph state machine.** First-class support for conditional edges, state mutation, and observability hooks. Each node is a function from `AgentState` to `AgentState`. Conditional edges return the name of the next node.

## Decision

Use LangGraph.

The deciding factors:
- **Conditional edges as first-class citizens.** `should_run_compliance` and `should_run_risk` are pure functions over state, declared at graph-build time. They are individually unit-testable (see `tests/test_workflow_helpers.py`) without invoking the whole workflow.
- **Observability hooks.** Each node is naturally a span boundary for Langfuse. Pre/post-node instrumentation is one wrapper.
- **State centralization.** All agents read and write a single `AgentState`. No parameter threading across six function signatures.
- **Visual mental model.** `mermaid` rendering of the graph (in the README) directly mirrors the code structure. Reviewers can verify the architecture from the diagram.

## Consequences

**Positive:**
- The workflow definition in `src/graph/workflow.py::build_workflow()` is 30 lines and reads top-to-bottom like a flowchart.
- Adding a new agent is a localized change: write the node function, add it to the graph, wire its edges.
- Conditional skipping (no findings → bypass compliance) is declarative.
- Tests for routing logic are decoupled from agent execution.

**Negative:**
- Coupling to LangGraph's API. If the API changes incompatibly, the workflow file needs updating. Mitigation: the agents themselves don't import from LangGraph; only the orchestration file does.
- Slightly more ceremony than direct function composition for simple linear flows. Acceptable cost given the conditional logic.

**Neutral:**
- LangGraph's checkpointing/persistence features are not used in this project but remain available if needed.