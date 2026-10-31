# Breaking the Composition Cliff: Mutation-Guided Specification Synthesis for Multi-Function Programs

This directory contains the complete source code, datasets, evaluation pipelines, and experimental results for the paper:
**"Breaking the Composition Cliff: Mutation-Guided Specification Synthesis for Multi-Function Programs"**.

---

## 1. Directory Structure

```text
composition-cliff/
├── dataset/
│   ├── clover_bench/          # Track A: 60 single-method Dafny programs (from CloverBench)
│   └── dafny_comp/            # Track B: 300 multi-procedure inter-dependent call graphs (DAFNYCOMP-300)
├── paper/                     # Paper sources (LaTeX) and camera-ready PDF
│   ├── Breaking_The_Composition_Cliff_NeurIPS_2026_Camera_Ready.pdf
│   ├── main.tex
│   └── references.bib
├── results/
│   ├── clover_bench/          # Complete evaluation data across 6 frontier models for Track A
│   ├── dafny_comp/            # Complete evaluation data across 6 frontier models for Track B
│   └── specification_quality_analysis.json # Pre-computed AST logical depth and failure diagnostics
├── verifier.py                # Dafny 4.x verifier wrapper (Z3 backend, SMT timeout ceiling)
├── mutator.py                 # Selective AST mutation generator (ROR, AOR, BCI operators)
├── synthesizer.py             # Multi-turn CEGIS engine (Mode 0, Mode 1, Mode 2)
├── run_eval.py                # Main benchmark execution script
├── run_parallel_models.py     # High-concurrency parallel model sweep orchestrator
├── analyze_specification_quality.py # AST parser for quantifiers, equalities, and vacuous pass analysis
├── test_harness.py            # Unit test suite verifying mutator and verifier integration
├── LICENSE                    # MIT License
└── README.md                  # Reproduction instructions
```

---

## 2. System Requirements & Setup

### Prerequisites
* **Python**: `3.10` or higher
* **uv**: Recommended fast Python package manager (`curl -LsSf https://astral.sh/uv/install.sh | sh` or `brew install uv`)
* **Dafny**: `4.11.0` or higher (installed and available on `PATH` via `dafny`)
* **.NET Runtime**: `8.0` or higher
* **OpenRouter API Key**: Required for querying frontier LLM inference endpoints

### Installation with `uv`

1. Create a virtual environment using `uv`:
   ```bash
   uv venv
   source .venv/bin/activate
   ```

2. Install dependencies using `uv`:
   ```bash
   uv pip install requests python-dotenv openai
   ```

3. Configure your API key:
   Create a `.env` file in this directory (or in the project root):
   ```bash
   OPENROUTER_API_KEY="your-openrouter-api-key-here"
   ```

4. Verify that Dafny is correctly installed and accessible:
   ```bash
   dafny --version
   ```

5. Run the unit test suite:
   ```bash
   uv run python test_harness.py
   ```

---

## 3. Evaluated Models

The benchmark evaluates 6 state-of-the-art frontier model families via OpenRouter:
* `google/gemini-3.7-flash` (Google DeepMind)
* `z-ai/glm-5.3-flash` (Z-AI / Zhipu)
* `openai/gpt-5.6-luna` (OpenAI)
* `qwen/qwen3.7-flash` (Alibaba Qwen Team)
* `deepseek/deepseek-v4-flash-0731` (DeepSeek AI)
* `inclusionai/ling-3.0-flash` (InclusionAI)

---

## 4. Reproduction & Execution

### Synthesis Modes
* **`zero_shot` (Mode 0):** Standard zero-shot specification generation without verifier interaction.
* **`compiler_only` (Mode 1):** Multi-turn repair loop guided solely by Dafny compiler error messages.
* **`mutation_cegis` (Mode 2):** Closed-loop inductive hardening using surviving AST code mutants as counterexample feedback.

### Running a Single Evaluation Run

To run evaluation on Track A (`clover_bench`) with Mutation-CEGIS:
```bash
uv run python run_eval.py \
    --model google/gemini-3.7-flash \
    --dataset clover_bench \
    --mode mutation_cegis \
    --workers 16
```

To run evaluation on Track B (`dafny_comp` - 300 multi-procedure call graphs):
```bash
uv run python run_eval.py \
    --model openai/gpt-5.6-luna \
    --dataset dafny_comp \
    --mode mutation_cegis \
    --workers 25
```

### Running Parallel Multi-Model Sweeps

To execute all 6 models concurrently across evaluation modes with process-level isolation:
```bash
uv run python run_parallel_models.py
```

Results will be automatically saved to `results/<dataset_name>/<model_name>/<mode>.json`.

---

## 5. Specification Quality & Diagnostic Analysis

To extract first-order quantifier depth ($\forall, \exists$), exact equality assertions ($==$), and the 50-character vacuous pass failure taxonomy from the saved evaluation logs:

```bash
uv run python analyze_specification_quality.py
```

This script computes:
1. **First-Order Logical Depth:** Counts quantifier clauses and equality assertions on Track A.
2. **Vacuous Pass vs. SMT Timeout Breakdown:** Analyzes the tasks where Mode 1 passed with trivial bounds while Mode 2 hit inductive SMT timeout ceilings.
3. Outputs structured JSON results to `results/specification_quality_analysis.json`.

---

## 6. Citation

If you use this benchmark or codebase in your research, please cite:

```bibtex
@inproceedings{smsp2026composition,
  title={Breaking the Composition Cliff: Mutation-Guided Specification Synthesis for Multi-Function Programs},
  author={Ishraq Tanvir},
  booktitle={NeurIPS 2026 Workshop on Who Verifies the Agents? Toward Reliable Agent Development},
  year={2026}
}
```

---

## 7. License

This repository is licensed under the [MIT License](LICENSE).


