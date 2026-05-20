# filter-sft-high-value-problems

Filter a JSONL of coding problems into:

- `kept`: high-value samples to retain for SFT
- `dropped`: low-value samples the solver already handles
- `audit`: one record per processed input row

The decision is subjective: one solver model writes code, one judge model reads that code and decides whether it is correct.

## What it does

For each input row:

1. Read `solver_prompt` from the row.
2. Send it to the solver model.
3. Send the generated code plus the original problem statement to the judge model.
4. If the judge says the solver is correct, write the row to `dropped`.
5. If the judge says the solver is wrong, write the row to `kept`.
6. Always write an audit record.

## Configuration

Use a JSON config file. The current implementation only supports per-role configuration.

Required top-level keys:

- `input_jsonl_path`
- one of:
  - `output_dir`
  - `kept_output_jsonl_path`, `dropped_output_jsonl_path`, `audit_log_jsonl_path`
- `solver`
- `judge`

Each role must define:

- `chat_completions_url`
- `api_key_env`
- `model`

Optional config keys:

- `env_file`
- `request_timeout_sec`
- `start_index`
- `max_items`
- `language_filter`
- `resume_from_audit`
- `solver_temperature`
- `judge_temperature`
- `judge_use_response_format`
- `solver_system_prompt`
- `judge_system_prompt`

Example:

```json
{
  "input_jsonl_path": "/path/to/problems.jsonl",
  "output_dir": "/path/to/output",
  "env_file": "/path/to/.env",
  "solver": {
    "chat_completions_url": "http://solver-host/v1/chat/completions",
    "api_key_env": "SOLVER_API_KEY",
    "model": "gpt-5.4"
  },
  "judge": {
    "chat_completions_url": "http://judge-host/v1/chat/completions",
    "api_key_env": "JUDGE_API_KEY",
    "model": "gpt-5.4"
  }
}
```

## `.env`

Store only keys here. The repo-local `.env` is preferred over shell env vars.

Example:

```env
SOLVER_API_KEY=...
JUDGE_API_KEY=...
```

## Input format

Each JSONL row must include:

- `id`
- `solver_prompt`
- `problem_statement`
- `function_signature`

Optional fields like `language`, `difficulty`, `constraints`, and `edge_cases_hinted` are passed into the judge prompt when present.

## Output format

The runner writes:

- `kept_problems.jsonl`
- `dropped_problems.jsonl`
- `audit_log.jsonl`

Each output row keeps the original record and adds:

- `filter_decision`
- `judge_correct`
- `judge_confidence`
- `judge_reason`
- `solver_code`
- `solver_model`
- `judge_model`

Audit records also include:

- `timestamp`
- `decision`
- `judge_raw_response`
- `normalized_verdict`
- `failure_stage`
- `error`

## Behavior notes

- `drop` means the judge says the solver is correct.
- `keep` means the judge says the solver is wrong, or the model stage failed.
- Judge output must include a valid `correct` value.
- If solver or judge fails, the row is kept by fallback.
- `response_format` can be disabled with `judge_use_response_format=false` if the gateway does not support it.

## Run

```bash
python3 scripts/filter_sft_high_value_problems.py --config /path/to/config.json
```

## Resume

If `resume_from_audit` is true, the runner skips rows whose `id` already appears in the audit log.

## Testing

```bash
pytest -q tests/test_filter_sft_high_value_problems.py
```
