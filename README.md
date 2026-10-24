# ai-delegates

Let **Claude Code be the lead** and hand off context-heavy, read-only reconnaissance to other AI CLIs as helpers: searching across many files, tracing call paths, reading large logs, getting oriented in unfamiliar code. A helper returns `file:line` locations plus a short summary, and Claude then opens those spots itself, confirms them, makes the changes and runs the tests.

```
You ──▶ Claude Code (lead: reasoning, edits, tests, git)
            │  read-only task
            ▼
        delegate.py ──▶ agy (Gemini) / codex (GPT) / hermes / … (pluggable backends)
            ▲
            └── report: key locations (file:line), core logic, suggested changes, open questions
```

## Backends

| Backend | Status | How it reads code | Read-only guarantee |
|---|---|---|---|
| `agy`: Antigravity CLI (Google Gemini) | ✅ Tested | Reads and searches files itself | Headless mode auto-denies file writes and shell commands |
| `codex`: OpenAI Codex CLI (GPT) | Template, disabled by default | Reads and searches files itself | `--sandbox read-only` |
| `hermes`: Hermes Agent | Template, disabled by default | The runner packs file contents into the prompt (`packed`) | Only a harmless toolset is enabled and tool calls are blocked |

## Installation

**1. Install the plugin.** In Claude Code, run:

```
/plugin marketplace add code09128/ai-delegates
/plugin install ai-delegates@code09128
```

Restart Claude Code afterwards. To update later, run `/plugin update ai-delegates`.

**2. Install at least one helper CLI.** For agy:

- Windows (PowerShell):

  ```
  irm https://antigravity.google/cli/install.ps1 | iex
  ```

- macOS / Linux:

  ```
  curl -fsSL https://antigravity.google/cli/install.sh | bash
  ```

Then run `agy` once and sign in with your Google account in the browser.

**3. Check the setup.** From any project folder, run:

```
python <plugin path>/skills/delegate/delegate.py list
```

Requires Python 3.10 or later. Only the standard library is used.

**4. Optional: skip the approval prompt.** Each delegation runs one `python …/delegate.py` command. To stop Claude Code from asking every time, add these rules to `permissions.allow` in `~/.claude/settings.json`:

```json
"Bash(python *ai-delegates*delegate.py *)",
"PowerShell(python *ai-delegates*delegate.py *)"
```

## Usage

- **Automatic**: when a task calls for broad exploration, Claude decides on its own whether to delegate. The rules are in `skills/delegate/SKILL.md`.
- **Manual**: invoke the skill directly (or just ask Claude to "delegate this to agy"):

  ```
  /ai-delegates:delegate agy find every caller of sendToMod2 and which state it changes
  ```

- **Direct**:

  ```
  python delegate.py ask auto "question" path1 path2 --timeout 15m --model model-name
  ```

### Run history

Every `ask` appends one line to `~/.ai-delegates/runs.jsonl`: time, project folder, backend, model, question, success or failure, duration, tokens, and any denied actions. To see the latest runs:

```
python delegate.py log -n 20
```

Or just ask Claude which tasks it delegated.

To keep a project's code from being sent to outside services, add the line `禁止使用外部 AI` ("do not use external AI") to that project's `CLAUDE.md`.

## Adding or adjusting a backend

**No code changes needed.** Add a JSON file to `skills/delegate/backends/`:

```json
{
  "name": "my-ai",
  "label": "Display name",
  "priority": 5,
  "enabled": true,
  "context": "agent",
  "good_at": "What it is good at (Claude uses this to pick a backend)",
  "exe": ["my-ai", "%LOCALAPPDATA%/my-ai/bin/my-ai.exe"],
  "args": ["run", "--print", "{prompt}", "--read-only", ["--model", "{model}"]],
  "output": {"type": "text"},
  "readonly": "How it guarantees it will not modify files",
  "install": "Install command",
  "login": "How to sign in"
}
```

**Placeholders**

| Placeholder | Meaning |
|---|---|
| `{prompt}` | The full prompt text |
| `{prompt_file}` | Temporary file containing the prompt |
| `{out_file}` | File the CLI writes its final answer to |
| `{usage_file}` | File the CLI writes its usage report to |
| `{timeout}` | Timeout, e.g. `10m` |
| `{timeout_seconds}` | Timeout in seconds |
| `{model}` | Model name |
| `{cwd}` | Current project folder |

A group of arguments wrapped in an inner array (for example `["--model", "{model}"]`) is dropped as a whole when any of its placeholders has no value.

**Other fields**

| Field | Values |
|---|---|
| `output.type` | `json`: read fields from JSON output; `text`: use stdout as is; `file`: read `{out_file}` |
| `context` | `agent`: the backend reads files itself and must have a read-only guarantee; `packed`: the runner reads the files and sends them, for backends that cannot be restricted to read-only |
| `stdin` | Set to `"prompt"` to send the prompt on standard input |

**Personal overrides** go in `~/.ai-delegates/backends/<name>.json`. Include only the fields you want to change; plugin updates will not overwrite them. For example, to enable codex:

```json
{ "enabled": true }
```

## Security

- **Read-only**: every backend must state how it guarantees it will not modify files. The runner never adds flags such as `--dangerously-skip-permissions` or `--yolo`.
- **Secrets excluded**: `packed` mode never sends any of the following:
  - `.env*` (except `.env.example`)
  - Key and credential files: `*.pem`, `*.key`, `credentials*`, `token*.json`
  - The folders `data/`, `logs/`, `secrets/`, `.git/`, `node_modules/`
  - Database and log files

  In `agent` mode the prompt instructs the helper not to read these files.
- **A helper's report is a lead, not a fact**: Claude must open the listed lines and confirm them before relying on them.

## Language

The skill instructions and the helper's reports are in Traditional Chinese. To change the report language, edit `RULES` in `skills/delegate/delegate.py`.

## License

MIT
