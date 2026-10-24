import json
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
TEXTBOOK_ALGO_DIR = BASE_DIR / "textbook_algo"
OUTPUT_JSON_PATH = BASE_DIR / "clover_tasks.json"

def parse_dafny_method(dfy_text: str):
  body_match = re.search(r"\n\s*\{(?!\:)", dfy_text)
  if not body_match:
    return {
        "signature": "",
        "ground_truth_specs": "",
        "implementation_body": dfy_text.strip(),
    }

  brace_idx = body_match.start()
  header_part = dfy_text[:brace_idx].strip()
  body_part = dfy_text[body_match.start():].strip()

  sig_match = re.search(
      r"(method\s+[\s\S]+?)(?=\n\s*(?:requires|ensures|modifies|reads|decreases)|$)",
      header_part,
  )

  signature = sig_match.group(1).strip() if sig_match else header_part
  specs_part = header_part[len(signature):].strip()

  return {
      "signature": signature,
      "ground_truth_specs": specs_part,
      "implementation_body": body_part,
  }


def convert_dataset_to_json(input_dir: Path, output_file: Path):
  if not input_dir.exists():
    raise FileNotFoundError(f"Directory not found: {input_dir.resolve()}")

  EXCLUDED_TASKS = {"double_array_elements", "match"}
  tasks = []
  task_id = 1

  for task_dir in sorted(input_dir.iterdir()):
    if not task_dir.is_dir() or task_dir.name in EXCLUDED_TASKS:
      continue

    task_name = task_dir.name

    txt_files = list(task_dir.glob("*.txt"))
    dfy_files = list(task_dir.glob("*.dfy"))

    if not txt_files or not dfy_files:
      print(f"[!] Skipping {task_name}: missing .txt or .dfy file")
      continue

    docstring = txt_files[0].read_text(encoding="utf-8").strip()
    full_dfy_code = dfy_files[0].read_text(encoding="utf-8").strip()

    parsed = parse_dafny_method(full_dfy_code)

    prompt_skeleton = (
        f"{parsed['signature']}\n  // TOFILL: requires and"
        f" ensures\n{parsed['implementation_body']}"
    )

    tasks.append({
        "task_id": task_id,
        "task_name": task_name,
        "docstring": docstring,
        "signature": parsed["signature"],
        "ground_truth_specs": parsed["ground_truth_specs"],
        "prompt_skeleton": prompt_skeleton,
        "implementation_body": parsed["implementation_body"],
        "full_code": full_dfy_code,
    })
    task_id += 1

  output_file.parent.mkdir(parents=True, exist_ok=True)
  with open(output_file, "w", encoding="utf-8") as f:
    json.dump(tasks, f, indent=2)

  print(f"[✓] Successfully converted {len(tasks)} tasks to {output_file}")


if __name__ == "__main__":
  convert_dataset_to_json(TEXTBOOK_ALGO_DIR, OUTPUT_JSON_PATH)