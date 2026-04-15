---
name: Feature request
about: Suggest a new tool or capability
title: "[feat] "
labels: enhancement
assignees: mofiaboss
---

## What problem does this solve?

<!-- Describe the use case. What are you trying to accomplish that the current tool surface can't? -->

## Proposed solution

<!--
Describe the new tool(s) or change you'd like. Be specific:
- Tool name(s)
- What Etsy API endpoint(s) they wrap
- Inputs and outputs
- Whether the tool is read-only or mutating
-->

## Pure Primitive Rule check

**Before proposing, please verify** the requested tool wraps an Etsy API endpoint as a thin primitive — no scoring, ranking, content generation, or "AI search readiness" judgments. Reasoning must stay in the model.

- [ ] My proposed tool wraps a specific Etsy API endpoint
- [ ] My proposed tool does NOT generate content the LLM could generate itself
- [ ] My proposed tool does NOT score, rank, or judge listing quality

If you can't check all three boxes, the answer is almost certainly "your LLM can already do this with the existing primitives." See [AGENTS.md](../AGENTS.md) -> Pure Primitive Rule and [docs/WORKFLOWS.md](../docs/WORKFLOWS.md) for examples.

## Alternatives considered

<!-- Have you tried solving this with existing tools? What didn't work? -->

## Additional context

<!-- Links to Etsy API docs for the endpoint, related issues, etc. -->
