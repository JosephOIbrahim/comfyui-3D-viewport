---
description: Run the MOE 5-pass code review harness against this repository
argument-hint: [--rounds N] [--model MODEL] [--budget-usd N] [--dry-run]
allowed-tools: [Bash]
---

Execute the multi-agent code review harness. This spawns 8 MOE expert
subagents + Synthesizer + Devil's Advocate across $1 refinement passes
(default 5), governed by `.claude/CONSTITUTION.md`. Output is written to
`reports/run_<sha>_<ts>/final_report.md`.

```bash
python -m review_harness $1
```

If no arguments are given, runs with the defaults: `--rounds 5
--model claude-opus-4-7 --budget-usd 50 --seed 42`. Use `--dry-run` first
to estimate cost before committing to a full run.
