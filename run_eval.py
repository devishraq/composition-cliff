import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import threading
import time
from typing import Optional
from dotenv import load_dotenv
from synthesizer import MutationCEGISSynthesizer
from verifier import DafnyVerifier

load_dotenv()

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

DEFAULT_MODELS = [
    "deepseek/deepseek-v4-flash-0731",
    "google/gemini-3.7-flash",
    "inclusionai/ling-3.0-flash",
    "z-ai/glm-5.3-flash",
    "openai/gpt-5.6-luna",
    "qwen/qwen3.7-flash",
]


def get_default_workers() -> int:
  cpu_cores = os.cpu_count() or 4
  return max(1, cpu_cores - 2)


def evaluate_model(
    model_slug: str,
    tasks: list,
    max_turns: int,
    output_dir: Path,
    baseline_path: str,
    dataset_name: str = "clover_bench",
    eval_mode: str = "mutation_cegis",
    max_tokens: int = 32768,
    temperature: float = 0.0,
    top_p: float = 1.0,
    workers: Optional[int] = None,
):
  safe_name = model_slug.replace("/", "_").replace(":", "_")
  model_dir = output_dir / dataset_name / safe_name
  model_dir.mkdir(parents=True, exist_ok=True)
  output_file = model_dir / f"{eval_mode}.json"
  num_workers = workers if workers is not None else get_default_workers()

  verifier = DafnyVerifier()
  dafny_ver = verifier.get_version()

  hyperparameters = {
      "temperature": temperature,
      "top_p": top_p,
      "max_tokens": max_tokens,
      "max_turns": max_turns,
  }

  print(f"\n{'='*70}")
  print(f"[*] LAUNCHING BENCHMARK: {model_slug}")
  print(f"[*] Evaluation Mode: {eval_mode}")
  print(f"[*] Dafny Version: {dafny_ver}")
  print(f"[*] Concurrency: {num_workers} parallel workers (CPU cores: {os.cpu_count()})")
  print(f"[*] Token Budget: {max_tokens} max tokens (Thinking/Reasoning Space)")
  print(f"{'='*70}")

  synthesizer = MutationCEGISSynthesizer(
      model_name=model_slug,
      api_key=OPENROUTER_API_KEY,
      base_url=OPENROUTER_BASE_URL,
      max_turns=max_turns,
      max_tokens=max_tokens,
      eval_mode=eval_mode,
      baseline_path=baseline_path,
  )

  results_dict = {}
  file_lock = threading.Lock()
  start_time = time.time()

  if output_file.exists():
    try:
      with open(output_file, "r", encoding="utf-8") as f:
        existing_data = json.load(f)
        for t in existing_data.get("tasks", []):
          if t.get("task_name"):
            results_dict[t["task_name"]] = t
    except Exception:
      pass

  def process_task(task, idx):
    if task["task_name"] in results_dict:
      return results_dict[task["task_name"]]

    print(f"[{safe_name}] [Task {idx+1:02d}/{len(tasks)}] Started: {task['task_name']}")
    try:
      task_res = synthesizer.synthesize_and_repair(task)
    except Exception as e:
      print(f"  [!] ERROR on {task['task_name']}: {e}")
      task_res = {
          "task_name": task["task_name"],
          "loc": len([l for l in task["implementation_body"].splitlines() if l.strip()]),
          "loop_count": 0,
          "total_ast_mutants": 0,
          "gt_killable_mutants": 0,
          "task_success": False,
          "total_turns_taken": 0,
          "final_specs": "",
          "final_raw_score": 0.0,
          "final_adj_score": 0.0,
          "task_total_tokens": 0,
          "task_cached_tokens": 0,
          "task_effective_cache_hit_ratio": 0.0,
          "error": str(e),
          "turn_history": [],
      }

    with file_lock:
      results_dict[task["task_name"]] = task_res
      ordered_results = [
          results_dict[t["task_name"]]
          for t in tasks
          if t["task_name"] in results_dict
      ]
      
      full_report = {
          "model_slug": model_slug,
          "eval_mode": eval_mode,
          "dafny_version": dafny_ver,
          "hyperparameters": hyperparameters,
          "tasks": ordered_results,
      }
      
      with open(output_file, "w", encoding="utf-8") as out:
        json.dump(full_report, out, indent=2)

    return task_res

  with ThreadPoolExecutor(max_workers=num_workers) as executor:
    futures = [
        executor.submit(process_task, task, i) for i, task in enumerate(tasks)
    ]
    for future in as_completed(futures):
      future.result()

  ordered_results = [
      results_dict[t["task_name"]]
      for t in tasks
      if t["task_name"] in results_dict
  ]
  elapsed = time.time() - start_time
  total_passed = sum(1 for r in ordered_results if r.get("task_success", False))
  avg_raw = (
      sum(r.get("final_raw_score", 0.0) for r in ordered_results)
      / len(ordered_results)
      if ordered_results
      else 0.0
  )
  avg_adj = (
      sum(r.get("final_adj_score", 0.0) for r in ordered_results)
      / len(ordered_results)
      if ordered_results
      else 0.0
  )
  avg_turns = (
      sum(r.get("total_turns_taken", 0) for r in ordered_results)
      / len(ordered_results)
      if ordered_results
      else 0.0
  )
  total_tokens = sum(r.get("task_total_tokens", 0) for r in ordered_results)
  total_cached = sum(r.get("task_cached_tokens", 0) for r in ordered_results)
  avg_cache_hit = (
      sum(r.get("task_effective_cache_hit_ratio", 0.0) for r in ordered_results)
      / len(ordered_results)
      if ordered_results
      else 0.0
  )

  summary = {
      "model": model_slug,
      "eval_mode": eval_mode,
      "dafny_version": dafny_ver,
      "hyperparameters": hyperparameters,
      "total_tasks": len(tasks),
      "hardened_count": total_passed,
      "hardened_pct": (
          round(total_passed / len(tasks) * 100, 2) if tasks else 0
      ),
      "avg_raw_mutation_score": round(avg_raw, 4),
      "avg_adj_mutation_score": round(avg_adj, 4),
      "avg_turns": round(avg_turns, 2),
      "total_tokens_consumed": total_tokens,
      "total_cached_tokens": total_cached,
      "mean_cache_hit_ratio": round(avg_cache_hit, 4),
      "elapsed_seconds": round(elapsed, 1),
  }

  print(f"\n--- {model_slug} [{eval_mode}] Summary ---")
  print(
      f"Hardened (S_adj = 1.0) : {summary['hardened_count']}/{summary['total_tasks']} ({summary['hardened_pct']}%)"
  )
  print(f"Avg Raw S_comp        : {summary['avg_raw_mutation_score']}")
  print(f"Avg Adj S_comp        : {summary['avg_adj_mutation_score']}")
  print(f"Avg Turns             : {summary['avg_turns']}")
  print(f"Total Tokens          : {summary['total_tokens_consumed']}")
  print(f"Cached Tokens         : {summary['total_cached_tokens']}")
  print(f"Mean Cache Hit Ratio  : {round(summary['mean_cache_hit_ratio']*100, 2)}%")
  print(f"Time Taken            : {summary['elapsed_seconds']}s")
  print(f"Saved to              : {output_file}")

  return summary


def main():
  parser = argparse.ArgumentParser(
      description="Mutation CEGIS Benchmark Runner (OpenRouter)"
  )
  parser.add_argument(
      "--model",
      type=str,
      default="all",
      help="Model slug on OpenRouter, comma-separated list, or 'all'",
  )
  parser.add_argument(
      "--mode",
      type=str,
      default="all_modes",
      help="Ablation mode (zero_shot, compiler_only, mutation_cegis, all_modes, or comma-separated list)",
  )
  parser.add_argument(
      "--manifest",
      type=str,
      default="dataset/clover_bench/clover_tasks.json",
      help="Path to tasks JSON file",
  )
  parser.add_argument(
      "--baseline",
      type=str,
      default="dataset/clover_bench/gt_mutant_baseline.json",
      help="Path to precomputed ground-truth mutant baseline",
  )
  parser.add_argument(
      "--max-turns", type=int, default=4, help="Max CEGIS repair turns"
  )
  parser.add_argument(
      "--max-tokens",
      type=int,
      default=32768,
      help="Max token generation space for thinking models",
  )
  parser.add_argument(
      "--workers",
      type=int,
      default=None,
      help="Number of parallel worker threads (default: CPU count - 2)",
  )
  parser.add_argument(
      "--output-dir", type=str, default="results", help="Output directory"
  )
  args = parser.parse_args()

  if not OPENROUTER_API_KEY:
    raise ValueError("[!] OPENROUTER_API_KEY environment variable is not set.")

  manifest_path = Path(args.manifest)
  if not manifest_path.exists():
    raise FileNotFoundError(f"[!] Manifest not found at: {manifest_path}")

  dataset_name = manifest_path.parent.name or manifest_path.stem

  with open(manifest_path, "r", encoding="utf-8") as f:
    tasks = json.load(f)

  output_dir = Path(args.output_dir)
  output_dir.mkdir(parents=True, exist_ok=True)

  models_to_run = (
      DEFAULT_MODELS
      if args.model == "all"
      else [m.strip() for m in args.model.split(",")]
  )

  modes_to_run = (
      ["zero_shot", "compiler_only", "mutation_cegis"]
      if args.mode == "all_modes"
      else [m.strip() for m in args.mode.split(",")]
  )

  summaries = []
  for mode in modes_to_run:
    for model in models_to_run:
      summary = evaluate_model(
          model_slug=model,
          tasks=tasks,
          max_turns=args.max_turns,
          output_dir=output_dir,
          baseline_path=args.baseline,
          dataset_name=dataset_name,
          eval_mode=mode,
          max_tokens=args.max_tokens,
          workers=args.workers,
      )
      summaries.append(summary)

  dataset_dir = output_dir / dataset_name
  dataset_dir.mkdir(parents=True, exist_ok=True)
  summary_file = dataset_dir / "summary.json"
  with open(summary_file, "w", encoding="utf-8") as f:
    json.dump(summaries, f, indent=2)

  print("\n" + "=" * 118)
  print(
      f"{'Model':<32} | {'Mode':<15} | {'Hardened (S_adj=1.0)':<20} |"
      f" {'Avg S_raw':<10} | {'Avg S_adj':<10} | {'Turns':<6} | {'Cache Hit':<10}"
  )
  print("-" * 118)
  for s in summaries:
    hardened_str = (
        f"{s['hardened_count']}/{s['total_tasks']} ({s['hardened_pct']}%)"
    )
    cache_str = f"{round(s.get('mean_cache_hit_ratio', 0.0)*100, 1)}%"
    print(
        f"{s['model']:<32} | {s['eval_mode']:<15} | {hardened_str:<20} |"
        f" {s['avg_raw_mutation_score']:<10} |"
        f" {s['avg_adj_mutation_score']:<10} | {s['avg_turns']:<6} | {cache_str:<10}"
    )
  print("=" * 118)
  print(f"\n[✓] All benchmarks finished. Summary written to: {summary_file}")


if __name__ == "__main__":
  main()