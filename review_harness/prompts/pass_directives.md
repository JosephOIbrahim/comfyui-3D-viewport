# Pass Directives

These directives govern how each pass treats prior findings.

## Action Vocabulary

- **NEW** — pass 1 only (first time a finding is raised), or pass 3 (blind
  rediscovery counts as NEW).
- **UPHOLD** — the finding is correct as stated; nothing to change.
- **REFINE** — the finding is correct but needs a non-trivial change to
  severity, evidence, or proposed fix. Wording-only edits are NOT a refine.
- **RETRACT** — the finding is wrong, duplicated, or unverifiable.
- **EXPAND** — the finding's pattern appears elsewhere in the codebase; cite
  the additional sites in `description` (R13: still ONE finding).

## Pass-Specific Modes

### Pass 1 — Discovery
You have not seen prior findings. Raise NEW findings only.

### Pass 2 — Anchored Refinement
You receive pass 1 findings filtered to your `rule_kinds`. For each, choose
UPHOLD / REFINE / RETRACT / EXPAND. You may also raise NEW findings, but
each NEW finding must justify why it was missed in pass 1.

### Pass 3 — Blind Second Opinion
You receive **no** prior findings. Re-do discovery from scratch. The
synthesizer will compare your output against pass 2's anchored output to
detect groupthink.

### Pass 4 — Solution Design
You receive the merged set from passes 1–3 plus the blind/anchored
agreement map. Focus on `proposed_change` quality: each finding's fix must
be specific enough to implement. REFINE liberally. Do not raise NEW unless
the agreement map exposes a clear gap.

### Pass 5 — Meta-Review
You receive the full lifecycle. Final pass; the synthesizer's output is
the canonical report. UPHOLD / RETRACT only — no NEW, no REFINE.

## REFINE Validation

When the orchestrator validates your REFINE actions, it checks the diff:

- `severity` changed, OR
- `evidence_quote` changed (not just normalized whitespace), OR
- `proposed_change` changed (>20% character delta).

If none of these are true, your REFINE is rejected and the finding is
treated as UPHOLD.

## Output

Always write to the file path the orchestrator gives you. Never write
elsewhere on disk.
