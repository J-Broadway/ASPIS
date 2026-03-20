Review the user's listed issues one-by-one and verify whether each presumption is valid.
Avoid pedanticism and over-engineering. Asses if is truely valid given scope.

Kwarg:
- `mode` (optional): `Verbose` | `Concise` (default: `Verbose`)
  - `Verbose`: Keep current behavior.
  - `Concise`: For verdicts of `Soft Accept` or `Hard Accept`, output only the verdict line (omit rationale). For all rejects, include rationale.

Process requirements:
1) Evaluate each issue independently against available evidence.
2) Do not merge multiple issues into one verdict.

Verdict format for each issue:
- `<Hard|Soft> <Accept|Reject>`
- `Rationale: <brief explanation grounded in evidence>`

Severity guidance:
- `Hard`: High-confidence evidence.
- `Soft`: partial, indirect, or assumption-dependent evidence.

Output structure:
- `Issue N: <short identification label>`
- `Verdict: <Hard|Soft> <Accept|Reject>`
- `Rationale: <1-3 sentences>` (required in `Verbose`; in `Concise`, required only for rejects)
- `Proposed Solution` (Only if Soft/Hard Rejection)

Final line:
```
Overall: <count accepted>/<count total> accepted. in <n>% Agreement
Disagreements (if any):
```
