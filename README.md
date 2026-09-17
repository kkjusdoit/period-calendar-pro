# 🌸 姨妈日历 Pro · Period Calendar & Care

<p align="center">
  <img src="app/static/images/logo.png" width="120" height="120" alt="姨妈日历 Logo" style="border-radius: 24px; box-shadow: 0 8px 24px rgba(250,82,120,0.25);" />
</p>

<p align="center">
  <b>专为爱人打造的高颜值、医学级智能生理期记录与双通道关怀提醒系统</b>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/FastAPI-0.100+-009688?logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/Vue.js-3.x-4FC08D?logo=vuedotjs&logoColor=white" alt="Vue3">
  <img src="https://img.shields.io/badge/TailwindCSS-3.x-38B2AC?logo=tailwind-css&logoColor=white" alt="Tailwind">
  <img src="https://img.shields.io/badge/Docker-Ready-2496ED?logo=docker&logoColor=white" alt="Docker">
  <img src="https://img.shields.io/badge/License-MIT-rose.svg" alt="License">
</p>

---

## 📖 项目初心

市面上的经期小程序或 App 普遍存在几个直戳痛点的问题：
1. **到处是广告与弹窗**，打卡一次要看几次推广；
2. **数据存放在第三方商业平台**，极具私密性的女性生理健康数据得不到隐私保障；
3. **提醒方式极其单一**：只能提醒女生自己，直男老公/男友根本接收不到同步提醒，经常错过最佳关怀时机；
4. **算法机械且呆板**：面对漏记、忘打卡或经期间隔异常，推算结果直接紊乱。

本项目**纯开源、私有化部署、零广告、高颜值**，不仅能自动推算生理周期与易孕窗口，更能**通过 QQ 邮箱与微信公众号服务通知，同时将温馨提醒准时推送到夫妻/情侣双方手机上**，让关怀无微不至。

---

## ✨ 核心亮点

### 1. 📊 现代女性健康数据看板 (Dashboard)
- **核心 KPI 卡片**：实时展示当前生理阶段（黄体期/经前期/月经期/排卵期）、下次来潮倒计时、近 10 年纯净平均周期、健康规律度评分；
- **全景走势图**：基于 Chart.js 绘制的历史周期天数折线波动图与经期持续天数分布直方图；
- **最近提醒状态**：首页一览最近一次提醒发送的时间、渠道与备忘概要。

### 2. 🧮 Calculator.net 临床黄金算法对齐
对标全球使用最广泛的 [Calculator.net](https://www.calculator.net/period-calculator.html) 算法，全面推演未来周期：
- **下次月经日**：支持标准设定周期（如 28天）或全历史纯净均值动态推算；
- **排卵日推算**：严格采用黄体期恒定 14 天法则（$D_{ovulation} = D_{next} - 14$）；
- **7 天易孕窗口 (Fertile Window)**：自动标定受孕黄金期（排卵前 5 天至排卵后 1 天）；
- **Naegele's Rule 临床预产期与试纸测试日推演**。

### 3. 🧹 异常数据智能诊断与清洗中心
面对现实中不可避免的记录偏差，系统内置分类诊断引擎：
- **疑似漏记识别（54 天左右）**：提供「一键智能拆分」，自动在中间补齐标准周期；
- **打卡忘记结束（如持续 49 天）**：提供「一键修正时长」，自动截断为标准 5~6 天；
- **孕产长停经 / 排卵期微量点滴出血**：自动打标识别并在计算正常均值时安全排除，不污染正常规律。

### 4. 💌 零点击无感双通道关怀提醒 (Zero-Click Preview)
- **QQ 邮箱通知**：
  - 采用前置折叠隐藏摘要技术（Hidden Preheader），**在手机通知栏或 Apple Watch 上抬腕一眼看清**来潮倒计时与备忘贴士，无需点开邮件；
  - 支持多接收人配置，自动同时推送至丈夫与妻子的两个 QQ 邮箱。
- **微信公众平台服务通知卡片**：
  - 基于微信官方公众平台测试号（Sandbox）模板消息机制；
  - **支持多关注者全员广播**：爱人只需微信扫一扫关注测试号二维码，系统到期即可自动向双方微信同步弹出微信原生服务通知卡片。

### 5. 🎨 极速轻量与精致交互
- 响应式支持移动端与桌面端自适应布局；
- 全新绘制的高清暖粉波浪爱心日历 Favicon 与 SVG 矢量图标；
- 移除所有冗余外部依赖，页面秒开，顺滑如原生 App。

---

## 🚀 快速开始

### 方式一：Docker Compose（推荐，1分钟部署）

1. **克隆代码并进入目录**：
   ```bash
   git clone https://github.com/kkjusdoit/period-calendar-pro.git
   cd period-calendar-pro
   ```

2. **配置环境变量（可选）**：
   ```bash
   cp .env.example .env
   # 按需编辑 .env（也可直接在网页端右侧设置抽屉中图形化配置）
   ```

3. **启动服务**：
   ```bash
   docker compose up -d
   ```

4. **打开浏览器访问**：
   访问 `http://localhost:3600` 即可开始使用！

---

### 方式二：本地 Python 运行

```bash
git clone https://github.com/kkjusdoit/period-calendar-pro.git
cd period-calendar-pro

# 安装依赖
pip install -r requirements.txt

# 启动 FastAPI 服务
uvicorn app.main:app --host 0.0.0.0 --port 3600
```

---

## ⚙️ 提醒服务配置指南

### 1. QQ 邮箱 SMTP 配置（免费稳定）
1. 登录电脑端 [QQ 邮箱网页版](https://mail.qq.com)；
2. 进入「设置」➔「账户」➔ 下滑找到「POP3/IMAP/SMTP/Exchange/CardDAV/CalDAV服务」；
3. 生成一组 **POP3/SMTP 授权码**（16位字母）；
4. 在网页右侧「设置」抽屉中填入：
   - 发件邮箱：您的 QQ 邮箱
   - SMTP 密码：刚才生成的授权码
   - 接收人列表：`your_wife@qq.com, your_email@qq.com`（英文逗号隔开）
5. 点击「发送测试邮件至双方 QQ 邮箱」即可实时验证。

### 2. 微信服务通知卡片配置（完全免费）
1. 电脑端打开并微信扫码登录 [微信公众平台接口测试账号](https://mp.weixin.qq.com/debug/cgi-bin/sandbox?t=sandbox/login)；
2. 页面中会获得 `appID` 与 `appsecret`；
3. 新增一个自定义模板：
   - 模板标题：`姨妈日历关怀提醒`
   - 模板内容填写：
     ```text
     {{header.DATA}}
     提醒日期：{{date.DATA}}
     当前状态：{{status.DATA}}
     周期推算：{{cycle.DATA}}
     关怀备忘：{{tips.DATA}}
     {{remark.DATA}}
     ```
4. 将生成的**模板 ID**（如 `t_D-Uy2-...`）填入网站设置中；
5. 让爱人用微信扫码页面上的测试号二维码进行关注；
6. 点击「发送测试微信卡片通知」，两人的微信都将同时收到服务通知卡片！

---

## 🔒 隐私与数据安全

- 所有的生理周期数据均持久化在您自己服务器的本地 SQLite 文件中（`data/period.db`）；
- 绝不向任何第三方或云端发送隐私健康数据；
- 支持在全量历史记录页面随时一键导出完整 JSON 备份。

---

## 📄 开源许可证

本项目基于 [MIT License](LICENSE) 开源发布，欢迎 Star 与 Fork！
