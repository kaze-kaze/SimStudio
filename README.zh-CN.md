<div align="center">
  <h1>SimStudio</h1>
  <p><strong>将工程需求转化为可审查、可追溯的 ANSYS Mechanical 仿真结果。</strong></p>
  <p>Codex Skill · 确定性仿真编译器 · <code>ansys-sim</code> CLI</p>
  <p>
    <a href="https://github.com/kaze-kaze/SimStudio/actions/workflows/ci.yml?query=branch%3Amain"><img src="https://github.com/kaze-kaze/SimStudio/actions/workflows/ci.yml/badge.svg?branch=main" alt="main 分支 CI"></a>
    <img src="https://img.shields.io/badge/Python-3.11--3.13-3776AB?logo=python&amp;logoColor=white" alt="基础 CLI：Python 3.11–3.13">
    <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-2EA44F" alt="MIT 许可证"></a>
    <img src="https://img.shields.io/badge/Status-Alpha-F59E0B" alt="Alpha 阶段">
  </p>
  <p>
    <a href="README.md">English</a> · <strong>简体中文</strong><br>
    <a href="https://kaze-kaze.github.io/SimStudio/">在线首页</a> ·
    <a href="https://kaze-kaze.github.io/SimStudio/examples/gusseted-bracket/demo/">浏览实例</a> ·
    <a href="https://kaze-kaze.github.io/SimStudio/docs/reports/mechanical-test-2026-09-06.zh-CN.html">测试报告</a> ·
    <a href="#快速开始">快速开始</a>
  </p>
</div>

[![SimStudio — ANSYS Mechanical 双肋托架真实结果](docs/assets/overview.png)](https://kaze-kaze.github.io/SimStudio/examples/gusseted-bracket/demo/)

Images used courtesy of ANSYS, Inc. 封面由已记录的真实结果排版组成；工程校核状态仍为 **WARN**。

**SimStudio** 将经过审查的工程需求转化为明确的 `simulation.yaml`、保存的 Mechanical 脚本、可追溯的运行清单、数值校核和报告。Python 包名为 **`text-to-ansys`**，命令为 **`ansys-sim`**。Codex Skill 负责整理需求，确定性编译器让仿真设置可以检查、可以复现。

- **先审查，再求解。** 单位、材料、约束、载荷、作用范围与假设均明确记录。
- **从离线流程开始。** 无需 ANSYS 或许可证即可校验、编译和 dry-run；真实执行必须指定 `--execute`。
- **保留验证证据。** 使用 PyDPF 读取保存的数值结果，区分 `PASS`、`WARN`、`FAIL` 和 `NOT_RUN`。

## 真实工程实例与验证边界

一件 **240 × 160 × 188 mm** 的钢制设备托架，包含**两条圆角加强肋、8 个安装孔与偏心承载台**。背面全固定，前端面承受 **[1000, 1500, −500] N** 三向力，承载台 **4200 mm²** 面积上施加 **0.8 MPa** 压力，并计入 **12.0284 kg** 钢材的自重。输入采用精确材料名 `Structural Steel` 和显式**二次单元**。

**2026 年 9 月 6 日**的测试记录为 **5 项真实集成测试通过，对应 5 次真实求解，耗时 208.16 秒**。环境为 Windows 11、ANSYS Student Mechanical 2026 R1、CPython 3.13.2、PyMechanical 0.13.2 和 PyDPF 0.16.1，显式选择 `mechanical_batch`。组合载荷分别使用 **12、8、5 mm** 网格，随后以 5 mm 网格求解仅自重及两倍力／压力工况。全部为 `SOLVED`、`synthetic: false`，**工程校核总状态仍为 `WARN`**。

| 5 mm 组合工况：记录的量 | 结果 |
| --- | ---: |
| 网格 | 5 mm · 27,980 个节点 · 15,508 个单元 |
| 最大总位移 | 0.019348617 mm |
| 节点平均等效应力最大值 | 9.040418 MPa |
| 承载台平均 Z 位移 | −0.009268916 mm |
| 承载台平均／第 95 百分位等效应力 | 1.291825 / 2.027259 MPa |
| 支承节点反力合计 Z 分量 | +3977.967017 N |
| 最大位移变化，8 → 5 mm | 0.6556% / 5% 容差 |
| 扣除自重后全场相对 L2 误差 | 1.8077 × 10⁻¹¹ |

独立的**力平衡、力矩平衡、两次网格加密变化和全场线性校核均通过**。承载台统计量对节点等权计算，未作面积加权；支承反力为逐分量求和结果。全局应力峰值仅供审查，未作为强度验收条件。背面全固定代表理想刚性安装界面，未建模螺栓预紧、接触、滑移、焊缝细节或安装板柔度。

<details>
<summary><strong>查看 5 mm 网格与原始结果云图</strong></summary>

### 网格
![双肋托架真实网格](examples/gusseted-bracket/demo/assets/mesh.png)

Images used courtesy of ANSYS, Inc. 记录网格：27,980 个节点、15,508 个单元。

### 总位移
![双肋托架真实总位移云图](examples/gusseted-bracket/demo/assets/total-deformation.png)

Images used courtesy of ANSYS, Inc. 最大总位移为 0.019348617 mm。

### 等效应力
![双肋托架真实等效应力云图](examples/gusseted-bracket/demo/assets/equivalent-stress.png)

Images used courtesy of ANSYS, Inc. 节点平均最大等效应力为 9.040418 MPa。工程状态：`WARN`。

</details>

[静态实例](https://kaze-kaze.github.io/SimStudio/examples/gusseted-bracket/demo/) 展示全部 5 次求解、3 档网格和 **5 mm 组合工况**的原始导出图，无需启动求解器。完整容差、失败情况和来源见[测试报告](docs/reports/mechanical-test-2026-09-06.zh-CN.md)；数值可追溯至[输入规格](examples/gusseted-bracket/simulation.yaml)和[公开 JSON 摘要](docs/reports/evidence/2026-09-06/summary.json)。仓库中的规格以 **8 mm** 为名义网格，测试显式生成 12 / 8 / 5 mm 变体。

公开 JSON 是正式测试报告的数据附件。原始 JUnit、Mechanical 工程、RST 与本机日志保留在已忽略的本地归档中。**252 passed、20 skipped** 是上一轮托架验证的离线基线，不是本次文档替换后新执行的测试结果。旧悬臂梁仅作为 `tests/fixtures/cantilever` 内部解析回归夹具保留。

## 工作方法

1. **整理需求并审查** — Skill 将工程意图、假设与未决问题写入 `simulation_brief.md` 和严格校验单位的 `simulation.yaml`。
2. **校验并编译** — 通过 Schema 与工程前置检查，生成确定性的 Mechanical 计划与脚本；精确对象名和唯一作用范围让选择过程明确可查。
3. **先 dry-run，再显式执行** — 离线检查计划；准备好 Mechanical 主机及有效许可证后，按明确的求解请求使用 `--execute`。
4. **提取结果并报告** — PyDPF 提取数值，校核结果、报告和输入哈希记录实际执行内容及尚未验证的部分。

规格、编译器源代码和参考文档是事实来源。修复这些源文件后重新生成输出。用户提供的 Python 和自然语言不会作为源代码执行。

## 快速开始

### 1. 安装 CLI

基础 CLI 支持 **Python 3.11–3.13**。如需安装可选 ANSYS 客户端，推荐使用 **Python 3.13**；这些客户端在本项目中的支持范围为 **Python 3.12–3.13**。

```bash
git clone https://github.com/kaze-kaze/SimStudio.git
cd SimStudio
python -m venv .venv
```

Linux/macOS 使用 `source .venv/bin/activate` 激活环境，PowerShell 使用 `.\.venv\Scripts\Activate.ps1`，然后安装：

```bash
python -m pip install -e .
```

如需在 Windows 上直接调用环境内的可执行文件，避免调整 PowerShell 激活策略，请参考 [Windows 测试指南](docs/windows-testing.md)。

### 2. 离线运行双肋托架示例

```bash
ansys-sim doctor --json
ansys-sim validate examples/gusseted-bracket/simulation.yaml --json
ansys-sim compile examples/gusseted-bracket/simulation.yaml --out build/bracket-compile --json
ansys-sim run examples/gusseted-bracket/simulation.yaml --out build/bracket-dry-run --json
```

最后一条命令返回 `DRY_RUN`，不启动 Mechanical 进程。离线主机上的 `doctor` 可能报告求解器组件不可用。每次编译或运行都使用**新的或空的输出目录**。

检查 `normalized-simulation.yaml`、`mechanical-plan.json` 和 `generated-mechanical.py`；dry-run 还会保存 `execution-plan.json`、`verification.json`、`results-summary.json`、`report.md`、`run-manifest.json` 及 `inputs/` 输入快照。dry-run 不构成数值求解结果。

### 3. 显式执行 Mechanical

在已单独安装 Mechanical 并配置有效许可证的主机上安装客户端：

```bash
python -m pip install -e ".[ansys]"
```

托架规格已显式配置 `execution.backend: mechanical_batch`。在准备好的 Windows 主机上校验并 dry-run 后，执行：

```bash
ansys-sim run examples/gusseted-bracket/simulation.yaml --out build/bracket-real-01 --execute --json
ansys-sim inspect build/bracket-real-01 --json
ansys-sim report build/bracket-real-01 --json
```

上述命令求解名义 **8 mm** 工况。按 [Windows 测试指南](docs/windows-testing.md)串行执行完整的**五次求解研究**，其中包括封面使用的 5 mm 工况。Batch 是本机 Windows 上的显式选择，不会在连接失败后自动切换。早期本机 gRPC 握手失败，托架研究未重测该路径。安装客户端不会安装 Mechanical 或提供许可证。其他配置及其要求见[执行指南](skills/ansys-mechanical-static/references/mechanical-execution.md)。

## 日常操作

| 命令 | 用途 |
| --- | --- |
| `ansys-sim init <directory>` | 创建初始规格与需求简报 |
| `ansys-sim doctor --json` | 诊断环境和默认传输配置 |
| `ansys-sim validate <spec> --json` | 检查 Schema、单位、引用与工程约束 |
| `ansys-sim compile <spec> --out <directory> --json` | 保存计划、脚本和运行清单 |
| `ansys-sim run <spec> --out <directory> --json` | 默认 dry-run；明确请求真实求解时添加 `--execute` |
| `ansys-sim inspect <run-directory-or-rst> --json` | 检查已保存的运行数据或 RST 文件 |
| `ansys-sim report <run-directory> --json` | 从保存的产物重新生成报告 |

使用 `--json` 时，stdout 为机器可读输出，进度写入 stderr。退出码：`0` 成功，`2` 规格或工程校验，`3` 环境或许可证，`4` Mechanical 或求解，`5` 后处理，`6` 结果验证。

### 配合 Codex 使用

仓库包含 [`ansys-mechanical-static` Skill](skills/ansys-mechanical-static/SKILL.md) 和[本地插件市场配置](.agents/plugins/marketplace.json)。沿用现有的本地开发安装方式，将下方路径替换为检出目录的绝对路径：

```bash
codex plugin marketplace add /absolute/path/to/SimStudio --json
codex plugin add text-to-ansys@text-to-ansys-local --json
codex plugin list --json
```

安装后新建 Codex 任务，以刷新 Skill 发现。可以用仓库自带的示例开始：

> 为 examples/gusseted-bracket/simulation.yaml 准备一次 dry-run。检查单位、背面固定、三向力、偏心压力、自重和二次网格，说明五次求解的验收条件，展示生成的计划和未完成的校核。

## 支持范围与验证边界

**v0.1 范围：** Mechanical 小变形线性静力结构分析；使用精确对象名的 `.mechdat` / `.mechdb` 模板，或单个简单 STEP/STP 实体；支持固定约束、力、压力、重力、全局网格尺寸、位移、等效应力和反力结果。Schema 可以表达自定义各向同性材料参数，但真实材料创建仍被阻止，等待接口验证。

Fluent/CFX、非线性或瞬态物理、接触推断、任意装配体、模态分析、屈曲、疲劳、断裂和设计认证均超出本 Skill 范围。详见[支持范围约定](skills/ansys-mechanical-static/references/supported-scope.md)。

| 状态 | 含义与记录中的边界 |
| --- | --- |
| `PASS` | 检查已执行且满足其条件。记录中的托架套件通过 5 项用例，不代表设计获准使用。 |
| `WARN` | 需要工程审查。五次运行均保留 `stress_singularity_review: WARN`。 |
| `FAIL` | 必需条件未满足。早期本机 gRPC 尝试失败，托架研究未重测该路径。 |
| `NOT_RUN` | 检查缺少条件或尚未执行。缺失证据不得计为通过。 |

托架 CLI 对混合压力／重力载荷保留 `reaction_balance: NOT_RUN`，未启用的悬臂梁比较保留 `cantilever_analytical: NOT_RUN`。测试中的独立校核依据 CAD 属性计算力与力矩平衡。`stress_singularity_review` 仍为 `WARN`，安全系数（未指定屈服强度）和自动 `visual_review` 仍为 `NOT_RUN`。已记录的人工图片查看独立于自动校核。其他 Mechanical 版本、远程执行与一般应力峰值收敛尚未验证。

两次网格加密均满足位移 5%、承载台应力统计量 10% 的变化容差。线性校核保持自重不变，按节点 ID 和坐标对齐后比较 `u(2P+G) = 2u(P+G) − u(G)`。这些判据用于本算例，不构成全场误差上界。

SimStudio 辅助工程审查，不提供认证、设计批准或最终工程签署。详见[校核策略](skills/ansys-mechanical-static/references/validation-policy.md)与[完整测试报告](docs/reports/mechanical-test-2026-09-06.zh-CN.md)。

## 参与贡献与延伸阅读

从 [CONTRIBUTING.md](CONTRIBUTING.md) 和 [AGENTS.md](AGENTS.md) 开始。先运行与改动直接相关的检查，再执行：

```bash
python -m pip install -e ".[dev]"
ruff check .
pytest -q
```

普通测试不依赖 ANSYS、许可证或网络。真实测试必须显式设置 `ANSYS_AVAILABLE=1`；按照 [Windows 测试指南](docs/windows-testing.md)串行复现已记录的 batch 套件。未执行的集成应报告为 `NOT_RUN`，保留验收标准，并先修复源文件再重新生成产物。

- [Schema 参考](skills/ansys-mechanical-static/references/schema-reference.md) · [模板示例](examples/template-mode/README.md)
- [官方 API 对照](skills/ansys-mechanical-static/references/official-api-map.md) · [路线图](ROADMAP.md)
- [测试报告](docs/reports/mechanical-test-2026-09-06.zh-CN.md) · [安全问题报告](SECURITY.md)

## 许可与署名

采用 [MIT 许可证](LICENSE)。SimStudio 是独立开源软件，与 ANSYS, Inc. 及其关联公司没有隶属、背书或赞助关系。ANSYS、Mechanical、Workbench 等名称属于各自权利人的商标。署名与再分发说明见 [NOTICE](NOTICE)。请勿在公开问题或贡献中提交专有模型、求解器归档、许可证数据、凭据或私人路径。
