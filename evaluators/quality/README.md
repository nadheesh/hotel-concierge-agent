# Quality evaluators

Most of Script A does not need a custom judge. Hallucination and
reasoning-quality evaluation are the two things Agent Manager ships evaluators
for, and the point of Exercise 4 is partly to find out how well those built-ins
work on a real agent. Reaching for a custom judge first would hide exactly the
result the study wants.

So the default is:

| Script A category | Evaluator |
|---|---|
| `grounded-retrieval` | built-in hallucination evaluator, with `expected` from the fixture as ground truth |
| `reasoning` | built-in reasoning-quality evaluator |
| `multi-hop` | built-in reasoning-quality evaluator |
| `out-of-corpus` | `grounded-refusal.md` in this directory |

## Why `out-of-corpus` needs a custom judge

The out-of-corpus cases ask about things the hotel has no data on at all: a
helipad, an airport shuttle, a group rate for forty rooms. There is no ground
truth to compare against, because the correct answer is an admission that the
agent does not know.

A hallucination evaluator scoring against an empty reference has nothing to work
with, and typically scores a confident invention and an honest "I don't have
that" much the same. That is the exact distinction this category exists to draw,
so it gets its own judge.

## Shape of the custom judge

`grounded-refusal.md` is an **LLM-judge** evaluator at **trace** level. The
template variable is `trace`, its `Template` block is the evaluator body pasted
verbatim, and it scores 0.0 to 1.0 with higher better, like every evaluator in
this repo. Do not add JSON or output-format instructions to the template: the
framework appends its own scoring-output block.

The judge sees only what a trace carries - `{trace.input}`,
`{trace.output}`, `{trace.format_evidence()}` and the tool calls. There is no
variable for the fixture's `expected` field, which is why the corpus boundaries
are written into the template as literal text rather than passed in.

## If the built-ins do not separate the two categories

The completion evidence for Exercise 4 requires hallucination and
reasoning-quality to be reported as **separate** results, each traceable to its
individual cases. If the console reports them as one blended score, that is a
finding. Record it, then fall back to running the two fixture slices as two
evaluators so the numbers stay distinguishable.
