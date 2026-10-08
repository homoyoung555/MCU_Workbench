# V1.4 Project Instructions

## Sol / Terra / Luna Collaboration

- The primary agent is the Sol architect and reviewer. It owns user discussion,
  requirement clarification, architecture, task slicing, integration review,
  platform-compiler evidence, and the final answer.
- Do not use subagents for a simple question, a one-file mechanical edit, or work
  whose next step depends on the immediately preceding result. Multi-agent work is
  justified only when at least two bounded workstreams can progress independently.
- Prefer the project agents `domain_terra` and `implementation_luna` when they fit.
  If custom agents are unavailable, use the equivalent model and effort explicitly.
- Use a fresh subagent for an unrelated domain slice. Pass only the context required
  for that slice; do not fork the full conversation by default.

## Task Allocation

- `domain_terra`: typed domain models, Product Compiler boundaries, invariants,
  algorithms, complex renderers, architecture evidence, and compatibility analysis.
- `implementation_luna`: fixed Skeleton sections, comments/formatting, test
  scaffolding, repetitive migrations, staging helpers, and other narrow work whose
  behavior is already specified.
- Sol keeps ambiguous business rules, cross-module decisions, destructive/external
  actions, registry/output changes, and final integration. A subagent must report an
  ambiguity instead of inventing a rule.

## Delegation Contract

Before spawning an agent, Sol must state:

1. the verifiable done condition;
2. the allowed files and forbidden paths;
3. the invariants and behavior that must not change;
4. the smallest relevant test command;
5. whether the task is read-only or may edit files.

Only one active agent may own a source file. If two slices necessarily touch the
same file, run them sequentially and require the later owner to reread and preserve
the earlier change. Subagents must not edit `PROJECT_MAP.md`, registry, published
outputs, or unrelated dirty-worktree files unless explicitly assigned.

## Verification Order

- Use TDD for behavior changes: public RED, minimal GREEN, then refactor.
- Each subagent runs only its focused tests and reports the exact command/result.
- Sol reviews the actual source/diff and reruns one cross-slice integration set.
- Move the smallest real platform syntax gate early: DEC/PLN for Chroma and
  PRJ/PRG for S100 as soon as the affected artifact exists.
- Run the full suite once after integration and real compiler gates are green.
- A task is not complete until Sol has reconciled agent claims with observable
  tests, compiler output, and the project architecture.

## Efficiency Review

- Optimize for accepted work, not agent count. Fewer calls or cheaper models are an
  improvement only when the same acceptance gates pass.
- At handoff, report agent allocation, overlapping files, retries/failed gates,
  targeted/full tests, real compiler results, and whether token usage is measured or
  only inferred. Never claim exact token savings without usage data and a baseline.

## Agent skills

### Issue tracker

Issues and PRDs are tracked as local Markdown under `.scratch/`; external PRs are
not a triage surface. See `docs/agents/issue-tracker.md`.

### Triage labels

Use the canonical labels `needs-triage`, `needs-info`, `ready-for-agent`,
`ready-for-human`, and `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

This is a single-context repository using root `CONTEXT.md` and `docs/adr/`. See
`docs/agents/domain.md`.
