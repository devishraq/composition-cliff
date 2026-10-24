import re
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class VerificationResult:
  verified: bool
  error_count: int
  output: str
  error_message: str = ""
  latency_sec: float = 0.0


class DafnyVerifier:

  def __init__(self, dafny_path: str = "dafny", timeout_seconds: int = 15):
    self.dafny_path = dafny_path
    self.timeout_seconds = timeout_seconds
    self._cached_version = None

  def get_version(self) -> str:
    if self._cached_version:
      return self._cached_version
    try:
      res = subprocess.run(
          [self.dafny_path, "--version"],
          capture_output=True,
          text=True,
          timeout=5,
          check=False,
      )
      self._cached_version = res.stdout.strip() or res.stderr.strip()
    except Exception:
      self._cached_version = "unknown"
    return self._cached_version

  def verify_code(self, dafny_code: str) -> VerificationResult:
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".dfy", delete=False, encoding="utf-8"
    ) as temp_file:
      temp_file.write(dafny_code)
      temp_path = Path(temp_file.name)

    try:
      return self.verify_file(temp_path)
    finally:
      if temp_path.exists():
        temp_path.unlink()

  def verify_file(self, file_path: Path) -> VerificationResult:
    start_time = time.time()
    try:
      cmd = [self.dafny_path, "verify", "--allow-warnings", str(file_path)]
      result = subprocess.run(
          cmd,
          capture_output=True,
          text=True,
          timeout=self.timeout_seconds,
          check=False,
      )
      latency = round(time.time() - start_time, 4)
      stdout = result.stdout
      stderr = result.stderr
      combined_output = f"{stdout}\n{stderr}".strip()

      match = re.search(
          r"finished with \d+ verified, (\d+) errors?", combined_output
      )

      if match:
        error_count = int(match.group(1))
        is_verified = error_count == 0 and result.returncode == 0
        return VerificationResult(
            verified=is_verified,
            error_count=error_count,
            output=combined_output,
            error_message="" if is_verified else combined_output,
            latency_sec=latency,
        )

      if "Error:" in combined_output or result.returncode != 0:
        return VerificationResult(
            verified=False,
            error_count=1,
            output=combined_output,
            error_message=combined_output,
            latency_sec=latency,
        )

      return VerificationResult(
          verified=True,
          error_count=0,
          output=combined_output,
          latency_sec=latency,
      )

    except subprocess.TimeoutExpired:
      latency = round(time.time() - start_time, 4)
      return VerificationResult(
          verified=False,
          error_count=1,
          output="Verifier timed out",
          error_message=f"Timeout after {self.timeout_seconds}s",
          latency_sec=latency,
      )
    except FileNotFoundError:
      latency = round(time.time() - start_time, 4)
      return VerificationResult(
          verified=False,
          error_count=1,
          output=f"Dafny executable not found at '{self.dafny_path}'",
          error_message="Dafny binary missing in environment",
          latency_sec=latency,
      )