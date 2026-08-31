from orch.env import child_env, parent_had_api_key


def test_allowlist_strips_api_key_and_claude_vars() -> None:
    src = {
        "HOME": "/home/x",
        "PATH": "/usr/bin",
        "ANTHROPIC_API_KEY": "sk-secret",
        "ANTHROPIC_BASE_URL": "https://example.invalid",
        "CLAUDECODE": "1",
        "CLAUDE_CODE_SESSION_ID": "inherited",
        "CURSOR_API_KEY": "nope",
        "LANG": "C",
        "LC_ALL": "C",
        "TERM": "xterm-256color",
    }
    env, report = child_env(environ=src)
    assert "ANTHROPIC_API_KEY" not in env
    assert "CLAUDECODE" not in env
    assert "CLAUDE_CODE_SESSION_ID" not in env
    assert "CURSOR_API_KEY" not in env
    assert env["TERM"] == "dumb"
    assert env["HOME"] == "/home/x"
    assert env["LC_ALL"] == "C"
    assert "ANTHROPIC_API_KEY" in report.stripped
    assert parent_had_api_key(src) is True


def test_orch_keys_pass() -> None:
    env, _ = child_env(
        extra={"ORCH_SESSION_DIR": "/tmp/s", "ORCH_NODE_ID": "scout"},
        environ={"PATH": "/bin"},
    )
    assert env["ORCH_SESSION_DIR"] == "/tmp/s"
    assert env["ORCH_NODE_ID"] == "scout"
