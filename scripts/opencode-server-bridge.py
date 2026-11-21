#!/usr/bin/env python3
"""Transparent bridge: My Virtual Office's OpenCode CLI contract -> OpenCode HTTP API.

This does NOT emulate OpenCode or invent a provider. Every request is made to a
real `opencode serve` instance using OpenCode's documented /api routes, and all
model turns are executed by that server with your existing OpenCode auth.

It exists because the upstream OpenCode native binary is glibc-linked and its
self-spawning CLI subcommands cannot re-exec under Android/Termux's loader. The
long-running `opencode serve` process works, so the office talks to it over HTTP.

Supported subset (exactly what app/providers/opencode.py uses):
  opencode --version
  opencode run --format json [--agent A] [--session ID] [--model P/M] [--auto]
               [--file PATH ...] "prompt"
  opencode session list --format json --max-count N
  opencode session delete ID
  opencode export ID

Streaming output is newline-delimited JSON compatible with OpenCodeProvider:
  {"type":"text","text":"...","sessionID":"ses_..."}
  {"type":"tool","part":{"type":"tool","tool":"...","state":{...}},"sessionID":"..."}
"""
from __future__ import annotations

import base64
import json
import os
import signal
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

TIMEOUT = float(os.environ.get("VO_OPENCODE_BRIDGE_TIMEOUT", "900"))
POLL = 0.45


def fail(message: str, code: int = 1) -> "None":
    print(message, file=sys.stderr)
    raise SystemExit(code)


def server_config() -> tuple[str, str, str]:
    # The office intentionally strips VO_* secrets from provider CLI
    # environments. OPENCODE_CONFIG_DIR is allowlisted and is set by the
    # provider itself, so the connection file lives there with mode 0600.
    config = {}
    config_dir = os.environ.get("OPENCODE_CONFIG_DIR") or ""
    if config_dir:
        try:
            with open(os.path.join(config_dir, "opencode-server.json"), encoding="utf-8") as handle:
                config = json.load(handle)
        except (OSError, ValueError):
            config = {}
    url = (config.get("url") or os.environ.get("VO_OPENCODE_SERVER_URL")
           or os.environ.get("OPENCODE_SERVER_URL") or "http://127.0.0.1:41777")
    user = config.get("user") or os.environ.get("VO_OPENCODE_SERVER_USER") or "opencode"
    password = config.get("password") or os.environ.get("VO_OPENCODE_SERVER_PASSWORD") or ""
    if not password:
        status_dir = os.environ.get("VO_STATUS_DIR") or ""
        if status_dir:
            try:
                with open(os.path.join(status_dir, ".opencode-server-password"), encoding="utf-8") as handle:
                    password = handle.read().strip()
            except OSError:
                pass
    if not password:
        password = os.environ.get("OPENCODE_SERVER_PASSWORD") or ""
    return url.rstrip("/"), user, password


def api(method: str, path: str, body=None, timeout: int = 30):
    base, user, password = server_config()
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if user or password:
        token = base64.b64encode(f"{user}:{password}".encode()).decode()
        headers["Authorization"] = f"Basic {token}"
    req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read()
            if not raw or response.status == 204:
                return {}
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")[:1000]
        raise RuntimeError(f"OpenCode server {method} {path} -> HTTP {exc.code}: {raw}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"OpenCode server unreachable at {base}: {exc.reason}") from exc


def emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def cmd_version() -> None:
    try:
        info = api("GET", "/api/info", timeout=10).get("version") or api("GET", "/api/info", timeout=10)
    except RuntimeError:
        # A real server must be running; never pretend a connection works.
        fail("opencode server is not reachable: start it with scripts/start-android.sh")
    version = info if isinstance(info, str) else (info.get("data", {}).get("version") or info.get("version") or "unknown")
    print(f"opencode v{version}")


def parse_run(argv: list[str]) -> dict:
    opts = {"agent": "", "session": "", "model": "", "auto": False, "files": [], "prompt": ""}
    i = 0
    positional = []
    while i < len(argv):
        arg = argv[i]
        if arg in ("--format",):
            i += 2  # skip "json"
            continue
        if arg == "--agent" and i + 1 < len(argv):
            opts["agent"] = argv[i + 1]; i += 2; continue
        if arg == "--session" and i + 1 < len(argv):
            opts["session"] = argv[i + 1]; i += 2; continue
        if arg == "--model" and i + 1 < len(argv):
            opts["model"] = argv[i + 1]; i += 2; continue
        if arg == "--file" and i + 1 < len(argv):
            opts["files"].append(argv[i + 1]); i += 2; continue
        if arg in ("--auto", "-y"):
            opts["auto"] = True; i += 1; continue
        if arg == "--format=json":
            i += 1; continue
        if arg.startswith("-"):
            i += 1; continue  # ignore unsupported flags rather than misparse a prompt
        positional.append(arg); i += 1
    opts["prompt"] = "\n\n".join(p.strip() for p in positional if p.strip()).lstrip()
    return opts


def ensure_session(opts: dict, directory: str) -> str:
    sid = opts.get("session") or ""
    if sid:
        try:
            api("GET", f"/api/session/{urllib.parse.quote(sid)}", timeout=10)
            return sid
        except RuntimeError:
            pass  # create below, reusing the caller's id
    payload = {}
    if sid:
        payload["id"] = sid
    if opts.get("agent"):
        payload["agent"] = opts["agent"]
    if opts.get("model") and "/" in opts["model"]:
        provider, model = opts["model"].split("/", 1)
        payload["model"] = {"providerID": provider, "modelID": model}
    if opts.get("auto"):
        payload["permissions"] = [{"action": "*", "resource": "*", "effect": "allow"}]
    query = ""
    if directory:
        query = "?" + urllib.parse.urlencode({"location.directory": directory})
    try:
        result = api("POST", "/api/session" + query, payload, timeout=30)
    except RuntimeError:
        if "model" in payload:
            payload.pop("model")
            result = api("POST", "/api/session" + query, payload, timeout=30)
        else:
            raise
    return result["data"]["id"]


def build_prompt(opts: dict) -> str:
    chunks = []
    for path in opts.get("files") or []:
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                content = handle.read()
            chunks.append(f"Attached file: {os.path.basename(path)}\n{content[:60000]}")
        except OSError as exc:
            print(f"opencode bridge: cannot read attachment {path}: {exc}", file=sys.stderr)
    chunks.append(opts.get("prompt") or "")
    return "\n\n".join(chunk for chunk in chunks if chunk.strip())


def message_parts(sid: str):
    data = api("GET", f"/api/session/{urllib.parse.quote(sid)}/message", timeout=20)
    return data.get("data") or []


def session_outcome(sid: str) -> tuple[bool, str]:
    data = api("GET", f"/api/session/{urllib.parse.quote(sid)}", timeout=20).get("data") or {}
    outcome = data.get("outcome") or ""
    return bool(data.get("time", {}).get("idle")), outcome


def cmd_run(argv: list[str]) -> None:
    opts = parse_run(argv)
    if not opts["prompt"]:
        fail("opencode run: a prompt is required")
    directory = os.getcwd()
    sid = ensure_session(opts, directory)

    # Baseline prevents a reused session's previous answer from being returned
    # as if it belonged to this turn. Only messages created after this point
    # are emitted, and completion requires a NEW idle timestamp.
    try:
        baseline_messages = {str(m.get("id") or "") for m in message_parts(sid)}
        baseline_idle = int((api("GET", f"/api/session/{urllib.parse.quote(sid)}", timeout=20)
                             .get("data") or {}).get("time", {}).get("idle") or 0)
    except RuntimeError as exc:
        fail(str(exc))

    emitted: set[tuple] = set()
    text_lengths: dict[tuple, int] = {}
    interrupted = {"value": False}

    def on_signal(_signum, _frame):
        interrupted["value"] = True
        try:
            api("POST", f"/api/session/{urllib.parse.quote(sid)}/interrupt", {}, timeout=10)
        except RuntimeError:
            pass

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)

    try:
        api("POST", f"/api/session/{urllib.parse.quote(sid)}/prompt",
            {"text": build_prompt(opts)}, timeout=60)
    except RuntimeError as exc:
        fail(str(exc))

    deadline = time.monotonic() + TIMEOUT
    outcome = ""
    saw_new_message = False
    while time.monotonic() < deadline:
        if interrupted["value"]:
            emit({"type": "result", "subtype": "stopped", "sessionID": sid})
            return
        try:
            messages = message_parts(sid)
            session_data = api("GET", f"/api/session/{urllib.parse.quote(sid)}", timeout=20).get("data") or {}
            idle_time = int(session_data.get("time", {}).get("idle") or 0)
            outcome = session_data.get("outcome") or ""
            idle = idle_time > baseline_idle
        except RuntimeError as exc:
            fail(str(exc))
        for message in sorted(messages, key=lambda m: m.get("time", {}).get("created", 0)):
            if message.get("type") != "assistant":
                continue
            mid = str(message.get("id") or "")
            if mid in baseline_messages:
                continue
            saw_new_message = True
            for index, part in enumerate(message.get("content") or []):
                ptype = part.get("type")
                key = (mid, index, ptype)
                if ptype == "text":
                    text = part.get("text") or ""
                    previous = text_lengths.get(key, 0)
                    if len(text) > previous:
                        delta = text[previous:]
                        text_lengths[key] = len(text)
                        if delta.strip():
                            emit({"type": "text", "text": delta, "sessionID": sid})
                elif ptype == "tool" and key not in emitted:
                    emitted.add(key)
                    state = part.get("state") or {}
                    emit({"type": "tool", "sessionID": sid, "part": {
                        "type": "tool", "id": part.get("id") or part.get("callID") or f"tool-{index}",
                        "tool": part.get("tool") or "tool", "name": part.get("tool") or "tool",
                        "state": {"status": state.get("status") or "completed",
                                  "input": state.get("input") or {}, "output": state.get("output") or "",
                                  "error": state.get("error") or ""},
                    }})
        if idle and (saw_new_message or outcome == "failed"):
            if outcome == "failed":
                text = " ".join(
                    p.get("text", "") for m in messages if m.get("type") == "assistant"
                    and str(m.get("id") or "") not in baseline_messages
                    for p in (m.get("content") or []) if p.get("type") == "text"
                )
                print(f"opencode run failed: {text[-800:] or 'model run failed'}", file=sys.stderr)
                emit({"type": "result", "subtype": "error", "sessionID": sid})
                raise SystemExit(1)
            emit({"type": "result", "subtype": "success", "sessionID": sid})
            return
        time.sleep(POLL)
    print(f"opencode run timed out after {int(TIMEOUT)}s", file=sys.stderr)
    try:
        api("POST", f"/api/session/{urllib.parse.quote(sid)}/interrupt", {}, timeout=10)
    except RuntimeError:
        pass
    emit({"type": "result", "subtype": "timeout", "sessionID": sid})
    raise SystemExit(1)


def cmd_session(argv: list[str]) -> None:
    if not argv:
        fail("opencode session: expected list or delete")
    action = argv[0]
    if action == "list":
        limit = 40
        if "--max-count" in argv:
            try:
                limit = int(argv[argv.index("--max-count") + 1])
            except (ValueError, IndexError):
                pass
        data = api("GET", f"/api/session?limit={limit}&order=desc", timeout=20).get("data") or {}
        rows = data.get("data") if isinstance(data, dict) else data
        directory = os.path.realpath(os.getcwd())
        rows = [r for r in (rows or [])
                if not r.get("location", {}).get("directory")
                or os.path.realpath(r["location"]["directory"]) == directory]
        print(json.dumps(rows[:limit], ensure_ascii=False))
        return
    if action == "delete" and len(argv) > 1:
        api("DELETE", f"/api/session/{urllib.parse.quote(argv[1])}", timeout=20)
        print(json.dumps({"deleted": True}))
        return
    fail(f"opencode session: unsupported action {action}")


def cmd_export(argv: list[str]) -> None:
    if not argv:
        fail("opencode export: session id required")
    data = api("GET", f"/api/experimental/session/{urllib.parse.quote(argv[0])}/export", timeout=30)
    print(json.dumps(data.get("data", data), ensure_ascii=False))


def main() -> None:
    argv = sys.argv[1:]
    if not argv:
        fail("opencode bridge: no command")
    if argv[0] == "--version":
        cmd_version(); return
    if argv[0] == "run":
        cmd_run(argv[1:]); return
    if argv[0] == "session":
        cmd_session(argv[1:]); return
    if argv[0] == "export":
        cmd_export(argv[1:]); return
    if argv[0] in ("--help", "help"):
        print(__doc__); return
    fail(f"opencode bridge: unsupported command {argv[0]}")


if __name__ == "__main__":
    main()
