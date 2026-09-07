import os
import json
import argparse
import urllib.request
from datetime import datetime, timezone
from urllib.parse import urlparse


class ConfigError(Exception):
    pass


_NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_DEFAULT_OPENER = urllib.request.build_opener()


class OpenAICompatibleClient:
    def __init__(self, cfg):
        self.solver_chat_completions_url = cfg["solver"]["chat_completions_url"]
        self.judge_chat_completions_url = cfg["judge"]["chat_completions_url"]
        self.solver_api_key = resolve_api_key(cfg, "solver")
        self.judge_api_key = resolve_api_key(cfg, "judge")
        self.solver_model = cfg["solver"]["model"]
        self.judge_model = cfg["judge"]["model"]
        self.request_timeout_sec = cfg.get("request_timeout_sec", 60)
        self.solver_temperature = cfg.get("solver_temperature", 0.0)
        self.judge_temperature = cfg.get("judge_temperature", 0.0)
        self.judge_use_response_format = cfg.get("judge_use_response_format", True)
        self.solver_system_prompt = cfg.get(
            "solver_system_prompt",
            "You are a coding model. Output pure code only. No markdown fences. No explanations.",
        )
        self.judge_system_prompt = cfg.get(
            "judge_system_prompt",
            "You are a strict code judge. Return JSON only with keys correct, confidence, reason.",
        )


def load_env_file(path):
    env = {}
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def _get_env_value(name, env_map):
    if name in env_map:
        return env_map[name]
    return os.environ.get(name)


def _apply_output_defaults(cfg):
    if cfg.get("output_dir"):
        output_dir = cfg["output_dir"]
        cfg.setdefault("kept_output_jsonl_path", os.path.join(output_dir, "kept_problems.jsonl"))
        cfg.setdefault("dropped_output_jsonl_path", os.path.join(output_dir, "dropped_problems.jsonl"))
        cfg.setdefault("audit_log_jsonl_path", os.path.join(output_dir, "audit_log.jsonl"))
    return cfg


def normalize_runtime_config(cfg):
    cfg = dict(cfg)
    cfg.setdefault("_env", {})
    cfg = _apply_output_defaults(cfg)

    for role in ("solver", "judge"):
        if role not in cfg or not isinstance(cfg[role], dict):
            raise ConfigError(f"Missing required {role} config")
        cfg[role] = dict(cfg[role])
    return cfg


def resolve_api_key(cfg, role):
    env_map = cfg.get("_env", {})
    if role not in cfg or not isinstance(cfg[role], dict):
        raise ConfigError(f"Missing required {role} config")
    env_name = cfg[role].get("api_key_env")
    if not env_name:
        raise ConfigError(f"Missing required {role}.api_key_env")
    value = _get_env_value(env_name, env_map)
    if not value:
        raise ConfigError(f"Missing API key environment variable for {role}: {env_name}")
    return value


def load_config(path):
    with open(path, "r", encoding="utf-8") as handle:
        cfg = json.load(handle)

    env_map = {}
    if cfg.get("env_file"):
        env_map = load_env_file(cfg["env_file"])
    cfg["_env"] = env_map

    cfg = normalize_runtime_config(cfg)

    for key in (
        "input_jsonl_path",
        "kept_output_jsonl_path",
        "dropped_output_jsonl_path",
        "audit_log_jsonl_path",
    ):
        if key not in cfg or not cfg[key]:
            raise ConfigError(f"Missing required config key: {key}")
    for role in ("solver", "judge"):
        if not cfg[role].get("model"):
            raise ConfigError(f"Missing required {role}.model")
        if not cfg[role].get("chat_completions_url"):
            raise ConfigError(f"Missing required {role}.chat_completions_url")
        if not cfg[role].get("api_key_env"):
            raise ConfigError(f"Missing required {role}.api_key_env")
    validate_config_paths(cfg)
    return cfg


def normalize_judge_response(raw):
    if "correct" not in raw:
        raise ValueError("Judge response missing required key: correct")
    correct_value = raw.get("correct")
    if isinstance(correct_value, bool):
        correct = correct_value
    else:
        normalized = str(correct_value).strip().lower()
        if normalized in {"true", "1", "yes"}:
            correct = True
        elif normalized in {"false", "0", "no"}:
            correct = False
        else:
            raise ValueError(f"Judge response has invalid correct value: {correct_value!r}")

    try:
        confidence = float(raw.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    reason = raw.get("reason") or "Judge did not provide a reason."
    return {
        "correct": correct,
        "confidence": confidence,
        "reason": reason,
    }


def route_record(verdict):
    return "drop" if verdict["correct"] else "keep"


def _format_optional_metadata(record):
    lines = []
    if record.get("language"):
        lines.append(f"Language: {record['language']}")
    if record.get("difficulty"):
        lines.append(f"Difficulty: {record['difficulty']}")
    if record.get("constraints"):
        constraints = record["constraints"]
        if isinstance(constraints, list):
            constraints = "\n".join(f"- {item}" for item in constraints)
        lines.append(f"Constraints:\n{constraints}")
    if record.get("edge_cases_hinted"):
        edge_cases = record["edge_cases_hinted"]
        if isinstance(edge_cases, list):
            edge_cases = "\n".join(f"- {item}" for item in edge_cases)
        lines.append(f"Edge cases hinted:\n{edge_cases}")
    return ("\n\n" + "\n\n".join(lines)) if lines else ""


def build_solver_prompt(record):
    return record["solver_prompt"]


def _solver_prompt_excerpt(prompt, limit=1200):
    return prompt[:limit]


def build_judge_prompt(record, solver_code):
    return (
        "You are a strict judge. Return JSON only with keys correct, confidence, reason.\n"
        f"Problem:\n{record['problem_statement']}\n\n"
        f"Function signature:\n{record['function_signature']}\n\n"
        f"{_format_optional_metadata(record)}\n\n"
        f"Solver code:\n{solver_code}\n"
    )


def _extract_content(payload):
    try:
        return payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ConfigError("Malformed chat completions response") from exc


def _no_proxy_entries():
    raw_values = [os.environ.get("no_proxy"), os.environ.get("NO_PROXY")]
    entries = []
    for raw in raw_values:
        if not raw:
            continue
        for entry in raw.split(","):
            entry = entry.strip().lower()
            if entry and entry not in entries:
                entries.append(entry)
    return entries


def _host_matches_no_proxy_entry(hostname, entry):
    if entry == "*":
        return True
    if entry.startswith("*."):
        entry = entry[1:]
    if entry.endswith("*"):
        return hostname.startswith(entry[:-1])
    entry = entry.lstrip(".")
    return hostname == entry or hostname.endswith("." + entry)


def _select_opener(url):
    hostname = (urlparse(url).hostname or "").lower()
    for entry in _no_proxy_entries():
        if _host_matches_no_proxy_entry(hostname, entry):
            return _NO_PROXY_OPENER
    return _DEFAULT_OPENER


def _post_chat_completion(chat_completions_url, api_key, body, timeout_sec):
    req = urllib.request.Request(
        chat_completions_url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with _select_opener(chat_completions_url).open(req, timeout=timeout_sec) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Chat completions request failed: {exc}") from exc
    return _extract_content(payload)


def load_jsonl(path):
    with open(path, "r", encoding="utf-8") as handle:
        for lineno, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise ConfigError(f"Invalid JSONL at line {lineno}: {exc}") from exc


def append_jsonl(path, record):
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    try:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        raise ConfigError(f"Failed to write output file: {path}") from exc


def enrich_output_record(record, decision, verdict, solver_code, cfg):
    output = dict(record)
    output.update(
        {
            "filter_decision": decision,
            "judge_correct": verdict["correct"],
            "judge_confidence": verdict["confidence"],
            "judge_reason": verdict["reason"],
            "solver_code": solver_code,
            "solver_model": cfg["solver"]["model"],
            "judge_model": cfg["judge"]["model"],
        }
    )
    return output


def build_audit_record(record, decision, verdict, solver_code, cfg, error=None, judge_raw_response=None, solver_prompt_excerpt="", judge_prompt_excerpt="", failure_stage=None):
    return {
        "id": record["id"],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "decision": decision,
        "judge_correct": verdict["correct"],
        "judge_confidence": verdict["confidence"],
        "judge_reason": verdict["reason"],
        "solver_model": cfg["solver"]["model"],
        "judge_model": cfg["judge"]["model"],
        "solver_code": solver_code,
        "judge_raw_response": judge_raw_response,
        "normalized_verdict": verdict,
        "solver_prompt_excerpt": solver_prompt_excerpt[:400],
        "judge_prompt_excerpt": judge_prompt_excerpt[:400],
        "failure_stage": failure_stage,
        "error": error,
    }


def validate_record(record):
    for key in ("id", "solver_prompt", "problem_statement", "function_signature"):
        if key not in record or not record[key]:
            raise ConfigError(f"Missing required field: {key}")


def load_processed_ids(audit_path):
    if not os.path.exists(audit_path):
        return set()
    processed_ids = set()
    for record in load_jsonl(audit_path):
        record_id = record.get("id")
        if record_id:
            processed_ids.add(record_id)
    return processed_ids


def validate_config_paths(cfg):
    input_path = cfg["input_jsonl_path"]
    if not os.path.exists(input_path):
        raise ConfigError(f"Input JSONL path does not exist: {input_path}")

    for key in ("kept_output_jsonl_path", "dropped_output_jsonl_path", "audit_log_jsonl_path"):
        parent = os.path.dirname(cfg[key]) or "."
        try:
            os.makedirs(parent, exist_ok=True)
            if not os.path.isdir(parent):
                raise OSError(f"Parent path is not a directory: {parent}")
            if not os.access(parent, os.W_OK):
                raise OSError(f"Parent path is not writable: {parent}")
        except OSError as exc:
            raise ConfigError(f"Output path is not writable: {cfg[key]}") from exc


def iter_selected_records(cfg, input_path):
    language_filter = cfg.get("language_filter")
    start_index = int(cfg.get("start_index", 0) or 0)
    max_items = cfg.get("max_items")
    max_items = None if max_items is None else int(max_items)

    yielded = 0
    filtered_index = 0
    for record in load_jsonl(input_path):
        if language_filter and record.get("language") != language_filter:
            continue
        if filtered_index < start_index:
            filtered_index += 1
            continue
        if max_items is not None and yielded >= max_items:
            break
        filtered_index += 1
        yielded += 1
        yield record


def process_records(cfg, client):
    cfg = normalize_runtime_config(cfg)
    resolve_api_key(cfg, "solver")
    resolve_api_key(cfg, "judge")

    input_path = cfg["input_jsonl_path"]
    kept_path = cfg["kept_output_jsonl_path"]
    dropped_path = cfg["dropped_output_jsonl_path"]
    audit_path = cfg["audit_log_jsonl_path"]
    processed_ids = load_processed_ids(audit_path) if cfg.get("resume_from_audit") else set()

    processed = 0
    skipped = 0
    for record in iter_selected_records(cfg, input_path):
        validate_record(record)
        if record["id"] in processed_ids:
            skipped += 1
            continue
        solver_prompt = ""
        solver_code = ""
        judge_prompt = ""
        judge_raw_response = None
        failure_stage = None
        try:
            solver_prompt = build_solver_prompt(record)
            failure_stage = "solver"
            solver_code = client.solve(record, solver_prompt)
            judge_prompt = build_judge_prompt(record, solver_code)
            failure_stage = "judge"
            judge_raw_response = client.judge(record, solver_code, judge_prompt)
            verdict = normalize_judge_response(judge_raw_response)
            decision = route_record(verdict)
            error = None
            failure_stage = None
        except Exception as exc:
            verdict = {
                "correct": False,
                "confidence": 0.0,
                "reason": "Model-stage failure; kept by fallback.",
            }
            decision = "keep"
            error = str(exc)

        output_record = enrich_output_record(record, decision, verdict, solver_code, cfg)
        audit_record = build_audit_record(
            record,
            decision,
            verdict,
            solver_code,
            cfg,
            error=error,
            judge_raw_response=judge_raw_response,
            solver_prompt_excerpt=_solver_prompt_excerpt(solver_prompt),
            judge_prompt_excerpt=judge_prompt,
            failure_stage=failure_stage,
        )

        target_path = dropped_path if decision == "drop" else kept_path
        append_jsonl(target_path, output_record)
        append_jsonl(audit_path, audit_record)
        processed += 1

    return {"processed": processed, "skipped": skipped}


def _client_solve(self, record, prompt):
    body = {
        "model": self.solver_model,
        "messages": [
            {"role": "system", "content": self.solver_system_prompt},
            {"role": "user", "content": prompt},
        ],
        "temperature": self.solver_temperature,
    }
    return _post_chat_completion(self.solver_chat_completions_url, self.solver_api_key, body, self.request_timeout_sec)


def _client_judge(self, record, solver_code, prompt):
    body = {
        "model": self.judge_model,
        "messages": [
            {"role": "system", "content": self.judge_system_prompt},
            {"role": "user", "content": prompt},
        ],
        "temperature": self.judge_temperature,
    }
    if self.judge_use_response_format:
        body["response_format"] = {"type": "json_object"}
    raw = _post_chat_completion(self.judge_chat_completions_url, self.judge_api_key, body, self.request_timeout_sec)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Judge returned non-JSON content: {raw}") from exc


OpenAICompatibleClient.solve = _client_solve
OpenAICompatibleClient.judge = _client_judge


def main():
    parser = argparse.ArgumentParser(description="Filter SFT problems into kept and dropped JSONL outputs.")
    parser.add_argument("--config", required=True, help="Path to JSON config file.")
    args = parser.parse_args()

    cfg = load_config(args.config)
    client = OpenAICompatibleClient(cfg)
    result = process_records(cfg, client=client)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
