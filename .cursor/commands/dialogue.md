---
description: Run structured dialogue to resolve issues and strategy.
---

Engage the user in a structured dialogue to work through {scope}.
- {scope} includes: issues, planning, or strategy.

# Required format and behavior:

1) Start by identifying the current set of points that must be resolved.
- Display the counter at the top of each turn as:
  Question x/n)
- `x` is the current question index (resolved questions + 1).
- `n` is the current total number of points to resolve.
- `n` can increase if new unresolved points are discovered during dialogue.
- `n` can increase if dialogue brings new questions into scope
- Determine a {Status} IE: Critical, Important, Suggestion.
- *Format*:
Question x/n - {Status}: {Contextual name for {Scope}}
The Problem: {Description of {scope}}
For Example: {why it's important, give tangable example to demonstrate importance}

2) Go one question at a time
- Determine which points are related enoughed to grouped be grouped into a single question
- Ask exactly one focused question per turn.
- Do not batch multiple questions in one message.
- For each point:
  - Help user visualize problem with concise yet highly relevant example/demonstration of the problem. 
  - Recommended path forward including rationale for why you recommend
- After the user responds, mark that point resolved (or carry it forward if unresolved), then move to the next question.

3) Keep an evolving issue list.
- Track resolved and unresolved points internally.
- If a user answer reveals a new dependency, risk, or decision point, add it to unresolved points and increment `n`.

4) After each question/point is resolved update related documentss
