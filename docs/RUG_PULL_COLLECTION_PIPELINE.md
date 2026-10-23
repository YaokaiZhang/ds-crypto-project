# Rug Pull 正式采集入口

当前公共阶段以 [统一入口说明](SCAM_PIPELINE.md) 为准：`sources / collect / prepare / train / all / status`。`all` 包含训练并要求 `--run`；本文较早的内部阶段与历史实验记录不改变既有结果。

2026-10-22 接入。复用现有 Token 采集、标准化、建图流程，不修改训练配方。
2026-10-23 采集已完成：3,107 个成功、5 个标准化失败。临时账号的进程配置
已失效，独立 quota 文件按用户要求删除。后续离线处理见
[训练准备说明](RUG_PULL_TRAINING_PIPELINE.md)。

## 固定输入

快照 `data/scam/rug_pull/tokenscout-eligible-1500-v2/` 的
`pools/verified_targets.jsonl` 和 `labels/verified_labels.jsonl`：
1,500 正例、1,612 负例，共 3,112 个 Token，3,111 个不同的所选池。
通过 `pools/verification_manifest.json` 验证文件校验和，按 sample_id 一对一匹配。
标签只进入独立的 candidate_labels.jsonl，不进入采集目标或图特征。

每个 Token 使用先前选定并验证的一个官方 Uniswap v2 池，可使用任意报价资产。
保持截止时间 `2023-02-28T23:59:59Z`、区块 `16730071` 和既有区块哈希。
这是来源覆盖结束时点，不是 Rug Pull 事件时间。直接复用历史 decimals、
池身份与证据，本阶段无需再次调用 RPC，也不会调用 Honeypot.is。

## 启动与独立 quota

在仓库根目录执行。先离线生成或核对计划：

```zsh
.venv/bin/python scripts/scam/run_pipeline.py \
  --task rug_pull --snapshot tokenscout-eligible-1500-v2 \
  --stage collect --graph-run recent-v1 \
  --settings data/scam/rug_pull/tokenscout-eligible-1500-v2/settings.json
```

新的账号只传给新启动的采集进程。用隐藏输入避免把 Key 写进命令历史：

```zsh
read -rs 'RUG_PULL_KEY?输入 Rug Pull 的 Etherscan Key: '
print
ETHERSCAN_API_KEY="$RUG_PULL_KEY" \
ETHERSCAN_QUOTA_FILE="$PWD/.runtime/etherscan/rug-pull-secondary.sqlite3" \
.venv/bin/python scripts/scam/run_pipeline.py \
  --task rug_pull --snapshot tokenscout-eligible-1500-v2 \
  --stage collect --graph-run recent-v1 \
  --settings data/scam/rug_pull/tokenscout-eligible-1500-v2/settings.json \
  --allow-network --progress on
unset RUG_PULL_KEY
```

此命令在执行时才开始真实采集。新 quota 文件在首次 HTTP 请求时建立；
沿用同一账号重启时必须继续使用同一路径，以保留 24 小时用量记录。
更换文件不重置 Etherscan 服务端额度；不同账号才应使用不同账本。
已有 Honeypot 进程继续使用启动时的 Key 和默认
`.runtime/etherscan/quota.sqlite3`，无需重启或修改 local_secrets.py。
未设置 ETHERSCAN_QUOTA_FILE 时继续使用原默认路径。Key 和账本路径均不进入数据配方。

## 采集如何进行

1. 为全部冻结目标生成 `graph_runs/recent-v1/plan.json`，固定来源哈希和采样预算；
   将现有元数据验证结果关联到每个样本，不重选池或补选 Token。
2. 默认四个样本并发，共享新账号的请求预算：最多 2.5 次 HTTP 启动/秒，
   本地滚动 24 小时上限 95,000 次；命中缓存不扣请求，额度用尽自动等待。
   同一账号在其他程序的用量仍须计入服务端限制。
3. 对 Token 地址和所选池地址分别请求 Etherscan `getLogs`、`txlist`、
   `txlistinternal`。按截止区块向过去采样；普通/内部交易倒序分页，
   日志从最新区块范围向过去扫描，必要时拆分拥挤范围。
4. 默认每轮每种数据最多增加 100 条，最多三轮。达到图预算、源记录耗尽或
   记录预算时停止。复用现有二跳、fanout `[32,16]`、最多 512 节点和
   4,096 边的图配方。日志扫描可能产生多个 HTTP 请求，因此不是固定
   每样本 18 次调用，也不能仅按样本数准确估算时间。
5. 标准化后保存可重放的压缩事件、coverage、审计和校验和引用。
   成功发布共享事件后才清理该样本私有 raw scratch；失败现场保留。
   有界采样完成不等于完整生命周期交易采集。
6. DNS、断连、超时等传输失败进入 runner 自动重试，默认最多 20 次尝试；
   鉴权失败或校验和损坏停止。样本自身的空图/数据质量失败保留排除原因，
   不伪造记录、不补选标签。加 `--strict-collection` 可将此类失败保留为待重试。
   3,112 是冻结的采集目标数，最终可用图数可能更少。

进度显示两个固定进度条；持久状态位于
`graph_runs/recent-v1/progress.json`，其中包含实际 quota 路径。
重复原启动命令即可续跑，已完成的样本和共享观测复用。

## 构图与其他阶段

采集完成后离线构图：

```zsh
.venv/bin/python scripts/scam/run_pipeline.py \
  --task rug_pull --snapshot tokenscout-eligible-1500-v2 \
  --stage collect --graph-run recent-v1 \
  --settings data/scam/rug_pull/tokenscout-eligible-1500-v2/settings.json \
  --progress on
```

`collect` 会为采样停止条件计算临时图，但不发布最终图集。
`build-graphs` 从留存事件生成 `graphs.jsonl`、逐样本图和 graph_manifest.json，
不发起网络请求。`graphs` 连续执行 plan → collect → build-graphs。
`--stage status --graph-run recent-v1` 查看状态；任一阶段加 `--dry-run` 可只验证计划。
试采样用独立的 `--graph-run pilot-v1 --graph-limit 10`，不能覆盖正式计划。
改变来源、池、截止时间或图预算须另建快照/graph-run，不能原地改变已冻结输入。

`all/evidence` 仍只做标签准备。`prepare-training` 离线准备监督和划分；
拟合通过 run_pipeline --stage train 单独执行，命令见训练准备说明。
