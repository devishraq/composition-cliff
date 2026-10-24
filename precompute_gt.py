import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import threading
from typing import Optional
from mutator import DafnyASTMutator
from verifier import DafnyVerifier


def precompute_ground_truth_baselines(
    manifest_path: str = "dataset/clover_bench/clover_tasks.json",
    out_path: str = "dataset/clover_bench/gt_mutant_baseline.json",
    workers: Optional[int] = None,
):
  m_path = Path(manifest_path)
  if not m_path.exists():
    print(f"[!] Manifest missing at {m_path}", flush=True)
    return

  with open(m_path, "r", encoding="utf-8") as f:
    tasks = json.load(f)

  mutator = DafnyASTMutator()
  gt_baseline = {}
  lock = threading.Lock()
  num_workers = (
      workers if workers is not None else max(1, (os.cpu_count() or 4) - 2)
  )

  print(
      f"[*] Profiling Ground-Truth Mutant Baselines across {len(tasks)} tasks"
      f" using {num_workers} parallel workers...",
      flush=True,
  )

  def process_task(task, idx):
    verifier = DafnyVerifier()
    name = task["task_name"]
    sig = task["signature"]
    specs = task["ground_truth_specs"]
    body = task["implementation_body"]

    mutants = mutator.generate_mutants(sig, specs, body)
    killed_ids = []
    survivor_ids = []

    for m in mutants:
      res = verifier.verify_code(m.full_code)
      if not res.verified:
        killed_ids.append(m.mutant_id)
      else:
        survivor_ids.append(m.mutant_id)

    total = len(mutants)
    killable = len(killed_ids)

    result = {
        "task_name": name,
        "total_mutants": total,
        "killable_mutants_count": killable,
        "equivalent_mutants_count": len(survivor_ids),
        "killable_mutant_ids": killed_ids,
        "equivalent_mutant_ids": survivor_ids,
        "gt_raw_score": round(killable / total, 4) if total > 0 else 1.0,
    }

    with lock:
      gt_baseline[name] = result
      print(
          f"[{len(gt_baseline):03d}/{len(tasks):03d}] {name:<35} | Total:"
          f" {total:<3} | Killable: {killable:<3} | Equiv:"
          f" {len(survivor_ids):<2} | Raw S_comp: {result['gt_raw_score']}",
          flush=True,
      )

  with ThreadPoolExecutor(max_workers=num_workers) as executor:
    futures = [
        executor.submit(process_task, task, i) for i, task in enumerate(tasks)
    ]
    for future in as_completed(futures):
      future.result()

  ordered_gt_baseline = {
      t["task_name"]: gt_baseline[t["task_name"]]
      for t in tasks
      if t["task_name"] in gt_baseline
  }

  o_path = Path(out_path)
  o_path.parent.mkdir(parents=True, exist_ok=True)
  with open(o_path, "w", encoding="utf-8") as f:
    json.dump(ordered_gt_baseline, f, indent=2)

  print(
      f"\n[✓] Ground-truth baseline for all {len(ordered_gt_baseline)} tasks"
      f" saved to: {o_path}",
      flush=True,
  )


if __name__ == "__main__":
  parser = argparse.ArgumentParser(
      description="Precompute Ground-Truth Mutant Baseline"
  )
  parser.add_argument(
      "--manifest",
      type=str,
      default="dataset/clover_bench/clover_tasks.json",
      help="Path to tasks JSON file",
  )
  parser.add_argument(
      "--output",
      type=str,
      default="dataset/clover_bench/gt_mutant_baseline.json",
      help="Path to output ground-truth baseline JSON",
  )
  parser.add_argument(
      "--workers",
      type=int,
      default=None,
      help="Number of parallel worker threads",
  )
  args = parser.parse_args()

  precompute_ground_truth_baselines(
      manifest_path=args.manifest, out_path=args.output, workers=args.workers
  )
