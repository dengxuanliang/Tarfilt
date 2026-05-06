---
title: Filter SFT High Value Problems Design
date: 2026-05-06
---

# Filter SFT High Value Problems Design

## Goal

Create a local skill in this project that filters a JSONL problem set into high-value and low-value subsets for later SFT work.

The workflow is:

1. Read one JSON object per line from an input JSONL file.
2. Extract the problem from `problem_statement` and related metadata.
3. Ask solver model `a` to produce pure code only.
4. Ask judge model `b` to subjectively decide whether the solver output solves the problem.
5. If the judge says the answer is correct, drop the problem as low-value.
6. If the judge says the answer is incorrect, keep the problem as high-value.
7. Write separate JSONL outputs for kept and dropped problems, plus an audit log.

## Non-Goals

- No automatic execution-based judging.
- No external test generation.
- No standard reference-solution comparison.
- No multi-turn human-in-the-loop review inside the runner.

## Input Contract

The runner expects a JSONL file where each line is a JSON object containing at least:

- `id`
- `problem_statement`
- `function_signature`

Other fields such as `language`, `difficulty`, `constraints`, and `edge_cases_hinted` are optional but will be forwarded into prompts when present.

Example shape:

```json
{
  "id": "S00001",
  "weakness_id": "W007",
  "batch_index": 0,
  "language": "python",
  "difficulty": "hard",
  "scenario": "real-time log compaction",
  "problem_statement": "Full natural-language problem statement...",
  "function_signature": "def compress_log(events: list[dict]) -> list[dict]:",
  "input_format": "Input description.",
  "output_format": "Output description.",
  "constraints": ["1 <= len(events) <= 1e5"],
  "edge_cases_hinted": ["empty input", "duplicate timestamps"],
  "anti_homogeneity_notes": "Different from others by scenario and pitfall.",
  "input_scale_class": "1e5-event-stream",
  "data_shape_class": "nested-records",
  "primary_pitfall": "ordering-stability",
  "novelty_reason": "Focuses on online stable compaction."
}
```

## Output Files

Three JSONL files are produced.

### 1. Kept Output

Contains the original problem record plus filtering metadata for problems judged as high-value.

Judging rule:

- `judge_correct == false` => keep

### 2. Dropped Output

Contains the original problem record plus filtering metadata for problems judged as low-value.

Judging rule:

- `judge_correct == true` => drop

### 3. Audit Log

Contains one log record per processed item for traceability and later QA.

Each audit record should include:

- problem id
- timestamp
- solver model name
- judge model name
- solver prompt digest or short metadata
- solver raw code output
- judge raw JSON decision
- normalized verdict
- confidence
- keep/drop decision
- short reason
- error fields if applicable

## Judging Model Assumption

The judge is treated as a subjective evaluator. This is explicitly a coarse filter, not a ground-truth evaluator.

Implications:

- false positives are possible
- false negatives are possible
- outputs must remain auditable
- confidence should be preserved
- operator should be warned not to use this as final data certification

## Model Interface

Both models are called through an OpenAI-compatible API.

Shared configuration:

- one `api_base`
- one environment variable for the API key by default

Distinct runtime settings:

- `solver_model`
- `judge_model`
- optional separate prompts
- optional separate temperatures

## Required Parameters

- `input_jsonl_path`
- `kept_output_jsonl_path`
- `dropped_output_jsonl_path`
- `audit_log_jsonl_path`
- `api_base`
- `solver_model`
- `judge_model`

The API key is not passed inline. It is read from an environment variable.

Default:

- `OPENAI_API_KEY`

Configurable:

- `api_key_env`

## Optional Parameters

- `start_index`
- `max_items`
- `concurrency`
- `request_timeout_sec`
- `solver_temperature`
- `judge_temperature`
- `solver_system_prompt`
- `judge_system_prompt`
- `language_filter`
- `resume_from_audit`

## Prompting Rules

### Solver Prompt

Must instruct the solver to:

- output pure code only
- avoid markdown fences
- implement exactly the requested function
- avoid extra explanation

### Judge Prompt

Must instruct the judge to:

- evaluate only from problem statement and solver code
- decide whether the code solves the task
- return structured JSON only

Judge JSON schema:

```json
{
  "correct": true,
  "confidence": 0.86,
  "reason": "Short explanation of the judgment."
}
```

Normalization rules:

- `correct` must become boolean
- `confidence` must be clamped into `[0, 1]`
- missing reason becomes a fallback string

## Error Handling

The runner should fail fast for configuration errors:

- missing input path
- missing required parameters
- missing API key env var

Per-item runtime failures should not abort the whole batch by default.

Per-item failures should:

- emit an audit log record with the error
- default to `keep` because uncertain or failed judgments are more valuable to retain than discard

## Resume Behavior

If `resume_from_audit` is enabled and the audit log exists, already processed problem ids should be skipped.

This avoids duplicate model calls in interrupted runs.

## Local Skill Layout

The project will contain:

- `skills/filter-sft-high-value-problems/SKILL.md`
- `skills/filter-sft-high-value-problems/scripts/filter_sft_high_value_problems.py`
- `tests/test_filter_sft_high_value_problems.py`

The skill should be repo-local and invoke the script with a JSON config file or CLI arguments.

## Recommended Invocation Style

The user should provide a complete parameter block in one shot.

Recommended config transport:

- a JSON config file path passed to the script

This reduces fragile shell quoting for prompts and paths.

## Risks

- subjective judging can mislabel problems
- malformed model JSON can reduce throughput
- solver can ignore pure-code requirement
- large batch sizes can create long-running partial outputs

## Mitigations

- strict solver instruction
- strict judge JSON response instruction
- per-item audit logging
- deterministic normalization
- keep-on-error policy
- optional resume support

## Success Criteria

The project is successful when:

1. A local skill exists and is discoverable in-project.
2. The runner can process an input JSONL file through two OpenAI-compatible models.
3. The runner emits separate kept, dropped, and audit JSONL outputs.
4. Sensitive API keys are read only from environment variables.
5. Tests cover configuration validation, verdict routing, normalization, and resume behavior.
