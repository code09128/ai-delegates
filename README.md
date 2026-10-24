# ai-delegates

讓 **Claude Code 當主控**，把耗 context 的只讀偵察工作派給其他 AI CLI 當副手。偵察工作包括跨很多檔案找程式碼、追呼叫路徑、讀大型 log、讀陌生程式碼。副手回傳「`檔案:行號`＋摘要」，Claude 再自己打開關鍵段落確認、修改並測試。

```
你 ──▶ Claude Code（主控：推理、修改、測試、git）
            │  派只讀任務
            ▼
        delegate.py ──▶ agy（Gemini）／codex（GPT）／hermes／…（後端，可擴充）
            ▲
            └── 回傳：關鍵位置（檔案:行號）、核心邏輯、修改方向、不確定之處
```

## 後端

| 後端 | 狀態 | 讀檔方式 | 只讀保護 |
|---|---|---|---|
| `agy`：Antigravity CLI（Google Gemini） | ✅ 已測試 | 自己讀檔、搜尋 | headless 模式自動拒絕寫檔與執行指令 |
| `codex`：OpenAI Codex CLI（GPT） | 範本，預設停用 | 自己讀檔、搜尋 | `--sandbox read-only` |
| `hermes`：Hermes Agent | 範本，預設停用 | 由執行器把檔案內容放進問題（packed） | 只開無害工具組，並禁止工具呼叫 |

## 安裝

**1. 安裝外掛**：在 Claude Code 裡執行：

```
/plugin marketplace add code09128/ai-delegates
/plugin install ai-delegates@code09128
```

裝好後重開 Claude Code。之後要更新外掛時執行 `/plugin update ai-delegates`。

**2. 安裝至少一個副手 CLI**，以 agy 為例：

- Windows（PowerShell）：

  ```
  irm https://antigravity.google/cli/install.ps1 | iex
  ```

- macOS／Linux：

  ```
  curl -fsSL https://antigravity.google/cli/install.sh | bash
  ```

裝好後執行一次 `agy`，用瀏覽器登入 Google 帳號。

**3. 確認**：在任一專案資料夾執行：

```
python <外掛路徑>/skills/delegate/delegate.py list
```

需求：Python 3.10 以上，只用標準函式庫。

## 使用

- **自動**：遇到大範圍探索時，Claude 會自己判斷要不要派副手，判斷規則見 `skills/delegate/SKILL.md`。
- **手動**：

  ```
  /delegate agy 找出所有呼叫 sendToMod2 的地方，以及它改了哪些狀態
  ```

- **直接執行**：

  ```
  python delegate.py ask auto "問題" 路徑1 路徑2 --timeout 15m --model 模型名稱
  ```

不想讓某個專案的程式碼送到外部服務時，在該專案的 `CLAUDE.md` 寫一行「禁止使用外部 AI」。

## 新增或調整後端

**不用改程式。** 在 `skills/delegate/backends/` 加一個 JSON 檔：

```json
{
  "name": "my-ai",
  "label": "顯示名稱",
  "priority": 5,
  "enabled": true,
  "context": "agent",
  "good_at": "擅長什麼（Claude 用來挑後端）",
  "exe": ["my-ai", "%LOCALAPPDATA%/my-ai/bin/my-ai.exe"],
  "args": ["run", "--print", "{prompt}", "--read-only", ["--model", "{model}"]],
  "output": {"type": "text"},
  "readonly": "說明它靠什麼保證不會改檔",
  "install": "安裝指令",
  "login": "登入方式"
}
```

**佔位符**

| 佔位符 | 代表什麼 |
|---|---|
| `{prompt}` | 完整的問題文字 |
| `{prompt_file}` | 問題寫入的暫存檔 |
| `{out_file}` | 讓 CLI 寫入最後回答的檔案 |
| `{usage_file}` | 讓 CLI 寫入用量紀錄的檔案 |
| `{timeout}` | 逾時設定，例如 `10m` |
| `{timeout_seconds}` | 逾時秒數 |
| `{model}` | 模型名稱 |
| `{cwd}` | 目前的專案資料夾 |

用陣列包起來的一組參數（例如 `["--model", "{model}"]`），在佔位符沒有值時會整組略過。

**其他欄位**

| 欄位 | 可選的值 |
|---|---|
| `output.type` | `json`：從 JSON 取欄位；`text`：直接用 stdout；`file`：讀 `{out_file}` |
| `context` | `agent`：後端自己讀檔，必須有只讀保護；`packed`：執行器讀好檔案再送，適合沒辦法限制成只讀的後端 |
| `stdin` | 設成 `"prompt"` 時，問題從標準輸入送進去 |

**個人覆寫**：放在 `~/.ai-delegates/backends/<名稱>.json`，只要寫要改的欄位，外掛更新時不會被蓋掉。例如啟用 codex：

```json
{ "enabled": true }
```

## 安全設計

- **只讀**：每個後端都必須說明自己怎麼保證不改檔。執行器絕對不會加 `--dangerously-skip-permissions`、`--yolo` 這類旗標。
- **排除機密**：packed 模式一律不送出以下內容：
  - `.env*`（`.env.example` 除外）
  - 金鑰與憑證檔：`*.pem`、`*.key`、`credentials*`、`token*.json`
  - `data/`、`logs/`、`secrets/`、`.git/`、`node_modules/` 資料夾
  - 資料庫與 log 檔

  agent 模式則在問題裡要求副手不要讀這些檔案。
- **副手的話只是線索**：Claude 必須自己打開它列出的行號確認後才能採用。

## 授權

MIT
