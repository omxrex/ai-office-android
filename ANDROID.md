# AI Office on Android / Termux

This is the **original My Virtual Office 0.12.0 repository** (`eliautobot/my-virtual-office`, HEAD `6721f84`), modified in place to run natively on Android without Docker or root. The Python server, its project/workflow engine, the Node provider layer and the original desktop UI are all preserved.

## What was added

| File | Purpose |
|---|---|
| `scripts/start-android.sh` | Starts the real OpenCode server and the original office server. Uses absolute `VO_STATUS_DIR`, a 0600 password file, and the glibc loader for the upstream OpenCode binary. |
| `scripts/setup_office_agents.py` | Creates six ordinary OpenCode agent definitions (`ceo`, `programmer`, `researcher`, `designer`, `writer`, `analyst`) with real prompts and permissions. The CEO is a primary agent allowed to launch the others as native OpenCode subagents. |
| `scripts/opencode-server-bridge.py` | Maps the app's existing OpenCode **CLI contract** to OpenCode's **documented HTTP API** (`/api/session`, `/api/session/{id}/prompt`, `/api/session/{id}/message`, `/api/session/{id}/interrupt`, …). It executes real model turns on the running `opencode serve` instance; it does not emulate OpenCode or invent an API. |
| `scripts/opencode-bridge` | Thin executable entry point used as `VO_OPENCODE_BIN`. |
| `scripts/opencode` | Launches the real glibc-linked OpenCode CLI through Termux's loader (kept for direct CLI use). Its self-spawning subcommands fail on Termux, which is why the server bridge exists. |
| `scripts/test-android-office.py` | End-to-end smoke test of the real backend and mobile entry point. |
| `app/mobile.html`, `app/mobile.css`, `app/mobile.js` | Additive portrait-first shell with the requested Office / Chat / Tasks / Agents / Settings navigation. It calls the original server's real APIs; no static or simulated content. |
| `app/server.py` (small edits) | Serves `/mobile` and auto-selects it for mobile user agents on `/`. Added `OpenCode` to the A2A provider label map. Desktop `/index.html` is untouched. |
| `app/provider-layer/server/providers/manifest.js` (small edit) | Standalone OpenCode manifest now declares `approvals: false`, matching the Python provider and office bridge (OpenCode has no pending/respond approval methods). |

## Run it

Prerequisites in Termux: Python 3.11+, `websockets==17.0.1`, Node 22.19+ (24 recommended) with `npm ci --omit=dev` run once in `app/provider-layer`, and the real OpenCode binary at `~/.opencode/bin/opencode` with Termux glibc packages installed.

```sh
cd /data/user/0/ai.antigm/files/home/projects/my-virtual-office
python3 -m pip install "websockets==17.0.1"
(cd app/provider-layer && npm ci --omit=dev --no-audit --no-fund)
sh scripts/start-android.sh
```

Open `http://127.0.0.1:8090/` on the phone. The mobile shell is served automatically for phone user agents; visit `http://127.0.0.1:8090/index.html` for the original desktop office. Set `VO_FORCE_DESKTOP_UI=1` or `VO_FORCE_MOBILE_UI=1` to override detection.

Runtime data (including chat history, projects, tasks, provider state and the 0600 OpenCode server password) lives in `$VO_STATUS_DIR`, which defaults to `$HOME/vo-data`. It is gitignored. No credentials are stored in frontend or source files.

## Architecture

```
Mobile shell (/mobile) ──HTTP──> original server.py (8090)
                                   ├─ /api/provider-chat, /api/provider-history
                                   │      └─ OpenCodeProvider ──CLI contract──>
                                   │           scripts/opencode-bridge
                                   │             └─ real OpenCode HTTP API (41777)
                                   │                   └─ model / tools / subagents
                                   ├─ /api/projects*, workflow start/status/stop
                                   │      └─ real pipeline: work → review → Done
                                   └─ /api/provider-interrupt → real run cancellation
```

The six role prompts live in `~/.config`-style OpenCode agent files under `$VO_STATUS_DIR/opencode-config/agents` and `$VO_STATUS_DIR/opencode-main/.opencode/agents`. Chat and task history are written by the original server into `VO_STATUS_DIR`.

## Approval checkpoints

Workflow runs are not silent: the Tasks tab requires an explicit **Approve & run** confirmation before starting a pipeline, with a warning that the assigned agent may create, edit or delete files. Sensitive provider/settings writes remain behind the original server's people-only route rules and passcode. The phone UI does not add or weaken any access control.

## Tested on this device (2026-11-21)

`python3 scripts/test-android-office.py` → **19/19 passed**:

- server health/version, mobile page and both assets
- real provider connection (`opencode v2.3.2`)
- real model replies from all six role agents (unique tokens echoed back)
- chat history persisted and reloaded
- unknown-agent errors returned correctly
- project + task creation, workflow start, real AI output in task comments, task reaching **Done**
- mobile page served to a phone user agent

Additional verified behaviour:

- Native delegation: the CEO used its OpenCode subagent tool and returned a real writer subagent output (no invented result).
- Cancellation: `POST /api/provider-interrupt` returned `{"ok": true, "interrupted": true}` for an active run and the chat correctly reported `Stopped`.
- Restart persistence: chat message count (2) and project count (2) were identical before and after a full server restart.
- Stale-reply race in the bridge (reused session returning the previous answer) was found, fixed and re-tested with two consecutive CEO turns.
- `node --check app/mobile.js` passes; no duplicate HTML ids; all assets return 200.

## Honest limitations

- **Visual browser automation was unavailable** in this environment (no connected browser/chromium), so the mobile layout was verified structurally and through its live API contract, not by a rendered screenshot. Touch gestures (drag/pinch) are implemented with touch events and pointer events but were not exercised by an automated gesture runner.
- The **OpenCode CLI subcommands** (`opencode run`, `opencode auth`, …) cannot reliably self-spawn under the Android glibc loader ("Standalone server exited before reporting readiness" / loader argv issues). The bridge deliberately uses the long-running `opencode serve` process and its documented HTTP API. This is real OpenCode, not a fake provider.
- The **unmodified demo license limits My Virtual Office's own roster to three agents**. This was not bypassed. The six employees are native OpenCode agents with their own prompts and permissions, and the CEO delegates to them inside OpenCode. If you hold a full license, the original app can register more of them in its roster.
- OpenCode's Python manifest declares `approvals: false` and has no approval request/respond protocol, so there are no provider-level approval prompts. The mobile workflow confirmation is an office-side checkpoint for the user.
- OpenCode subagents are executed by OpenCode itself; the office does not yet parse parent/child subagent IDs into its own task ledger. Delegation results appear in the CEO's real reply, not as separate VO task records.
- Mobile chat uses the synchronous `/api/provider-chat` endpoint. Live token streaming is available in the original desktop chat/provider layer, but the mobile shell shows a typing indicator and the final real reply instead of streaming partial text.
- The bridge polls the OpenCode API for new assistant messages; very slow models may show a longer "working" state than the desktop streaming UI.
