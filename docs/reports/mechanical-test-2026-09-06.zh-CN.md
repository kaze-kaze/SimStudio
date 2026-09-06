# Mechanical 测试报告 — 2026-09-06

## 结论

记录中的本机 Windows `mechanical_batch` 验收套件共 **9 项用例通过，对应 5 次真实求解**，失败、错误和跳过均为 0。JUnit 记录的开始时间为 `2026-09-06T02:42:49.859730-05:00`，总耗时为 194.345 秒。五次求解均有 `synthetic=false`、`SOLVED` 运行清单和 `POSTPROCESSED` 数值结果。**五个运行的工程校核总状态均保持 WARN。**

首轮真实 PyMechanical gRPC 尝试失败；batch 通过未建立 gRPC 已恢复的证据。远程执行保持 `NOT_RUN`。本报告结论限定于记录中的线性静力编译工作流及其具体校核条件。

默认套件的**历史基线为 175 passed、11 skipped，耗时 11.03 秒**。[公开 JSON 摘要](evidence/2026-09-06/summary.json)提供本报告记录的数据；历史基准不作为新一轮求解结果。

## 环境和方法

记录环境为 ANSYS Student Mechanical 2026 R1、Windows 11 AMD64、CPython 3.13.2、PyMechanical 0.13.2、PyDPF 0.16.1 和 DPF server 11.0。Student 产品身份依据本地归档的验收证据；运行时版本和结果已与最终 JSON、JUnit 核对。

基准采用 200 × 20 × 40 mm 钢梁，杨氏模量为 200 GPa，X-min 端面固定，X-max 端面施加沿 Z 方向的 −1000 N 力。五个运行均有 1077 个节点、160 个单元，网格全局尺寸为 10 mm，单元阶次为 `program_controlled`。

验收串行执行编译、显式本机 batch 求解、独立 DPF 提取、校核和报告生成。模板夹具有意改变坐标系、力分量、结果范围和方向、反力绑定；保存输出后，由新进程读取并检查对象设置。输入保全结论依据历史测试断言。

## 9 项验收用例

| JUnit 用例 | 运行及覆盖内容 | 状态 | 耗时（秒） |
| --- | --- | --- | ---: |
| `test_real_cantilever` | R1，悬臂梁数值验收 | PASS | 35.465 |
| `test_real_image_export[mesh.png]` | 复用 R1，网格 PNG | PASS | 0.001 |
| `test_real_image_export[total-deformation.png]` | 复用 R1，总位移 PNG | PASS | 0.001 |
| `test_real_image_export[equivalent-stress.png]` | 复用 R1，等效应力 PNG | PASS | 0.001 |
| `test_real_raw_rst_inspect_and_report` | 复用 R1，原始 RST 提取和报告再生成 | PASS | 3.269 |
| `test_real_pressure` | R2，面压力独立基准 | PASS | 34.591 |
| `test_real_gravity` | R3，重力独立基准 | PASS | 35.379 |
| `test_real_template_synchronization[.mechdat]` | R4，模板同步和保存后读回 | PASS | 42.889 |
| `test_real_template_synchronization[.mechdb]` | R5，模板同步和保存后读回 | PASS | 42.706 |

表中耗时直接取自 JUnit，不能作为纯求解器耗时。三项图片检查和原始 RST 检查复用 R1 产物，因此没有增加求解次数。PNG 判据要求对应导出记录唯一且为 PASS、文件超过 33 字节、PNG 签名和 IHDR 头合法、宽高均大于 0。这三项独立检查只覆盖 R1，其他运行的图片导出状态来自 JSON。

原始 RST 独立提取与基线的位移、应力、节点反力模最大值按规范化单位比较，容差为 `rel=1e-8, abs=1e-12`；反力合量向量容差为 `rel=1e-8, abs=1e-6 N`。历史断言确认报告再生成保持数值摘要及 RST 哈希。

两种模板的保存后读回均确认：力、方向位移和反力坐标系 ID 为 0，力为 `[0,0,-1000] N`，方向为 `ZAxis`，结果采用 `Component` 范围 `TTA_SCOPE_LOAD_FACE`，反力通过 `BoundaryCondition` 绑定至 `fixed_support`。

## 数值结果和容差

下表为舍入后的展示值。方向位移从载荷端面 37 个节点中选取分量绝对值最大的节点，并保留符号，不是端面平均位移。应力为 `stress_eqv_as_mechanical` 节点平均输出的最大值。

| 运行 | 端面方向位移（mm） | 最大总位移（mm） | 等效应力最大值（MPa） | 单节点反力模最大值（N） |
| --- | ---: | ---: | ---: | ---: |
| R1，力载荷 | Z: −0.127583025482 | 0.128950635781 | 38.0902173163 | 1564.25967035445 |
| R2，压力 | X: −0.000995021458 | 0.000995586612 | 1.19715891066 | 59.1860091398 |
| R3，重力 | Z: −0.000592845373 | 0.000597726930 | 0.230504482861 | 9.53210636828 |
| R4，.mechdat | Z: −0.127583025482 | 0.128950635781 | 38.0902173163 | 1564.25967035445 |
| R5，.mechdb | Z: −0.127583025482 | 0.128950635781 | 38.0902173163 | 1564.25967035445 |

**支承反力合量由固定支承范围内的 37 个节点反力逐分量求和。** 记录中的主要分量为：R1/R4/R5 的 Z 分量 `1000.0000000088805 N`，R2 的 X 分量 `799.999999999942 N`，R3 的 Z 分量 `12.317152400047146 N`；其他分量接近零。R1 的 `1564.2596703544452 N` 是节点 936 的单节点反力模最大值，不能用作支承反力合量。平衡检查使用 `canonical_sum_vector`，而非 `reported_maximum`。

- **力载荷：** 判据为 `||R + [0,0,-1000]||₂ / 1000 ≤ 0.05`，记录的相对残差为 `1.1759996441626767e-11`。Euler–Bernoulli 参考位移幅值约为 0.125 mm，误差定义为 `abs(abs(actual)-expected)/expected`，记录值为 `0.020664203857241034`，即约 2.0664%，低于 15% 容差。R4/R5 具有相同结果。
- **压力：** `pA = 1 MPa × 800 mm² = 800 N`。支反力向量与 `[800,0,0] N` 的距离须不超过 40 N；轴向位移以 −0.001 mm 为参考，采用 5% 相对容差。
- **重力：** `ρVg = 7850 × (0.2 × 0.02 × 0.04) × 9.80665 = 12.3171524 N`。支反力向量误差须不超过该重量的 5%。位移要求以 meter 表示、数值有限且为负；测试未设置重力挠度解析误差判据。
- **小变形：** 最大总位移除以 200 mm，力载荷、压力和重力的比值分别约为 0.000644753179、0.00000497793306、0.00000298863465，均小于 0.02，判为 PASS；区间 [0.02, 0.1) 为 WARN，达到或超过 0.1 为 FAIL。

压力和重力的独立基准断言通过，但通用 `reaction_balance` 和 `cantilever_analytical` 仍为 `NOT_RUN`。两项独立反力检查没有单独归档残差标量，本报告不补造其读值。

## 失败驱动的修复

Python 3.11 安装因 PyMechanical 0.13.2 要求 Python ≥ 3.12 而失败。恢复的输出确认退出码为 1，但内容带有截断，不能称为完整原文。首轮真实 gRPC 用例在 604.240 秒后失败，CLI 退出码为 4；包括 grpcio 1.71.0 在内的连接探针未解决问题。精确根因仍未闭合。batch 由显式选择启用，没有自动回退。

早期 batch 失败暴露了静力分析枚举、内置材料属性库存和结果范围 API 的兼容问题。实际导入实体名称与输入声明不符的问题通过修正输入解决。DPF 从读取不存在的等效应力属性改为使用 `stress_eqv_as_mechanical`；期间还发生过 batch 模块暂时缺失导致的导入故障，独立检查因此中断。

首次完整套件为 7 项通过、2 项模板失败。后续依次修复 IronPython Unicode 转换、只读范围属性赋值，以及更改 `Location` 前未清除已求值结果的问题。之后的空文本 Error 定位到模板夹具中未完整定义的附加坐标系；补全定义后，模板保存后读回通过，错误检查门槛得以保留。历史失败中曾出现原生进程退出码为 0、脚本仍失败的情况，因此成功判断必须同时检查结构化状态。

## 保留的 WARN 和 NOT_RUN

五个运行均保持 `stress_singularity_review: WARN`，固定端、载荷处和尖角附近的应力峰值仍需判断。v1 规范未提供用于安全系数计算的屈服强度，故 `safety_factor: NOT_RUN`；`visual_review` 也保持 `NOT_RUN`。无规格的原始 RST 检查中，工程校核和规格恢复为 `NOT_RUN`。

batch doctor 的 license、port、pymechanical、transport 预检保持 `NOT_RUN`。远程认证、传输及上传下载、真实 gRPC 超时和取消、网格收敛、显式单元阶次覆盖及其他 Mechanical 版本均未验证。历史默认套件的 11 项跳过包括 9 项需显式启用的真实用例，以及 2 项被 `WinError 1314` 阻止的原生符号链接检查；后两项仍为 `NOT_RUN`。

## 复现步骤

从仓库根目录按 [Windows 测试说明](../windows-testing.md) 执行：

1. 创建 Python 3.13 环境，安装 `.[dev,ansys]`，另行准备 Mechanical。
2. 按文档流程复制现有[悬臂梁规格](../../examples/cantilever/simulation.yaml)，保持几何路径可解析，并显式选择 `mechanical_batch`。
3. 执行 `doctor`、`validate` 和默认 dry-run，要求返回 `DRY_RUN`，并在真实执行前检查生成输入。
4. 如需显式真实求解，执行文档中的 `run --execute`、`inspect` 和 `report`。复现全部 9 项用例时，使用文档中的串行 pytest 命令，设置 `ANSYS_AVAILABLE=1` 和 `ANSYS_TEST_BACKEND=mechanical_batch`，结束后恢复这两个环境变量。输出目录和 pytest 临时目录均选择新目录。

## 公开证据与图片

公开 JSON 文件仅作为本正式测试报告的数据附件：[汇总](evidence/2026-09-06/summary.json)、[用例明细](evidence/2026-09-06/cases.json)、[来源信息](evidence/2026-09-06/provenance.json)。公开副本按字段白名单整理，保留精确数值、检查状态与来源哈希，排除机器私有路径和许可证诊断。原始 JUnit 和本机执行日志只保存在已忽略的本地归档中。使用 `python tools/export_benchmark_evidence.py` 可独立检查公开文件。

## 后续验证重点

扩大兼容范围前，应在支持的执行环境中复现 gRPC 握手问题，并增加第二个 Mechanical 版本的真实验收。将应力峰值用于设计判断前，应增加网格加密序列，复核固定端和载荷区域的应力集中。压力、重力的通用合力核验，以及显式单元阶次设置能否跨版本一致工作，仍是需要证据回答的问题。

[悬臂梁案例演示](../../examples/cantilever/demo/index.html)。以下为 Student 原始导出图：

- [网格](../../examples/cantilever/demo/assets/mesh.png) — Images used courtesy of ANSYS, Inc.
- [总位移](../../examples/cantilever/demo/assets/total-deformation.png) — Images used courtesy of ANSYS, Inc.
- [等效应力](../../examples/cantilever/demo/assets/equivalent-stress.png) — Images used courtesy of ANSYS, Inc.

导出记录证明产物可用，视觉工程审查仍待完成。后续采集的界面截图不能替代求解原图。部分早期运行清单停留在 `COMPILED`；空日志、截断输出和被重复使用的中间目录限制了历史重建。本报告不推断缺失的耗时、哈希或故障细节。
