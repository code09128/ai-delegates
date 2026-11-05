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

After [installing](#installation), choose which AI handles each role. Pick **one** of these three ways; they all write the same settings file.

**1. In Claude Code (easiest).** Run:

```
/ai-delegates:setup
```

Claude shows a menu for each role (backend, then model) and saves your choices. You can also say it in one line, for example `/ai-delegates:setup search uses agy, review uses codex`.

**2. In a terminal, with a menu.** From the project root:

```
python <plugin path>/skills/delegate/delegate.py setup
```

It walks through the five roles. For each one, pick a backend, then a model; press Enter to keep the current choice. Only installed, enabled backends are listed, and agy's models are fetched live.

**3. One command per role**, handy for scripts or copying to teammates:

```
python …/delegate.py set lead claude
python …/delegate.py set search agy --model gemini-3.8-flash-medium
python …/delegate.py set review codex --model gpt-5
python …/delegate.py show          # check the result
```

Then just work: ask as usual, and the CLI delegates by role.

`<plugin path>` is where Claude Code installed the plugin, under `~/.claude/plugins/`. To find it and save typing, add an alias to your shell profile:

```
find ~/.claude/plugins -name delegate.py -path '*ai-delegates*'
alias delegate='python /that/path/delegate.py'      # then: delegate setup, delegate show …
```

### Where the settings live

The commands above write JSON files. You can also edit them by hand.

| File | Applies to | Written by |
|---|---|---|
| `~/.ai-delegates/config.json` | every project (your default) | `setup`, `set`, `reset` |
| `.ai-delegates.json` in a project root | that project only; overrides your default | the same commands with `--project` |

```json
{
  "roles": {
    "lead":   { "backend": "claude" },
    "search": { "backend": "agy", "model": "gemini-3.8-flash-medium" },
    "review": { "backend": "codex", "model": "gpt-5" }
  }
}
```

Roles you leave out keep their defaults (`lead` = `claude`, others = `auto`). Leaving out `model` uses the backend's default model. `set` refuses a disabled or missing backend right away. If you edit the file by hand instead, the same check happens when that role is used, and the error tells you to run `setup`.

### Animated demo

**[▶ Open the animated demo](https://code09128.github.io/ai-delegates/docs/demo.html#en)** ([中文版](https://code09128.github.io/ai-delegates/docs/demo.html#zh)). It shows how a request travels between the lead, `delegate.py` and each AI. To view it offline, open `docs/demo.html` in a browser.

1. Choose **where you work** (Claude Code, or another AI's CLI such as Codex), then the AI for `lead`, `search` and `review`.
2. Press **▶ Play**. The left side animates each hand-off; the terminal on the right shows the matching command and reply.
3. Use **Next** to go one step at a time and **Reset** to start over; the panel below explains each step.
4. Switch between **中文 / English** at the top right. The bottom of the page lists real test runs and compares mode A and mode B.

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

See [Quick start](#quick-start) for the three ways to choose. Other commands:

```
python delegate.py reset [role] [--project]   # back to default
python delegate.py models agy                 # models a backend offers
python delegate.py route search               # which backend and model a role resolves to
```

A project override is useful, for example, to allow only `claude` in a sensitive project.

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
| `claude`: Claude Code as a helper | ✅ Tested (for non-Claude leads) | Reads and searches files itself | `--tools Read,Grep,Glob` (no write or shell tools), plan permission mode, `--restricted` |

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
