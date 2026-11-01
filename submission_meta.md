# Submission metadata

复制粘贴用。正文见 `draft_final.md`，本文件不进正文，也不随论文分发。

---

## Title

**EN:** From Formal Verification to Agents: A Method-Transfer Audit of "False Completion" in AI Agent
Harnesses

**ZH:** 从形式验证到智能体：一次方法迁移审计，及其在"假完成"上的结果

**短标题（仓库名 / 海报 / 邮件主题建议）：** Auditing Execution-Layer False Completion

---

## Abstract (EN, for preprint)

An agent that reports `Task Completed` has produced a **claim**, not an observation. In 2026 measurements
this is not a corner case: 65.4% of one industry evaluation's agent failures ended in confident false
completion `[CITED]`, and a separate 2026 study across two benchmarks found that **no LLM-judge
configuration it tested** stayed above AUROC 0.65 at separating false successes from real ones `[CITED]`.
The failure is therefore not only common but resistant to the obvious remedy — asking a second model to
look — because that remedy is still reading the agent's own account.

Audit methods are usually presented as though they were about their subject matter. They are just as much
about their **medium** — and that becomes visible when the medium changes. This paper takes an audit
method built for a formal-verification corpus and asks what survives when it is transferred to AI agent
harnesses, a setting that differs on four axes: it is stochastic rather than deterministic, its inputs
are private rather than public, it has no reference implementation, and its observables are the system's
own narration.

We give a transfer analysis instrument by instrument. Three instruments move. **The falsifiability
condition** — a property no mutant can kill is a decoration — carries over unchanged, because it is a
statement about signals, not about specifications. **Same-origin detection** moves but degrades: in the
source system it was a computation (re-derive both artifacts from public bytes and compare); in the
target it is only a *search* for a shared coordinate. **Mutation** moves and *strengthens*, because in
the target it needs no correct reference — a condition that must fail can be synthesised. **Recomputation
is lost entirely**, and we argue this single loss is the load-bearing fact: it is what forces the metric
denominator from a workload to a published probe suite, and what makes `INVALID` the modal verdict rather
than an edge case.

Applied to the target, the transferred method yields a four-mode taxonomy of false completion generated
from one condition (a signal losing its carrier, moment, referent, or range), an audit procedure over
evidence origin, execution witness and mutation probing, a four-valued verdict alphabet, and three
metrics with probe-suite denominators.

We are explicit that the *mechanism* is not our discovery: that an agent derives its check from the same
reading as its solution — so the check inherits the misreading and passes — has been stated in prose by
2026 industry evaluation work `[CITED]`, and that LLM judges are weak at this is now measured `[CITED]`
(no configuration above AUROC 0.65). Our claim is about the transfer: which instruments survive, what
they cost, and which conclusions become unsupportable on arrival. We claim mechanism, not prevalence.

---

## Abstract (ZH, for HAL 中文摘要)

Agent 报告 `Task Completed` 时，产出的是**声称**而非**观察**。这在 2026 年的测量里不是边角情况：一份
产业评测中 65.4% 的 Agent 失败以自信的假完成收场 `[CITED]`；另一项 2026 年跨两个基准的系统研究则发现，
它测试的**没有任何** LLM 裁判配置在区分真假成功上超过 AUROC 0.65 `[CITED]`。所以这个失败不仅常见，而且
对最显而易见的补救——再叫一个模型来看——是免疫的，因为那个补救读的仍然是 Agent 自己的自述。

审计方法通常被当作是关于其研究对象的。它同样关乎它的**媒介**——而这在媒介改变时才看得见。本文取一套
为形式验证语料构建的审计方法，追问当它被迁移到 AI Agent Harness 上时，什么能活下来。目标场景在四个
轴上不同：它是随机的而非确定的、输入是私有的而非公开的、没有参考实现、且可观测量就是系统自己的自述。

我们逐件仪器给出迁移分析。三件能搬。**可失败条件**——没有变异体能杀死的属性不是检查，是装饰——原样
搬过去，因为它说的是信号，不是规约。**同源检测**搬得过去但会退化：在源系统里它是计算（从公开字节重新
生成两个产物再比对），在目标系统里它只是对共享坐标的一次*搜索*。**变异**搬得过去而且**变强**，因为
目标里它不需要正确的参照——一个必须失败的条件可以凭空合成。**重算完全丧失**，我们认为这单一损失是
承重事实：正是它把度量分母从工作负载逼成了公开探针套件，也正是它让 `INVALID` 从边缘判词变成常见判词。

施加到目标上，迁移后的方法产出一个由单一条件生成的假完成四模式分类（信号丢失载体、时刻、指称、值域）、
一套覆盖来源/见证/变异注入的审计流程、一个四值判词，以及三个带探针分母的度量。

我们明确说明*机制*不是我们的发现：Agent 从与解法相同的误读中派生校验、于是校验继承误读并通过，这一点
2026 年的产业评测已用散文说过 `[CITED]`；LLM 裁判在这件事上很弱，也已被测量 `[CITED]`（无配置超过
AUROC 0.65）。我们的主张是关于**迁移**的：哪些仪器能活、代价是什么、以及哪些结论一落地就不再成立。
我们主张机制，不主张普遍率。

---

## Keywords

`AI agents` · `agent evaluation` · `false completion` · `mutation testing` ·
`formal verification` · `auditability` · `LLM reliability` · `software verification`

（如需 ≤5 个的场合：`AI agents`, `agent evaluation`, `mutation testing`, `auditability`,
`formal verification`）

---

## One-sentence summary

**GitHub repository description（≤150 字符）：**

> Auditing execution-layer false completion in AI agent harnesses: a method-transfer analysis, a
> four-valued verdict alphabet, and a runnable demo.

**HAL / 邮件里的一句话：**

> Agent 说"任务完成"时给你的是声称而非观察——本文把形式验证的审计仪器搬到 Agent Harness 上，
> 论证哪件搬得动、哪件搬不动，并附一个能证明自己不是装饰的可运行 Demo。

---

## Suggested repository metadata

- **Repo name:** `agent-harness-audit`
- **Topics:** `ai-agents`, `llm`, `software-verification`, `agent-evaluation`, `formal-verification`,
  `mutation-testing`, `auditability`
- **License:** MIT（见 `LICENSE`）
- **Entry point for readers:** `README.md`；给决策者：`EXECUTIVE_BRIEF.md`

---

## HAL submission notes

- **Domain:** Computer Science > Software Engineering
- **Type:** Preprint / working paper（方法论，无实验数据）
- **Files to upload:** `draft_final.md`（正文）+ 如需附件，`agent_audit_demo.py` 与 `LICENSE`
- **不建议上传：** 本文件、`README.md`、`EXECUTIVE_BRIEF.md`（仓库物料，非论文组成部分）
- **与 EDA 论文的关系：** 本文 §2 明确说明 EquivSVA 审计是**独立的前序工作**，其审计工具包不随本文
  分发（附录 B.3）。投稿时若被问及，答"companion artifact, submitted separately"，不要暗示本文自带复现。

---

## 投稿前必读：三处仍需作者确认

1. **作者联系方式。** 正文第 5 行是 `liaozhizhi@foxmail.com`。若要换成主页或 GitHub，
   只改这一行，别处无引用。
2. **EquivSVA 的表述。** 附录 B.3 现写"our audit tooling for EquivSVA is a separate artifact… not
   bundled…"。**不要**改成"基于公开仓库的独立验证"——本文没有证据支持"独立验证"这个措辞，而这正是
   全文批判的那种无据加强。数据集本身已作为 S9 列入附录 C（`arXiv:2609.26751`），可核查；不可核查的
   是那四个数字，因为它们出自我们自己的审计。
3. **两位数字的口径。** §3.1 的 65.4% 与 67.2% 来自同一项目的两个页面，分母不同（前者为该项目
   自报口径，后者为 2,574 条失败轨迹）。正文已分别标注；若审稿人追问，务必答"两者不可互相换算"，
   这也是 §8.1 的论点。
