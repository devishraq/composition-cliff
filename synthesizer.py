import json
import os
from pathlib import Path
import re
import time
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Set, Tuple
from dotenv import load_dotenv
from openai import OpenAI
from verifier import DafnyVerifier
from mutator import DafnyASTMutator, Mutant

load_dotenv()


@dataclass
class TurnLog:
  turn_number: int
  prompt_sent: List[Dict]
  raw_response: str
  reasoning_chain: str
  candidate_specs: str
  is_sound: bool
  verifier_error: Optional[str]
  solver_latency_sec: float
  prompt_tokens: int
  cached_tokens: int
  completion_tokens: int
  reasoning_tokens: int
  cache_hit_rate: float
  raw_mutation_score: float
  adj_mutation_score: float
  operator_kill_breakdown: Dict[str, Dict[str, int]]
  surviving_killable_ids: List[str]


class MutationCEGISSynthesizer:

  def __init__(
      self,
      model_name: str = "openai/gpt-4o",
      api_key: Optional[str] = None,
      base_url: Optional[str] = "https://openrouter.ai/api/v1",
      max_turns: int = 4,
      max_tokens: int = 32768,
      eval_mode: str = "mutation_cegis",
      baseline_path: str = "dataset/clover_bench/gt_mutant_baseline.json",
  ):
    resolved_key = (
        api_key
        or os.getenv("OPENROUTER_API_KEY")
        or os.getenv("OPENAI_API_KEY")
    )
    if not resolved_key:
      raise ValueError(
          "[!] API Key missing. Set OPENROUTER_API_KEY in your environment."
      )

    self.client = OpenAI(
        api_key=resolved_key,
        base_url=base_url or "https://openrouter.ai/api/v1",
        timeout=45.0,
        default_headers={
            "HTTP-Referer": "https://github.com/formal-verification/smsp",
            "X-Title": "SMSP Dafny Mutation Benchmark",
        },
    )
    self.model_name = model_name
    self.max_turns = max_turns if eval_mode != "zero_shot" else 1
    self.max_tokens = max_tokens
    self.eval_mode = eval_mode
    self.verifier = DafnyVerifier()
    self.mutator = DafnyASTMutator()

    self.gt_baselines = {}
    p = Path(baseline_path)
    if p.exists():
      with open(p, "r", encoding="utf-8") as f:
        self.gt_baselines = json.load(f)

  def _call_llm_with_retry(
      self, messages: list, max_retries: int = 5
  ) -> Tuple[str, str, int, int, int, int]:
    """Returns (content, reasoning_chain, prompt_tokens, cached_tokens, completion_tokens, reasoning_tokens)."""
    for attempt in range(max_retries):
      try:
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            temperature=0.0,
            max_tokens=self.max_tokens,
            timeout=45.0,
        )
        choice = response.choices[0]
        content = choice.message.content or ""
        
        reasoning_chain = ""
        if hasattr(choice.message, "reasoning_content") and choice.message.reasoning_content:
          reasoning_chain = choice.message.reasoning_content
        elif hasattr(choice.message, "reasoning") and choice.message.reasoning:
          reasoning_chain = choice.message.reasoning
        else:
          think_match = re.search(r"<think>([\s\S]*?)</think>", content)
          if think_match:
            reasoning_chain = think_match.group(1).strip()

        if not content.strip() and reasoning_chain:
          content = reasoning_chain

        usage = response.usage
        prompt_tokens = usage.prompt_tokens if usage else 0
        completion_tokens = usage.completion_tokens if usage else 0
        
        cached_tokens = 0
        if usage and hasattr(usage, "prompt_tokens_details") and usage.prompt_tokens_details:
          cached_tokens = getattr(usage.prompt_tokens_details, "cached_tokens", 0) or 0

        reasoning_tokens = 0
        if usage and hasattr(usage, "completion_tokens_details") and usage.completion_tokens_details:
          reasoning_tokens = getattr(usage.completion_tokens_details, "reasoning_tokens", 0) or 0

        return content, reasoning_chain, prompt_tokens, cached_tokens, completion_tokens, reasoning_tokens
      except Exception as e:
        wait_time = 2 ** (attempt + 1)
        print(f"    [!] LLM API Error (Attempt {attempt+1}/{max_retries}): {e}. Retrying in {wait_time}s...")
        time.sleep(wait_time)
        
    return "", "", 0, 0, 0, 0

  def synthesize_and_repair(self, task: Dict) -> Dict:
    task_name = task["task_name"]
    docstring = task["docstring"]
    signature = task["signature"]
    body = task["implementation_body"]

    body_lines = [l for l in body.splitlines() if l.strip()]
    loc = len(body_lines)
    loop_count = len(re.findall(r"\b(while|for)\b", body))

    task_baseline = self.gt_baselines.get(task_name, {})
    killable_ids: Set[str] = set(
        task_baseline.get("killable_mutant_ids", [])
    )
    total_killable = len(killable_ids)

    turn_logs: List[TurnLog] = []
    turn = 0
    prompt_history = []

    system_msg = (
        "You are an expert formal methods engineer specializing in Dafny.\n"
        "Your task is to write strict, sound, and complete formal specifications"
        " (`requires` and `ensures` clauses) for a Dafny method.\n"
        "Rules:\n"
        "1. Output ONLY the formal contract lines"
        " (requires/ensures/modifies/reads).\n"
        "2. Do NOT wrap them in a method signature or body.\n"
        "3. Ensure your postconditions are mathematically complete so that any"
        " buggy implementation is rejected."
    )

    user_msg = (
        f"Method Intent (Docstring):\n{docstring}\n\n"
        f"Method Signature:\n{signature}\n\n"
        f"Implementation Body:\n{body}\n\n"
        "Provide the formal Dafny specifications (requires and ensures"
        " clauses):"
    )

    prompt_history.append({"role": "system", "content": system_msg})
    prompt_history.append({"role": "user", "content": user_msg})

    final_specs = ""
    task_success = False
    task_total_tokens = 0
    task_prompt_tokens = 0
    task_cached_tokens = 0

    while turn < self.max_turns:
      turn += 1
      print(f"[*] Task [{task_name}] - Turn {turn}/{self.max_turns}")

      prompt_sent_snapshot = json.loads(json.dumps(prompt_history))

      raw_content, reasoning_chain, p_tokens, cached_tokens, c_tokens, r_tokens = self._call_llm_with_retry(prompt_history)
      task_total_tokens += (p_tokens + c_tokens)
      task_prompt_tokens += p_tokens
      task_cached_tokens += cached_tokens
      cache_hit_rate = (cached_tokens / p_tokens) if p_tokens > 0 else 0.0

      if not raw_content:
        print(f"  [-] Turn {turn}: API request failed after all retries. Aborting task.")
        turn_logs.append(
            TurnLog(
                turn_number=turn,
                prompt_sent=prompt_sent_snapshot,
                raw_response="",
                reasoning_chain="",
                candidate_specs="",
                is_sound=False,
                verifier_error="API request failed after all retries",
                solver_latency_sec=0.0,
                prompt_tokens=p_tokens,
                cached_tokens=cached_tokens,
                completion_tokens=c_tokens,
                reasoning_tokens=r_tokens,
                cache_hit_rate=round(cache_hit_rate, 4),
                raw_mutation_score=0.0,
                adj_mutation_score=0.0,
                operator_kill_breakdown={},
                surviving_killable_ids=[],
            )
        )
        break

      candidate_specs = self._clean_llm_spec_output(raw_content)

      full_program = f"{signature}\n{candidate_specs}\n{body}"
      soundness_res = self.verifier.verify_code(full_program)

      if not soundness_res.verified:
        print(
            f"  [-] Turn {turn}: Soundness FAILED (Ground truth code rejected | Latency: {soundness_res.latency_sec}s)"
        )
        feedback = (
            "Your proposed specifications failed to verify on the valid ground"
            f" truth code.\nDafny Verifier Error:\n{soundness_res.error_message}\n"
            "Please fix the specifications so that the valid code verifies."
        )
        prompt_history.append({"role": "assistant", "content": candidate_specs})
        prompt_history.append({"role": "user", "content": feedback})

        turn_logs.append(
            TurnLog(
                turn_number=turn,
                prompt_sent=prompt_sent_snapshot,
                raw_response=raw_content,
                reasoning_chain=reasoning_chain,
                candidate_specs=candidate_specs,
                is_sound=False,
                verifier_error=soundness_res.error_message,
                solver_latency_sec=soundness_res.latency_sec,
                prompt_tokens=p_tokens,
                cached_tokens=cached_tokens,
                completion_tokens=c_tokens,
                reasoning_tokens=r_tokens,
                cache_hit_rate=round(cache_hit_rate, 4),
                raw_mutation_score=0.0,
                adj_mutation_score=0.0,
                operator_kill_breakdown={},
                surviving_killable_ids=[],
            )
        )
        continue

      mutants = self.mutator.generate_mutants(signature, candidate_specs, body)
      total_ast_mutants = len(mutants)
      killed_total = 0
      killed_killable = 0
      surviving_killable: List[Mutant] = []
      total_solver_latency = soundness_res.latency_sec

      op_breakdown: Dict[str, Dict[str, int]] = {}
      for op in ["ROR", "AOR", "CR", "CID", "RSM"]:
        op_breakdown[op] = {"total": 0, "killed": 0}

      for m in mutants:
        if m.operator in op_breakdown:
          op_breakdown[m.operator]["total"] += 1

        res = self.verifier.verify_code(m.full_code)
        total_solver_latency += res.latency_sec

        if not res.verified:
          killed_total += 1
          if m.operator in op_breakdown:
            op_breakdown[m.operator]["killed"] += 1
          if m.mutant_id in killable_ids:
            killed_killable += 1
        else:
          if m.mutant_id in killable_ids:
            surviving_killable.append(m)

      raw_score = (killed_total / len(mutants)) if mutants else 1.0
      adj_score = (
          min(1.0, killed_killable / total_killable) if total_killable > 0 else 1.0
      )

      print(
          f"  [+] Turn {turn}: Soundness PASSED | S_raw = {raw_score:.2f} |"
          f" S_adj = {adj_score:.2f} ({killed_killable}/{total_killable}"
          f" killable killed | Latency: {total_solver_latency:.2f}s | Cache Hit: {cache_hit_rate*100:.1f}%)"
      )

      surviving_ids = [m.mutant_id for m in surviving_killable]

      turn_logs.append(
          TurnLog(
              turn_number=turn,
              prompt_sent=prompt_sent_snapshot,
              raw_response=raw_content,
              reasoning_chain=reasoning_chain,
              candidate_specs=candidate_specs,
              is_sound=True,
              verifier_error=None,
              solver_latency_sec=round(total_solver_latency, 4),
              prompt_tokens=p_tokens,
              cached_tokens=cached_tokens,
              completion_tokens=c_tokens,
              reasoning_tokens=r_tokens,
              cache_hit_rate=round(cache_hit_rate, 4),
              raw_mutation_score=round(raw_score, 4),
              adj_mutation_score=round(adj_score, 4),
              operator_kill_breakdown=op_breakdown,
              surviving_killable_ids=surviving_ids,
          )
      )

      final_specs = candidate_specs

      if adj_score >= 1.0 or not surviving_killable:
        print(f"[✓] Task [{task_name}] FULLY HARDENED (S_adj = 1.0) at Turn {turn}!")
        task_success = True
        break

      if self.eval_mode == "zero_shot":
        break

      if self.eval_mode == "compiler_only":
        feedback_prompt = (
            "Your specifications verified on the ground truth code, but are weak."
            " Please refine your `ensures` postconditions to make them stronger."
        )
      else:
        feedback_lines = [
            "Your specifications are SOUND but INCOMPLETE (Adjusted Completeness"
            f" S_adj = {adj_score:.2f}).",
            f"The following {len(surviving_killable)} defective code"
            " implementations accidentally passed your specification:\n",
        ]

        for idx_s, s in enumerate(surviving_killable[:3]):
          feedback_lines.append(
              f"Defect Variant #{idx_s+1} ({s.operator} at line {s.line_number}):\n"
              f"  Original: {s.original_snippet}\n"
              f"  Buggy   : {s.mutated_snippet}\n"
          )

        feedback_lines.append(
            "Tighten your `ensures` postconditions to mathematically reject"
            " these buggy implementations."
        )
        feedback_prompt = "\n".join(feedback_lines)

      prompt_history.append({"role": "assistant", "content": candidate_specs})
      prompt_history.append({"role": "user", "content": feedback_prompt})

    mutants_on_final = self.mutator.generate_mutants(signature, final_specs, body)
    total_ast_count = len(mutants_on_final)

    effective_cache_hit_ratio = (
        (task_cached_tokens / task_prompt_tokens) if task_prompt_tokens > 0 else 0.0
    )

    return {
        "task_name": task_name,
        "loc": loc,
        "loop_count": loop_count,
        "total_ast_mutants": total_ast_count,
        "gt_killable_mutants": total_killable,
        "task_success": task_success,
        "total_turns_taken": turn,
        "final_specs": final_specs,
        "final_raw_score": turn_logs[-1].raw_mutation_score if turn_logs else 0.0,
        "final_adj_score": turn_logs[-1].adj_mutation_score if turn_logs else 0.0,
        "task_total_tokens": task_total_tokens,
        "task_cached_tokens": task_cached_tokens,
        "task_effective_cache_hit_ratio": round(effective_cache_hit_ratio, 4),
        "turn_history": [asdict(tl) for tl in turn_logs],
    }

  def _clean_llm_spec_output(self, text: str) -> str:
    text = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.DOTALL)
    code_block_match = re.search(r"```(?:dafny)?\s*([\s\S]*?)\s*```", text)
    if code_block_match:
      text = code_block_match.group(1)
    else:
      text = re.sub(r"```(?:dafny)?", "", text).replace("```", "").strip()

    spec_keywords = ("requires", "ensures", "modifies", "reads", "decreases")
    cleaned_lines = []
    in_spec_block = False

    for line in text.splitlines():
      stripped = line.strip()
      if not stripped or stripped.startswith(("//", "/*", "*")):
        continue

      if stripped.startswith(spec_keywords):
        cleaned_clause = re.sub(r";\s*$", "", stripped)
        cleaned_lines.append(cleaned_clause)
        in_spec_block = True
      elif in_spec_block:
        if (
            stripped.startswith(
                ("method ", "function ", "predicate ", "lemma ", "{")
            )
            or stripped.startswith(
                ("###", "##", "#", "Explanation:", "Note:", "Here is")
            )
            or re.match(r"^[A-Z][a-z]+:", stripped)
        ):
          in_spec_block = False
        else:
          cleaned_clause = re.sub(r";\s*$", "", line)
          cleaned_lines.append(cleaned_clause)

    return "\n".join(cleaned_lines)