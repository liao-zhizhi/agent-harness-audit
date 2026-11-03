# DOGFOOD_AUDIT — `metabolism_paper` 发布前自审

> 本报告中的每一条判词都由 `harness-audit-sidecar` v0.7.0 依据**独立见证**（git change set、PDF 页数、ZIP 字节）作出，不采信 agent 自报的 `success`。

| 项目 | 值 |
| --- | --- |
| 运行 ID | `dogfood-metabolism-vckjt44q` |
| 开始时间 | `2026-11-02T23:37:15+08:00` |
| sidecar | `agent-harness-audit` v0.7.0 |
| 判词格 | `PASS` / `FAIL` / `INVALID` / `NOT RUN` |
| 炎症阈值 | 2 次连续 `FAIL` 或 1 次 `INVALID` → `INFLAMED`；5 次连续 `PASS` → `NORMAL` |
| 判决层 | tier1 `stat` / tier2 `git change set`（`run_command` 无策略，被强制 tier2） |
| 临时仓库 | `/tmp/dogfood-metabolism-vckjt44q/repo` |
| 免疫状态文件 | `/tmp/dogfood-metabolism-vckjt44q/immune_state.json` |

## 0. 结论

12 次判词：**9 PASS / 3 FAIL**。最终状态：**NORMAL**。

1. **假完成被抓出。** CI 包装脚本吞掉 `pdflatex` 的退出码并 `exit 0`，agent 收到的响应是 `run_command: ok`；sidecar 去看 git change set，发现 `main.pdf` 从未出现，判 `FAIL`。
2. **炎症需要两次。** 第一次 `FAIL` 只是 `danger=1`（设计上「孤立的失败是正常的一天」），第二次 `FAIL` 进入 `INFLAMED`。
3. **恢复需要五次。** 修复源码后 5 次 `latexmk -g -pdf` 全部 `PASS`，`recovery_progress` 逐次 1→5，第 5 次回到 `NORMAL`。
4. **浅见证看不见归档内部。** 缺 `references.bib` 的 zip 在 git 眼里是一次正常的 `??`——tool 层判 `PASS`；`zipfile` 见证判 `FAIL`。这就是论文 §4.5 说的一类盲区，被我们自己的发布脚本复现了。

5. **引用也要见证。** `references.bib` 的 11 条里，3 条能解析到 arXiv 记录并标题相符（PASS），8 条没有任何可复算的标识符（INVALID）——后者不是伪造，是**不可见证**，正是论文对「无见证不可信」的定义。
6. **见证要能传到读者手里。** 第一轮只写 `eprint`，`main.pdf` 字节未变（`IEEEtran.bst` 丢弃该字段）；第二轮把同样的 arXiv 号写成 `note` 里的 `\url`，PDF 变为 `85c225066f4f06ff…`，并携带 9 条可点击的 `/URI` 注记。同一份知识，两种可见性。

## 1. 判词时间线

| # | 阶段 | 调用 | agent 声称 | 见证 | 判词 | tier | 免疫状态 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `fake-build` | `run_command` | `success` | missing: `main.pdf` | **FAIL** | `tier2` | `NORMAL` (d=1, r=0) |
| 2 | `fake-build` | `run_command` | `success` | missing: `main.pdf` | **FAIL** | `tier2` | `INFLAMED` (d=2, r=0) |
| 3 | `build` | `run_command` | `success` | changed: `main.pdf` | **PASS** | `tier2` | `INFLAMED` (d=2, r=1) |
| 4 | `build` | `run_command` | `success` | changed: `main.pdf` | **PASS** | `tier2` | `INFLAMED` (d=2, r=2) |
| 5 | `build` | `run_command` | `success` | changed: `main.pdf` | **PASS** | `tier2` | `INFLAMED` (d=2, r=3) |
| 6 | `build` | `run_command` | `success` | changed: `main.pdf` | **PASS** | `tier2` | `INFLAMED` (d=2, r=4) |
| 7 | `build` | `run_command` | `success` | changed: `main.pdf` | **PASS** | `tier2` | `NORMAL` (d=0, r=0) |
| 8 | `pack-bad` | `run_command` | `success` | changed: `metabolism_paper_v1.zip` | **PASS** | `tier2` | `NORMAL` (d=0, r=0) |
| 9 | `pack-bad` | `archive_witness` | `success` | effect=False | **FAIL** | `artifact` | `NORMAL` (d=1, r=0) |
| 10 | `pack-good` | `run_command` | `success` | changed: `metabolism_paper_v1.zip` | **PASS** | `tier2` | `NORMAL` (d=0, r=0) |
| 11 | `pack-good` | `archive_witness` | `success` | effect=True | **PASS** | `artifact` | `NORMAL` (d=0, r=0) |
| 12 | `release` | `archive_witness` | `success` | effect=True | **PASS** | `artifact` | `NORMAL` (d=0, r=0) |

## 2. 场景一：假完成，以及它为什么不立刻发炎

CI 包装脚本（`/tmp/dogfood-metabolism-vckjt44q/scripts/build.sh`）：

```sh
#!/bin/sh
# CI wrapper for the paper build.
#
# THE BUG UNDER AUDIT: the wrapper reads pdflatex's exit status, prints it,
# and then exits 0 regardless. The tool layer therefore tells the agent the
# build succeeded even when no PDF was produced. Nothing in the transcript is
# a lie -- the agent is simply wrong about the world, and consistent with
# everything it was told.
#
# SOURCE_DATE_EPOCH is pinned for a reason that has nothing to do with the bug
# under audit: without it pdfTeX stamps the current time into /CreationDate and
# draws a fresh /ID, so the artefact built in the sandbox differs from the
# released one by a few bytes and a hash. The report would then print one
# filename with two hashes and no way to tell which is the deliverable -- the
# ambiguity this paper is about, reintroduced by the audit tooling itself.
export SOURCE_DATE_EPOCH=1793577600
export FORCE_SOURCE_DATE=1
pdflatex -interaction=nonstopmode -halt-on-error main.tex > build.log 2>&1
status=$?
echo "pdflatex exited with ${status}"
echo "build finished"
exit 0
```

`pdflatex` 的真实反应（`build.log` 中与错误有关的前几行）：

```text
! LaTeX Error: File `dogfood-audit-package-that-does-not-exist.sty' not found.
! Emergency stop.
!  ==> Fatal error occurred, no output PDF file produced!
```

但 agent 看到的是：

```text
run_command: ok
```

sidecar 看到的（同一时刻、独立读取）：

```text
changed_files     = []
missing_expected = ['main.pdf']
exit_code         = 0
reason            = false completion: report says success, witness says no effect (expected but untouched: main.pdf)
```

判词 **FAIL**。注意 `exit_code=0` 不是读错了：包装脚本**确实**成功退出了，失败只存在于它丢掉的 `pdflatex` 状态里。sidecar 之所以没被骗，是因为判词来自见证而不是退出码，而 `check` 取的是工具层转述给 agent 的那句话（`protocol`），不是 shell 的状态。

| 第几次假完成 | `danger_count` | 状态 |
| --- | --- | --- |
| 1 | 1 | `NORMAL` |
| 2 | 2 | `INFLAMED` |

第一次 `FAIL` **没有**触发 `INFLAMED`，这是 `ImmuneState` 有意的不对称：只有*连续*失败才构成攻击信号，被验证过的工作包围的偶发失败是正常的一天。第二次 `FAIL` 把 `danger_count` 推到阈值 2，状态变为 `INFLAMED`。

## 3. 场景二：真实构建与免疫恢复

修复 `main.tex` 后，命令换成真实的 `latexmk -g -pdf`，并且**在每次构建前先把 `main.pdf` 删除**（删除动作发生在被审计命令之外）：

```sh
latexmk -g -pdf -interaction=nonstopmode -halt-on-error main.tex
```

这条前置条件不是装饰。两次相隔 0.8 秒的重建可能产出**字节完全相同**的 PDF（pdfTeX 只盖秒级时间戳），而内容见证无法把「重建了但字节没变」和「根本没构建」区分开。先删产物，见证要证明的就变成「从零生成」，这个方向上的歧义被消掉了。

| rebuild | 判词 | `main.pdf` 变化 | 页数 | `recovery_progress` | 状态 |
| --- | --- | --- | --- | --- | --- |
| 1 (#3) | **PASS** | `main.pdf` | 8 | 1/5 | `INFLAMED` |
| 2 (#4) | **PASS** | `main.pdf` | 8 | 2/5 | `INFLAMED` |
| 3 (#5) | **PASS** | `main.pdf` | 8 | 3/5 | `INFLAMED` |
| 4 (#6) | **PASS** | `main.pdf` | 8 | 4/5 | `INFLAMED` |
| 5 (#7) | **PASS** | `main.pdf` | 8 | 5/5 → 治愈 | `NORMAL` |

第 5 次 `PASS` 让 `recovery_progress` 到达 5/5，状态回到 `NORMAL`，`danger_count` 清零。愈合比受伤慢——这是设计，不是缺陷。

页数是**第二见证**：git 只能说「`main.pdf` 变了」，`pdfinfo` 才能说「变出来的是一篇 8 页的论文」。两者不一致时（例如只编出一页错误页），本脚本会在发布闸门里判 `FAIL`。

## 4. 场景三：打包完整性 —— 浅见证的盲区

第一次打包用的脚本（事故版本）：

```sh
#!/bin/sh
# Release script as it was at the time of the incident: it zips the compiled
# paper and its source, and quietly forgets the bibliography.
rm -f metabolism_paper_v1.zip
zip -q metabolism_paper_v1.zip main.pdf main.tex
echo "packaged 2 file(s)"
exit 0
```

| 见证层 | 观察 | 判词 |
| --- | --- | --- |
| git change set | `metabolism_paper_v1.zip` | **PASS** |
| `zipfile` 成员表 | members=['main.pdf', 'main.tex']，missing=['references.bib'] | **FAIL** |

同一个物理动作，两个见证给出两个判词，而且**两个都对**：归档确实被重写了（tool 层没撒谎），归档确实不完整（agent 的结论错了）。git 看不见 zip 内部，所以发布闸门不能只用一个浅见证。

sidecar 对归档的判词：

```text
false completion: report says success, witness says no effect
```

这次归档 `FAIL` 让 `danger_count` 升到 1，但状态停在 `NORMAL`：系统刚愈合，孤立的失败不足以再次发炎。判词是 `FAIL`，炎症是另一件事——两者被刻意分开，否则审计器会变成一个对任何风吹草动都拉警报的装饰品。

修复后（`pack_complete.sh`）：

| 成员 | 大小 (B) | zip 内 sha256 | 源文件 sha256 | 一致 |
| --- | --- | --- | --- | --- |
| `main.pdf` | 270604 | `85c225066f4f06ff` | `85c225066f4f06ff` | ✓ |
| `main.tex` | 53333 | `1dcfd8b0a4f8eadc` | `1dcfd8b0a4f8eadc` | ✓ |
| `references.bib` | 8495 | `e402f2b9751a15f1` | `e402f2b9751a15f1` | ✓ |

两次判词均为 **PASS**，`danger_count` 归零，状态 `NORMAL`。

## 5. 引用见证：`references.bib` 逐条解析

`.bib` 文件里的每一条都是一句关于世界的话：*这个标识符* 指的是 *这篇论文*。`CitationAuditProxy` 把这句话交给注册机构核对，判词由同一个 `VerdictEngine` 给出——与文件写入共用一套格，而不是另立一套更宽松的通过标准。

| 条目 | 标识符 | 判词 | 机构 / 未通过原因 |
| --- | --- | --- | --- |
| `liaozhizhi2026methodtransfer` | - | **INVALID** | 无 DOI、无 arXiv 号（动态网页 / 仓库 / 会议论文集） |
| `liaozhizhi2026sidecar` | - | **INVALID** | 无 DOI、无 arXiv 号（动态网页 / 仓库 / 会议论文集） |
| `liaozhizhi2026metabolism` | - | **INVALID** | 无 DOI、无 arXiv 号（动态网页 / 仓库 / 会议论文集） |
| `chase2022langchain` | - | **INVALID** | 无 DOI、无 arXiv 号（动态网页 / 仓库 / 会议论文集） |
| `wu2024autogen` | `2308.08155` | **PASS** | arxiv 返回标题与条目一致 |
| `langchain2024langgraph` | - | **INVALID** | 无 DOI、无 arXiv 号（动态网页 / 仓库 / 会议论文集） |
| `moura2024crewai` | - | **INVALID** | 无 DOI、无 arXiv 号（动态网页 / 仓库 / 会议论文集） |
| `zheng2023judging` | `2306.05685` | **PASS** | arxiv 返回标题与条目一致 |
| `panickssery2024evaluators` | `2404.13076` | **PASS** | arxiv 返回标题与条目一致 |
| `hewitt1973actor` | - | **INVALID** | 无 DOI、无 arXiv 号（动态网页 / 仓库 / 会议论文集） |
| `nygard2018release` | - | **INVALID** | 无 DOI、无 arXiv 号（动态网页 / 仓库 / 会议论文集） |

3 PASS / 0 FAIL / 8 INVALID。FAIL 为零：没有任何一条的标题与解析到的记录相互矛盾。8 条 INVALID 全部属于「条目本身没有可复算的标识符」，包括本文两篇自引软件与三个 GitHub 项目——把它们的 URL 抄进 `url` 字段并不构成见证，因为没有人能 re-resolve 出一个稳定记录。

反过来，凡是**声明了**标识符的条目，本次全部解析成功。这一点被单独设为闸门条件：否则网络一断，八条诚实的 INVALID 会把三条本应可解析的 INVALID 一起盖住，而后者是可以修的。

## 6. 发布闸门：真实交付物

审计对象不是沙箱副本，而是将要上传的那一个：`/home/liaozhizhi/Gradia/metabolism_paper/metabolism_paper_v1.zip`。

| 检查项 | 结果 |
| --- | --- |
| 三个成员齐全 | ✓ |
| 成员哈希与源文件一致 | ✓ |
| 无多余成员 | ✓ |
| `main.pdf` 页数 | 8（期望 8） |
| 引用：无 FAIL | ✓ |
| 引用：声明了标识符的条目均可解析 | ✓ |
| 引用：arXiv 链接在 PDF 中可点击 | ✓ 3/3 条（全档共 9 条 `/URI`） |
| **判词** | **PASS** |

成员指纹：

| 成员 | 大小 (B) | sha256（前 16 位） |
| --- | --- | --- |
| `main.pdf` | 270604 | `85c225066f4f06ff` |
| `main.tex` | 53333 | `1dcfd8b0a4f8eadc` |
| `references.bib` | 8495 | `e402f2b9751a15f1` |

## 7. 交付物哈希

下表是文件系统上实际存在的字节，不是构建日志里的自述。`main.pdf` 与 `main.tex` 在多次独立会话中重编后哈希不变，因为 `SOURCE_DATE_EPOCH` 已固定；`references.bib` 与 `main.pdf` 因新增可点击的 arXiv 注记而改变。

| 文件 | 大小 (B) | SHA256 |
| --- | --- | --- |
| `main.pdf` | 270604 | `85c225066f4f06ff692b411862712149335038d31b941d85ca74f3b784d4f790` |
| `main.tex` | 53333 | `1dcfd8b0a4f8eadcacc1d79b514d75d0d74a7c3dae756531f95f82b2dbaa5cca` |
| `references.bib` | 8495 | `e402f2b9751a15f1772cebfb11de81f424054f6f521790c8c186f0c45fafedae` |
| `metabolism_paper_v1.zip` | 286382 | `59943a3b82271c79bfc817acf94e09b14030bfa369515996d41f91de86f07484` |

### 7.1 两轮修订，两种见证深度

| 轮次 | 改动 | `main.pdf` SHA256 | 页数 |
| --- | --- | --- | --- |
| 第一轮 | 仅加 `eprint`（机器可读） | `5724b84e41f8b5e0…`（**未变**） | 8 |
| 第二轮 | 追加 `note` 中的 `\url`（人可读） | `85c225066f4f06ff…`（**已变**） | 8 |

同一个标识符，两种写法，两种命运。第一轮加 `eprint` 后 `main.pdf` **一个字节都没变**：`IEEEtran.bst` 1.14 没有 `eprint` 处理器，字段被读入即丢弃，`main.bbl` 里出现 0 次。审计器照样能判 `PASS`——它读 `.bib`，不读 PDF。第二轮把同一个号码写成 `note` 里的 `\url`，PDF 立刻变了：`85c225066f4f06ff…`，页数仍是 8，overfull hbox 仍为 0。

**机器能审计到的，人眼未必能看到。** 这不是比喻，是两轮之间唯一的差别：标识符没变，判词没变，变的只是它被写进了哪个字段。第一轮的 `PASS` 对读者毫无帮助——他们手里只有一个无法复核的引文，而那正是本文反对的东西。

## 8. 这次吃狗粮发现了什么

1. **`exit 0` 吞错是这个管线最真实的故障模式。** 包装脚本没有撒谎，它只是把退出码打印到日志里然后丢弃；agent 的转录完全自洽。只有独立见证能把「自洽」和「正确」分开。
2. **一次失败不该拉响警报。** 第一次 `FAIL` 保持 `NORMAL`。把阈值设成 1 会让免疫系统对每个偶发失败发炎，最终被运维关掉——与被审计的系统同归于尽。
3. **见证深度必须匹配意图深度。** 打包的意图是「归档里有三个文件」，而 git 见证只能回答「归档变了」。发布闸门因此必须下沉到归档字节；否则一次缺文件的发布会被判 `PASS`，而这正是论文要防的那种假完成。
4. **审计器不修正 agent 的视图。** 两次假完成里，agent 收到的都还是`run_command: ok`。旁路观察者一旦改写被审计者的世界观，它就成了系统的一部分。
5. **凭记忆给出的标识符，只有经过物理见证才算数。** 审计过程中我们按记忆填过一个 arXiv 号（Panickssery 那篇），解析结果是 *Style Over Substance*——一篇完全不同的论文，判 `FAIL`；按标题反查才得到 `2404.13076`。这个错误在排版、在 PDF、在任何自洽性检查里都看不见。
6. **`eprint` 是给机器的字段，不是给读者的。** 同样的 arXiv 号，写进 `eprint` 时 PDF 一个字节不变；改写进 `note` 的 `\url` 后 PDF 立刻换了哈希。`IEEEtran.bst` 丢弃前者，排版后者。若读者要复算，标识符必须出现在会被排版出来的地方，否则「文件里有见证」和「读者能复核」始终是两件事。
7. **链接本身也要被见证。** 本轮把「arXiv 链接必须是 PDF 里的 `/URI` 注记」做成了闸门条件：脚本解压 PDF 的对象流，取出全部链接目标，与 `.bib` 承诺的URL 逐一比对。它不读 `.bib` 来确认 `.bib`，而是读交付物确认交付物。本次 3 条承诺、9 条命中。

## 附录 A：控制台判词记录（原始输出）

```text
==============================================================================
harness-audit-sidecar v0.7.0 | dogfood run | 2026-11-02T23:37:15+08:00
==============================================================================
  (sandbox kept at /tmp/dogfood-metabolism-vckjt44q for inspection)
sandbox : /tmp/dogfood-metabolism-vckjt44q
repo    : /tmp/dogfood-metabolism-vckjt44q/repo (git, 3 files committed)

-- 场景一：注入假完成（CI 吞掉 pdflatex 的失败）--
[01] fake-build run_command     claim=success missing=main.pdf                               -> FAIL    [tier2] state=NORMAL(danger=1, recovery=0/5)
        pdflatex said: ! LaTeX Error: File `dogfood-audit-package-that-does-not-exist.sty' not found.
        pdflatex said: ! Emergency stop.
        pdflatex said: !  ==> Fatal error occurred, no output PDF file produced!
[02] fake-build run_command     claim=success missing=main.pdf                               -> FAIL    [tier2] state=INFLAMED(danger=2, recovery=0/5)

-- 场景二：真实构建，连续 5 次 PASS 以愈合 --
[03] build      run_command     claim=success changed=main.pdf                               -> PASS    [tier2] state=INFLAMED(danger=2, recovery=1/5)
        pdfinfo: main.pdf has 8 page(s)
[04] build      run_command     claim=success changed=main.pdf                               -> PASS    [tier2] state=INFLAMED(danger=2, recovery=2/5)
        pdfinfo: main.pdf has 8 page(s)
[05] build      run_command     claim=success changed=main.pdf                               -> PASS    [tier2] state=INFLAMED(danger=2, recovery=3/5)
        pdfinfo: main.pdf has 8 page(s)
[06] build      run_command     claim=success changed=main.pdf                               -> PASS    [tier2] state=INFLAMED(danger=2, recovery=4/5)
        pdfinfo: main.pdf has 8 page(s)
[07] build      run_command     claim=success changed=main.pdf                               -> PASS    [tier2] state=NORMAL(danger=0, recovery=0/5)
        pdfinfo: main.pdf has 8 page(s)

-- 场景三：打包完整性（缺 references.bib）--
[08] pack-bad   run_command     claim=success changed=metabolism_paper_v1.zip                -> PASS    [tier2] state=NORMAL(danger=0, recovery=0/5)
        zipfile: members=['main.pdf', 'main.tex'] missing=['references.bib'] hash-mismatch=[]
[09] pack-bad   archive_witness claim=success effect=False                                   -> FAIL    [artifact] state=NORMAL(danger=1, recovery=0/5)
[10] pack-good  run_command     claim=success changed=metabolism_paper_v1.zip                -> PASS    [tier2] state=NORMAL(danger=0, recovery=0/5)
        zipfile: members=['main.pdf', 'main.tex', 'references.bib'] missing=[] hash-mismatch=[]
[11] pack-good  archive_witness claim=success effect=True                                    -> PASS    [artifact] state=NORMAL(danger=0, recovery=0/5)

-- 引用见证：references.bib 逐条解析 --
[cite] liaozhizhi2026methodtransfer none:-                         -> INVALID  (no_identifier)
[cite] liaozhizhi2026sidecar      none:-                         -> INVALID  (no_identifier)
[cite] liaozhizhi2026metabolism   none:-                         -> INVALID  (no_identifier)
[cite] chase2022langchain         none:-                         -> INVALID  (no_identifier)
[cite] wu2024autogen              arxiv:2308.08155               -> PASS
[cite] langchain2024langgraph     none:-                         -> INVALID  (no_identifier)
[cite] moura2024crewai            none:-                         -> INVALID  (no_identifier)
[cite] zheng2023judging           arxiv:2306.05685               -> PASS
[cite] panickssery2024evaluators  arxiv:2404.13076               -> PASS
[cite] hewitt1973actor            none:-                         -> INVALID  (no_identifier)
[cite] nygard2018release          none:-                         -> INVALID  (no_identifier)
        references: 11 total, 3 PASS, 0 FAIL, 8 INVALID (8 without an identifier)

-- 发布闸门：真实交付物 --
[12] release    archive_witness claim=success effect=True                                    -> PASS    [artifact] state=NORMAL(danger=0, recovery=0/5)

        pdf links: promised=3 embedded=9 missing=[]
==============================================================================
sidecar verdicts over tool calls: PASS=7, FAIL=2, INVALID=0, NOT RUN=0
immune state: NORMAL (danger=0, recovery=0/5)
release gate : PASS
==============================================================================
```

## 附录 B：免疫状态文件

`/tmp/dogfood-metabolism-vckjt44q/immune_state.json`（进程退出后仍可恢复，重启不能洗掉怀疑）：

```json
{
  "danger_count": 0,
  "fail_threshold": 2,
  "invalid_threshold": 1,
  "recovery_passes": 5,
  "recovery_progress": 0,
  "state": "NORMAL",
  "version": 1
}
```

---

生成于 `2026-11-02T23:37:29+08:00`，sidecar v0.7.0，宿主 `liaozhizhi-DR5820-Tower`。
