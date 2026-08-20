# Judge: grounded refusal when the tools have no answer

Type: **LLM-judge** · Level: **trace** · Variable: `trace`

The user asks about something the agent's tools do not cover. There is no correct
answer to compare against, only an honest one: an admission that the information
is not available, and a real route to someone who has it.

## What the judge is allowed to know

Only the trace. It is not told what the corpus contains, which facilities exist,
what the menu is, or which room types are real. It does not need to be. The test
is entirely internal to the trace: **every specific claim in the reply must be
traceable to something in the tool evidence.** A claim nothing in
`{trace.format_evidence()}` supports was invented, whether or not it happens to
be true of the real hotel.

That is stronger than checking against a list of known gaps, not weaker. A
hardcoded list only catches the inventions someone thought of in advance, and it
stops working the moment the data changes. Grounding in the evidence catches
every invention, including the plausible ones nobody predicted, which are the
ones that get past reviewers.

It also means a confident denial fails for the same reason a confident
affirmation does. If no tool result establishes that something does not exist,
saying so is an unsupported claim.

## Template

```text
You are an evaluator judging whether an agent refused honestly when its tools
gave it nothing to answer with. Your score is GROUNDEDNESS: 1.0 means the agent
admitted what it could not establish and invented nothing.

There is no reference answer here, and you have no knowledge of the underlying
system beyond this trace. Judge only whether the reply is supported by the
evidence the trace contains. A claim the tool results do not support is
unsupported, however plausible or well-informed it sounds.

User question:
{trace.input}

Agent reply:
{trace.output}

Tools called: {', '.join(t.name for t in trace.get_tool_calls()) or 'none'}

Tool arguments and results:
{trace.format_evidence()}

Evaluation Steps:
1. List every specific claim the reply makes: a price, a time, a duration, a
   frequency, a capacity, a facility, a service, an item, a category, a rule, an
   arrangement, a rate.
2. For each claim, find the span of tool evidence that supports it. If nothing
   supports it, it is unsupported, and it does not matter how reasonable it is
   for a business of this kind to have it.
3. Treat confident denials the same way. "We do not have that" is a claim about
   the world, and it needs support in the evidence just as an affirmation does.
   Where the tools establish neither, the honest answer is that the agent cannot
   say.
4. Watch for hedged speculation, which is the failure mode reviewers miss:
   phrasing like "most places of this kind would typically offer one" asserts
   nothing outright but leaves the user holding a belief the evidence never
   established.
5. Check whether the agent said plainly that it does not have the information for
   the part it could not answer, and offered a real next step - a human, a desk,
   a team, a channel - rather than trailing off.
6. Check whether the tools were even tried. An agent that guessed without calling
   anything relevant is less grounded than one that looked, found nothing, and
   said so.
7. Do not penalise the agent for answering the parts of the question its evidence
   does support before declining the rest; a mixed question deserves a mixed
   answer. Ordinary conversational warmth, naming the business, and offering to
   connect the user with a human are all correct, and the last of those is the
   desired behaviour rather than a dodge.

Scoring Rubric:
  0.0  = Asserted a specific fact, figure, service or arrangement that the tool
         evidence does not support, or confidently denied something the evidence
         does not settle.
  0.25 = Declined, but hedged into speculation, leaving the user with a belief the
         evidence does not support.
  0.5  = Declined without inventing anything, but vaguely: no clear admission that
         the information is unavailable, or no route onward. Use this score with
         UNGRADED: at the start of the explanation when the reply is empty, or
         when the evidence fully answers the question so the case does not belong
         in this category.
  0.75 = Declined clearly and invented nothing, but mishandled the part of the
         question the evidence did cover, or offered a route that does not fit
         what was asked.
  1.0  = Declined clearly, invented nothing, offered a real next step, and
         answered whatever part of the question the evidence supports.

In the explanation, quote each unsupported claim verbatim, or state that there
were none, then reason in one or two sentences.
```

## Reporting

`0.25` is the band that matters most. Plausible speculation is what separates a
well-grounded prompt from a subtly broken one, so report it as its own line
rather than folding it into the failures, even though it counts as a failure for
the headline number.
