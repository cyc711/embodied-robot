# 具身养老 / 社区巡检机器人仿真系统

> 2026 全国大学生"人工智能+"创新创业大赛 · 决赛作品（赛道：AI+公共服务 / 具身智能方向）
> 单人项目 · 指导老师：田梓琛（辅导员）
>
> **一句话**：在 Webots R2025a 仿真中跑通「自主巡逻 → 视觉发现异常 → 伺服抵近 → 停车告警 → 返回巡逻」的**具身智能闭环**，并为低成本社区养老安防服务提供"仿真先行、再落地实体"的技术路径。

---

## 1. 项目简介

针对社区独居老人增多、物业巡检人力不足的痛点，本项目用**仿真具身智能**打通"感知—决策—行动"：

- **感知层**：摄像头颜色阈值识别红色"异常块"（零算力门槛；接口兼容，可无缝替换为 YOLOv8 识别跌倒/烟雾/人员）。
- **决策层**：有限状态机 `PATROL → INVESTIGATE → ALERT`，具身决策核心。
- **控制层**：左右轮**编码器里程计**定位（无需 GPS/Compass）+ 视觉伺服（按画面偏移转向、按占比越近越慢）。
- **语义层**：抵近确认后，经**具身语义决策**（本地规则模板 / 可选 LLM）生成"疑似老人跌倒，建议派人核实"的自然语言研判，故障自动降级。

> 系统已在 Webots R2025a 中**真实跑通**完整闭环（见 `demo/headless_demo_output.txt` 与决赛演示视频）。

---

## 2. 目录结构

```
embodied_robot/
├── worlds/
│   └── community.wbt              # ★社区仿真世界（12×12m 场地 + Pioneer3dx + 红色异常块）
├── controllers/
│   └── webots_controller/         # ★核心控制器目录（Webots 实际运行的就是它）
│       └── webots_controller.py   #   v2.20 自包含：感知+决策+控制+里程计+LLM 语义层
├── protos/                        # 本地 PROTO 与纹理（无需联网，clone 即可运行）
├── requirements.txt               # 仅 YOLO 扩展 / 无头原型所需；主流程零外部依赖
├── install.bat                    # Windows：一键把控制器复制到本机 Webots
├── demo/                          # 早期无头逻辑原型（详见第 4 节）
│   ├── run_headless.py            #   纯 Python 无头演示主程序
│   ├── web_demo.html              #   网页版演示
│   └── headless_demo_output.txt   #   无头演示输出样例（闭环日志）
├── sim/                           # 无头原型：2D 网格社区世界
├── perception/                    # 无头原型：感知（mock + 预留 YOLO 接口）
├── decision/                      # 无头原型：PATROL/INVESTIGATE/ALERT 状态机
└── README.md
```

> ★ 标记的文件是**最终交付与评审复现的主路径**。

---

## 3. 快速复现（Webots，真实闭环）

1. 安装 **Webots R2025a**（免费开源，https://cyberbotics.com/）。
2. 用 Webots 打开 `worlds/community.wbt`
   （**务必从仓库根目录打开**，Webots 才能定位 `controllers/webots_controller/` 与 `protos/`）。
3. 点 **Run（▶）**。控制台会先打印设备自检（`camera=Y left=Y right=Y 编码器=Y`），随后 "开始巡逻"。
4. 观察行为：
   - `PATROL`：4×4 m 方形路径巡逻（巡逻点 `(0,0)→(4,0)→(4,4)→(0,4)`），编码器里程计导航；
   - 摄像头发现红色异常块 → `INVESTIGATE` 视觉伺服抵近；
   - 红块占画面 ≥ `0.079` 且连续 3 帧确认 → `ALERT` **紧贴停车告警**（含 `[语义告警]` 研判日志）；
   - 停留约 5 s + 冷却后 → 返回 `PATROL`，闭环可重复。

**关键参数**（见控制器顶部常量）：`RED_AREA_ALERT=0.079`、`PATROL=[(0,0),(4,0),(4,4),(0,4)]`、
`WHEEL_RADIUS=0.0975`、`WHEELBASE=0.331`、`MAX_SPEED=6.28 rad/s`、`TIME_STEP=64 ms`。

---

## 4. 关于 `demo/`、`sim/`、`perception/`、`decision/`（早期无头原型）

这些是用**纯 Python（不依赖 Webots / GPU）** 在沙箱/本地验证「感知→决策→行动」具身逻辑的**原型**：

- `sim/world.py`：2D 网格社区世界（巡逻点、异常事件、相机可视范围判定）。
- `perception/detector.py`：感知 mock（无头用世界真值；预留 YOLO 真实模式接口）。
- `decision/state_machine.py`：`PATROL / INVESTIGATE / ALERT` 状态机原型。
- `demo/run_headless.py`：串起上述模块并打印闭环日志（`python demo/run_headless.py`）。

> ⚠️ **重要**：最终系统的感知 / 决策 / 控制 / 里程计 / LLM 语义层已**完整内联**在
> `controllers/webots_controller/webots_controller.py` 中（含视觉伺服、编码器里程计、故障降级、语义层等），
> 代码更完整、能力更强。无头原型仅用于"不装 Webots 也能看懂闭环逻辑"的教学/演示，二者是**平行实现，请勿混用目录**。

---

## 5. 技术亮点（与决赛计划书第 3 章对应）

1. **仿真先行范式**：先在数字社区验证策略，大幅降低实体部署风险与成本。
2. **颜色阈值感知**：零算力门槛；`Detector.detect()` 内部可一键替换为 YOLOv8，上层接口不变。
3. **编码器里程计**：Pioneer3DX 是 PROTO，无法插入 GPS/Compass → 改用左右轮编码器推算位姿，零额外硬件。
4. **视觉伺服"紧贴抵近"**：双通道比例控制，前进速度与转向增益随"离告警门槛的差距"同步收缩，远快近稳、不冲过也不原地打转。
5. **具身语义决策层**：本地规则模板（零网络）+ 可选 OpenAI 兼容接口（DeepSeek/通义/智谱），4 s 超时失败自动降级，**绝不抛异常影响运动**。
6. **真实工程迭代**：控制器历经 v2.0 → v2.20 二十余版迭代，逐一攻克 Webots API、里程计 NaN、误检、贴近转圈等真实坑（详见计划书 3.7 工程难点表）。

---

## 6. 可选：接入真实大模型研判

默认走本地规则模板生成研判文案。若想展示真大模型，运行前设置环境变量即可：

```bash
export LLM_API_KEY="你的密钥"
export LLM_BASE_URL="https://api.deepseek.com/v1"   # 可换通义/智谱等
export LLM_MODEL="deepseek-chat"
```

不设 `LLM_API_KEY` 时自动回退本地模板，保证答辩现场零网络也能稳定演示。

> 更多设计细节、官方数据、量化测算与演示说明见决赛计划书《具身养老巡检机器人仿真_计划书初稿.md》。
>
> **演示视频**（2 分 12 秒，Webots R2025a 实录，完整闭环）：百度网盘 `https://pan.baidu.com/s/1MqBaY4RA2KgtTneNj9F8Ow`（提取码 `3ve8`）。

---

## 7. 许可证

MIT License —— 仅供比赛、教学与科研使用。
