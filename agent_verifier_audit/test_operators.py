"""Offline unit tests for the output-mutation operators (no Docker, no network)."""
import json

from agent_verifier_audit.operators import ACCEPT, REJECT, mutants_for


def test_numeric_answer_gets_substring_mutants():
  ops = {m.operator: m for m in mutants_for("79586")}
  assert ops["APD"].content == "795860" and ops["APD"].expectation == REJECT
  assert ops["PPD"].content == "179586"
  assert ops["WS"].expectation == ACCEPT


def test_text_mutants_never_equal_oracle_when_rejectable():
  for oracle in ["honeybear", "flag{x}", "g2g4 e2e4", "A"]:
    for m in mutants_for(oracle):
      if m.expectation == REJECT:
        assert m.content.strip() != oracle.strip(), (oracle, m.operator)


def test_json_list_mutants():
  oracle = json.dumps([{"word": "testword02", "value": 10.0},
                       {"word": "testword03", "value": 25.0}])
  ops = {m.operator: m for m in mutants_for(oracle)}
  sup = json.loads(ops["SUP"].content)
  assert len(sup) == 52 and sup[:2] == json.loads(oracle)
  assert all(r not in json.loads(oracle) for r in sup[2:])
  assert ops["ORD"].expectation == ACCEPT


if __name__ == "__main__":
  test_numeric_answer_gets_substring_mutants()
  test_text_mutants_never_equal_oracle_when_rejectable()
  test_json_list_mutants()
  print("all operator tests passed")
