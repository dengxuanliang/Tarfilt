import importlib.util
import json
from pathlib import Path

import pytest


MODULE_PATH = (
    Path(__file__).resolve().parent.parent
    / "scripts"
    / "filter_sft_high_value_problems.py"
)


def load_module():
    spec = importlib.util.spec_from_file_location("filter_skill", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def write_jsonl(path, records):
    with open(path, "w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_jsonl(path):
    with open(path, "r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def gateway_cfg():
    return {
        "solver": {
            "chat_completions_url": "https://solver.example/v1/chat/completions",
            "api_key_env": "SOLVER_API_KEY",
            "model": "solver-a",
        },
        "judge": {
            "chat_completions_url": "https://judge.example/v1/chat/completions",
            "api_key_env": "JUDGE_API_KEY",
            "model": "judge-b",
        },
    }


def test_resolve_api_key_requires_role_specific_env_var(monkeypatch):
    module = load_module()
    monkeypatch.delenv("SOLVER_API_KEY", raising=False)
    cfg = {"solver": {"api_key_env": "SOLVER_API_KEY"}}
    with pytest.raises(module.ConfigError):
        module.resolve_api_key(cfg, "solver")


def test_load_config_reads_role_specific_gateway_settings(tmp_path, monkeypatch):
    module = load_module()
    env_path = tmp_path / ".env"
    env_path.write_text(
        'SOLVER_API_KEY="solver-key"\n'
        'JUDGE_API_KEY="judge-key"\n',
        encoding="utf-8",
    )
    input_path = tmp_path / "input.jsonl"
    input_path.write_text("", encoding="utf-8")
    output_dir = tmp_path / "out"
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "input_jsonl_path": str(input_path),
                "output_dir": str(output_dir),
                "env_file": str(env_path),
                "solver": {
                    "chat_completions_url": "https://solver.example/v1/chat/completions",
                    "api_key_env": "SOLVER_API_KEY",
                    "model": "solver-model",
                },
                "judge": {
                    "chat_completions_url": "https://judge.example/v1/chat/completions",
                    "api_key_env": "JUDGE_API_KEY",
                    "model": "judge-model",
                },
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.delenv("SOLVER_API_KEY", raising=False)
    monkeypatch.delenv("JUDGE_API_KEY", raising=False)

    cfg = module.load_config(str(config_path))
    assert cfg["solver"]["chat_completions_url"] == "https://solver.example/v1/chat/completions"
    assert cfg["judge"]["chat_completions_url"] == "https://judge.example/v1/chat/completions"
    assert module.resolve_api_key(cfg, "solver") == "solver-key"
    assert module.resolve_api_key(cfg, "judge") == "judge-key"


def test_client_routes_solver_and_judge_to_role_specific_endpoints(tmp_path, monkeypatch):
    module = load_module()
    monkeypatch.setenv("SOLVER_API_KEY", "solver-key")
    monkeypatch.setenv("JUDGE_API_KEY", "judge-key")

    captured = []

    def fake_post(chat_completions_url, api_key, body, timeout_sec):
        captured.append(
            {
                "url": chat_completions_url,
                "api_key": api_key,
                "body": body,
                "timeout_sec": timeout_sec,
            }
        )
        if body["model"] == "judge-model":
            return '{"correct": true, "confidence": 0.9, "reason": "ok"}'
        return "def solve():\n    return 1\n"

    original = module._post_chat_completion
    module._post_chat_completion = fake_post
    try:
        cfg = module.normalize_runtime_config(
            {
                "input_jsonl_path": str(tmp_path / "input.jsonl"),
                "kept_output_jsonl_path": str(tmp_path / "kept.jsonl"),
                "dropped_output_jsonl_path": str(tmp_path / "dropped.jsonl"),
                "audit_log_jsonl_path": str(tmp_path / "audit.jsonl"),
                "solver": {
                    "chat_completions_url": "https://solver.example/v1/chat/completions",
                    "api_key_env": "SOLVER_API_KEY",
                    "model": "solver-model",
                },
                "judge": {
                    "chat_completions_url": "https://judge.example/v1/chat/completions",
                    "api_key_env": "JUDGE_API_KEY",
                    "model": "judge-model",
                },
            }
        )
        client = module.OpenAICompatibleClient(cfg)
        solver_code = client.solve(
            {"id": "S1", "problem_statement": "A", "function_signature": "def solve():"},
            "solve prompt",
        )
        verdict = client.judge(
            {"id": "S1", "problem_statement": "A", "function_signature": "def solve():"},
            solver_code,
            "judge prompt",
        )
    finally:
        module._post_chat_completion = original

    assert solver_code.startswith("def solve")
    assert verdict["correct"] is True
    assert captured[0]["url"] == "https://solver.example/v1/chat/completions"
    assert captured[0]["api_key"] == "solver-key"
    assert captured[1]["url"] == "https://judge.example/v1/chat/completions"
    assert captured[1]["api_key"] == "judge-key"


def test_select_opener_uses_no_proxy_for_matching_host(monkeypatch):
    module = load_module()
    monkeypatch.setenv("NO_PROXY", "solver.example,.internal.example")
    no_proxy_opener = object()
    default_opener = object()
    monkeypatch.setattr(module, "_NO_PROXY_OPENER", no_proxy_opener, raising=False)
    monkeypatch.setattr(module, "_DEFAULT_OPENER", default_opener, raising=False)

    assert module._select_opener("https://solver.example/v1/chat/completions") is no_proxy_opener
    assert module._select_opener("https://api.internal.example/v1/chat/completions") is no_proxy_opener
    assert module._select_opener("https://public.example/v1/chat/completions") is default_opener


def test_post_chat_completion_uses_selected_opener(monkeypatch):
    module = load_module()
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                {"choices": [{"message": {"content": "print(1)"}}]}
            ).encode("utf-8")

    class FakeOpener:
        def open(self, req, timeout=None):
            captured["req"] = req
            captured["timeout"] = timeout
            return FakeResponse()

    monkeypatch.setattr(module, "_select_opener", lambda url: FakeOpener())

    out = module._post_chat_completion(
        "https://solver.example/v1/chat/completions",
        "solver-key",
        {"model": "solver-model", "messages": []},
        42,
    )

    assert out == "print(1)"
    assert captured["timeout"] == 42
    assert captured["req"].full_url == "https://solver.example/v1/chat/completions"


def test_normalize_judge_response_clamps_confidence_and_defaults_reason():
    module = load_module()
    verdict = module.normalize_judge_response({"correct": "yes", "confidence": 7})
    assert verdict["correct"] is True
    assert verdict["confidence"] == 1.0
    assert verdict["reason"]


def test_route_record_drops_correct_and_keeps_incorrect():
    module = load_module()
    assert module.route_record({"correct": True}) == "drop"
    assert module.route_record({"correct": False}) == "keep"


def test_process_records_writes_kept_dropped_and_audit(tmp_path, monkeypatch):
    module = load_module()
    monkeypatch.setenv("SOLVER_API_KEY", "solver-test-key")
    monkeypatch.setenv("JUDGE_API_KEY", "judge-test-key")

    input_path = tmp_path / "input.jsonl"
    kept_path = tmp_path / "kept.jsonl"
    dropped_path = tmp_path / "dropped.jsonl"
    audit_path = tmp_path / "audit.jsonl"

    write_jsonl(
        input_path,
        [
            {
                "id": "S1",
                "problem_statement": "Return 1.",
                "function_signature": "def solve() -> int:",
                "language": "python",
                "solver_prompt": "Return only code for S1.",
            },
            {
                "id": "S2",
                "problem_statement": "Return 2.",
                "function_signature": "def solve() -> int:",
                "language": "python",
                "solver_prompt": "Return only code for S2.",
            },
        ],
    )

    class FakeClient:
        def solve(self, record, prompt):
            return "def solve() -> int:\n    return 1\n"

        def judge(self, record, solver_code, prompt):
            if record["id"] == "S1":
                return {"correct": True, "confidence": 0.9, "reason": "Solved."}
            return {"correct": False, "confidence": 0.8, "reason": "Wrong."}

    cfg = {
        "input_jsonl_path": str(input_path),
        "kept_output_jsonl_path": str(kept_path),
        "dropped_output_jsonl_path": str(dropped_path),
        "audit_log_jsonl_path": str(audit_path),
        **gateway_cfg(),
    }

    result = module.process_records(cfg, client=FakeClient())
    kept = read_jsonl(kept_path)
    dropped = read_jsonl(dropped_path)
    audit = read_jsonl(audit_path)

    assert result["processed"] == 2
    assert [row["id"] for row in kept] == ["S2"]
    assert [row["id"] for row in dropped] == ["S1"]
    assert audit[0]["solver_code"]
    assert audit[0]["judge_correct"] is True


def test_resume_skips_existing_problem_ids(tmp_path, monkeypatch):
    module = load_module()
    monkeypatch.setenv("SOLVER_API_KEY", "solver-test-key")
    monkeypatch.setenv("JUDGE_API_KEY", "judge-test-key")

    input_path = tmp_path / "input.jsonl"
    kept_path = tmp_path / "kept.jsonl"
    dropped_path = tmp_path / "dropped.jsonl"
    audit_path = tmp_path / "audit.jsonl"

    write_jsonl(
        input_path,
        [
            {"id": "S1", "problem_statement": "Return 1.", "function_signature": "def solve() -> int:", "solver_prompt": "Return only code for S1."},
            {"id": "S2", "problem_statement": "Return 2.", "function_signature": "def solve() -> int:", "solver_prompt": "Return only code for S2."},
        ],
    )
    write_jsonl(
        audit_path,
        [
            {
                "id": "S1",
                "decision": "drop",
                "judge_correct": True,
                "judge_confidence": 0.9,
                "judge_reason": "done",
                "solver_model": "solver-a",
                "judge_model": "judge-b",
                "solver_code": "def solve(): pass",
                "error": None,
            }
        ],
    )

    class FakeClient:
        def __init__(self):
            self.solve_count = 0

        def solve(self, record, prompt):
            self.solve_count += 1
            return "def solve() -> int:\n    return 2\n"

        def judge(self, record, solver_code, prompt):
            return {"correct": False, "confidence": 0.7, "reason": "Wrong."}

    client = FakeClient()
    cfg = {
        "input_jsonl_path": str(input_path),
        "kept_output_jsonl_path": str(kept_path),
        "dropped_output_jsonl_path": str(dropped_path),
        "audit_log_jsonl_path": str(audit_path),
        "resume_from_audit": True,
        **gateway_cfg(),
    }

    result = module.process_records(cfg, client=client)
    assert result["processed"] == 1
    assert result["skipped"] == 1
    assert client.solve_count == 1
    assert [row["id"] for row in read_jsonl(kept_path)] == ["S2"]


def test_judge_parse_failure_defaults_to_keep_and_audit_error(tmp_path, monkeypatch):
    module = load_module()
    monkeypatch.setenv("SOLVER_API_KEY", "solver-test-key")
    monkeypatch.setenv("JUDGE_API_KEY", "judge-test-key")

    input_path = tmp_path / "input.jsonl"
    kept_path = tmp_path / "kept.jsonl"
    dropped_path = tmp_path / "dropped.jsonl"
    audit_path = tmp_path / "audit.jsonl"

    write_jsonl(
        input_path,
        [{"id": "S1", "problem_statement": "Return 1.", "function_signature": "def solve() -> int:", "solver_prompt": "Return only code for S1."}],
    )

    class FakeClient:
        def solve(self, record, prompt):
            return "def solve() -> int:\n    return 1\n"

        def judge(self, record, solver_code, prompt):
            raise ValueError("bad judge output")

    cfg = {
        "input_jsonl_path": str(input_path),
        "kept_output_jsonl_path": str(kept_path),
        "dropped_output_jsonl_path": str(dropped_path),
        "audit_log_jsonl_path": str(audit_path),
        **gateway_cfg(),
    }

    result = module.process_records(cfg, client=FakeClient())
    kept = read_jsonl(kept_path)
    audit = read_jsonl(audit_path)

    assert result["processed"] == 1
    assert [row["id"] for row in kept] == ["S1"]
    assert audit[0]["decision"] == "keep"
    assert audit[0]["failure_stage"] == "judge"
    assert "bad judge output" in audit[0]["error"]


def test_judge_missing_correct_key_defaults_to_keep_and_audit_error(tmp_path, monkeypatch):
    module = load_module()
    monkeypatch.setenv("SOLVER_API_KEY", "solver-test-key")
    monkeypatch.setenv("JUDGE_API_KEY", "judge-test-key")

    input_path = tmp_path / "input.jsonl"
    kept_path = tmp_path / "kept.jsonl"
    dropped_path = tmp_path / "dropped.jsonl"
    audit_path = tmp_path / "audit.jsonl"

    write_jsonl(
        input_path,
        [{"id": "S1", "problem_statement": "Return 1.", "function_signature": "def solve() -> int:", "solver_prompt": "Return only code for S1."}],
    )

    class FakeClient:
        def solve(self, record, prompt):
            return "def solve() -> int:\n    return 1\n"

        def judge(self, record, solver_code, prompt):
            return {"confidence": 0.9, "reason": "missing correct"}

    cfg = {
        "input_jsonl_path": str(input_path),
        "kept_output_jsonl_path": str(kept_path),
        "dropped_output_jsonl_path": str(dropped_path),
        "audit_log_jsonl_path": str(audit_path),
        **gateway_cfg(),
    }

    result = module.process_records(cfg, client=FakeClient())
    kept = read_jsonl(kept_path)
    audit = read_jsonl(audit_path)

    assert result["processed"] == 1
    assert [row["id"] for row in kept] == ["S1"]
    assert audit[0]["decision"] == "keep"
    assert audit[0]["failure_stage"] == "judge"
    assert "missing required key: correct" in audit[0]["error"]


def test_judge_invalid_correct_value_defaults_to_keep_and_audit_error(tmp_path, monkeypatch):
    module = load_module()
    monkeypatch.setenv("SOLVER_API_KEY", "solver-test-key")
    monkeypatch.setenv("JUDGE_API_KEY", "judge-test-key")

    input_path = tmp_path / "input.jsonl"
    kept_path = tmp_path / "kept.jsonl"
    dropped_path = tmp_path / "dropped.jsonl"
    audit_path = tmp_path / "audit.jsonl"

    write_jsonl(
        input_path,
        [{"id": "S1", "problem_statement": "Return 1.", "function_signature": "def solve() -> int:", "solver_prompt": "Return only code for S1."}],
    )

    class FakeClient:
        def solve(self, record, prompt):
            return "def solve() -> int:\n    return 1\n"

        def judge(self, record, solver_code, prompt):
            return {"correct": "maybe", "confidence": 0.9, "reason": "ambiguous"}

    cfg = {
        "input_jsonl_path": str(input_path),
        "kept_output_jsonl_path": str(kept_path),
        "dropped_output_jsonl_path": str(dropped_path),
        "audit_log_jsonl_path": str(audit_path),
        **gateway_cfg(),
    }

    result = module.process_records(cfg, client=FakeClient())
    kept = read_jsonl(kept_path)
    audit = read_jsonl(audit_path)

    assert result["processed"] == 1
    assert [row["id"] for row in kept] == ["S1"]
    assert audit[0]["decision"] == "keep"
    assert audit[0]["failure_stage"] == "judge"
    assert "invalid correct value" in audit[0]["error"]


def test_rejects_invalid_jsonl_input(tmp_path, monkeypatch):
    module = load_module()
    monkeypatch.setenv("SOLVER_API_KEY", "solver-test-key")
    monkeypatch.setenv("JUDGE_API_KEY", "judge-test-key")

    input_path = tmp_path / "input.jsonl"
    input_path.write_text("{bad json}\n", encoding="utf-8")

    cfg = {
        "input_jsonl_path": str(input_path),
        "kept_output_jsonl_path": str(tmp_path / "kept.jsonl"),
        "dropped_output_jsonl_path": str(tmp_path / "dropped.jsonl"),
        "audit_log_jsonl_path": str(tmp_path / "audit.jsonl"),
        **gateway_cfg(),
    }

    class FakeClient:
        def solve(self, record, prompt):
            raise AssertionError("should not be called")

        def judge(self, record, solver_code, prompt):
            raise AssertionError("should not be called")

    with pytest.raises(module.ConfigError):
        module.process_records(cfg, client=FakeClient())


def test_solver_failure_defaults_to_keep_and_audit_error(tmp_path, monkeypatch):
    module = load_module()
    monkeypatch.setenv("SOLVER_API_KEY", "solver-test-key")
    monkeypatch.setenv("JUDGE_API_KEY", "judge-test-key")

    input_path = tmp_path / "input.jsonl"
    kept_path = tmp_path / "kept.jsonl"
    dropped_path = tmp_path / "dropped.jsonl"
    audit_path = tmp_path / "audit.jsonl"

    write_jsonl(
        input_path,
        [
                {"id": "S1", "problem_statement": "Return 1.", "function_signature": "def solve() -> int:", "solver_prompt": "Return only code for S1."},
                {"id": "S2", "problem_statement": "Return 2.", "function_signature": "def solve() -> int:", "solver_prompt": "Return only code for S2."},
            ],
        )

    class FakeClient:
        def solve(self, record, prompt):
            if record["id"] == "S1":
                raise RuntimeError("solver timeout")
            return "def solve() -> int:\n    return 2\n"

        def judge(self, record, solver_code, prompt):
            return {"correct": False, "confidence": 0.7, "reason": "Wrong."}

    cfg = {
        "input_jsonl_path": str(input_path),
        "kept_output_jsonl_path": str(kept_path),
        "dropped_output_jsonl_path": str(dropped_path),
        "audit_log_jsonl_path": str(audit_path),
        **gateway_cfg(),
    }

    result = module.process_records(cfg, client=FakeClient())
    kept = read_jsonl(kept_path)
    audit = read_jsonl(audit_path)

    assert result["processed"] == 2
    assert [row["id"] for row in kept] == ["S1", "S2"]
    assert audit[0]["decision"] == "keep"
    assert audit[0]["failure_stage"] == "solver"
    assert "solver timeout" in audit[0]["error"]


def test_solver_failure_does_not_reuse_previous_solver_code(tmp_path, monkeypatch):
    module = load_module()
    monkeypatch.setenv("SOLVER_API_KEY", "solver-test-key")
    monkeypatch.setenv("JUDGE_API_KEY", "judge-test-key")

    input_path = tmp_path / "input.jsonl"
    kept_path = tmp_path / "kept.jsonl"
    dropped_path = tmp_path / "dropped.jsonl"
    audit_path = tmp_path / "audit.jsonl"

    write_jsonl(
        input_path,
        [
            {"id": "S1", "problem_statement": "1", "function_signature": "def solve() -> int:", "solver_prompt": "Return only code for S1."},
            {"id": "S2", "problem_statement": "2", "function_signature": "def solve() -> int:", "solver_prompt": "Return only code for S2."},
        ],
    )

    class FakeClient:
        def solve(self, record, prompt):
            if record["id"] == "S1":
                raise RuntimeError("solver timeout")
            return "def solve() -> int:\n    return 2\n"

        def judge(self, record, solver_code, prompt):
            return {"correct": False, "confidence": 0.7, "reason": "Wrong."}

    cfg = {
        "input_jsonl_path": str(input_path),
        "kept_output_jsonl_path": str(kept_path),
        "dropped_output_jsonl_path": str(dropped_path),
        "audit_log_jsonl_path": str(audit_path),
        **gateway_cfg(),
    }

    module.process_records(cfg, client=FakeClient())
    audit = read_jsonl(audit_path)

    assert audit[0]["solver_code"] == ""
    assert audit[1]["solver_code"]


def test_load_config_reads_role_specific_env_and_derives_output_paths(tmp_path, monkeypatch):
    module = load_module()
    env_path = tmp_path / ".env"
    env_path.write_text(
        'SOLVER_API_KEY="solver-key"\n'
        'JUDGE_API_KEY="judge-key"\n',
        encoding="utf-8",
    )
    input_path = tmp_path / "input.jsonl"
    input_path.write_text("", encoding="utf-8")
    output_dir = tmp_path / "out"
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "input_jsonl_path": str(input_path),
                "output_dir": str(output_dir),
                "env_file": str(env_path),
                "solver": {
                    "chat_completions_url": "https://solver.example/v1/chat/completions",
                    "api_key_env": "SOLVER_API_KEY",
                    "model": "solver-model",
                },
                "judge": {
                    "chat_completions_url": "https://judge.example/v1/chat/completions",
                    "api_key_env": "JUDGE_API_KEY",
                    "model": "judge-model",
                },
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.delenv("SOLVER_API_KEY", raising=False)
    monkeypatch.delenv("JUDGE_API_KEY", raising=False)

    cfg = module.load_config(str(config_path))
    assert cfg["solver"]["chat_completions_url"] == "https://solver.example/v1/chat/completions"
    assert cfg["judge"]["chat_completions_url"] == "https://judge.example/v1/chat/completions"
    assert cfg["solver"]["model"] == "solver-model"
    assert cfg["judge"]["model"] == "judge-model"
    assert cfg["kept_output_jsonl_path"].endswith("kept_problems.jsonl")
    assert cfg["dropped_output_jsonl_path"].endswith("dropped_problems.jsonl")
    assert cfg["audit_log_jsonl_path"].endswith("audit_log.jsonl")
    assert module.resolve_api_key(cfg, "solver") == "solver-key"
    assert module.resolve_api_key(cfg, "judge") == "judge-key"


def test_load_config_env_file_overrides_process_env_for_role_credentials(tmp_path, monkeypatch):
    module = load_module()
    env_path = tmp_path / ".env"
    env_path.write_text(
        'SOLVER_API_KEY="env-file-solver-key"\n'
        'JUDGE_API_KEY="env-file-judge-key"\n',
        encoding="utf-8",
    )
    input_path = tmp_path / "input.jsonl"
    input_path.write_text("", encoding="utf-8")
    output_dir = tmp_path / "out"
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "input_jsonl_path": str(input_path),
                "output_dir": str(output_dir),
                "env_file": str(env_path),
                "solver": {
                    "chat_completions_url": "https://solver.example/v1/chat/completions",
                    "api_key_env": "SOLVER_API_KEY",
                    "model": "solver-model",
                },
                "judge": {
                    "chat_completions_url": "https://judge.example/v1/chat/completions",
                    "api_key_env": "JUDGE_API_KEY",
                    "model": "judge-model",
                },
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("SOLVER_API_KEY", "process-env-solver-key")
    monkeypatch.setenv("JUDGE_API_KEY", "process-env-judge-key")

    cfg = module.load_config(str(config_path))
    assert module.resolve_api_key(cfg, "solver") == "env-file-solver-key"
    assert module.resolve_api_key(cfg, "judge") == "env-file-judge-key"


def test_language_filter_only_processes_matching_records(tmp_path, monkeypatch):
    module = load_module()
    monkeypatch.setenv("SOLVER_API_KEY", "solver-test-key")
    monkeypatch.setenv("JUDGE_API_KEY", "judge-test-key")

    input_path = tmp_path / "input.jsonl"
    kept_path = tmp_path / "kept.jsonl"
    dropped_path = tmp_path / "dropped.jsonl"
    audit_path = tmp_path / "audit.jsonl"

    write_jsonl(
        input_path,
        [
            {"id": "P1", "problem_statement": "A", "function_signature": "def solve():", "language": "python", "solver_prompt": "Solve P1."},
            {"id": "J1", "problem_statement": "B", "function_signature": "def solve():", "language": "java", "solver_prompt": "Solve J1."},
            {"id": "P2", "problem_statement": "C", "function_signature": "def solve():", "language": "python", "solver_prompt": "Solve P2."},
        ],
    )

    class FakeClient:
        def solve(self, record, prompt):
            return "def solve():\n    pass\n"

        def judge(self, record, solver_code, prompt):
            return {"correct": False, "confidence": 0.5, "reason": "Wrong."}

    cfg = {
        "input_jsonl_path": str(input_path),
        "kept_output_jsonl_path": str(kept_path),
        "dropped_output_jsonl_path": str(dropped_path),
        "audit_log_jsonl_path": str(audit_path),
        "language_filter": "python",
        **gateway_cfg(),
    }

    result = module.process_records(cfg, client=FakeClient())
    kept = read_jsonl(kept_path)

    assert result["processed"] == 2
    assert [row["id"] for row in kept] == ["P1", "P2"]


def test_start_index_and_max_items_limit_processed_window(tmp_path, monkeypatch):
    module = load_module()
    monkeypatch.setenv("SOLVER_API_KEY", "solver-test-key")
    monkeypatch.setenv("JUDGE_API_KEY", "judge-test-key")

    input_path = tmp_path / "input.jsonl"
    kept_path = tmp_path / "kept.jsonl"
    dropped_path = tmp_path / "dropped.jsonl"
    audit_path = tmp_path / "audit.jsonl"

    write_jsonl(
        input_path,
        [
            {"id": "S0", "problem_statement": "0", "function_signature": "def solve():", "solver_prompt": "Solve S0."},
            {"id": "S1", "problem_statement": "1", "function_signature": "def solve():", "solver_prompt": "Solve S1."},
            {"id": "S2", "problem_statement": "2", "function_signature": "def solve():", "solver_prompt": "Solve S2."},
            {"id": "S3", "problem_statement": "3", "function_signature": "def solve():", "solver_prompt": "Solve S3."},
        ],
    )

    class FakeClient:
        def solve(self, record, prompt):
            return "def solve():\n    pass\n"

        def judge(self, record, solver_code, prompt):
            return {"correct": False, "confidence": 0.5, "reason": "Wrong."}

    cfg = {
        "input_jsonl_path": str(input_path),
        "kept_output_jsonl_path": str(kept_path),
        "dropped_output_jsonl_path": str(dropped_path),
        "audit_log_jsonl_path": str(audit_path),
        "start_index": 1,
        "max_items": 2,
        **gateway_cfg(),
    }

    result = module.process_records(cfg, client=FakeClient())
    kept = read_jsonl(kept_path)

    assert result["processed"] == 2
    assert [row["id"] for row in kept] == ["S1", "S2"]


def test_audit_record_includes_raw_and_normalized_judge_evidence(tmp_path, monkeypatch):
    module = load_module()
    monkeypatch.setenv("SOLVER_API_KEY", "solver-test-key")
    monkeypatch.setenv("JUDGE_API_KEY", "judge-test-key")

    input_path = tmp_path / "input.jsonl"
    kept_path = tmp_path / "kept.jsonl"
    dropped_path = tmp_path / "dropped.jsonl"
    audit_path = tmp_path / "audit.jsonl"

    write_jsonl(
        input_path,
        [{"id": "S1", "problem_statement": "Return 1.", "function_signature": "def solve() -> int:", "solver_prompt": "Return only code for S1."}],
    )

    class FakeClient:
        def solve(self, record, prompt):
            return "def solve() -> int:\n    return 1\n"

        def judge(self, record, solver_code, prompt):
            return {"correct": True, "confidence": 0.9, "reason": "Solved."}

    cfg = {
        "input_jsonl_path": str(input_path),
        "kept_output_jsonl_path": str(kept_path),
        "dropped_output_jsonl_path": str(dropped_path),
        "audit_log_jsonl_path": str(audit_path),
        **gateway_cfg(),
    }

    module.process_records(cfg, client=FakeClient())
    audit = read_jsonl(audit_path)

    assert "judge_raw_response" in audit[0]
    assert "normalized_verdict" in audit[0]
    assert audit[0]["normalized_verdict"]["correct"] is True
    assert "solver_prompt_excerpt" in audit[0]
    assert "judge_prompt_excerpt" in audit[0]


def test_prompts_include_optional_problem_metadata():
    module = load_module()
    record = {
        "id": "S1",
        "problem_statement": "Solve it.",
        "function_signature": "def solve(x: int) -> int:",
        "language": "python",
        "difficulty": "hard",
        "constraints": ["1 <= x <= 10^5"],
        "edge_cases_hinted": ["x = 0", "max input"],
        "solver_prompt": "REAL SOLVER PROMPT",
    }

    solver_prompt = module.build_solver_prompt(record)
    judge_prompt = module.build_judge_prompt(record, "def solve(x: int) -> int:\n    return x\n")

    assert solver_prompt == "REAL SOLVER PROMPT"

    for expected in (
        "python",
        "hard",
        "1 <= x <= 10^5",
        "x = 0",
        "max input",
    ):
        assert expected in judge_prompt


def test_load_config_rejects_missing_input_path(tmp_path):
    module = load_module()
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "input_jsonl_path": str(tmp_path / "missing.jsonl"),
                "output_dir": str(tmp_path / "out"),
                "solver": {
                    "chat_completions_url": "https://solver.example/v1/chat/completions",
                    "api_key_env": "SOLVER_API_KEY",
                    "model": "solver-a",
                },
                "judge": {
                    "chat_completions_url": "https://judge.example/v1/chat/completions",
                    "api_key_env": "JUDGE_API_KEY",
                    "model": "judge-b",
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(module.ConfigError):
        module.load_config(str(config_path))


def test_load_jsonl_is_streaming_generator(tmp_path):
    module = load_module()
    input_path = tmp_path / "input.jsonl"
    write_jsonl(
        input_path,
        [
            {"id": "A", "problem_statement": "A", "function_signature": "def solve():"},
            {"id": "B", "problem_statement": "B", "function_signature": "def solve():"},
        ],
    )

    iterator = module.load_jsonl(str(input_path))
    assert hasattr(iterator, "__iter__")
    assert not isinstance(iterator, list)
    rows = list(iterator)
    assert [row["id"] for row in rows] == ["A", "B"]


def test_judge_use_response_format_can_be_disabled(tmp_path, monkeypatch):
    module = load_module()
    monkeypatch.setenv("SOLVER_API_KEY", "solver-test-key")
    monkeypatch.setenv("JUDGE_API_KEY", "judge-test-key")

    captured = {}

    def fake_post(chat_completions_url, api_key, body, timeout_sec):
        captured["body"] = body
        return '{"correct": true, "confidence": 0.8, "reason": "ok"}'

    original = module._post_chat_completion
    module._post_chat_completion = fake_post
    try:
        cfg = module.normalize_runtime_config(
            {
                "input_jsonl_path": str(tmp_path / "input.jsonl"),
                "kept_output_jsonl_path": str(tmp_path / "kept.jsonl"),
                "dropped_output_jsonl_path": str(tmp_path / "dropped.jsonl"),
                "audit_log_jsonl_path": str(tmp_path / "audit.jsonl"),
                **gateway_cfg(),
                "judge_use_response_format": False,
            }
        )
        client = module.OpenAICompatibleClient(cfg)
        client.judge(
            {"id": "S1", "problem_statement": "A", "function_signature": "def solve():"},
            "def solve():\n    pass\n",
            "judge prompt",
        )
    finally:
        module._post_chat_completion = original

    assert "response_format" not in captured["body"]


def test_load_config_rejects_unwritable_output_path(tmp_path):
    module = load_module()
    input_path = tmp_path / "input.jsonl"
    input_path.write_text("", encoding="utf-8")
    blocked_parent = tmp_path / "blocked-parent"
    blocked_parent.write_text("not a directory", encoding="utf-8")
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "input_jsonl_path": str(input_path),
                "kept_output_jsonl_path": str(blocked_parent / "kept.jsonl"),
                "dropped_output_jsonl_path": str(tmp_path / "dropped.jsonl"),
                "audit_log_jsonl_path": str(tmp_path / "audit.jsonl"),
                "solver": {
                    "chat_completions_url": "https://solver.example/v1/chat/completions",
                    "api_key_env": "SOLVER_API_KEY",
                    "model": "solver-a",
                },
                "judge": {
                    "chat_completions_url": "https://judge.example/v1/chat/completions",
                    "api_key_env": "JUDGE_API_KEY",
                    "model": "judge-b",
                }
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(module.ConfigError):
        module.load_config(str(config_path))


def test_load_config_does_not_create_output_files(tmp_path):
    module = load_module()
    input_path = tmp_path / "input.jsonl"
    input_path.write_text("", encoding="utf-8")
    output_dir = tmp_path / "out"
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "input_jsonl_path": str(input_path),
                "output_dir": str(output_dir),
                **gateway_cfg(),
            }
        ),
        encoding="utf-8",
    )

    assert not output_dir.exists()
    cfg = module.load_config(str(config_path))
    assert cfg["kept_output_jsonl_path"].endswith("kept_problems.jsonl")
    assert not (output_dir / "kept_problems.jsonl").exists()
    assert not (output_dir / "dropped_problems.jsonl").exists()
    assert not (output_dir / "audit_log.jsonl").exists()


def test_append_jsonl_wraps_write_failures(monkeypatch, tmp_path):
    module = load_module()

    class Boom(OSError):
        pass

    def fake_open(*args, **kwargs):
        raise Boom("disk full")

    monkeypatch.setattr(module, "open", fake_open, raising=False)

    with pytest.raises(module.ConfigError, match="Failed to write output file"):
        module.append_jsonl(str(tmp_path / "out.jsonl"), {"id": "S1"})


def test_validate_record_requires_solver_prompt():
    module = load_module()
    with pytest.raises(module.ConfigError):
        module.validate_record(
            {
                "id": "S1",
                "problem_statement": "A",
                "function_signature": "def solve():",
            }
        )


def test_process_records_uses_solver_prompt_from_input(tmp_path, monkeypatch):
    module = load_module()
    monkeypatch.setenv("SOLVER_API_KEY", "solver-test-key")
    monkeypatch.setenv("JUDGE_API_KEY", "judge-test-key")

    input_path = tmp_path / "input.jsonl"
    kept_path = tmp_path / "kept.jsonl"
    dropped_path = tmp_path / "dropped.jsonl"
    audit_path = tmp_path / "audit.jsonl"

    write_jsonl(
        input_path,
        [
            {
                "id": "S1",
                "problem_statement": "A",
                "function_signature": "def solve():",
                "solver_prompt": "THIS IS THE REAL SOLVER INPUT",
            }
        ],
    )

    seen = {}

    class FakeClient:
        def solve(self, record, prompt):
            seen["prompt"] = prompt
            return "def solve():\n    pass\n"

        def judge(self, record, solver_code, prompt):
            return {"correct": False, "confidence": 0.5, "reason": "Wrong."}

    cfg = {
        "input_jsonl_path": str(input_path),
        "kept_output_jsonl_path": str(kept_path),
        "dropped_output_jsonl_path": str(dropped_path),
        "audit_log_jsonl_path": str(audit_path),
        **gateway_cfg(),
    }

    module.process_records(cfg, client=FakeClient())
    assert seen["prompt"] == "THIS IS THE REAL SOLVER INPUT"
