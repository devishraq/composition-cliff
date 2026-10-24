"""
SMSP Multi-Model Parallel Orchestrator for Track B (DafnyComp-300)
Runs all frontier models simultaneously in parallel processes with high concurrency.
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path
import json

MODELS_CONFIG = [
    {
        "model": "deepseek/deepseek-v4-flash-0731",
        "modes": "mutation_cegis",
        "workers": 25,
    },
    {
        "model": "google/gemini-3.7-flash",
        "modes": "compiler_only,mutation_cegis",
        "workers": 25,
    },
    {
        "model": "inclusionai/ling-3.0-flash",
        "modes": "compiler_only,mutation_cegis",
        "workers": 25,
    },
    {
        "model": "z-ai/glm-5.3-flash",
        "modes": "compiler_only,mutation_cegis",
        "workers": 25,
    },
    {
        "model": "openai/gpt-5.6-luna",
        "modes": "compiler_only,mutation_cegis",
        "workers": 25,
    },
    {
        "model": "qwen/qwen3.7-flash",
        "modes": "compiler_only,mutation_cegis",
        "workers": 25,
    },
]

def build_final_summary(dataset_name="dafny_comp"):
    results_dir = Path("results") / dataset_name
    summaries = []
    
    for model_dir in sorted(results_dir.glob("*")):
        if not model_dir.is_dir():
            continue
        for mode_file in sorted(model_dir.glob("*.json")):
            if mode_file.name == "summary.json":
                continue
            try:
                with open(mode_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    tasks = data.get("tasks", [])
                    hardened = sum(1 for t in tasks if t.get("task_success", False))
                    total = len(tasks)
                    avg_raw = sum(t.get("final_raw_score", 0.0) for t in tasks) / total if total else 0.0
                    avg_adj = sum(t.get("final_adj_score", 0.0) for t in tasks) / total if total else 0.0
                    avg_turns = sum(t.get("turns_taken", 0) for t in tasks) / total if total else 0.0
                    summaries.append({
                        "model": data.get("model_slug", model_dir.name),
                        "eval_mode": data.get("eval_mode", mode_file.stem),
                        "total_tasks": total,
                        "hardened_count": hardened,
                        "hardened_pct": round((hardened / total * 100) if total else 0.0, 2),
                        "avg_raw_mutation_score": round(avg_raw, 4),
                        "avg_adj_mutation_score": round(avg_adj, 4),
                        "avg_turns": round(avg_turns, 2),
                    })
            except Exception as e:
                print(f"Error reading {mode_file}: {e}")
                
    summary_file = results_dir / "summary.json"
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(summaries, f, indent=2)
    print(f"\n[✓] Compiled final summary with {len(summaries)} benchmark runs to: {summary_file}")

def main():
    parser = argparse.ArgumentParser(description="SMSP Parallel Multi-Model Runner")
    parser.add_argument("--manifest", default="dataset/dafny_comp/dafnycomp_tasks.json")
    parser.add_argument("--baseline", default="dataset/dafny_comp/gt_mutant_baseline.json")
    parser.add_argument("--per-model-workers", type=int, default=25)
    args = parser.parse_args()

    print("=" * 80)
    print("🚀 SMSP MULTI-MODEL MASSIVE PARALLEL DISPATCH (Track B: DafnyComp-300)")
    print(f"Launching 6 Frontier Models simultaneously with {args.per_model_workers} workers per model (~150 total threads)")
    print("=" * 80)

    processes = {}
    logs_dir = Path("results/parallel_logs")
    logs_dir.mkdir(parents=True, exist_ok=True)

    for cfg in MODELS_CONFIG:
        model = cfg["model"]
        modes = cfg["modes"]
        workers = args.per_model_workers
        safe_name = model.replace("/", "_").replace(":", "_")
        log_path = logs_dir / f"{safe_name}.log"

        cmd = [
            sys.executable,
            "-u",
            "run_eval.py",
            "--manifest", args.manifest,
            "--baseline", args.baseline,
            "--model", model,
            "--mode", modes,
            "--workers", str(workers),
        ]

        log_file = open(log_path, "w", buffering=1)
        proc = subprocess.Popen(cmd, stdout=log_file, stderr=subprocess.STDOUT)
        processes[model] = (proc, log_file, log_path)
        print(f"[*] Launched [{model}] -> PID {proc.pid} (Modes: {modes}, Workers: {workers}, Log: {log_path})")

    print("\n[+] All 6 model workers are running simultaneously in parallel!")
    print("[+] Monitoring progress until all processes finish...\n")

    while processes:
        time.sleep(10)
        done_models = []
        for model, (proc, log_file, log_path) in processes.items():
            ret = proc.poll()
            if ret is not None:
                log_file.close()
                done_models.append(model)
                if ret == 0:
                    print(f"[✓] COMPLETED: {model} (Exited normally with code 0)")
                else:
                    print(f"[!] FAILED/EXITED: {model} with returncode {ret}. Check log: {log_path}")

        for m in done_models:
            del processes[m]

    build_final_summary()
    print("\n🎉 ALL MODEL EVALUATIONS FINISHED!")

if __name__ == "__main__":
    main()
