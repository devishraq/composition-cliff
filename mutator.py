from dataclasses import dataclass
import hashlib
import re
from typing import List


@dataclass
class Mutant:
  mutant_id: str
  operator: str
  original_snippet: str
  mutated_snippet: str
  full_code: str
  line_number: int


class DafnyASTMutator:
  """Generates deterministic syntactic and semantic mutants on Dafny method implementations."""

  RELATIONAL_MAP = {
      "<=": ["<", ">=", "=="],
      ">=": [">", "<=", "=="],
      "<": ["<=", ">", "!="],
      ">": [">=", "<", "!="],
      "==": ["!="],
      "!=": ["=="],
  }

  ARITHMETIC_MAP = {
      "+": ["-", "*"],
      "-": ["+", "*"],
      "*": ["+", "/"],
  }

  def generate_mutants(
      self, signature: str, specs: str, body: str
  ) -> List[Mutant]:
    mutants: List[Mutant] = []
    lines = body.splitlines()

    for idx, line in enumerate(lines):
      stripped = line.strip()

      if stripped.startswith(
          ("invariant", "decreases", "assert", "assume", "//", "/*", "*")
      ):
        continue

      for op, replacements in self.RELATIONAL_MAP.items():
        pattern = re.compile(rf"(?<![<>=!])({re.escape(op)})(?![<>=!])")
        for match in pattern.finditer(line):
          for repl in replacements:
            mutated_line = line[: match.start()] + repl + line[match.end() :]
            mutants.append(
                self._create_mutant(
                    "ROR",
                    line,
                    mutated_line,
                    idx + 1,
                    signature,
                    specs,
                    lines,
                    idx,
                )
            )

      for op, replacements in self.ARITHMETIC_MAP.items():
        pattern = re.compile(rf"(?<![\+\-\*\/])({re.escape(op)})(?![\+\-\*\/])")
        for match in pattern.finditer(line):
          for repl in replacements:
            mutated_line = line[: match.start()] + repl + line[match.end() :]
            mutants.append(
                self._create_mutant(
                    "AOR",
                    line,
                    mutated_line,
                    idx + 1,
                    signature,
                    specs,
                    lines,
                    idx,
                )
            )

      for match in re.finditer(r"\b(\d+)\b", line):
        val = int(match.group(1))
        replacements = [str(val + 1), str(max(0, val - 1))]
        if val != 0:
          replacements.append("0")

        for repl in set(replacements):
          if repl == str(val):
            continue
          mutated_line = line[: match.start()] + repl + line[match.end() :]
          mutants.append(
              self._create_mutant(
                  "CR",
                  line,
                  mutated_line,
                  idx + 1,
                  signature,
                  specs,
                  lines,
                  idx,
              )
          )

      if stripped.startswith("if ") and "{" in stripped:
        cond_match = re.search(r"if\s+(.+?)\s*\{", line)
        if cond_match:
          cond = cond_match.group(1).strip()
          inverted = f"!({cond})" if not cond.startswith("!") else cond[1:]
          mutated_line = line.replace(cond, inverted, 1)
          mutants.append(
              self._create_mutant(
                  "CID",
                  line,
                  mutated_line,
                  idx + 1,
                  signature,
                  specs,
                  lines,
                  idx,
              )
          )

      if re.search(r"\breturn\b", line):
        if "true" in line:
          mutated_line = line.replace("true", "false", 1)
        elif "false" in line:
          mutated_line = line.replace("false", "true", 1)
        elif stripped == "return;":
          mutated_line = line.replace("return;", "// removed return;")
        else:
          mutated_line = line.rstrip(";") + " + 1;"

        mutants.append(
            self._create_mutant(
                "RSM", line, mutated_line, idx + 1, signature, specs, lines, idx
            )
        )

    return self._deduplicate(mutants)

  def _create_mutant(
      self,
      operator: str,
      orig: str,
      mut: str,
      line_no: int,
      signature: str,
      specs: str,
      lines: List[str],
      idx: int,
  ) -> Mutant:
    body_copy = list(lines)
    body_copy[idx] = mut
    mutated_body = "\n".join(body_copy)
    full_code = f"{signature}\n{specs}\n{mutated_body}".strip()

    h = hashlib.sha1(f"{operator}:{line_no}:{mut.strip()}".encode()).hexdigest()[
        :8
    ]
    mutant_id = f"{operator}_L{line_no}_{h}"

    return Mutant(
        mutant_id=mutant_id,
        operator=operator,
        original_snippet=orig.strip(),
        mutated_snippet=mut.strip(),
        full_code=full_code,
        line_number=line_no,
    )

  def _deduplicate(self, mutants: List[Mutant]) -> List[Mutant]:
    seen = set()
    unique = []
    for m in mutants:
      if m.full_code not in seen:
        seen.add(m.full_code)
        unique.append(m)
    return unique