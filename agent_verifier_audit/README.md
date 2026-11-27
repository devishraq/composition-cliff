# Agent Verifier Audit: Mutation Testing for Benchmark Verifiers

Mutation-CEGIS tests whether a **specification** is too weak by mutating the **program**.
This extension applies the same idea one level up, to agent benchmarks: it mutates an
agent's **output** to test whether the task's **verifier** is too weak.

A verifier that passes a deliberately wrong or gamed output has a *surviving mutant*.
That is the agent-task analogue of a vacuous contract (`ensures res >= 0`), and it is
exactly the kind of gap that lets agents score without solving the task.

## Mutation operators (`operators.py`)

| Op | Applies to | Expectation | What it does |
|---|---|---|---|
| `WS` | text | accept | trailing newline (semantically identical) |
| `CHF` / `TRN` | text | reject | change / drop the last character |
| `HDG` | text | reject* | hedge: correct answer listed among wrong candidates |
| `LOG` | text | reject | answer buried inside a log dump |
| `APD` / `PPD` | numbers | reject | append / prepend a digit (a different number that *contains* the answer) |
| `SUP` / `SUP-1` | JSON rows | reject | correct rows + 50 fabricated rows |
| `VAL` | JSON rows | reject | wrong numeric values |
| `DUP` / `DRP` | JSON rows | neutral | duplicated rows / partial recovery (reported, not scored) |
| `ORD` | JSON rows | accept | same rows, reversed order |

\* Tasks whose instruction explicitly allows an operator (e.g. `password-recovery`:
"You are allowed to make multiple guesses") mark it `neutral_operators` in the oracle file.

## Results on Terminal-Bench 2.1 (file mode, 10 tasks)

Benchmark: [`harbor-framework/terminal-bench-2-1`](https://github.com/harbor-framework/terminal-bench-2-1) @ `12b7565`.
Cost: $0 (no LLM calls; the real `tests/test_outputs.py` is run on each mutant).

| | |
|---|---|
| Tasks audited | 10 |
| Killable (should-reject) mutants | 40 |
| Surviving mutants | **6** (mutation score 0.85) |
| Verifiers with survivors | **2 / 10** |

**`count-dataset-tokens`** checks `expected in actual`, so it accepts the wrong answers
`795860` and `179586`, a hedged list of candidates, and the answer buried in a log.

**`sqlite-db-truncate`** counts how many true rows appear but never penalises extra rows,
so it accepts the correct rows plus 50 fabricated rows, and even 7/8 true rows plus 50 fabricated ones.

The other 8 verifiers (exact-match checks) killed every rejectable mutant and accepted
every semantically identical one. Full per-mutant log: `results/tb21_file_mode.json`.

**Scope and limits.** These 10 tasks are the TB-2.1 tasks whose verifiers only read answer
files under `/app` and whose expected answer is stated in the verifier. Mutants are
hand-designed operators, not exhaustive; a surviving mutant is evidence of weakness, and a
killed set is not proof of strength. Container-state tasks need docker mode.

## Results on Terminal-Bench 2.1 (Docker mode, all 89 tasks)

Run on Apple Silicon with `--platform linux/amd64`; raw output in `results/tb21_docker_full.json`.

| Outcome | Tasks |
|---|---|
| Mutated and scored | 57 |
| Reference solution passes but writes no checkable answer file (code, binaries or state only) | 14 |
| Reference solution fails in this harness (services, VMs, long builds) | 15 |
| Error: 900 s timeout (2), binary-file decode bug in this tool (1, fixed in this commit) | 3 |

Of the 57 scored tasks, 11 had at least one mutant survive (27 of 256 rejectable mutants, 0.894
mutation score). **Survival is not the same as a weak verifier.** Reading the test files of the 11:

- **Accepts wrong answers (verifier checks containment, not equality):** `count-dataset-tokens`
  (`79586` only has to appear in the file), `sqlite-db-truncate` (correct rows plus 50 fabricated
  rows pass), `feal-linear-cryptanalysis` (each expected token only has to appear somewhere in the
  file).
- **Tolerant by design, so not a flaw:** `extract-moves-from-video` (Levenshtein similarity),
  `adaptive-rejection-sampler` (statistical test), `winning-avg-corewars` (win-rate thresholds),
  `break-filter-js-from-html` (runs the page and checks an alert fires).
- **Not triaged:** `dna-assembly`, `dna-insert`, `make-mips-interpreter`, `openssl-selfsigned-cert`.
  Their survivors are mostly last-character edits, which are probably a trailing newline or a
  value range, but this has not been checked.
- **False rejects (rejects an equivalent answer):** `build-pov-ray` and `sanitize-git-repo`
  (trailing newline), `db-wal-recovery` (row order). These may be intended.

Docker mode skips any file the verifier still accepts when emptied, so solver scripts are not
counted as answers. Only answer files up to 64 kB are mutated, so tasks whose output is a large
file or a service are not covered.

## Usage

```bash
# Unit tests for the operators (offline)
uv run python -m agent_verifier_audit.test_operators

# Get the benchmark
git clone https://github.com/harbor-framework/terminal-bench-2-1.git ../terminal-bench-2-1

# File mode: no containers, runs in seconds
uv run python -m agent_verifier_audit.audit file \
    --tasks ../terminal-bench-2-1/tasks \
    --oracles agent_verifier_audit/oracles_tb21.json

# Docker mode (experimental): runs each task's reference solution in its container,
# finds the answer files it wrote under /app, mutates them on a snapshot, and runs tests/test.sh.
# On Apple Silicon add --platform linux/amd64.
uv run python -m agent_verifier_audit.audit docker \
    --tasks ../terminal-bench-2-1/tasks \
    --only count-dataset-tokens sqlite-db-truncate
```

Docker mode needs Docker and network access for the task images. It has been smoke-tested on
`count-dataset-tokens` and `sqlite-db-truncate` (Apple Silicon, `--platform linux/amd64`), where it
reproduces the file-mode survivors inside the real containers (6 survivors of 9 rejectable mutants
on those two tasks, which were picked because file mode had flagged them, so 0.333 is not a
benchmark-wide rate). It has not yet been run across the full benchmark.
