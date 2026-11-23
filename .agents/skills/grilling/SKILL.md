---
name: grilling
description: Grill the user relentlessly about a plan, decision, or idea. Use when the user wants to stress-test their thinking, or uses any 'grill' trigger phrases.
---

<!--
Vendored（原樣收進本 repo）自 mattpocock-skills plugin 的 skills/productivity/grilling。
授權 MIT，Copyright (c) 2026 Matt Pocock；完整授權見同目錄 ./LICENSE（MIT 要求隨附版權與授權聲明）。
收進 repo 版控的原因：pm 入口引用它，讓每個 clone／交接包都自帶，不必各機器另裝 plugin。
下方英文指令為原文逐字保留；最後一節〈本 repo 補充（非原文）〉不是原文（源專案 v5.36.0 加），升級 vendored 版本時要保留。
本 repo pm 入口實際引用時以繁體中文白話進行。
-->

Interview me relentlessly about every aspect of this until we reach a shared understanding. Walk down each branch of the decision tree, resolving dependencies between decisions one-by-one. For each question, provide your recommended answer.

Ask the questions one at a time, waiting for feedback on each question before continuing. Asking multiple questions at once is bewildering.

If a *fact* can be found by exploring the environment (filesystem, tools, etc.), look it up rather than asking me. The *decisions*, though, are mine — put each one to me and wait for my answer.

Do not act on it until I confirm we have reached a shared understanding.

## 本 repo 補充（非原文）：對非工程師出取捨題、規則題

（源專案 v5.36.0、v5.36.1）對象是不看程式的 PM、案主或客戶，不限特定的人。

- 題目與選項用對方看得到的情境命名：哪張單、哪張票、改給誰處理、顧客會看到什麼。不用演算法或統計術語（例：離群值、中位數、權重、重新分配）。
- 用到可能有兩種意思的詞，先講清楚指哪一種再問（例：「舊資料」是指上線前建的，還是很久沒人動的？）。
- 出題前自問：「他沒看過程式，答得出這題嗎？」答不出來就改寫。
- 白話的通則在 `pm` 入口〈語言與紀律〉；本節只管出題這一步。

> 為什麼（源專案 v5.36.0）：源專案的取捨題用了「離群值」「中位數」，還有一個同時有兩種意思的詞，非工程師都看不懂。
> 這條規則在源專案曾放在 AGENTS.md，後來改放 CLAUDE.md（v5.36.1：Claude 每個 session 一定載入的只有 CLAUDE.md）；本範本在 CLAUDE.md 留一行指到這一節。
