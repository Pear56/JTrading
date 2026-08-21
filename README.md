# 📈 JTrading - RSI 策略与动态阈值回测项目

[![Daily RSI Check](https://github.com/Pear56/JTrading/actions/workflows/rsi_check.yml/badge.svg)](https://github.com/Pear56/JTrading/actions/workflows/rsi_check.yml)
[![Weekly Parameter Optimization](https://github.com/Pear56/JTrading/actions/workflows/weekly_optimization.yml/badge.svg)](https://github.com/Pear56/JTrading/actions/workflows/weekly_optimization.yml)
[![Send Confirmation](https://github.com/Pear56/JTrading/actions/workflows/send_confirmation.yml/badge.svg)](https://github.com/Pear56/JTrading/actions/workflows/send_confirmation.yml)
[![GitHub Pages](https://img.shields.io/badge/GitHub%20Pages-Deployed-success)](https://pear56.github.io/JTrading/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

JTrading 是一个基于 GitHub Actions 的自动化量化研究项目，围绕红利低波 ETF (512890) 提供：

- 交易时段小时级 RSI 信号更新（前端实时看板）
- 每周一次基础回测 + 动态参数优化
- 自动生成回测结果与 Markdown 报告

在线页面: https://pear56.github.io/JTrading/

---

## 当前数据快照（以仓库最新结果为准）

数据来源: `backtest/backtest_result.json`（`meta.generated_at = 2026-05-30 05:42:05`）

- 标的: 红利低波ETF (512890)
- 区间: 2019-01-18 到 2026-05-29
- 交易日: 1781
- 自然日: 2688

| 策略                         |  总收益 | 年化收益 | 最大回撤 | 交易次数 |    胜率 |
| :--------------------------- | ------: | -------: | -------: | -------: | ------: |
| RSI+波动率 动态调优          | 291.09% |   20.34% |   13.11% |       13 | 100.00% |
| RSI(15) 固定阈值基线 (32/77) | 256.71% |   18.85% |   13.11% |        8 | 100.00% |
| 买入持有 (512890)            | 132.47% |   12.14% |   16.57% |        0 |   0.00% |

对照资产（同区间）:

- 黄金ETF (518880): 总收益 251.48%，年化 18.61%
- 纳指ETF (159941): 总收益 243.01%，年化 18.22%
- 沪深300ETF (510300): 总收益 86.99%，年化 8.87%
- 标普500ETF (513500): 总收益 190.75%，年化 15.60%

说明:

- 页面与文档中的数字均应以 `backtest_result.json` 最新字段为准。
- 标普500数据已在回测脚本中加入失败兜底逻辑；若未来出现数据源异常，字段可能回落为 `null`。

---

## 核心策略

### 1) 固定阈值 RSI 基线

- RSI 周期: 15
- 平滑: EMA
- 买入条件: RSI < 32
- 卖出条件: RSI > 77

### 2) RSI + 波动率动态阈值

动态参数（最新）:

- `rsi_period`: 15
- `rsi_buy_base`: 34
- `rsi_sell_base`: 71
- `vol_window`: 48
- `k_vol`: -0.429324
- `vol_anchor`: 15.0

动态阈值:

$$
Buy = rsi\_buy\_base - k\_{vol} \cdot (Vol - vol\_anchor)
$$

$$
Sell = rsi\_sell\_base + k\_{vol} \cdot (Vol - vol\_anchor)
$$

其中波动率采用对数收益率滚动标准差年化:

$$
Vol = \mathrm{StdDev}\!\left(\ln\frac{P_t}{P_{t-1}},\;window\right)\sqrt{252}\times 100
$$

---

## 自动化架构

```mermaid
flowchart TD
    A["AKShare 数据"] --> B["rsi_check.py / backtest scripts"]

    subgraph GH["GitHub Actions"]
        C["rsi_check.yml<br/>北京 09:00-15:00 每小时"]
        D["weekly_optimization.yml<br/>每周六 10:00 北京时间"]
        E["send_confirmation.yml<br/>订阅确认"]
    end

    B --> C
    B --> D

    C --> F["docs/data.json"]
    C --> G["docs/dynamic_data.json 可选"]
    C --> H["docs/config.js"]

    D --> I["backtest/backtest_result.json"]
    D --> J["backtest/best_combined_params.json"]
    D --> K["docs/backtest_result.json"]
    D --> L["backtest/最新参数优化报告.md"]
    D --> M["backtest/策略对比报告.md"]

    F --> N["index.html"]
    G --> N
    K --> O["backtest.html"]
    K --> P["backtest_dynamic.html"]
```

---

## 页面说明

- `docs/index.html`: 小时级 RSI 信号看板（含动态阈值/波动率更新时间）
- `docs/backtest.html`: 周度回测快照（固定阈值与动态策略对比）
- `docs/backtest_dynamic.html`: 动态策略专题页

---

## 项目结构

```text
JTrading/
├── .github/workflows/
│   ├── rsi_check.yml
│   ├── weekly_optimization.yml
│   └── send_confirmation.yml
├── backtest/
│   ├── rsi_backtest.py
│   ├── combined_optimization.py
│   ├── generate_markdown_reports.py
│   ├── backtest_result.json
│   ├── best_combined_params.json
│   ├── 最新参数优化报告.md
│   └── 策略对比报告.md
├── docs/
│   ├── index.html
│   ├── backtest.html
│   ├── backtest_dynamic.html
│   ├── data.json
│   ├── dynamic_data.json
│   ├── backtest_result.json
│   └── config.js
├── github_action_runner.py
├── send_confirmation.py
└── requirements.txt
```

---

## 本地运行

```powershell
pip install -r requirements.txt

# 基础回测
python backtest/rsi_backtest.py

# 动态优化
python backtest/combined_optimization.py

# 生成报告
python backtest/generate_markdown_reports.py
```

---

## 风险提示

本项目仅用于研究与工程实践展示，不构成投资建议。

- 历史回测不代表未来表现
- 参数优化存在过拟合风险
- 实盘需计入交易成本、滑点与执行时延

---
## Star History

<a href="https://www.star-history.com/?repos=Pear56%2FJTrading&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=Pear56/JTrading&type=date&theme=dark&legend=top-left&sealed_token=omKm7IBeHu7s-e1FX_a9H-S7218b8qbrTWBhtHIfoyEPsSk3ZQMgV4dR5RJQHj6KyCQR9nTng5y3llI2GIsz5OtvnsfoHCFHyEITSMtdr4YodpXStFwBuA" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=Pear56/JTrading&type=date&legend=top-left&sealed_token=omKm7IBeHu7s-e1FX_a9H-S7218b8qbrTWBhtHIfoyEPsSk3ZQMgV4dR5RJQHj6KyCQR9nTng5y3llI2GIsz5OtvnsfoHCFHyEITSMtdr4YodpXStFwBuA" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=Pear56/JTrading&type=date&legend=top-left&sealed_token=omKm7IBeHu7s-e1FX_a9H-S7218b8qbrTWBhtHIfoyEPsSk3ZQMgV4dR5RJQHj6KyCQR9nTng5y3llI2GIsz5OtvnsfoHCFHyEITSMtdr4YodpXStFwBuA" />
 </picture>
</a>

## 许可证

[MIT License](https://opensource.org/licenses/MIT)
