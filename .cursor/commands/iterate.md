---
description: Iterate on a master artifact by spawning a fresh emissary reviewer subagent until it is ready for intended use or the loop limit is reached.
---

Use this command to run a `Master` / `Emissary` iteration loop over an artifact under review.

The current chat thread is the `Master`.
Do not spawn a master subagent.
Do not reset the master context.
The emissary should begin each iteration as a fresh subagent invocation.
After the Master adjudicates the emissary's claims, the same emissary may be resumed only for targeted reconciliation of rejected claims.
Only disputed claims may be sent back and forth between the `Master` and `Emissary`.
Do not re-litigate accepted claims.
Do not recurse beyond a single disagreement check.

Kwargs:
- `emissary`: emissary profile to use.
  - Supported values:
    - `kimi`
    - `kimi-k2.5`
    - `kimi K2.5`
    - `opus`
    - `opus-4.6`
    - `Opus 4.6`
    - `gpt-5.3`
    - `GPT-5.3`
    - `gpt-5.3-codex`
    - `GPT-5.3 Codex`
    - `composer-2`
    - `Composer 2`
    - `composer-2-fast`
    - `Composer 2 fast`
- `loop_limit` (optional): maximum number of review iterations. Default: `7`

Emissary profile mapping:
- If `emissary` is omitted, use the `GPT-5.3 Codex` profile.
- If `emissary` matches any Kimi alias above, use the `emissary-kimi-k2-5` subagent.
- If `emissary` matches any Opus 4.6 alias above, use the `emissary-opus-4-6` subagent.
- If `emissary` matches any GPT-5.3 alias above, use the `emissary-gpt-5-3` subagent.
- If `emissary` matches any GPT-5.3 Codex alias above, use the `emissary-gpt-5-3-codex` subagent.
- If `emissary` matches any Composer 2 fast alias above, use the `emissary-composer-2-fast` subagent.
- If `emissary` matches any other Composer 2 alias above, use the `emissary-composer-2` subagent.
- If the requested emissary profile has no matching subagent file, stop and ask the user to create or choose one.

Execution contract:
1. Treat the current conversation as the long-lived `Master`.
2. Identify or create a single durable authoritative artifact in the workspace to serve as the primary object under iteration.
3. Determine the artifact's intended use. If the intended use is ambiguous, infer it from the prompt when possible; otherwise ask the user a concise clarifying question before iterating.
4. Gather only the context necessary to review and improve that artifact.
5. Run at most `loop_limit` iterations.
6. In each iteration:
   - Read the current authoritative artifact and the directly relevant evidence.
   - Invoke the mapped emissary subagent as a fresh reviewer.
   - Ask it to determine whether the artifact is `ready for intended use`.
   - Require it to return either:
     - exactly `ready`, or
     - a structured list of substantive issues with stable issue IDs and an optional proposed solution for each issue.
   - If the emissary returns exactly `ready` and no critical issues, stop the iteration loop successfully.
   - If the emissary reports any critical issues, do not stop the loop, even if its response also includes `ready`.
   - Otherwise, the Master must apply the adjudication procedure defined in `@.cursor/commands/feedback.md` to the returned issues.
   - During adjudication, evaluate issue claims independently from the emissary's proposed solutions.
   - A Master may accept an issue claim while rejecting the proposed solution. Proposed solutions are advisory only.
   - Accepted issue claims must be incorporated into the authoritative artifact immediately.
   - Rejected issue claims must be collected into a disputed-claims set keyed by issue ID.
   - Send only that disputed-claim(s) set back to the same emissary thread for emissary to run `@.cursor/commands/feedback.md` reconciliation on master's disputed-claim(s).
   - If the emissary accepts the Master's rejection for a disputed claim, terminate that claim with no further action.
   - If the emissary rejects the Master's rejection for a disputed claim, promote that issue directly to explicit user supervision.
   - A disagreement about a rejection must not trigger another emissary pass. Promote it immediately.
   - Only after accepted claims are incorporated, upheld rejections are closed, and residual disagreements are promoted should the next fresh emissary iteration begin.
   - Keep a brief iteration log (including which iter you're on) so the loop remains legible.
   - At the end of each iteration, the Master must explicitly assess whether diminishing returns have been reached.
   - If diminishing returns are true, the Master may authoritatively terminate `/iterate` early even if the emissary has not returned `ready`.
7. Stop early if the emissary returns `ready` including no gaps.
8. If `loop_limit` is reached before `ready`, stop and clearly report that the artifact improved but did not stabilize fully.

Output requirements:
- State which emissary profile was used.
- State the intended use the artifact was evaluated against.
- State the loop limit and actual iteration count.
- State final status: `ready`, `loop limit reached`, or `terminated for diminishing returns`.
- Summarize the accepted changes to the artifact.
- Summarize any claim rejections that were upheld after emissary reconciliation.
- List any issues promoted for user supervision, keyed by issue ID.
- List any unresolved gaps or risks that remain.
- State whether diminishing returns was assessed, and if termination occurred on that basis, briefly explain why.

Subagent model note (Cursor behavior):
- In `.cursor/agents/*.md`, `model: fast` is **not** the same thing as “Composer 2 Fast” in the model picker. `fast` is Cursor’s generic speed-optimized subagent tier; the UI may still show “Composer 2” or match the parent agent.
- For a Composer-2-Fast-shaped emissary, `emissary-composer-2-fast` uses an explicit model id (`composer-2-fast` in frontmatter). Confirm that slug under **Cursor Settings → Models**; rename it in the agent file if Cursor ships a different id. If the UI still shows plain Composer 2, your build may be ignoring subagent `model` (known issue on some plans/builds—see [Cursor subagent docs](https://cursor.com/docs/agent/subagents) FAQ and forum threads on “subagent configured model not honored”). Until that is fixed, the parent chat’s selected model may override.

Behavioral constraints:
- The `Emissary` is a critic, not the owner of the artifact.
- The `Master` retains synthesis authority.
- Keep the process high-signal and concise.
- The default `loop_limit` when the user does not specify one.
- Do not claim `ready` unless the emissary explicitly returned it.
- The only claims that may be sent back to the emissary are those the Master rejected.
- Residual disagreement after reconciliation must go to the user, not into another recursive dispute loop.
- Diminishing-returns termination is a Master judgment call and should be used when additional iterations are unlikely to produce materially new or useful improvements relative to token cost.
