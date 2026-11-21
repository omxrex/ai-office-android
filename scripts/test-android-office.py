#!/usr/bin/env python3
"""End-to-end smoke test for the Android/Termux AI Office integration.

Requires a running office started with scripts/start-android.sh.
Exits non-zero if any *real* backend function fails.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ.get("VO_TEST_OFFICE_URL", "http://127.0.0.1:8090")
SPECIALISTS = [
    "opencode-ceo", "opencode-programmer", "opencode-researcher",
    "opencode-designer", "opencode-writer", "opencode-analyst",
]
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))
    print(("PASS " if ok else "FAIL ") + name + ((" :: " + detail) if detail else ""))


def call(method: str, path: str, body=None, timeout: int = 180):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read()
            return response.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            payload = json.loads(raw) if raw else {}
        except ValueError:
            payload = {"error": raw.decode("utf-8", "replace")[:200]}
        return exc.code, payload


def main() -> int:
    try:
        status, health = call("GET", "/health", timeout=10)
        check("server health", status == 200 and health.get("ok") and health.get("status") == "running",
              str(health.get("version", "")))

        status, page = None, None
        req = urllib.request.Request(BASE + "/mobile", headers={"User-Agent": "Mozilla/5.0 (Linux; Android 14) Mobile"})
        with urllib.request.urlopen(req, timeout=10) as response:
            html = response.read().decode()
            status, page = response.status, html
        check("mobile page served", status == 200 and "AI Office" in page and 'id="bottomNav"' in page)
        for asset in ("mobile.css", "mobile.js"):
            with urllib.request.urlopen(BASE + "/" + asset, timeout=10) as response:
                check("asset " + asset, response.status == 200 and len(response.read()) > 1000)

        _, provider = call("POST", "/api/provider-test", {"providerKind": "opencode"}, timeout=120)
        check("real OpenCode provider connected", bool(provider.get("ok")) and "v2" in str(provider.get("version", "")),
              str(provider.get("version", "")))

        _, agents = call("GET", "/api/agents", timeout=20)
        check("office roster responds", isinstance(agents.get("agents"), list),
              str([a.get("id") for a in agents.get("agents", [])]))

        for index, agent in enumerate(SPECIALISTS):
            token = f"SMOKE-{index}-7F3A"
            _, reply = call("POST", "/api/provider-chat", {
                "agentId": agent,
                "message": f"Reply with exactly: {token}",
                "fromType": "human",
                "fromDisplayName": "Smoke test",
            }, timeout=180)
            check("chat " + agent, bool(reply.get("ok")) and token in str(reply.get("reply", "")),
                  repr(reply.get("reply", ""))[:80])

        _, history = call("GET", "/api/provider-history?agentId=opencode-programmer", timeout=20)
        texts = [str(m.get("text", "")) for m in history.get("messages", [])]
        check("chat history persisted", any("SMOKE-1-7F3A" in t for t in texts), f"{len(texts)} messages")

        _, unknown = call("POST", "/api/provider-chat", {"agentId": "does-not-exist", "message": "hi"}, timeout=20)
        check("unknown agent error handled", unknown.get("ok") is False, str(unknown.get("error", ""))[:80])

        _, created = call("POST", "/api/projects", {
            "title": "Android smoke " + str(int(time.time())),
            "description": "Automated workflow verification",
            "createdBy": "smoke-test",
        }, timeout=20)
        project = created.get("project") or {}
        pid = project.get("id", "")
        check("project created", bool(pid))

        if pid:
            _, task = call("POST", f"/api/projects/{pid}/tasks", {
                "title": "Verify workflow",
                "description": "Reply with exactly: WORKFLOW-SMOKE-OK. Do not modify any files.",
                "assignee": "opencode-ceo", "priority": "low", "by": "smoke-test",
            }, timeout=20)
            check("task created", bool((task.get("task") or {}).get("id")))

            _, start = call("POST", f"/api/projects/{pid}/workflow/start", {"autoMode": False}, timeout=20)
            check("workflow started", bool(start.get("ok")), str(start.get("status", "")))

            detail, phase = {}, ""
            for _ in range(30):
                time.sleep(2)
                _, status_data = call("GET", f"/api/projects/{pid}/workflow/status", timeout=20)
                phase = str(status_data.get("phase", ""))
                if not status_data.get("active"):
                    break
            _, detail = call("GET", f"/api/projects/{pid}", timeout=20)
            project_data = detail.get("project") or {}
            comments = " ".join(str(c.get("text", "")) for t in project_data.get("tasks", [])
                                for c in t.get("comments", []))
            check("workflow produced real AI output", "WORKFLOW-SMOKE-OK" in comments, phase)
            done = [t for t in project_data.get("tasks", [])
                    if any(c.get("title") == "Done" for c in project_data.get("columns", []) if c.get("id") == t.get("columnId"))]
            check("workflow reached Done", bool(done), phase)

    except Exception as exc:
        check("test run completed without transport error", False, repr(exc))

    failed = [name for name, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        print("Failed: " + ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
