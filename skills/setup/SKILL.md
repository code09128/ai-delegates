---
name: setup
description: 用選單設定 ai-delegates 每個角色（lead 主控、search、log、explore、review）要用哪個 AI 後端與模型。使用者說「設定派工」「換主控模型」「搜尋改用 GPT」或呼叫 /ai-delegates:setup 時使用。
---

# 設定角色

執行器在 delegate 技能資料夾：本技能資料夾的上一層 `../delegate/delegate.py`。都在**專案根目錄**執行。

1. 執行 `python "<delegate 資料夾>/delegate.py" show` 和 `list`，讓使用者看到目前設定與哪些後端可用（「可用」才能選；「停用」「未安裝」的把安裝或啟用方式告訴使用者）。
2. 問使用者要改哪些角色（AskUserQuestion，multiSelect；選項是角色名稱加說明）。使用者在指令後面已經講清楚（例如 `/ai-delegates:setup search 用 codex`）就直接照做，不用問。
3. 每個要改的角色：
   - 問後端：選項是「可用」的後端；副手角色多一個 `auto（依 priority 自動挑）`；lead 不能 auto。
   - 選了後端後，執行 `delegate.py models <後端>` 取得模型清單，問模型：「後端預設」加上清單前幾個常用的（選項最多 4 個，其他讓使用者用「其他」自己輸入）。
4. 寫入：`python "<delegate 資料夾>/delegate.py" set <角色> <後端> [--model 模型]`。使用者說「只有這個專案」時加 `--project`（寫到專案根目錄的 `.ai-delegates.json`）。
5. 最後執行 `show`，把結果給使用者看。

說明重點（使用者問時）：
- lead 設成 claude＝在 Claude Code 裡就是 Claude 自己當主控（預設）。設成其他 AI 時，那個 AI 只做唯讀規劃，改檔與測試仍由 Claude 做。
- 想讓其他 AI 真正自己動手當主控，要在它自己的 CLI 裡工作（例如 Codex CLI），把 repo 裡 `templates/AGENTS.md` 的派工規則放進專案；那時 claude 可以當副手。
- 副手角色設成 claude 而目前就在 Claude Code 裡時，會用 Claude 的內建子代理，不另外開一個 claude。
- 專案的 `.ai-delegates.json` 優先於使用者設定；`reset [角色]` 回到預設。
