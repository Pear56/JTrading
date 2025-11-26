# 📈 JTrading - 红利低波ETF (512890) 智能监控系统

[![Daily RSI Check](https://github.com/Pear56/JTrading/actions/workflows/rsi_check.yml/badge.svg)](https://github.com/Pear56/JTrading/actions/workflows/rsi_check.yml)
[![GitHub Pages](https://img.shields.io/badge/GitHub%20Pages-Deployed-success)](https://pear56.github.io/JTrading/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**JTrading** 是一个基于 GitHub Actions 的 Serverless 自动化交易辅助系统。它专为 **红利低波ETF (512890)** 设计，能够全自动监控 RSI 技术指标，提供现代化的可视化看板，并在出现买卖信号时通过多渠道发送提醒。

---

## ✨ 核心功能

### 1. 📊 现代化可视化看板
- **环形进度仪表盘**: 采用全新的环形进度条设计，视觉焦点集中，RSI 数值一目了然。
- **动态状态反馈**: 仪表盘颜色根据 RSI 状态（超买/超卖/中性）自动变化 (绿/红/灰)。
- **响应式布局**: 基于 CSS Grid 的自适应设计，完美适配桌面大屏与移动端设备。
- **深色模式**: 支持系统级 Dark Mode，夜间查看更护眼。
- **实时数据**: 展示最新价格、RSI 数值及明确的操作建议。

### 2. 🤖 全自动智能监控
- **交易时段巡航**: 仅在 A 股交易时段 (北京时间 09:00 - 15:00) 每小时自动运行一次，节省资源。
- **数据持久化**: 每次运行自动生成静态数据文件，驱动前端页面更新，无需后端服务器。

### 3. 🔔 多渠道即时通知
- **邮件推送**: 触发买卖阈值时，发送包含详细数据的 HTML 格式邮件。
- **微信提醒**: 集成 Server酱，支持微信端即时消息推送。
- **订阅管理**: 内置 Formspree 表单，支持访客自助订阅邮件提醒。

---

## 🏗️ 系统架构

本系统完全基于 GitHub 免费生态构建，零服务器成本：

```mermaid
graph LR
    A["GitHub Actions\n(定时任务)"] -->|运行 Python 脚本| B("数据抓取 & 分析")
    B -->|生成| C{"RSI 信号判定"}
    C -->|触发阈值| D["发送通知\n(邮件/微信)"]
    C -->|更新数据| E["生成 data.json"]
    E -->|部署| F["GitHub Pages\n(静态托管)"]
    G[用户] -->|访问| F
    G -->|订阅| H[Formspree]
```

## 📂 项目结构

```text
trading_rsi_app/
├── .github/workflows/
│   └── rsi_check.yml      # GitHub Actions 调度配置 (Cron: 0 1-7 * * *)
├── public/
│   ├── index.html         # 前端看板 (HTML5 + CSS3 + Vanilla JS)
│   └── data.json          # (自动生成) 最新监控数据
├── github_action_runner.py # 核心脚本: 爬虫、计算、通知、生成数据
├── requirements.txt       # Python 依赖库
└── README.md              # 项目文档
```

---

## 🚀 快速部署指南 (Fork & Run)

只需简单几步，即可拥有自己的监控系统：

### 1. Fork 项目
点击右上角 **Fork** 按钮，将仓库复制到您的 GitHub 账号下。

### 2. 配置 Secrets (敏感信息)
进入仓库 **Settings** -> **Secrets and variables** -> **Actions** -> **Secrets**，添加以下密钥：

| Secret 名称 | 必填 | 说明 | 示例 |
| :--- | :--- | :--- | :--- |
| `SENDER_EMAIL` | ✅ | 发件人邮箱 (SMTP) | `example@126.com` |
| `SENDER_PASSWORD` | ✅ | 邮箱 SMTP 授权码 | `abcdefghijklmn` |
| `SUBSCRIBER_EMAILS` | ✅ | 接收通知的邮箱 (逗号分隔) | `me@qq.com,you@126.com` |
| `FORMSPREE_ENDPOINT` | ✅ | Formspree 表单地址 | `https://formspree.io/f/xxxx` |
| `SERVERCHAN_KEY` | ❌ | Server酱 SendKey (可选) | `SCTxxxxxxxx` |

*(注: 默认使用 smtp.126.com。如需其他邮箱，请额外配置 `SMTP_SERVER` 和 `SMTP_PORT`)*

### 3. 配置 Variables (阈值参数)
进入 **Settings** -> **Secrets and variables** -> **Actions** -> **Variables**，添加变量：

| Variable 名称 | 默认值 | 说明 |
| :--- | :--- | :--- |
| `RSI_BUY_THRESHOLD` | `40` | RSI **低于** 此值触发买入提醒 |
| `RSI_SELL_THRESHOLD` | `70` | RSI **高于** 此值触发卖出提醒 |

### 4. 启用 GitHub Pages
1. 进入 **Actions** 页面，手动触发一次 "Daily RSI Check" 工作流。
2. 待运行成功后，进入 **Settings** -> **Pages**。
3. **Source** 选择 `Deploy from a branch`，分支选择 `gh-pages`，文件夹 `/ (root)`。
4. 保存后，您的看板将在 `https://<您的用户名>.github.io/JTrading/` 上线。

---

## 💻 本地开发

如果您想在本地修改前端或调试脚本：

1.  **安装依赖**:
    ```bash
    pip install -r requirements.txt
    ```
2.  **设置环境变量** (PowerShell 示例):
    ```powershell
    $env:SENDER_EMAIL="your_email@126.com"
    $env:SENDER_PASSWORD="your_password"
    # ... 其他必要变量
    ```
3.  **运行脚本**:
    ```bash
    python github_action_runner.py
    ```
    脚本运行后会在 `public` 目录下生成 `data.json`，您可以直接打开 `public/index.html` 查看效果。

---

## ⚠️ 免责声明

本项目仅供编程学习和技术交流使用，数据来源于网络，不保证准确性与实时性。**本项目不构成任何投资建议**。市场有风险，投资需谨慎。

## 📄 许可证

MIT License
