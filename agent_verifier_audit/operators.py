"""Output-mutation operators for auditing agent-task verifiers.

Mutation-CEGIS mutates a *program* to test whether a *specification* is too weak.
Here we mutate an agent's *output* (the artifact a verifier reads) to test whether
the task's *verifier* is too weak. Each mutant carries an expectation:

  REJECT  - the output is wrong or gamed; a sound verifier must fail it.
  ACCEPT  - the output is semantically identical; a verifier should pass it.
  NEUTRAL - debatable (e.g. partial credit); reported but never scored.

A REJECT mutant that the verifier passes is a *surviving mutant*: concrete evidence
that the verifier admits wrong answers (the agent-task analogue of a vacuous spec).
"""
from dataclasses import dataclass
import json
import re
from typing import List

REJECT, ACCEPT, NEUTRAL = "reject", "accept", "neutral"


@dataclass
class OutputMutant:
  operator: str
  expectation: str
  content: str
  description: str


_NUM = re.compile(r"-?\d+(?:\.\d+)?")


def _flip_char(s: str) -> str:
  if not s:
    return "x"
  c = s[-1]
  repl = "0" if c.isdigit() and c != "0" else ("1" if c.isdigit() else
         (c.lower() if c.isupper() else (c.upper() if c.islower() else "#")))
  return s[:-1] + repl


def text_mutants(oracle: str) -> List[OutputMutant]:
  """Mutants for plain-text answer files (numbers, passwords, flags, moves)."""
  core = oracle.strip()
  out: List[OutputMutant] = [
      OutputMutant("WS", ACCEPT, core + "\n",
                   "trailing newline (semantically identical)"),
      OutputMutant("CHF", REJECT, _flip_char(core),
                   "last character changed"),
      OutputMutant("TRN", REJECT, core[:-1] if len(core) > 1 else "",
                   "last character dropped"),
      OutputMutant("HDG", REJECT,
                   "\n".join([_flip_char(core), core, core + "0"]),
                   "hedged: correct answer listed among wrong candidates"),
      OutputMutant("LOG", REJECT,
                   f"debug: step 1 ok\nvalue={core}\nother=12345\n",
                   "answer buried inside a log dump"),
  ]
  if _NUM.fullmatch(core):
    out.append(OutputMutant("APD", REJECT, core + "0",
                            "digit appended: different number containing the answer"))
    out.append(OutputMutant("PPD", REJECT, "1" + core,
                            "digit prepended: different number containing the answer"))
  return out


def json_list_mutants(oracle: str, n_fabricated: int = 50) -> List[OutputMutant]:
  """Mutants for JSON list-of-records answers (e.g. recovered DB rows)."""
  rows = json.loads(oracle)
  if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
    return []
  template = rows[0]

  def fake(i: int) -> dict:
    r = {}
    for k, v in template.items():
      if isinstance(v, bool):
        r[k] = not v
      elif isinstance(v, (int, float)):
        r[k] = type(v)(1000 + i)
      else:
        r[k] = f"{str(v)[:-2]}{i:02d}fab"
    return r

  fabricated = [fake(i) for i in range(n_fabricated)]
  perturbed = [dict(r) for r in rows]
  for r in perturbed:
    for k, v in r.items():
      if isinstance(v, (int, float)) and not isinstance(v, bool):
        r[k] = v + 1
        break
  return [
      OutputMutant("SUP", REJECT, json.dumps(rows + fabricated),
                   f"all correct rows + {n_fabricated} fabricated rows"),
      OutputMutant("SUP-1", REJECT, json.dumps(rows[:-1] + fabricated),
                   f"one correct row missing + {n_fabricated} fabricated rows"),
      OutputMutant("VAL", REJECT, json.dumps(perturbed),
                   "every row has a wrong numeric value"),
      OutputMutant("DUP", NEUTRAL, json.dumps(rows + rows),
                   "every row duplicated"),
      OutputMutant("DRP", NEUTRAL, json.dumps(rows[:-1]),
                   "one correct row missing (partial credit)"),
      OutputMutant("ORD", ACCEPT, json.dumps(list(reversed(rows))),
                   "same rows, reversed order"),
  ]


def mutants_for(oracle: str) -> List[OutputMutant]:
  try:
    if isinstance(json.loads(oracle), list):
      return json_list_mutants(oracle)
  except (ValueError, TypeError):
    pass
  return text_mutants(oracle)
