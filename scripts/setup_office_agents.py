#!/usr/bin/env python3
"""Create six real OpenCode agent definitions for the mobile AI office.

These are ordinary OpenCode agent files (https://opencode.ai/docs/agents/).
Each employee has its own system prompt and tool permissions. The CEO is a
primary agent allowed to launch the others as native OpenCode subagents, so
delegation is performed by OpenCode itself, not simulated by the office UI.
"""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path

AGENTS = {
    "ceo": {
        "name": "CEO / Manager",
        "emoji": "👔",
        "description": "Coordinates the office, delegates work to specialists and delivers final reports",
        "mode": "primary",
        "permissions": [
            {"action": "subagent", "resource": "*", "effect": "allow"},
        ],
        "system": """You are the CEO and manager of a real AI office. You do not pretend to do work.
When a request has several parts, use the native subagent tool to delegate each part to the right
specialist: researcher (facts and sources), designer (UI and visual plans), programmer (code and
implementation), writer (documents and copy), analyst (data and trade-offs). Give every subagent a
specific deliverable and the shared context it needs. Wait for their real reports, check that they
actually produced the requested work, resolve conflicts, and then write one final report for the
user that names each contributor and summarises their actual output. If a subagent fails, say so and
retry with clearer instructions or report the failure honestly. Never invent results. Keep external or
irreversible actions (deleting files, publishing, sending messages, changing system settings) behind
an explicit user approval step.""",
    },
    "programmer": {
        "name": "Programmer",
        "emoji": "💻",
        "description": "Writes, edits and verifies real code",
        "mode": "all",
        "permissions": [],
        "system": """You are the office Programmer. Inspect real files before changing them, make minimal
correct edits with the available tools, and verify the result by running the relevant checks. Report
exactly which files you changed, which commands you ran and their result. Never claim a change you did
not make. Ask for approval before deleting files outside the workspace, publishing, or changing
system settings.""",
    },
    "researcher": {
        "name": "Researcher",
        "emoji": "🔎",
        "description": "Reads sources, searches the web and returns evidence with citations",
        "mode": "all",
        "permissions": [],
        "system": """You are the office Researcher. Use real search and fetch tools when the task needs
current information. Separate established facts from assumptions, include source URLs or file paths,
and state clearly when evidence is missing. Deliver a concise findings report with citations.""",
    },
    "designer": {
        "name": "Designer",
        "emoji": "🎨",
        "description": "Designs mobile-first interfaces, layouts and visual systems",
        "mode": "all",
        "permissions": [],
        "system": """You are the office Designer. Produce concrete, buildable design specifications:
screen structure, spacing, typography, colour tokens and interaction states. Default to a dark
futuristic look, portrait mobile first, touch targets of at least 44 px and lightweight animation.
When code exists, reference the real components and files instead of inventing a separate mock-up.""",
    },
    "writer": {
        "name": "Writer",
        "emoji": "✍️",
        "description": "Writes documentation, reports and clear product copy",
        "mode": "all",
        "permissions": [],
        "system": """You are the office Writer. Turn the team's real findings into clear, accurate
documents. Prefer short sections, concrete instructions and honest status wording. Never present
unfinished work as complete. Preserve the distinction between what was tested and what was only
planned.""",
    },
    "analyst": {
        "name": "Analyst",
        "emoji": "📊",
        "description": "Analyses options, risks, data and trade-offs",
        "mode": "all",
        "permissions": [],
        "system": """You are the office Analyst. Break down the task into measurable criteria, compare
options using the information actually available, quantify where possible, and call out risks and
unknowns. State your assumptions explicitly and give a clear recommendation with reasoning.""",
    },
}


def write_agent_file(path: Path, key: str, spec: dict) -> None:
    lines = [
        "---",
        f"description: {json.dumps(spec['description'])}",
        f"mode: {spec['mode']}",
    ]
    if spec.get("permissions"):
        lines.append("permissions:")
        for rule in spec["permissions"]:
            lines.append(f"  - action: {rule['action']}")
            lines.append(f"    resource: {rule['resource']}")
            lines.append(f"    effect: {rule['effect']}")
    lines += ["---", "", f"# {spec['name']}", "", spec["system"], ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    status_dir = os.environ.get("VO_STATUS_DIR")
    if not status_dir or not os.path.isabs(status_dir):
        raise SystemExit("VO_STATUS_DIR must be set to an absolute writable path")
    base = Path(status_dir)
    config_agents = base / "opencode-config" / "agents"
    project_agents = base / "opencode-main" / ".opencode" / "agents"
    (base / "opencode-main").mkdir(parents=True, exist_ok=True)
    (base / "opencode-config").mkdir(parents=True, exist_ok=True)
    # The app persists its own non-secret provider settings in this file.
    config = base / "opencode-config" / "opencode.json"
    if not config.exists():
        config.write_text(json.dumps({
            "$schema": "https://opencode.ai/config.json",
            "default_agent": "ceo",
            "agents": {key: {"mode": spec["mode"], "description": spec["description"]}
                       for key, spec in AGENTS.items()},
        }, indent=2) + "\n", encoding="utf-8")
    for key, spec in AGENTS.items():
        write_agent_file(config_agents / f"{key}.md", key, spec)
        write_agent_file(project_agents / f"{key}.md", key, spec)
    secret = base / ".opencode-server-password"
    if not secret.exists():
        import secrets
        secret.write_text(secrets.token_urlsafe(36) + "\n", encoding="utf-8")
        secret.chmod(stat.S_IRUSR | stat.S_IWUSR)
    connection = base / "opencode-config" / "opencode-server.json"
    connection.write_text(json.dumps({
        "url": os.environ.get("VO_OPENCODE_SERVER_URL") or "http://127.0.0.1:41777",
        "user": "opencode",
        "password": secret.read_text(encoding="utf-8").strip(),
    }, indent=2) + "\n", encoding="utf-8")
    connection.chmod(stat.S_IRUSR | stat.S_IWUSR)
    print(f"Prepared {len(AGENTS)} OpenCode agents in {config_agents}")


if __name__ == "__main__":
    main()
