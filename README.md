# ai-delegates

Pick which AI does which job. The **lead** understands the request and plans; **helpers** do context-heavy, read-only reconnaissance: searching across many files, tracing call paths, reading large logs, getting oriented in unfamiliar code. A helper returns `file:line` locations plus a short summary, and the lead opens those spots, confirms them, makes the changes and runs the tests.

```
You ──▶ Claude Code ──▶ delegate.py route <role> ──▶ who handles it? (your settings)
            │                      ├── lead    : claude (itself) / gpt / gemini … (external leads plan read-only)
            │                      └── helpers : search / log / explore / review → agy / codex / hermes / claude …
            ▼
        edits, tests, git (always done by the CLI you are working in)
```

## Quick start

After [installing](#installation), pick who does what, then just work:

| Step | In Claude Code | In a terminal (from the project root) |
|---|---|---|
| 1. See what is available | `/ai-delegates:setup` | `python <plugin path>/skills/delegate/delegate.py list` |
| 2. Choose each role's AI and model | answer the menus | `python …/delegate.py setup` (add `--project` for this project only) |
| 3. Check | Claude shows the result | `python …/delegate.py show` |
| 4. Work | ask as usual; Claude delegates by role | `python …/delegate.py ask search "question" path…` |

`<plugin path>` is where Claude Code installed the plugin, under `~/.claude/plugins/`. To find it:

```
find ~/.claude/plugins -name delegate.py -path '*ai-delegates*'
```

### Animated demo

**[▶ Open the animated demo](https://code09128.github.io/ai-delegates/docs/demo.html)**. It shows how a request travels between the lead, `delegate.py` and each AI. To view it offline, open `docs/demo.html` in a browser.

1. Choose **where you work** (Claude Code, or another AI's CLI such as Codex), then the AI for `lead`, `search` and `review`.
2. Press **▶ 播放** (play). The left side animates each hand-off; the terminal on the right shows the matching command and reply.
3. Use **下一步** (next step) to go one step at a time and **重來** (start over) to reset; the panel below explains each step.
4. The bottom of the page lists real test runs and compares mode A and mode B.

The demo only replays recorded steps. It does not run any AI or touch your files.

## Roles

| Role | Job | Default |
|---|---|---|
| `lead` | Understand the request, plan, decide | `claude` |
| `search` | Search across files, trace call paths | `auto` |
| `log` | Large logs / JSON / data files | `auto` |
| `explore` | Get oriented in unfamiliar or third-party code | `auto` |
| `review` | Cross-check after changes | `auto` |

`auto` picks the first installed, enabled backend by `priority`. Each role can have its own backend **and model**.

### Choosing

- **In Claude Code**: run `/ai-delegates:setup`. Claude asks with menus and saves your choices.
- **In a terminal**:

  ```
  python delegate.py setup            # menu: each role → backend → model (only installed, enabled backends are listed)
  python delegate.py show             # current settings
  python delegate.py set search agy --model gemini-3.8-flash-medium
  python delegate.py set lead codex --model gpt-5
  python delegate.py reset [role]     # back to default
  python delegate.py models agy       # models a backend offers
  ```

Settings live in `~/.ai-delegates/config.json`. A project can override them with `.ai-delegates.json` in its root (add `--project` to `setup`/`set`/`reset`), for example to allow only `claude` in a sensitive project.

### When the lead is not Claude

There are two ways, depending on who should edit the files:

| | A: other AI plans inside Claude Code | B: other AI is the real lead in its own CLI |
|---|---|---|
| Where you work | Claude Code | Codex CLI or another AI's CLI |
| Planning | The `lead` you chose (e.g. GPT), read-only, via `delegate.py plan` | That AI |
| Edits, tests, git | Claude, following the plan and verifying each step | That AI |
| Helpers | agy / codex / hermes | agy / hermes / **claude** |
| Setup | `set lead codex` | Copy `templates/AGENTS.md` into the project's `AGENTS.md` |

In A, Claude stops and tells you when the plan does not match the code instead of following it blindly. In B, `claude` works as a read-only helper (`claude -p` with only Read, Grep and Glob).

## Backends

| Backend | Status | How it reads code | Read-only guarantee |
|---|---|---|---|
| `agy`: Antigravity CLI (Google Gemini) | ✅ Tested | Reads and searches files itself | Headless mode auto-denies file writes and shell commands |
| `codex`: OpenAI Codex CLI (GPT) | Template, disabled by default | Reads and searches files itself | `--sandbox read-only` |
| `hermes`: Hermes Agent | Template, disabled by default | The runner packs file contents into the prompt (`packed`) | Only a harmless toolset is enabled and tool calls are blocked |
| `claude`: Claude Code as a helper | For non-Claude leads | Reads and searches files itself | `--tools Read,Grep,Glob` (no write or shell tools), plan permission mode, `--restricted` |

When you are already in Claude Code, a role set to `claude` is handled by Claude's own subagents instead of starting another `claude`.

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
  /ai-delegates:delegate search find every caller of sendToMod2 and which state it changes
  ```

- **Direct**:

  ```
  python delegate.py ask search "question" path1 path2       # by role (uses your settings)
  python delegate.py ask agy "question" path1 --model name    # a specific backend; --model overrides the role setting
  python delegate.py plan "the task" path1 path2              # ask the lead to plan (read-only)
  ```

### Run history

Every `ask` and `plan` appends one line to `~/.ai-delegates/runs.jsonl`: time, project folder, role, backend, model, question, success or failure, duration, tokens, and any denied actions. To see the latest runs:

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
| `models` | Fixed list of model names shown by `setup` |
| `models_cmd` | Arguments that make the CLI print its models, e.g. `["models"]` for agy (first column is used) |

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
