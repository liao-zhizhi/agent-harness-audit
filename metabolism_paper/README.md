# Metabolism Paper — 论文与代码仓库对应关系

> **DOI 已分配（Zenodo v1）。五个 DOI 的完整清单、核验结果与冻结字节说明见 [`ZENODO_DOIS.md`](ZENODO_DOIS.md)。**

本目录存放第二篇论文的 LaTeX 源码与构建产物。

## 论文

| # | 标题 | 主题 | 状态 |
|:--|:--|:--|:--|
| 第一篇 | *From Formal Verification to Agents: A Method-Transfer Audit of "False Completion" in AI Agent Harnesses* | 判词与见证：如何**判定**一次调用是否真的发生了（四值判词格 PASS / FAIL / INVALID / NOT RUN，独立见证） | 完成初稿 |
| 第二篇（本目录） | *Agent Metabolism and Conditional Immunity: A Bio-Inspired Runtime Architecture for Reliable LLM Agents* | 判定之后**运行时该做什么**：代谢层 L1–L7、痛觉罚金账本、条件免疫 Tier 1 / Tier 2 与跨进程炎症持久化 | v2：新增规则接口（`RuleRegistry`）与 Lean 形式化证明审计 |

两篇的分工是刻意的，不是重复：

- 第一篇回答「**怎么知道**它没做」。核心是 witness（见证）来自物理世界而非 Agent 的自述。
- 第二篇回答「**知道之后怎么办**」。核心是让判词产生代价：扣能量、降并发、涨罚金、升档位。
- 第二篇把第一篇的判词当作**输入**，而不是重新论证判词本身。

## 代码仓库

| 仓库 | 链接 | 对应关系 |
|:--|:--|:--|
| `agent-harness-audit` （论文仓库） | https://github.com/liao-zhizhi/agent-harness-audit | 第一篇论文的稿件与复现材料；也是第二篇 `references.bib` 中自引条目 `liaozhizhi2026methodtransfer` 指向的地址 |
| `harness-audit-sidecar` （代码仓库） | https://github.com/liao-zhizhi/harness-audit-sidecar | 两篇论文共用的审计侧车实现。第二篇中承担 **L5 饱和制动**与**条件免疫**（Tier 1 `stat` / Tier 2 `git` change set、炎症阈值、`.immune_state.json` 持久化）。v0.7.0 是本文评测所用版本 |
| `agent-metabolism-os` （代谢运行时） | https://github.com/liao-zhizhi/agent-metabolism-os | 第二篇评测中的代谢侧实现：L1–L4、L6–L7 与罚金账本。v0.3.0 是本文评测所用版本 |

补充说明：

- 上述三个仓库均已写入 `references.bib`（`[1]` 论文仓库、`[10]` 侧车、`[11]` 代谢运行时），正文 Setup 段逐一引用。
- 论文表 II 中的 **L5** 不在代谢仓库里，由 `harness-audit-sidecar` 承担。这正是「免疫系统判定、代谢系统执行」的分工，也是本文主张的核心。读代码时请按此对应，不要在本仓库中寻找 L5 模块。

## 构建

```bash
cd metabolism_paper
./build.sh              # 编译 + 门禁（0 overfull、0 未定义引用、/Title 与 /Author 非空）
./build.sh --check      # 只核验已提交的 main.pdf，不重编
```

`build.sh` 固定 `SOURCE_DATE_EPOCH=1793577600`（与另两篇同一做法），因此同一份源码两次编译得到**逐字节相同**的 PDF、SHA256 可复现。手工 `latexmk -pdf main.tex` 会让 pdfTeX 写入当前时间与新的 `/ID`，两次数值不同——那样记录下来的哈希谁也复现不了，包括第二天我们自己。

它同时检查 PDF 元数据：hyperref 不会把 `\title` 复制进 `/Title`，缺了这一步，XML/Zenodo/arXiv 会把文件登记成「无标题文档」——本仓库论文所审计的假完成，发生在文件自己身上。门禁比注释可靠，所以这一步是硬失败。

产物：`main.pdf`（10 页）。中间文件已列入 `.gitignore`。

## 文件清单

| 文件 | 说明 |
|:--|:--|
| `main.tex` | 论文源码，`IEEEtran` conference 格式 |
| `references.bib` | 14 条文献，元数据均已联网核对（COLM / NeurIPS / IJCAI 官方页面、出版社产品页、被审计仓库的 remote 与 README） |
| `main.pdf` | 编译产物，10 页 |
| `metabolism_paper_v1.zip` | 上述三份文件的归档 |

## 已知待办（v2）

1. 正文润色：模型生成段落需作者重写口吻。
2. 第一篇论文若已投出或录用，`references.bib` 中 `liaozhizhi2026methodtransfer` 需从 `@misc` 改为对应类型并补会议/期刊信息。
