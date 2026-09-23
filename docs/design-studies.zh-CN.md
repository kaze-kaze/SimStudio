# 代理模型辅助设计研究

SimStudio 的设计研究工作流针对受控的单实体双肋托架参数族，使用 ANSYS Mechanical 线性静力求解，并记录不可变样本计划、求解证据、质量判断、数据集和模型来源、候选方案复核及可重建报告。工作流已在源码中实现；完整 Windows 真实 Mechanical 数据验收尚未完成。本文档不宣称模型精度、减重或提速。

## 安装与开始

建议使用 Python 3.13。从源码仓库安装离线、CAD 与数值计算依赖：

```console
python -m pip install -e ".[dev,study]"
ansys-sim study init build/bracket-inputs --json
```

`init` 会在新目录中写入 `study.yaml` 和 `base-simulation.yaml`。规划之前，请审查其中的单位、材料依据、载荷、参数范围、目标限值、网格尺寸和求解预算。`examples/bracket-study/` 中的托架文件是编写的演示输入，其验收限值不是生产要求。

从 `study.yaml` 生成计划，并在准备样本之前检查计划：

```console
ansys-sim study validate build/bracket-inputs/study.yaml --json
ansys-sim study plan build/bracket-inputs/study.yaml --out build/bracket-study --json
ansys-sim study status build/bracket-study --json
```

`plan` 写入可移植的 `study.yaml`、`base-simulation.yaml`、`study-plan.json` 和 `study-manifest.json`，但不生成 CAD。`study run` 才会为每个样本准备受控 CAD 和仿真输入，然后预览常规单次仿真工作流；只有显式给出 `--execute` 才会启动 Mechanical。要限制离线预览规模，请使用新的 study 目录和 `--limit 1`：

```console
ansys-sim study run build/bracket-study --limit 1 --json
ansys-sim study report build/bracket-study --json
```

不要把 `examples/bracket-study/base-simulation.yaml` 或 study 生成的 `base-simulation.yaml` 传给普通 `ansys-sim validate` 或 `ansys-sim run`。它们是供 study 使用的模板，依赖样本准备阶段生成的 `geometry.step`。通过 `study plan` 和 `study run` 使用它们，确保几何、不可变样本输入和哈希保持关联。

## 命令契约

CLI 返回状态 NOT_RUN 时退出码为 6。应保留该状态和退出码；没有符合条件的冻结 holdout 证据，就不算模型评估成功。

所有 study 和 surrogate 命令都支持 `--json`。默认执行方式是预览；`--execute` 才明确允许调用 Mechanical，但仍受 study 的求解次数和时间预算约束。`--limit` 只适用于 `study run`，限制新增设计点数量，不限制每点的网格级数。继续已有尝试必须使用 `--resume`。用户对一次有明确预算的 study 批次作出执行授权后，该授权涵盖预算内的全部样本；不要每个样本都暂停并重复询问批准。

| 命令 | 用途与边界 |
| --- | --- |
| `study init DIR` | 写入可编辑的起始输入；目标目录必须是新的或为空。 |
| `study validate STUDY.yaml` | 校验 study/base 输入、约束和采样，不启动求解器。 |
| `study plan STUDY.yaml --out DIR` | 创建可移植的不可变计划和身份清单。 |
| `study run DIR [--limit N] [--resume] [--execute]` | 生成每个样本的受控 CAD，并预览或串行执行网格任务。 |
| `study status DIR` | 查看 study 与样本执行状态。 |
| `study recover DIR` | 核验锁和任务进程停止后恢复本地陈旧锁，将遗留 RUNNING 尝试标记为 INTERRUPTED，并保留原记录。 |
| `study collect DIR [--reviews FILE]` | 评估已保存的真实 RST 证据，创建按版本记录、按目标区分的数据集。 |
| `study report DIR` | 根据保存的证据重建 HTML 和 Markdown 报告。 |
| `study export DIR --out ZIP [--kind task\|results]` | 创建带哈希校验的可移植任务包或结果包。 |
| `study import ZIP --out NEW_DIR [--expected-study-id ID]` | 校验数据包并导入全新目录。 |
| `study optimize DIR [--model PATH] [--execute]` | 提出受约束候选方案；执行需显式启用且受预算约束。 |
| `study verify DIR [--model PATH] [--reviews FILE] [--execute]` | 显式启用后用 Mechanical 确认候选方案。 |
| `study compare DIR [--reviews FILE] [--execute]` | 在记录的求解预算相同条件下比较直接搜索与代理搜索。 |
| `study workflow DIR [--resume] [--reviews FILE] [--execute]` | 编排带质量门槛的完整工作流；不带 `--execute` 时只准备预览并生成报告。 |
| `surrogate train DIR` | 用符合条件的训练行拟合模型，并安全地写出 JSON 模型文件。 |
| `surrogate evaluate DIR [--model PATH]` | 在冻结测试集上评估；评估后该 holdout 视为已使用。 |
| `surrogate predict MODEL_DIR --parameters JSON` | 根据模型目录预测；超出范围或不确定的请求应标记为需要真实求解。 |

工作流按串行方式运行，记录尝试、进程状态、耗时和求解次数，并支持经过核对的中断恢复。代码身份发生变化后，系统会拒绝继续复用该 study。保留生成的输入和证据。导入必须使用全新目录；数据包会校验文件哈希、study 身份、Schema 版本和代码指纹。运行导入的 study 时，必须使用创建它时相同的 SimStudio 代码指纹。

## 质量与模型证据

当前示例指定三个带单位的几何参数、带依据来源的目标限值、三档严格递进的网格、明确的采样种子以及求解次数/时间预算。其中 `max_solver_calls: 400` 是整个初始计划、自适应补样、候选复算、重试和等预算直接搜索对照共用的上限。此示例计划的初始网格求解预算为 120 次；400 是上限，不代表一定会用完。每次实际求解尝试都消耗这一个总预算。活动时间记录包含 CAD 准备、单次仿真、数据汇总、训练、候选搜索和评估，也记录失败分析耗时；不计等待审查的空闲时间。阶段入口检查时间预算，正在进行的数值拟合不会被强行中断。单次仿真耗时包含网格、求解和后处理；后端没有提供独立阶段计时时不会推算拆分。

演示位移限值为 `0.025 mm`，应力响应限值为 `10 MPa`。这两个值由作者参考已记录的基准响应设置（位移约 0.01935 mm，全局最大等效应力约 9.04 MPa）。10 MPa 是人工设定的响应约束，不是材料许用值、屈服值、强度批准或认证标准。即使设置了这两个限值，示例也不适用于生产决策。

样本划分为 baseline、training 和冻结的 test；后续自适应采样与候选验证会分别记录。数据按目标独立判断是否可用，必须具备所需数值和工程证据，并通过配置的网格收敛检查。

等效应力目标必须有可追溯的奇异性审查记录。审查文件以每个确切 RST 的 SHA-256 为键，记录 `status: PASS`、审查人、理由和非空证据引用。缺少审查时状态为 `REVIEW_REQUIRED`；针对其他 RST 的审查不适用。应在一次已获授权的 study 批次范围内集中审查保存的结果，无需逐个样本重新授权。不能根据缺失的 RST 或截图推断审查通过。

模型以经过校验的 JSON（`model.json` 与模型说明文件）保存，不使用 pickle。训练只读取符合条件的 training 行；holdout 评估会报告各目标指标及 false-safe 情况。预测不会调用 Mechanical；超出支持范围或超过不确定性限值时可能返回 `NEEDS_SOLVE`。优化建议不等于工程批准：必须用真实 Mechanical 证据确认候选方案、审查目标质量，并在相同求解次数预算下完成直接搜索对照，之后才能作比较结论。

必须先完成训练集优化、自适应补样和所有模型重训，再对最终模型执行一次冻结 holdout 评估。全部冻结测试点通过数据准入后，评估会锁定该模型并禁止在本 study 中继续重训或适应模型；测试数据尚不完整时不查看误差、不锁定模型。状态为 NOT_RUN 时 CLI 返回退出码 6，不得报告为成功。

字段和 Schema 说明见[设计研究英文总览](design-studies.md)，任务转移和 Windows 主机说明见 [Windows 执行指南](windows-study.md)，演示输入说明见[示例指南](../examples/bracket-study/README.md)。独立 Codex Skill 位于 [ansys-design-study](../skills/ansys-design-study/SKILL.md)。

## 验证状态

模型 Schema 1.1 把冻结测试设计 ID 绑定到模型，拒绝未预先规划的测试行，也禁止把冻结设计放入训练分组。评估分别保存总体、设计空间边界、约束附近的误差和两种约束误判；没有样本的分组显示 NOT_RUN，指标为 null。数据集和模型卡保留材料、载荷、支承、目标定义及运行环境。预测参数通过 JSON 文件提供，属性排列顺序不影响结果。

Mechanical 消息、所需结果、小变形和反力平衡检查不能从目标中删除；仅自重工况也必须核对实际选面。最终评估同时锁定模型路径和内容 ID。直接搜索对照固定计算额度时使用的设计与求解记录；证据变化时拒绝复用旧额度。报告分别展示已观察到的最佳设计和经过单独求解确认的推荐方案，并给出约束余量。工作流结论仅在记录及结果文件指纹仍匹配时显示。

新运行分别记录 Mechanical 内的网格、求解，以及命令进程中的后端、后处理和报告耗时；未记录阶段保持 NOT_RUN。网格和求解包含在后端总耗时内，预测和候选 CAD 包含在搜索耗时内，不能把父子阶段重复相加。

离线单元测试和 Linux/Windows Python 3.13 CI 会检查 study 与安装流程，不需要 ANSYS；这不能证明求解准确性。受控样本 CAD、字体和依赖兼容性、真实 RST 质量审查、模型 holdout 精度、候选求解及同预算对照，仍需在目标 Mechanical 安装环境中完成并留存 Windows 验收记录。在此之前，真实工程结果应记为 `NOT_RUN`，不要宣称已验证准确率、减重幅度或提速幅度。
