# 四任务统一离线入口

2026-10-23 流程契约修订。本文定义当前公共入口，取代各任务早期文档中
`all` 只准备数据以及任务专属 stage 的约定。标签、图配方、90/10 划分、
AP 早停和已保存模型均不改变。

从仓库根目录运行：

```bash
.venv/bin/python scripts/scam/run_pipeline.py --help
```

`chainrisk-scam` 和 `python -m research.scam` 是同一入口的别名，接受相同参数。
不再公开旧的 `chainrisk-scam train ...` 子命令。内部 `_commands.py` 仅供
流水线适配器和工程测试使用；旧 Task A token 训练脚本不属于这四个 Scam 任务。

## 固定阶段

| stage | 对四任务统一的完成条件 |
|---|---|
| `sources` | 来源冻结、必要的审计/验证及样本选择完成，得到可采集目标 |
| `collect` | 目标交易采集、标准化和图构建完成 |
| `prepare` | 图与监督通过准入，训练/验证划分及训练配置冻结 |
| `train` | 校验冻结输入，训练并导出预测、指标和完整模型包 |
| `all` | 顺序执行 `sources → collect → prepare → train` |
| `status` | 只读查看数据准备状态、图进度和已有模型 run |

`all` 和 `train` 必须指定 `--run NAME`。真实执行时，非空模型输出目录在
开始采集前就会被拒绝；使用新的 run 名称。仅处理数据时，按需单独调用前三个阶段。
旧的 `addresses/evidence/audit/discover/label/plan/verify/graphs/build-graphs/prepare-training`
不再是公共 stage。每次仅执行一个 stage 不会自动补跑之前的阶段。

## 各任务内部适配

| 任务 | sources | collect | prepare |
|---|---|---|---|
| Phishing | Forta/背景来源、队列与目标 | 地址交易、标准化、图 | 监督、划分及配置 |
| Ponzi | XBlock/Unica 验证、冲突排除、队列 | 历史地址交易、标准化、图 | 监督、划分及配置 |
| Honeypot | Trapdoor 审计、候选发现、API 标签与证据 | 图计划、截止点池验证、交易及图 | 混合来源准入、划分及配置 |
| Rug Pull | TokenScout 审计、池匹配/验证、目标冻结 | 图计划、交易及图 | 来源策略准入、划分及配置 |

必要的数据完整性检查继续在内部执行。删除的是独立诊断脚本，已有分析报告保留。
四个任务调用同一个训练调度器和训练实现，各自使用独立输入、权重和阈值。

## 使用示例

完整流程（真实执行；示例 run 名称须尚未使用）：

```bash
.venv/bin/python scripts/scam/run_pipeline.py --task phishing --snapshot forta-recent-v1 --stage all --run mean-sage-v2 --allow-network
.venv/bin/python scripts/scam/run_pipeline.py --task ponzi --snapshot xblock-unica-recent-v1 --stage all --run mean-sage-v2 --allow-network
.venv/bin/python scripts/scam/run_pipeline.py --task honeypot --snapshot trapdoor-api-v1 --graph-run all-recent-v1 --stage all --run sage-v2 --allow-network
.venv/bin/python scripts/scam/run_pipeline.py --task rug_pull --snapshot tokenscout-eligible-1500-v2 --graph-run recent-v1 --stage all --run sage-v2 --allow-network
```

新 Honeypot 图运行可用 `--graph-cohort both --historical-cutoff 2023-01-31T23:59:59Z`
及 `--settings PATH` 固定混合来源策略；已有图计划优先复用冻结选择。
token 任务的 `--graph-run` 默认 `recent-v1`，现有 Honeypot 模型应显式选 `all-recent-v1`。

分阶段处理同一个快照：

```bash
.venv/bin/python scripts/scam/run_pipeline.py --task ponzi --snapshot NEW --stage sources
.venv/bin/python scripts/scam/run_pipeline.py --task ponzi --snapshot NEW --stage collect --allow-network
.venv/bin/python scripts/scam/run_pipeline.py --task ponzi --snapshot NEW --stage prepare
.venv/bin/python scripts/scam/run_pipeline.py --task ponzi --snapshot NEW --stage train --run mean-sage-v1
```

`--epochs/--patience/--min-delta/--device/--architecture/--loss` 可用于 `all` 或 `train`；
参数覆盖记录到模型 run，不改写冻结数据。新来源选择参数只作用于相应数据阶段。
Ponzi 默认来源为保留的 `xblock-unica-recent-v1/sources/`，可用 `--source-snapshot` 指定其他来源。

## dry-run 与恢复

```bash
.venv/bin/python scripts/scam/run_pipeline.py --task rug_pull --snapshot tokenscout-eligible-1500-v2 --graph-run recent-v1 --stage all --run sage-v1 --dry-run
.venv/bin/python scripts/scam/run_pipeline.py --task ponzi --snapshot xblock-unica-recent-v1 --stage status
```

dry-run 不写文件、不联网、不拟合；已存在的 run 可以只读校验。
已有 prepared 数据时，`all --dry-run` 实际校验冻结输入及训练准入。
全新快照尚无下游输入，只输出完整计划，并明确标记训练校验待准备阶段完成；
这不代表已验证未生成的数据。单阶段 dry-run 会检查该阶段已有的前置输入。

数据采集保留有界重试、缓存复用和已冻结失败排除规则。任何阶段失败都阻止下游训练。
Phishing/Ponzi 的 `all --drop-failed` 先重试，随后仅把允许排除的样本失败交给 prepare 审核。
provider/配额/完整性错误不可绕过。已完成模型不可覆盖，尚不支持优化器状态恢复。

训练数据位于 `data/scam/<task>/<snapshot>/prepared/`；token 任务位于
`graph_runs/<graph-run>/prepared/`。模型位于 `artifacts/scam/<task>/<snapshot>/<run>/`。
共享观察记录仍是复现依赖。90/10 验证集用于模型及阈值选择，没有独立测试集。
