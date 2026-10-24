"""
ai-delegates 共用執行器：把只讀的偵察任務派給外部 AI CLI（agy、Hermes、Codex…），回傳「檔案:行號＋摘要」。

    python delegate.py list
    python delegate.py ask <後端|auto> "問題" [路徑 ...] [--timeout 10m] [--model 名稱]

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
from pathlib import Path

HERE = Path(__file__).resolve().parent
USER_DIR = Path.home() / ".ai-delegates" / "backends"

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

def build_prompt(b: dict, question: str, targets) -> tuple:
    mode = b.get("context", "agent")
    head = RULES.format(tool_rule=TOOL_RULE[mode])
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


def run(b: dict, question: str, targets, timeout: str, model):
    exe = find_exe(b)
    if not exe:
        raise SystemExit(f"找不到 {b['name']} 的執行檔。安裝／登入方式：{b.get('install', '見 README')}")
    prompt, _ = build_prompt(b, question, targets)
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
    info, denied, text, ok = [], [], "", r.returncode == 0
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
            tok = (data.get("usage") or {}).get("total_tokens")
            if tok:
                info.append(f"tokens {tok:,}")
            denied = [d.get("display_name") or d.get("action") for d in data.get(o.get("denied", "denied_actions")) or []]
    elif o["type"] == "file":
        text = out_file.read_text(encoding="utf-8", errors="replace") if out_file.exists() else ""
    else:
        text = r.stdout
    if usage_file.exists():
        try:
            u = json.loads(usage_file.read_text(encoding="utf-8"))
            info.append(f"model {u.get('model')}")
            if u.get("input_tokens") is not None:
                info.append(f"tokens {(u.get('input_tokens') or 0) + (u.get('output_tokens') or 0):,}")
            if u.get("failed"):
                ok = False
                info.append(f"失敗：{u.get('failure')}")
        except ValueError:
            pass
    text = text.replace("file:///" + Path.cwd().as_posix() + "/", "")
    return {"ok": ok and bool(text.strip()), "text": text.strip(), "info": info, "denied": denied,
            "stderr": r.stderr.strip(), "code": r.returncode}


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
    a = sub.add_parser("ask", help="派一個任務")
    a.add_argument("backend", help="後端名稱，或 auto")
    a.add_argument("question")
    a.add_argument("targets", nargs="*", help="相對路徑（檔案或資料夾），預設 .")
    a.add_argument("--timeout", default="10m")
    a.add_argument("--model", default=None)
    args = ap.parse_args()

    backends = load_backends()
    if args.cmd == "list":
        cmd_list(backends)
        return 0
    if args.backend == "auto":
        b = pick_auto(backends)
    elif args.backend in backends:
        b = backends[args.backend]
        if not b.get("enabled", True):
            raise SystemExit(f"{b['name']} 已停用（{b.get('disabled_reason', '見設定檔')}）")
    else:
        raise SystemExit(f"沒有這個後端：{args.backend}（可用：{', '.join(backends)}）")

    res = run(b, args.question, args.targets, args.timeout, args.model)
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
