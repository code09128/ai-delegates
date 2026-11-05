"""
ai-delegates 共用執行器：把只讀的偵察任務派給外部 AI CLI（agy、Hermes、Codex…），回傳「檔案:行號＋摘要」。

    python delegate.py list
    python delegate.py ask <角色|後端|auto> "問題" [路徑 ...] [--timeout 10m] [--model 名稱]
    python delegate.py plan "任務" [路徑 ...]          # 請主控角色（lead）唯讀規劃
    python delegate.py setup | show | set <角色> <後端> [--model 名稱] | reset [角色] | route <角色> | models <後端>
    python delegate.py log [-n 20]

- 角色（lead 主控、search、log、explore、review）各自選後端與模型：~/.ai-delegates/config.json，
  專案根目錄的 .ai-delegates.json 可覆蓋（例如某專案只准用 claude）

- 每次 ask 都會在 ~/.ai-delegates/runs.jsonl 追加一行紀錄（時間、專案、後端、問題、結果、耗時、token）
- 後端定義在 backends/*.json；使用者覆寫放在 ~/.ai-delegates/backends/*.json（同名欄位覆蓋，外掛更新不會蓋掉）
- context="agent"：後端自己讀檔（必須有只讀保護，例如 agy headless 自動拒絕寫檔與指令）
- context="packed"：後端不給任何檔案／指令工具，由這支程式讀好檔案（排除機密）放進問題
- 只用 Python 標準函式庫
"""

import argparse
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
USER_DIR = Path.home() / ".ai-delegates" / "backends"
RUN_LOG = Path.home() / ".ai-delegates" / "runs.jsonl"
USER_CFG = Path.home() / ".ai-delegates" / "config.json"
PROJECT_CFG = ".ai-delegates.json"

# 角色 → 說明。lead 是主控（理解需求、規劃、判斷）；其他是只讀副手的任務類型
ROLES = {
    "lead": "主控：理解需求、規劃步驟、判斷",
    "search": "跨檔案搜尋、追呼叫路徑",
    "log": "大型 log／JSON／資料檔",
    "explore": "導讀陌生或第三方程式碼",
    "review": "改完後交叉檢查",
}
# 沒設定時：主控是 claude（在 Claude Code 裡就是它自己），副手依 priority 自動挑
DEFAULT_ROUTES = {"lead": {"backend": "claude", "model": None}, **{r: {"backend": "auto", "model": None} for r in ROLES if r != "lead"}}

EXCLUDE_DIRS = {".git", "node_modules", "dist", "build", "data", "logs", "secrets", "__pycache__", ".venv", "venv",
                ".idea", ".vscode", ".claude", ".next", "coverage", ".mypy_cache", ".pytest_cache"}
EXCLUDE_FILES = [".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx", "id_rsa*", "id_ed25519*", "credentials*",
                 "*secret*", "token*.json", "*.sqlite", "*.db", "*.log", "*.lock", "package-lock.json"]
ALLOW_FILES = [".env.example", ".env.sample"]
TEXT_EXT = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".json", ".md", ".txt", ".html", ".css", ".scss",
            ".yml", ".yaml", ".toml", ".ini", ".cfg", ".bat", ".cmd", ".ps1", ".sh", ".sql", ".go", ".rs", ".java",
            ".kt", ".c", ".h", ".cpp", ".hpp", ".cs", ".rb", ".php", ".swift", ".vue", ".svelte", ".xml", ".csv"}

RULES = """你是主控 Agent（Claude Code）的偵察副手，只負責讀取與分析，回答一律用繁體中文。
嚴格規則：
1. 不得建立、修改、刪除任何檔案，也不要執行任何終端機指令（沒有權限，會被拒絕而中斷任務）。{tool_rule}
2. 不得讀取或引用機密檔案（.env、金鑰、憑證、token、data/、logs/、secrets/）。
3. 只回報實際讀到的內容；找不到就直接說找不到，不要猜。
4. 回報格式（精簡，總長盡量在 60 行內）：
   ## 關鍵位置
   - `相對路徑:起始行-結束行` — 這段在做什麼
   ## 核心邏輯摘要
   - 3 到 5 點
   ## 修改建議方向
   - 1 到 3 點（只寫方向，不要貼整段程式碼）
   ## 不確定之處
   - 沒有就寫「無」
"""
PLAN_RULES = """你是主控 Agent，負責理解需求並規劃；實際修改由執行端（另一個 AI）照你的計畫做並驗證。回答一律用繁體中文。
嚴格規則：
1. 不得建立、修改、刪除任何檔案，也不要執行任何終端機指令（沒有權限，會被拒絕而中斷任務）。{tool_rule}
2. 不得讀取或引用機密檔案（.env、金鑰、憑證、token、data/、logs/、secrets/）。
3. 計畫要根據實際讀到的程式；沒讀到的不要假設。
4. 回報格式（精簡，總長盡量在 80 行內）：
   ## 需求理解
   - 1 到 3 點；有歧義就列出來
   ## 要改的位置
   - `相對路徑:起始行-結束行` — 要改什麼、為什麼
   ## 步驟
   1. 依序寫，每步附「怎麼驗證」
   ## 風險與注意
   - 會影響到的其他地方、相容性
   ## 需要使用者決定的事
   - 沒有就寫「無」
"""
TOOL_RULE = {
    "agent": "\n   只使用內建的列出資料夾、讀取檔案、搜尋檔案內容等工具。",
    "packed": "\n   你沒有任何工具；只能根據下方提供的檔案內容回答（每行開頭是行號）。",
}


# ---------- 後端設定 ----------

def load_backends() -> dict:
    out = {}
    for p in sorted((HERE / "backends").glob("*.json")):
        b = json.loads(p.read_text(encoding="utf-8"))
        out[b["name"]] = b
    if USER_DIR.is_dir():
        for p in sorted(USER_DIR.glob("*.json")):
            b = json.loads(p.read_text(encoding="utf-8"))
            name = b.get("name") or p.stem
            out[name] = {**out.get(name, {}), **b, "name": name, "_override": str(p)}
    return out


def find_exe(b: dict):
    for cand in b.get("exe", []):
        cand = os.path.expandvars(os.path.expanduser(cand))
        hit = shutil.which(cand) if not os.path.isabs(cand) else (cand if Path(cand).exists() else None)
        if hit:
            return hit
    return None


def parse_timeout(s: str) -> int:
    m = re.fullmatch(r"(\d+)\s*([smh]?)", s.strip().lower())
    if not m:
        raise SystemExit(f"--timeout 格式錯誤：{s}（例如 90s、10m、1h）")
    return int(m.group(1)) * {"": 1, "s": 1, "m": 60, "h": 3600}[m.group(2)]


# ---------- 讀檔（packed 模式） ----------

def _excluded(path: Path) -> bool:
    name = path.name
    if any(fnmatch.fnmatch(name.lower(), a) for a in ALLOW_FILES):
        return False
    return any(fnmatch.fnmatch(name.lower(), pat) for pat in EXCLUDE_FILES)


def collect_files(targets, max_chars: int, max_file_chars: int):
    cwd = Path.cwd().resolve()
    files, skipped = [], []
    for t in targets or ["."]:
        p = (cwd / t).resolve()
        if p.is_file():
            cands = [p]
        elif p.is_dir():
            cands = []
            for root, dirs, names in os.walk(p):
                dirs[:] = sorted(d for d in dirs if d not in EXCLUDE_DIRS and not d.startswith("."))
                cands += [Path(root) / n for n in sorted(names)]
        else:
            skipped.append(f"{t}（不存在）")
            continue
        for f in cands:
            if any(part in EXCLUDE_DIRS for part in f.relative_to(cwd).parts[:-1]) or _excluded(f):
                continue
            if f.suffix.lower() not in TEXT_EXT and f.name.lower() not in ALLOW_FILES:
                continue
            if f not in files:
                files.append(f)

    chunks, total = [], 0
    for f in files:
        rel = f.relative_to(cwd).as_posix()
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            skipped.append(f"{rel}（讀取失敗）")
            continue
        if len(text) > max_file_chars:
            skipped.append(f"{rel}（{len(text):,} 字元，超過單檔上限）")
            continue
        if total + len(text) > max_chars:
            skipped.append(f"{rel}（超過總量上限）")
            continue
        numbered = "\n".join(f"{i:>5}| {line}" for i, line in enumerate(text.splitlines(), 1))
        chunks.append(f"===== 檔案：{rel} =====\n{numbered}")
        total += len(text)
    return chunks, skipped, total


# ---------- 執行 ----------

def build_prompt(b: dict, question: str, targets, rules: str = RULES) -> tuple:
    mode = b.get("context", "agent")
    head = rules.format(tool_rule=TOOL_RULE[mode])
    if mode == "agent":
        scope = "、".join(targets) if targets else "."
        return head + f"\n分析範圍：{scope}（相對於專案資料夾 {Path.cwd()}）\n\n任務：{question}\n", []
    chunks, skipped, total = collect_files(targets, b.get("max_context_chars", 400_000),
                                           b.get("max_file_chars", 120_000))
    if not chunks:
        raise SystemExit("沒有可送出的檔案（可能全被排除或超過上限）：" + "；".join(skipped))
    note = f"\n（已略過：{'；'.join(skipped[:20])}{' …' if len(skipped) > 20 else ''}）\n" if skipped else ""
    sys.stderr.write(f"[送出 {len(chunks)} 個檔案，約 {total:,} 字元]\n")
    return head + f"\n任務：{question}\n{note}\n" + "\n\n".join(chunks) + "\n", skipped


def fill(args, values: dict):
    """args 的元素可以是字串或字串陣列（一組）；任一佔位符沒有值時，整組略過，例如 ["--model", "{model}"]。"""
    out = []
    for a in args:
        group = a if isinstance(a, list) else [a]
        if any("{" + k + "}" in s and values.get(k) is None for s in group for k in values):
            continue
        out += [s.format(**{k: ("" if v is None else v) for k, v in values.items()}) for s in group]
    return out


def run(b: dict, question: str, targets, timeout: str, model, rules: str = RULES):
    exe = find_exe(b)
    if not exe:
        raise SystemExit(f"找不到 {b['name']} 的執行檔。安裝／登入方式：{b.get('install', '見 README')}")
    prompt, _ = build_prompt(b, question, targets, rules)
    secs = parse_timeout(timeout)
    tmp = Path(tempfile.mkdtemp(prefix="ai-delegates-"))
    prompt_file, out_file, usage_file = tmp / "prompt.txt", tmp / "last_message.txt", tmp / "usage.json"
    prompt_file.write_text(prompt, encoding="utf-8")
    values = {"prompt": prompt, "prompt_file": str(prompt_file), "out_file": str(out_file),
              "usage_file": str(usage_file), "timeout": timeout, "timeout_seconds": str(secs),
              "model": model or b.get("model"), "cwd": str(Path.cwd())}
    cmd = [exe] + fill(b["args"], values)
    stdin = prompt if b.get("stdin") == "prompt" else None
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", **b.get("env", {})}
    try:
        r = subprocess.run(cmd, input=stdin, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=secs + 60, env=env)
    except subprocess.TimeoutExpired:
        raise SystemExit(f"[{b['name']}] 超過 {timeout} 仍未完成，已中止")
    except OSError as e:
        raise SystemExit(f"無法執行 {exe}：{e}")
    try:
        return parse_output(b, r, out_file, usage_file)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def parse_output(b: dict, r, out_file: Path, usage_file: Path):
    o = b.get("output", {"type": "text"})
    info, denied, text, ok, tokens, model = [], [], "", r.returncode == 0, None, None
    if o["type"] == "json":
        try:
            data = json.loads(r.stdout)
        except ValueError:
            data = None
        if data is None:
            text, ok = "", False
        else:
            text = data.get(o.get("text", "response")) or ""
            ok = ok and data.get(o.get("status", "status"), o.get("ok", "SUCCESS")) == o.get("ok", "SUCCESS")
            if "duration_seconds" in data:
                info.append(f"{data['duration_seconds']:.0f} 秒")
            tokens = (data.get("usage") or {}).get("total_tokens")
            if tokens:
                info.append(f"tokens {tokens:,}")
            denied = [d.get("display_name") or d.get("action") for d in data.get(o.get("denied", "denied_actions")) or []]
    elif o["type"] == "file":
        text = out_file.read_text(encoding="utf-8", errors="replace") if out_file.exists() else ""
    else:
        text = r.stdout
    if usage_file.exists():
        try:
            u = json.loads(usage_file.read_text(encoding="utf-8"))
            model = u.get("model")
            info.append(f"model {model}")
            if u.get("input_tokens") is not None:
                tokens = (u.get("input_tokens") or 0) + (u.get("output_tokens") or 0)
                info.append(f"tokens {tokens:,}")
            if u.get("failed"):
                ok = False
                info.append(f"失敗：{u.get('failure')}")
        except ValueError:
            pass
    text = text.replace("file:///" + Path.cwd().as_posix() + "/", "")
    return {"ok": ok and bool(text.strip()), "text": text.strip(), "info": info, "denied": denied,
            "stderr": r.stderr.strip(), "code": r.returncode, "tokens": tokens, "model": model}


# ---------- 執行紀錄 ----------

def write_log(entry: dict) -> None:
    """紀錄失敗不影響派工結果。"""
    try:
        RUN_LOG.parent.mkdir(parents=True, exist_ok=True)
        with RUN_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as e:
        sys.stderr.write(f"[無法寫入執行紀錄 {RUN_LOG}：{e}]\n")


def cmd_log(n: int) -> None:
    if not RUN_LOG.exists():
        print(f"還沒有任何紀錄（{RUN_LOG}）")
        return
    lines = RUN_LOG.read_text(encoding="utf-8").splitlines()[-n:]
    print(f"最近 {len(lines)} 筆（完整紀錄：{RUN_LOG}）")
    for line in lines:
        try:
            e = json.loads(line)
        except ValueError:
            continue
        tok = f"，tokens {e['tokens']:,}" if e.get("tokens") else ""
        print(f"- {e.get('time')}｜{e.get('role') or '-'}｜{e.get('backend')}{'／' + e['model'] if e.get('model') else ''}｜"
              f"{'成功' if e.get('ok') else '失敗'}｜"
              f"{e.get('seconds')} 秒{tok}｜{Path(e.get('cwd', '')).name}")
        print(f"    問題：{e.get('question')}")
        if e.get("error"):
            print(f"    錯誤：{e['error']}")


# ---------- 角色設定 ----------

def _read_json(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    except ValueError as e:
        raise SystemExit(f"設定檔格式錯誤：{p}（{e}）")


def load_routes() -> tuple:
    """(角色 → {backend, model, source}, 專案設定檔路徑或 None)。預設 ← 使用者 ← 專案。"""
    routes = {r: {**v, "source": "預設"} for r, v in DEFAULT_ROUTES.items()}
    proj = Path.cwd() / PROJECT_CFG
    for p, src in ((USER_CFG, "使用者"), (proj, "專案")):
        for r, v in (_read_json(p).get("roles") or {}).items():
            if r in ROLES and isinstance(v, dict) and v.get("backend"):
                routes[r] = {"backend": v["backend"], "model": v.get("model"), "source": src}
    return routes, (proj if proj.is_file() else None)


def save_route(role: str, backend, model, project: bool) -> Path:
    p = Path.cwd() / PROJECT_CFG if project else USER_CFG
    cfg = _read_json(p)
    roles = cfg.setdefault("roles", {})
    if backend is None:
        roles.pop(role, None)
    else:
        roles[role] = {"backend": backend, **({"model": model} if model else {})}
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p


def resolve(role: str, backends: dict) -> tuple:
    """角色 → (後端設定, 模型)。設定成 auto 就依 priority 挑；設定的後端不能用時講清楚，不偷偷換別的。"""
    route = load_routes()[0][role]
    if route["backend"] == "auto":
        return pick_auto(backends), route["model"]
    b = backends.get(route["backend"])
    if not b:
        raise SystemExit(f"角色 {role} 設定的後端 {route['backend']} 不存在（{route['source']}設定）；執行 setup 或 set 重新選")
    if not b.get("enabled", True):
        raise SystemExit(f"角色 {role} 設定的後端 {b['name']} 已停用（{b.get('disabled_reason', '見設定檔')}）")
    return b, route["model"]


def inside_claude_code() -> bool:
    """在 Claude Code 的終端機裡執行（它會設 CLAUDECODE=1）：角色是 claude 時直接用它自己，不另外開一個 claude。"""
    return os.environ.get("CLAUDECODE") == "1"


def model_choices(b: dict) -> list:
    """後端可選的模型：設定檔的 models，或執行 models_cmd 即時列（例如 agy models）。拿不到就空的，讓人自己輸入。"""
    if b.get("models"):
        return list(b["models"])
    exe = find_exe(b)
    if not (exe and b.get("models_cmd")):
        return []
    try:
        r = subprocess.run([exe, *b["models_cmd"]], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [ln.split()[0] for ln in r.stdout.splitlines() if ln.strip() and not ln.endswith("...") and " " not in ln.split("\t")[0]]


def cmd_show():
    routes, proj = load_routes()
    print(f"角色設定（使用者：{USER_CFG}{'；專案：' + str(proj) if proj else ''}）")
    for r, desc in ROLES.items():
        v = routes[r]
        print(f"- {r:8}{v['backend']}{'／' + v['model'] if v.get('model') else ''}（{v['source']}）— {desc}")
    if inside_claude_code():
        print("  目前在 Claude Code 裡：設定成 claude 的角色由它自己（內建子代理）處理")


def cmd_route(role: str, backends: dict):
    """給主控 AI 看的：這個角色現在該交給誰。self=true 表示就是正在執行的主控自己。"""
    route = load_routes()[0][role]
    self_ = route["backend"] == "claude" and inside_claude_code()
    out = {"role": role, "backend": route["backend"], "model": route["model"], "self": self_, "source": route["source"]}
    if not self_:
        b, model = resolve(role, backends)
        out.update(backend=b["name"], model=model or b.get("model"))
    print(json.dumps(out, ensure_ascii=False))


def _choose(prompt: str, options: list, default: int) -> int:
    for i, o in enumerate(options):
        print(f"  {i}) {o}")
    while True:
        a = input(f"{prompt} [{default}]：").strip()
        if not a:
            return default
        if a.isdigit() and int(a) < len(options):
            return int(a)
        print("  請輸入上面的數字")


def cmd_setup(backends: dict, project: bool):
    """在終端機用選單設定每個角色。只列已安裝、已啟用的後端。"""
    if not sys.stdin.isatty():
        raise SystemExit("setup 需要在終端機互動；非互動環境請用：set <角色> <後端> [--model 名稱]")
    usable = [n for n, b in backends.items() if b.get("enabled", True) and find_exe(b)]
    routes, _ = load_routes()
    print(f"設定會寫到：{Path.cwd() / PROJECT_CFG if project else USER_CFG}（直接按 Enter 保留目前的）\n")
    for role, desc in ROLES.items():
        cur = routes[role]
        print(f"■ {role} — {desc}（目前：{cur['backend']}{'／' + cur['model'] if cur.get('model') else ''}）")
        opts = ["保留目前的", *(["auto（依 priority 自動挑）"] if role != "lead" else []), *usable]
        k = _choose("選後端", opts, 0)
        if k == 0:
            print()
            continue
        backend = "auto" if opts[k].startswith("auto") else opts[k]
        model = None
        if backend != "auto":
            ms = model_choices(backends[backend])
            mopts = ["後端預設", *ms, "自己輸入"]
            j = _choose(f"選 {backend} 的模型", mopts, 0)
            model = None if j == 0 else (input("模型名稱：").strip() or None) if j == len(mopts) - 1 else mopts[j]
        p = save_route(role, backend, model, project)
        print(f"  → {role} = {backend}{'／' + model if model else ''}（已寫入 {p}）\n")
    cmd_show()


# ---------- CLI ----------

def cmd_list(backends):
    for name, b in backends.items():
        exe = find_exe(b)
        state = "停用" if not b.get("enabled", True) else ("可用" if exe else "未安裝")
        extra = f"｜覆寫：{b['_override']}" if b.get("_override") else ""
        print(f"- {name}（{b.get('label', '')}）：{state}｜{b.get('context', 'agent')}｜{b.get('tested', '未測試')}{extra}")
        print(f"    擅長：{b.get('good_at', '')}")
        if not exe:
            print(f"    安裝：{b.get('install', '')}")


def pick_auto(backends):
    usable = [b for b in backends.values() if b.get("enabled", True) and find_exe(b)]
    usable.sort(key=lambda b: b.get("priority", 99))
    if not usable:
        raise SystemExit("沒有可用的後端，請先執行 list 看安裝方式")
    return usable[0]


def main() -> int:
    for s in (sys.stdout, sys.stderr):  # Windows 主控台預設 cp950
        s.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="派只讀偵察任務給外部 AI CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="列出後端與安裝狀態")
    a = sub.add_parser("ask", help="派一個只讀任務")
    a.add_argument("backend", help=f"角色（{'、'.join(r for r in ROLES if r != 'lead')}）、後端名稱，或 auto")
    a.add_argument("question")
    a.add_argument("targets", nargs="*", help="相對路徑（檔案或資料夾），預設 .")
    a.add_argument("--timeout", default="10m")
    a.add_argument("--model", default=None)
    pl = sub.add_parser("plan", help="請主控角色（lead）唯讀規劃；主控是正在執行的 Claude Code 時不需要")
    pl.add_argument("question")
    pl.add_argument("targets", nargs="*")
    pl.add_argument("--timeout", default="15m")
    pl.add_argument("--model", default=None)
    st = sub.add_parser("setup", help="在終端機用選單設定每個角色的後端與模型")
    st.add_argument("--project", action="store_true", help=f"寫到專案的 {PROJECT_CFG}（預設寫使用者設定）")
    sub.add_parser("show", help="顯示每個角色目前用誰")
    se = sub.add_parser("set", help="設定一個角色")
    se.add_argument("role", choices=list(ROLES))
    se.add_argument("backend", help="後端名稱，或 auto（lead 不能 auto）")
    se.add_argument("--model", default=None)
    se.add_argument("--project", action="store_true")
    rs = sub.add_parser("reset", help="角色回到預設（不給角色就全部）")
    rs.add_argument("role", nargs="?", choices=list(ROLES))
    rs.add_argument("--project", action="store_true")
    mo = sub.add_parser("models", help="列出後端可選的模型")
    mo.add_argument("backend")
    ro = sub.add_parser("route", help="（給主控 AI）這個角色現在交給誰，輸出 JSON")
    ro.add_argument("role", choices=list(ROLES))
    lg = sub.add_parser("log", help="顯示最近的派工紀錄")
    lg.add_argument("-n", type=int, default=20)
    args = ap.parse_args()

    if args.cmd == "log":
        cmd_log(args.n)
        return 0
    if args.cmd == "show":
        cmd_show()
        return 0
    if args.cmd == "reset":
        for r in [args.role] if args.role else list(ROLES):
            save_route(r, None, None, args.project)
        cmd_show()
        return 0
    backends = load_backends()
    if args.cmd == "list":
        cmd_list(backends)
        return 0
    if args.cmd == "setup":
        cmd_setup(backends, args.project)
        return 0
    if args.cmd == "models":
        if args.backend not in backends:
            raise SystemExit(f"沒有這個後端：{args.backend}（可用：{', '.join(backends)}）")
        print("\n".join(model_choices(backends[args.backend])) or "（列不出模型清單，可直接輸入名稱）")
        return 0
    if args.cmd == "route":
        cmd_route(args.role, backends)
        return 0
    if args.cmd == "set":
        if args.backend == "auto" and args.role == "lead":
            raise SystemExit("lead（主控）要指定後端，不能 auto")
        if args.backend != "auto":
            b = backends.get(args.backend)
            if not b:
                raise SystemExit(f"沒有這個後端：{args.backend}（可用：{', '.join(backends)}）")
            if not b.get("enabled", True):  # 設定當下就講,不要等到派工才失敗
                raise SystemExit(f"{b['name']} 已停用（{b.get('disabled_reason', '見設定檔')}）")
            if not find_exe(b):
                raise SystemExit(f"找不到 {b['name']} 的執行檔，先安裝：{b.get('install', '見 README')}")
        p = save_route(args.role, args.backend, args.model, args.project)
        print(f"{args.role} = {args.backend}{'／' + args.model if args.model else ''}（已寫入 {p}）")
        return 0

    role, rules = None, RULES
    if args.cmd == "plan":
        role, rules = "lead", PLAN_RULES
        route = load_routes()[0]["lead"]
        if route["backend"] == "claude" and inside_claude_code():
            raise SystemExit("主控（lead）設定為 claude，也就是正在執行的 Claude Code 本身，不需要 plan；直接自己規劃")
        b, cfg_model = resolve("lead", backends)
    elif args.backend in ROLES:
        role = args.backend
        b, cfg_model = resolve(role, backends)
        if b["name"] == "claude" and inside_claude_code():
            sys.stderr.write(f"[角色 {role} 設定為 claude，而目前就在 Claude Code 裡：建議改用內建子代理，不必另開 claude]\n")
    elif args.backend == "auto":
        b, cfg_model = pick_auto(backends), None
    elif args.backend in backends:
        b, cfg_model = backends[args.backend], None
        if not b.get("enabled", True):
            raise SystemExit(f"{b['name']} 已停用（{b.get('disabled_reason', '見設定檔')}）")
    else:
        raise SystemExit(f"沒有這個角色或後端：{args.backend}（角色：{', '.join(ROLES)}；後端：{', '.join(backends)}）")
    model = args.model or cfg_model  # 手動指定優先於角色設定

    entry = {"time": datetime.now().isoformat(timespec="seconds"), "cwd": str(Path.cwd()), "role": role,
             "backend": b["name"], "model": model or b.get("model"), "question": args.question[:500], "targets": args.targets}
    t0 = time.monotonic()
    try:
        res = run(b, args.question, args.targets, args.timeout, model, rules)
    except SystemExit as e:  # 找不到執行檔、逾時、沒有可送的檔案
        write_log({**entry, "ok": False, "seconds": round(time.monotonic() - t0), "error": str(e.code)[:500]})
        raise
    write_log({**entry, "model": res["model"] or entry["model"], "ok": res["ok"],
               "seconds": round(time.monotonic() - t0), "tokens": res["tokens"], "denied": res["denied"],
               "answer_chars": len(res["text"]),
               "error": None if res["ok"] else (res["stderr"][-300:] or f"結束代碼 {res['code']}")})
    print(res["text"] or "[副手沒有回傳內容]")
    sys.stderr.write(f"[{b['name']} {'成功' if res['ok'] else '失敗'}"
                     f"{'，' + '，'.join(res['info']) if res['info'] else ''}]\n")
    for d in res["denied"]:
        sys.stderr.write(f"[已拒絕副手的動作：{d}]\n")
    if not res["ok"]:
        sys.stderr.write((res["stderr"][-2000:] or "") + f"\n[結束代碼 {res['code']}]\n")
        if b.get("login"):
            sys.stderr.write(f"[若是登入或額度問題：{b['login']}]\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
