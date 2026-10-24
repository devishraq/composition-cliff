import json
from pathlib import Path
from mutator import DafnyASTMutator
from verifier import DafnyVerifier


def test_single_task():
  manifest_path = Path("dataset/clover_bench/clover_tasks.json")
  if not manifest_path.exists():
    print(f"[!] {manifest_path} not found.")
    return

  with open(manifest_path, "r", encoding="utf-8") as f:
    tasks = json.load(f)

  task = tasks[0]
  print(f"[*] Testing task: {task['task_name']}")

  verifier = DafnyVerifier(dafny_path="dafny")
  mutator = DafnyASTMutator()

  gt_result = verifier.verify_code(task["full_code"])
  print(
      f"Ground Truth Verified: {gt_result.verified} (Errors:"
      f" {gt_result.error_count})"
  )

  mutants = mutator.generate_mutants(
      signature=task["signature"],
      specs=task["ground_truth_specs"],
      body=task["implementation_body"],
  )
  print(f"Generated {len(mutants)} AST mutants.")

  killed = 0
  for m in mutants:
    res = verifier.verify_code(m.full_code)
    if not res.verified:
      killed += 1
    else:
      print(f"  [SURVIVOR] Mutant {m.mutant_id} ({m.operator}) survived!")
      print(f"    Original: {m.original_snippet}")
      print(f"    Mutated : {m.mutated_snippet}")

  score = killed / len(mutants) if mutants else 1.0
  print(f"Raw Mutation Score S_comp: {score:.2f} ({killed}/{len(mutants)})")


if __name__ == "__main__":
  test_single_task()