# Filter SFT High Value Problems Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a repo-local skill and Python runner that filters problem JSONL records into kept and dropped outputs using a solver model and a subjective judge model over an OpenAI-compatible API.

**Architecture:** A local `SKILL.md` defines triggering conditions, config contract, and invocation flow. A single Python runner handles config loading, prompt construction, model calls, verdict normalization, output routing, audit logging, and resume behavior. Tests isolate the core logic with fake model clients so the workflow is deterministic.

**Tech Stack:** Python 3, standard library, `urllib` for HTTP, `pytest` for tests, repo-local skill layout

---

### Task 1: Create project structure and red test for config validation

**Files:**
- Create: `skills/filter-sft-high-value-problems/SKILL.md`
- Create: `skills/filter-sft-high-value-problems/scripts/filter_sft_high_value_problems.py`
- Create: `tests/test_filter_sft_high_value_problems.py`

- [ ] **Step 1: Write the failing test**

```python
def test_load_config_requires_api_key_env(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    cfg = {"api_key_env": "OPENAI_API_KEY"}
    with pytest.raises(ConfigError):
        resolve_api_key(cfg)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_filter_sft_high_value_problems.py::test_load_config_requires_api_key_env -v`
Expected: FAIL because the module and function do not exist yet

- [ ] **Step 3: Write minimal implementation**

Implement the module, `ConfigError`, and `resolve_api_key`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_filter_sft_high_value_problems.py::test_load_config_requires_api_key_env -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_filter_sft_high_value_problems.py skills/filter-sft-high-value-problems/SKILL.md skills/filter-sft-high-value-problems/scripts/filter_sft_high_value_problems.py
git commit -m "feat: add initial config validation for filter skill"
```

### Task 2: Add verdict normalization and routing tests

**Files:**
- Modify: `tests/test_filter_sft_high_value_problems.py`
- Modify: `skills/filter-sft-high-value-problems/scripts/filter_sft_high_value_problems.py`

- [ ] **Step 1: Write the failing test**

```python
def test_normalize_judge_response_clamps_confidence_and_defaults_reason():
    raw = {"correct": "yes", "confidence": 7}
    verdict = normalize_judge_response(raw)
    assert verdict["correct"] is True
    assert verdict["confidence"] == 1.0
    assert verdict["reason"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_filter_sft_high_value_problems.py::test_normalize_judge_response_clamps_confidence_and_defaults_reason -v`
Expected: FAIL because normalization does not exist yet

- [ ] **Step 3: Write minimal implementation**

Implement normalization and record routing helpers.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_filter_sft_high_value_problems.py::test_normalize_judge_response_clamps_confidence_and_defaults_reason -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_filter_sft_high_value_problems.py skills/filter-sft-high-value-problems/scripts/filter_sft_high_value_problems.py
git commit -m "feat: normalize judge verdicts and route records"
```

### Task 3: Add batch processing tests with fake clients

**Files:**
- Modify: `tests/test_filter_sft_high_value_problems.py`
- Modify: `skills/filter-sft-high-value-problems/scripts/filter_sft_high_value_problems.py`

- [ ] **Step 1: Write the failing test**

```python
def test_process_records_writes_kept_dropped_and_audit(tmp_path):
    ...
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_filter_sft_high_value_problems.py::test_process_records_writes_kept_dropped_and_audit -v`
Expected: FAIL because end-to-end processing is incomplete

- [ ] **Step 3: Write minimal implementation**

Implement JSONL reading, prompt assembly, model-client interface, record processing, and output writing.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_filter_sft_high_value_problems.py::test_process_records_writes_kept_dropped_and_audit -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_filter_sft_high_value_problems.py skills/filter-sft-high-value-problems/scripts/filter_sft_high_value_problems.py
git commit -m "feat: process problem batches into kept and dropped outputs"
```

### Task 4: Add resume behavior and malformed judge output tests

**Files:**
- Modify: `tests/test_filter_sft_high_value_problems.py`
- Modify: `skills/filter-sft-high-value-problems/scripts/filter_sft_high_value_problems.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_resume_skips_existing_problem_ids(tmp_path):
    ...

def test_judge_parse_failure_defaults_to_keep_and_audit_error(tmp_path):
    ...
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_filter_sft_high_value_problems.py -k "resume or judge_parse_failure" -v`
Expected: FAIL because those flows are not implemented yet

- [ ] **Step 3: Write minimal implementation**

Implement audit-log replay for processed ids and keep-on-error fallback.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_filter_sft_high_value_problems.py -k "resume or judge_parse_failure" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_filter_sft_high_value_problems.py skills/filter-sft-high-value-problems/scripts/filter_sft_high_value_problems.py
git commit -m "feat: support resume and keep-on-error fallback"
```

### Task 5: Write the skill contract and usage guidance

**Files:**
- Modify: `skills/filter-sft-high-value-problems/SKILL.md`

- [ ] **Step 1: Write the failing review checklist**

Checklist:
- skill description triggers on creating or running this filter workflow
- documents required config keys
- states API key env behavior
- states coarse subjective-judge limitation
- points to exact script path

- [ ] **Step 2: Verify the checklist currently fails**

Run: `sed -n '1,240p' skills/filter-sft-high-value-problems/SKILL.md`
Expected: missing or incomplete content

- [ ] **Step 3: Write minimal implementation**

Fill `SKILL.md` with concise trigger conditions, workflow, config contract, and warnings.

- [ ] **Step 4: Verify the checklist passes**

Run: `sed -n '1,240p' skills/filter-sft-high-value-problems/SKILL.md`
Expected: all checklist items are present

- [ ] **Step 5: Commit**

```bash
git add skills/filter-sft-high-value-problems/SKILL.md
git commit -m "docs: add local skill contract for sft problem filtering"
```

### Task 6: Run full verification

**Files:**
- Verify: `tests/test_filter_sft_high_value_problems.py`
- Verify: `skills/filter-sft-high-value-problems/scripts/filter_sft_high_value_problems.py`
- Verify: `skills/filter-sft-high-value-problems/SKILL.md`

- [ ] **Step 1: Run the full test suite**

Run: `pytest tests/test_filter_sft_high_value_problems.py -v`
Expected: all tests pass

- [ ] **Step 2: Run a smoke CLI invocation check**

Run: `python3 skills/filter-sft-high-value-problems/scripts/filter_sft_high_value_problems.py --help`
Expected: exit 0 and usage output

- [ ] **Step 3: Review requirements against the spec**

Check:
- reads `problem_statement`
- solver outputs pure code by prompt contract
- judge outputs structured JSON by prompt contract
- writes kept, dropped, and audit JSONL
- reads API key from environment variable

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-05-06-filter-sft-high-value-problems-design.md docs/superpowers/plans/2026-05-06-filter-sft-high-value-problems.md skills/filter-sft-high-value-problems tests
git commit -m "feat: implement local skill for filtering sft problem value"
```
