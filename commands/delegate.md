---
description: 手動派一個只讀偵察任務給外部 AI 副手（例如 /delegate agy 找出所有呼叫 X 的地方）
argument-hint: "[後端|auto] <問題> [路徑...]"
---

使用 `delegate` 技能處理這個請求：$ARGUMENTS

- 第一個詞如果是後端名稱（例如 agy）或 auto，就用它；否則用 auto。
- 先執行 `delegate.py list` 確認後端可用，再執行 `ask`。
- 拿到回報後，打開關鍵的 `檔案:行號` 確認，再用繁體中文向使用者摘要，並標明哪些已確認。
