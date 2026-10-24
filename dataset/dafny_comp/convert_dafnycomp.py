import json
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
RAW_JSON_PATH = BASE_DIR / "raw_dafnycomp_300.json"
OUTPUT_JSON_PATH = BASE_DIR / "dafnycomp_tasks.json"


def parse_dafnycomp_entry(org_input: str, gt_output: str, task_id: int):
  main_match = (
      re.search(r"\n\s*(method\s+main_\w+[\s\S]+)$", gt_output)
      or re.search(r"(method\s+main_\w+[\s\S]+)$", gt_output)
      or re.search(r"\n\s*(method\s+[\s\S]+)$", gt_output)
  )

  helpers_with_specs = (
      gt_output[: main_match.start()].strip() if main_match else ""
  )
  gt_main_block = main_match.group(1).strip() if main_match else gt_output

  body_match = re.search(r"\n\s*\{(?!\:)", gt_main_block) or re.search(
      r"\{(?!\:)", gt_main_block
  )

  if body_match:
    main_sig_and_specs = gt_main_block[: body_match.start()].strip()
    main_body = gt_main_block[body_match.start() :].strip()
  else:
    main_sig_and_specs = gt_main_block.splitlines()[0].strip()
    main_body = "{}"

  sig_match = re.search(
      r"(method\s+main_\w+\s*\([^)]*\)\s*returns\s*\([^)]*\))",
      main_sig_and_specs,
  ) or re.search(
      r"(method\s+[\s\S]+?)(?=\n\s*(?:requires|ensures|modifies|reads|decreases)|$)",
      main_sig_and_specs,
  )

  main_signature = (
      sig_match.group(1).strip()
      if sig_match
      else main_sig_and_specs.splitlines()[0].strip()
  )
  ground_truth_specs = main_sig_and_specs[len(main_signature) :].strip()

  name_match = re.search(r"method\s+([A-Za-z0-9_]+)", main_signature)
  method_name = name_match.group(1) if name_match else f"main_comp_{task_id:03d}"
  task_name = f"dafnycomp_{task_id:03d}_{method_name}"
  docstring = (
      f"Synthesize complete compositional Dafny specifications for {method_name}"
      " across the multi-function call graph."
  )

  full_signature = (
      f"{helpers_with_specs}\n\n{main_signature}"
      if helpers_with_specs
      else main_signature
  )

  prompt_skeleton = (
      f"// Helper subroutines & pipeline logic:\n{helpers_with_specs}\n\n"
      "// TOFILL: requires and ensures contracts for the compositional"
      f" pipeline\n{main_signature}\n{main_body}"
  )

  return {
      "task_id": task_id,
      "task_name": task_name,
      "track": "comp",
      "docstring": docstring,
      "signature": full_signature,
      "ground_truth_specs": ground_truth_specs,
      "prompt_skeleton": prompt_skeleton,
      "implementation_body": main_body,
      "full_code": gt_output.strip(),
  }


def convert():
  if not RAW_JSON_PATH.exists():
    raise FileNotFoundError(f"Missing raw file: {RAW_JSON_PATH}")

  with open(RAW_JSON_PATH, "r", encoding="utf-8") as f:
    raw_entries = json.load(f)

  tasks = []
  for idx, item in enumerate(raw_entries, start=1):
    org_input = item.get("org_input", "")
    gt_output = item.get("gt_output", "")
    task_id = item.get("org_input_id", idx)

    parsed_task = parse_dafnycomp_entry(org_input, gt_output, task_id)
    tasks.append(parsed_task)

  OUTPUT_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
  with open(OUTPUT_JSON_PATH, "w", encoding="utf-8") as f:
    json.dump(tasks, f, indent=2)

  print("==================================================")
  print(f"[✓] Converted Tasks : {len(tasks)} / {len(raw_entries)}")
  print(f"[📁] Output Manifest: {OUTPUT_JSON_PATH}")
  print("==================================================")


if __name__ == "__main__":
  convert()
