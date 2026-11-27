"""Mutation audit of Terminal-Bench verifiers.

Two modes:

  file    No containers. For tasks whose verifier only reads answer files under
          /app, write each mutant into a temp dir, rewrite "/app" in the verifier
          to point there, and run the real tests/test_outputs.py with pytest.
          Oracle answers come from --oracles (a JSON {task: {file: content}}).

  docker  General mode. Run the task's reference solution (solution/solve.sh) in
          its container, snapshot it, find the text files the solution created or
          changed under /app, mutate them one at a time on a fresh copy of the
          snapshot, and run the task's own tests/test.sh (reward 1 = pass).

Usage:
  python -m agent_verifier_audit.audit file   --tasks <tb>/tasks --oracles agent_verifier_audit/oracles_tb21.json
  python -m agent_verifier_audit.audit docker --tasks <tb>/tasks --only count-dataset-tokens sqlite-db-truncate
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import tomllib
from pathlib import Path

from agent_verifier_audit.operators import ACCEPT, NEUTRAL, REJECT, mutants_for


def _record(task, path, m, passed):
  survived = m.expectation == REJECT and passed
  false_reject = m.expectation == ACCEPT and not passed
  return dict(task=task, file=path, operator=m.operator, expectation=m.expectation,
              description=m.description, verifier_passed=passed,
              survived=survived, false_reject=false_reject)


# ----------------------------------------------------------------------------- file mode
def _run_pytest_on(task_dir: Path, files: dict) -> bool:
  with tempfile.TemporaryDirectory() as tmp:
    for rel, content in files.items():
      p = Path(tmp, rel)
      p.parent.mkdir(parents=True, exist_ok=True)
      p.write_text(content)
    src = (task_dir / "tests" / "test_outputs.py").read_text()
    patched = re.sub(r"(['\"])/app(?=[/'\"])", lambda m: m.group(1) + tmp, src)
    test_file = Path(tmp, "_patched_test_outputs.py")
    test_file.write_text(patched)
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                        str(test_file)], capture_output=True, text=True, cwd=tmp)
    return r.returncode == 0


def run_file_mode(tasks_dir: Path, oracles: dict, only):
  rows = []
  for task, spec in oracles.items():
    if task.startswith("_") or (only and task not in only):
      continue
    files, neutral = spec["files"], set(spec.get("neutral_operators", []))
    tdir = tasks_dir / task
    oracle_ok = _run_pytest_on(tdir, files)
    print(f"\n== {task} (oracle passes: {oracle_ok})")
    if not oracle_ok:
      print("   [skip] oracle answer does not pass; fix the oracle first")
      continue
    for rel, content in files.items():
      for m in mutants_for(content):
        if m.content == content:
          continue
        if m.operator in neutral:  # allowed by this task's instruction
          m.expectation = NEUTRAL
        passed = _run_pytest_on(tdir, {**files, rel: m.content})
        rows.append(_record(task, rel, m, passed))
        _print(rows[-1])
  return rows


# ----------------------------------------------------------------------------- docker mode
def _sh(cmd, timeout=None, input_=None):
  return subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=timeout, input=input_)


def _image_for(tdir: Path, platform):
  cfg = tomllib.loads((tdir / "task.toml").read_text())
  img = cfg.get("environment", {}).get("docker_image")
  if img:
    _sh(["docker", "pull", *(["--platform", platform] if platform else []), img])
    return img
  tag = f"vaudit-build:{tdir.name}"
  _sh(["docker", "build", *(["--platform", platform] if platform else []),
       "-t", tag, str(tdir / "environment")])
  return tag


def _start(image, name, platform):
  _sh(["docker", "rm", "-f", name])
  r = _sh(["docker", "run", "-d", "--name", name,
           *(["--platform", platform] if platform else []),
           "--entrypoint", "sleep", image, "infinity"])
  if r.returncode != 0:
    raise RuntimeError(r.stderr.strip())


def _verify(name, tdir: Path, timeout):
  _sh(["docker", "cp", str(tdir / "tests"), f"{name}:/tests"])
  _sh(["docker", "exec", name, "bash", "-c", "mkdir -p /logs/verifier"])
  try:
    _sh(["docker", "exec", name, "bash", "/tests/test.sh"], timeout=timeout)
  except subprocess.TimeoutExpired:
    return False
  r = _sh(["docker", "exec", name, "cat", "/logs/verifier/reward.txt"])
  return r.stdout.strip() == "1"


def _answer_files(name, max_files, max_bytes):
  diff = _sh(["docker", "diff", name]).stdout.splitlines()
  out = {}
  for line in diff:
    kind, path = line[:1], line[2:]
    if kind not in "AC" or not path.startswith("/app/"):
      continue
    r = _sh(["docker", "exec", name, "bash", "-c",
             f"[ -f '{path}' ] && [ $(stat -c%s '{path}') -le {max_bytes} ] "
             f"&& grep -Iq . '{path}' && cat '{path}'"])
    if r.returncode == 0 and r.stdout.strip():
      out[path] = r.stdout
    if len(out) >= max_files:
      break
  return out


def run_docker_mode(tasks_dir: Path, only, platform, timeout, max_files):
  rows = []
  for tdir in sorted(p for p in tasks_dir.iterdir() if (p / "solution" / "solve.sh").exists()):
    if only and tdir.name not in only:
      continue
    task, base, snap = tdir.name, f"vaudit-{tdir.name}", f"vaudit-snap:{tdir.name}"
    print(f"\n== {task}")
    try:
      image = _image_for(tdir, platform)
      _start(image, base, platform)
      _sh(["docker", "cp", str(tdir / "solution"), f"{base}:/solution"])
      t0 = time.time()
      _sh(["docker", "exec", base, "bash", "/solution/solve.sh"], timeout=timeout)
      print(f"   oracle solution ran in {time.time() - t0:.0f}s")
      files = _answer_files(base, max_files, 64_000)
      _sh(["docker", "commit", base, snap])
      _sh(["docker", "rm", "-f", base])

      _start(snap, base, platform)
      oracle_ok = _verify(base, tdir, timeout)
      _sh(["docker", "rm", "-f", base])
      print(f"   oracle passes: {oracle_ok} | candidate answer files: {list(files)}")
      if not oracle_ok or not files:
        rows.append(dict(task=task, skipped=True, oracle_passes=oracle_ok,
                         answer_files=list(files)))
        continue
      for path, content in files.items():
        # Control: if the verifier still passes with this file emptied, it never
        # reads it (e.g. the solver script), so mutants of it prove nothing.
        _start(snap, base, platform)
        _sh(["docker", "exec", base, "bash", "-c", f": > '{path}'"])
        ctrl = _verify(base, tdir, timeout)
        _sh(["docker", "rm", "-f", base])
        if ctrl:
          print(f"   skip {path}: verifier passes with it emptied (not load-bearing)")
          continue
        for m in mutants_for(content):
          if m.content == content:
            continue
          _start(snap, base, platform)
          _sh(["docker", "exec", "-i", base, "bash", "-c", f"cat > '{path}'"],
              input_=m.content)
          passed = _verify(base, tdir, timeout)
          _sh(["docker", "rm", "-f", base])
          rows.append(_record(task, path, m, passed))
          _print(rows[-1])
    except Exception as e:  # keep going across tasks
      print(f"   [error] {e}")
      rows.append(dict(task=task, error=str(e)))
    finally:
      _sh(["docker", "rm", "-f", base])
      _sh(["docker", "rmi", "-f", snap])
  return rows


# ----------------------------------------------------------------------------- reporting
def _print(r):
  tag = ("SURVIVED (verifier too weak)" if r["survived"] else
         "FALSE REJECT (verifier too strict)" if r["false_reject"] else "ok")
  print(f"   {'PASS' if r['verifier_passed'] else 'fail'}  "
        f"[{r['operator']:5s}] {r['description'][:55]:55s} -> {tag}")


def summarize(rows):
  scored = [r for r in rows if r.get("expectation") == REJECT]
  surv = [r for r in scored if r["survived"]]
  tasks = sorted({r["task"] for r in rows if "operator" in r})
  weak = sorted({r["task"] for r in surv})
  per_task = {t: dict(
      killable=sum(1 for r in scored if r["task"] == t),
      survived=sum(1 for r in surv if r["task"] == t)) for t in tasks}
  return dict(tasks_audited=len(tasks), killable_mutants=len(scored),
              surviving_mutants=len(surv),
              mutation_score=round(1 - len(surv) / len(scored), 3) if scored else None,
              tasks_with_survivors=weak, per_task=per_task)


def main():
  ap = argparse.ArgumentParser()
  ap.add_argument("mode", choices=["file", "docker"])
  ap.add_argument("--tasks", required=True, type=Path)
  ap.add_argument("--oracles", type=Path)
  ap.add_argument("--only", nargs="*")
  ap.add_argument("--platform", default=None,
                  help="e.g. linux/amd64 on Apple Silicon")
  ap.add_argument("--timeout", type=int, default=900)
  ap.add_argument("--max-files", type=int, default=3)
  ap.add_argument("--out", type=Path)
  a = ap.parse_args()

  if a.mode == "file":
    rows = run_file_mode(a.tasks, json.loads(a.oracles.read_text()), a.only)
  else:
    rows = run_docker_mode(a.tasks, a.only, a.platform, a.timeout, a.max_files)
  summary = summarize(rows)
  print("\n" + json.dumps({k: v for k, v in summary.items() if k != "per_task"}, indent=1))
  out = a.out or Path(__file__).parent / "results" / f"tb21_{a.mode}_mode.json"
  out.parent.mkdir(parents=True, exist_ok=True)
  out.write_text(json.dumps(dict(summary=summary, mutants=rows), indent=1))
  print(f"saved -> {out}")


if __name__ == "__main__":
  main()
