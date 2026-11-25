<div align="center">

# AI Hub Core

**独立轻量 · 开箱即用的企业级 AI 智能体、技能（Skill）与 MCP 管理平台**

[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Vue 3](https://img.shields.io/badge/Vue-3.x-4FC08D?style=flat-square&logo=vue.js&logoColor=white)](https://vuejs.org/)
[![Element Plus](https://img.shields.io/badge/Element%20Plus-UI-409EFF?style=flat-square&logo=element&logoColor=white)](https://element-plus.org/)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-blue?style=flat-square)](#)

</div>

---

## 项目简介

**AI Hub Core** 是一个独立部署的 AI 能力中枢与智能体工作台，集成了 **Agent 对话与隔离运行时**、**Skill 技能全生命周期管理**、**MCP 服务接入与调试**、**提示词模板库**、**模型网关与多模型路由**、**知识库控制台**、**积分计费与用量看板** 等核心模块。

系统采用 **前后端分离架构 + 本地 JWT 账号体系**，无需依赖外部网关或统一身份认证服务，仅需启动后端（FastAPI）与前端（Vite + Vue 3）即可完整运行。

---

## 核心特性

| 模块 | 功能说明 |
| :--- | :--- |
| **Agent 工作台** | 支持默认助手与自定义专家 Agent，提供 SSE 流式对话、工具调用追踪、权限确认、工作区文件树、HTML/Markdown 实时预览与会话分享 |
| **Skill 技能中心** | 支持 `SKILL.md` / ZIP 导入、在线树形编辑、Git 同步（GitHub / GitLab）、版本发布（Release）、公开分享与安全审计 |
| **MCP 服务管理** | 支持 HTTP / SSE / Stdio 类型 MCP 服务注册、请求头加密存储、在线工具/资源探测与权限隔离 |
| **提示词与资产** | 支持系统提示词模板管理、自定义模型配置、模型网关（Model Gateway）凭证签发与兼容性校验 |
| **知识库控制台** | 支持对接阿里云百炼知识库，提供文件上传解析、检索测试与调用用量统计 |
| **积分计费与看板** | 内置个人/全局积分账户、每日额度领取、运行消耗实时结算、异常任务恢复及 Token/积分用量统计 |
| **独立本地鉴权** | 内置 `users` 用户表与 PBKDF2-SHA256 + HS256 JWT 认证，首次启动自动初始化管理员，提供后台用户管理界面 |

---

## 系统架构

```mermaid
flowchart LR
    Browser["Vue 3 前端工作台 (:15173)"] -->|"/api/* & /uploads/*"| Backend["FastAPI 后端服务 (:15174)"]
    Backend --> MySQL[("MySQL 业务库")]
    Backend --> Redis[("Redis 对话流缓存")]
    Backend --> Runtime["Agent Runtime Cell (Container / Native)"]
    Runtime -->|"内部凭证"| Gateway["Model Gateway (/api/model-gateway)"]
    Gateway --> Upstream["上游大模型 API"]
```

---

## 目录结构

```text
aihub-core/
├── backend/                  # FastAPI 后端
│   ├── main.py               # 应用入口与路由注册
│   ├── auth.py               # 本地 JWT 认证与默认管理员初始化
│   ├── models.py             # SQLAlchemy 数据模型（含 User / Skill / Mcp / Agent / Credit 等）
│   ├── database.py           # 环境配置与数据库连接
│   ├── agent_routes.py       # Agent 管理与对话接口
│   ├── agent_service.py      # Agent 运行编排与流式事件处理
│   ├── model_gateway.py      # 模型网关与用量采集
│   ├── enterprise_routes.py  # 工作台引导、全局设置与积分接口
│   ├── credit_billing.py     # 积分计费与对账逻辑
│   ├── knowledge_routes.py   # 知识库管理与检索代理
│   ├── git_routes.py         # Skill Git 同步接口
│   └── user_management_routes.py # 本地用户管理接口
├── frontend/                 # Vue 3 + Vite + Element Plus 前端
│   ├── vite.config.js        # 本地开发代理配置（/api -> :15174）
│   └── src/
│       ├── api/              # Axios 实例与业务 API 封装
│       ├── stores/           # Pinia 状态管理（auth / app）
│       ├── router/           # 路由与鉴权守卫
│       ├── components/       # 公共布局与导航组件
│       └── views/            # 登录页、公开广场、工作台与管理后台
├── .env.example              # 环境变量模板
└── start-local.ps1           # Windows 一键本地启动脚本
```

---

## 快速开始

### 1. 环境准备

- **Python** 3.11+
- **Node.js** 20+
- **MySQL** 8.0+
- **Redis** 5.0+（用于 Web 对话流式输出）

### 2. 配置环境变量

复制环境变量模板并填写数据库连接、Redis 及加密密钥：

```bash
cp .env.example .env
```

重点配置项说明：
- `DATABASE_URL`：MySQL 连接串，例如 `mysql+pymysql://root:password@127.0.0.1:3306/aihub`
- `REDIS_HOST` / `REDIS_PORT`：Redis 服务地址
- `JWT_SECRET_KEY`：本地 JWT 签名密钥（生产环境请务必修改为强随机串）
- `AGENT_CREDENTIAL_ENCRYPTION_KEY`：32 字节密钥，用于加密存储模型与 MCP 凭证

### 3. 启动后端与前端

**方式一：Windows 一键启动**

```powershell
.\start-local.ps1
```

**方式二：分别手动启动**

```bash
# 1. 启动后端（默认监听 15174）
cd backend
pip install -r requirements.txt
uvicorn main:app --host 127.0.0.1 --port 15174

# 2. 启动前端（默认监听 15173）
cd frontend
npm install
npm run dev
```

### 4. 访问系统

打开浏览器访问：[http://localhost:15173](http://localhost:15173)

- **默认管理员账号**：`admin`
- **默认管理员密码**：`admin123`（可通过 `.env` 中的 `DEFAULT_ADMIN_USERNAME` / `DEFAULT_ADMIN_PASSWORD` 自定义，仅在 `users` 表为空时自动初始化）

---

## 技术栈

- **后端**：FastAPI · SQLAlchemy · PyMySQL · Pydantic v2 · Redis · Claude Agent SDK · MCP
- **前端**：Vue 3 · Vite · Element Plus · Pinia · Vue Router · Axios · CodeMirror · ECharts
