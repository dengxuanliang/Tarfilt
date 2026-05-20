---
name: filter-sft-high-value-problems
description: Use when filtering a problem JSONL into kept and dropped subsets by asking one coding model to answer and one judge model to subjectively evaluate the answer through an OpenAI-compatible API.
---

# Filter SFT High Value Problems

## Overview

Use this skill to coarse-filter SFT problem data with two models:

- solver model `a` writes pure code
- judge model `b` subjectively decides whether that code solves the problem

If the judge says correct, drop the problem as low-value. If the judge says incorrect, keep it as high-value.

This is a coarse filter only. It is not a ground-truth evaluator.

## Inputs

Provide the full parameter set in one shot through a JSON config file.

This skill supports a `cgen`-style configuration mechanism.

Current mode:

- `solver` and `judge` are configured independently
- each role provides its own full `chat_completions_url`
- each role provides its own `api_key_env`
- each role provides its own `model`

Required top-level config keys:

- `input_jsonl_path`

Required output configuration:

- either `output_dir`
- or all of:
  - `kept_output_jsonl_path`
  - `dropped_output_jsonl_path`
  - `audit_log_jsonl_path`

Optional config keys:

- `env_file`
- `start_index`
- `max_items`
- `request_timeout_sec`
- `solver_temperature`
- `judge_temperature`
- `judge_use_response_format`
- `solver_system_prompt`
- `judge_system_prompt`
- `language_filter`
- `resume_from_audit`

Role configuration:

- `solver`
- `judge`

Each role may define:

- `chat_completions_url`
- `api_key_env`
- `model`

Bearer auth is used for both roles:

- `Authorization: Bearer <api key>`

Runtime precedence:

- if `env_file` is configured, values loaded from that file take precedence
- process environment variables are only used as fallback

This is intentional so the skill always prefers the repo-local `.env` over unrelated shell-level credentials.

The current implementation does not support the old shared-gateway config shape.


## Input Record Contract

Each JSONL row must contain:

- `id`
- `solver_prompt`
- `problem_statement`
- `function_signature`

The solver model receives `solver_prompt` directly from the input row.

`problem_statement` and `function_signature` are used for judge prompting and audit records.

## Outputs

The runner writes three JSONL files:

- kept output
- dropped output
- audit log

The kept and dropped files include the original problem plus:

- `filter_decision`
- `judge_correct`
- `judge_confidence`
- `judge_reason`
- `solver_code`
- `solver_model`
- `judge_model`

The audit log includes:

- `id`
- `timestamp`
- `decision`
- `judge_correct`
- `judge_confidence`
- `judge_reason`
- `solver_model`
- `judge_model`
- `solver_code`
- `error`

Filtering order:

1. `language_filter`
2. `start_index`
3. `max_items`
4. `resume_from_audit` skip

So slicing applies to the filtered input stream before resume skips already-audited ids.

## Invocation

Run:

```bash
python3 scripts/filter_sft_high_value_problems.py --config /path/to/config.json
```

Recommended config:

```json
{
  "input_jsonl_path": "/path/to/problems.jsonl",
  "output_dir": "/path/to/output",
  "env_file": "/Users/deng/开发/Tarfilt/.worktrees/filter-sft-high-value-problems/.env",
  "solver": {
    "chat_completions_url": "http://solver-host/v1/chat/completions",
    "api_key_env": "SOLVER_API_KEY",
    "model": "your-solver-model"
  },
  "judge": {
    "chat_completions_url": "http://judge-host/v1/chat/completions",
    "api_key_env": "JUDGE_API_KEY",
    "model": "your-judge-model"
  }
}
```

Recommended `.env`:

```env
SOLVER_API_KEY=...
JUDGE_API_KEY=...
```

## Warnings

- The judge is subjective and can mislabel samples.
- Judge failures are kept by fallback.
- Malformed input JSONL should be fixed before trusting results.
- Some OpenAI-compatible gateways do not support `response_format`; set `judge_use_response_format` to `false` in that case.
