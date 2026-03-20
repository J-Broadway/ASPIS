---
description: Build a feature from a plan using a durable builder subagent plus fresh reviewer-fixer subagents until quality converges or max iterations is reached.
---

Use this command to run a `StartAgent` / `ReviewAgent` implementation loop over a target feature or plan.

The current chat thread is the long-lived `StartAgent` orchestrator.
Do not spawn a master/orchestrator subagent.
Do not reset the current chat context.
The builder subagent is durable for the initial implementation phase.
Each review pass must be a fresh reviewer subagent invocation.
The reviewer is allowed to modify files to fix material gaps it finds.

Kwargs:
- `review_agent` (optional): reviewer profile to use. Default: `review-gpt-5-4`
  - Supported values:
    - `gpt-5.4`
    - `GPT-5.4`
    - `opus`
    - `opus-4.6`
    - `Opus 4.6`
- `max_iterations` (optional): maximum number of review/fix passes. Default: `5`

Review profile mapping:
- If `review_agent` is omitted, use `review-gpt-5-4`.
- If `review_agent` matches any GPT-5.4 alias above, use `review-gpt-5-4`.
- If `review_agent` matches any Opus 4.6 alias above, use `review-opus-4-6`.
- If the requested reviewer profile has no matching subagent file, stop and ask the user to create or choose one.

Execution contract:
1. Treat the current conversation as the long-lived `StartAgent`.
2. Determine the implementation target and intended outcome from the prompt and referenced plan/artifact.
3. Launch one durable builder subagent to implement the feature end-to-end from the referenced plan.
4. After the builder completes, run a fresh `review_agent` pass against:
   - the original plan/intended scope,
5. Require each reviewer pass to return either:
   - exactly `good`, or
   - a structured list of substantive gaps (stable IDs), plus the concrete fixes the `review_agent` applied before returning.
6. If the reviewer returns exactly `good`, stop successfully.
7. If gaps are returned:
   - the `review_agent` must fix the substantive in-scope gaps it identified before returning its report,
   - `StartAgent` records the reported gaps and fixes in the loop log,
   - `StartAgent` then spawns a fresh reviewer pass for the next iteration,
   - `StartAgent` does not perform the repair work itself.
8. Repeat until:
   - `good` is returned, or
   - `max_iterations` is reached.
9. Do not recurse into review-of-review loops. One reviewer pass per iteration, always fresh.
10. Keep the process high-signal: no style-only churn, no out-of-scope expansion.

Output requirements:
- State which reviewer profile was used.
- State what plan/feature was built.
- State `max_iterations` and actual iteration count.
- State final status: `good` or `loop limit reached`.
- Provide a cumulative gap ledger with stable gap IDs across iterations.
- Summarize fixes applied per iteration.
- List unresolved gaps/risks remaining at stop.
- Do not forget to check off to-do's of referenced build plan

Behavioral constraints:
- The current chat retains orchestration authority.
- The builder focuses on implementation; the reviewer focuses on independent verification and targeted repair.
- Reviewer context must be fresh each iteration.
- Do not claim `good` unless the reviewer explicitly returned exactly `good`.
- Default `review_agent` to `review-gpt-5-4` if omitted.
- Default `max_iterations` to `5` if omitted.
