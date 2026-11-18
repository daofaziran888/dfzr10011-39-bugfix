# 分布式采集调度引擎

面向大规模数据采集团队的分布式采集调度引擎。覆盖采集节点集群管理、任务分片调度、结果聚合归并、节点健康监控、采集流量均衡、断点续采恢复与全局采集看板的完整分布式采集链路。

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/            每个业务模块一个页面
│   ├── src/api/              统一请求封装
│   ├── src/stores/           会话与筛选状态
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/          每个业务模块一组接口
│   ├── app/services/         业务规则与状态流转
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8000/api/health`

### 前端

```bash
cd frontend
npm install
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 采集节点集群 | `cluster` | 集群节点 | 节点编号、节点地址、节点角色 |
| 任务分片调度 | `shard` | 分片任务 | 分片编号、采集计划、分片范围 |
| 结果聚合归并 | `merge` | 聚合任务 | 任务编号、采集计划、分片总数 |
| 节点状态巡检 | `nodecheck` | 巡检记录 | 记录编号、节点编号、CPU使用率 |
| 采集流量均衡 | `balance` | 均衡策略 | 策略编号、负载算法、权重因子 |
| 断点续采恢复 | `resume` | 断点记录 | 断点编号、采集计划、断点位置 |
| 全局采集看板 | `dashboard` | 看板面板 | 面板编号、面板名称、显示指标 |
| 采集配置模板 | `crawlconf` | 配置模板 | 模板编号、模板名称、目标类型 |
| 采集数据源池 | `datasource` | 数据源条目 | 条目编号、数据源名称、源类型 |
| 采集日志解析 | `logparse` | 日志模板 | 模板编号、日志类型、解析规则 |
| 采集频率控制 | `ratelimit` | 频率规则 | 规则编号、目标站点、请求间隔 |
| 采集代理路由 | `proxy` | 代理配置 | 配置编号、代理地址、代理协议 |
| RPA执行记录 | `robot` | 执行记录 | 记录编号、流程模板、执行节点 |
| 采集结果校验 | `verify` | 校验规则 | 规则编号、采集计划、校验类型 |
| 采集操作审计 | `audit` | 审计记录 | 记录编号、操作类型、操作对象 |
| 采集存储分层 | `storage` | 存储策略 | 策略编号、存储层级、文件格式 |

## 约定

- 每个模块的前端页面在 `frontend/src/views/<模块>/index.vue`，后端接口在
  `backend/app/routers/<模块>.py`，业务规则在 `backend/app/services/<模块>.py`。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。
- 动作判定与字段输出只有一份实现：`app/services/template_actions.py`（判定、解析、版本快照）
  和 `app/services/base.py`（各模块共用的列表 / 登记 / 动作流程）。新模块只声明字段与状态序列。

## 采集日志解析 → 采集结果校验

日志模板的状态与解析规则绑定在同一个版本上（`logparse_versions`），版本号只在解析规则变化时前进。

| 接口 | 说明 |
| --- | --- |
| `POST /api/logparse/{id}/actions` | 启用 / 暂停 / 关闭模板；关闭是终态，其后不再产生结构化输出 |
| `POST /api/logparse/{id}/rule` | 修改解析规则，推进版本；已关闭的模板拒绝修改 |
| `POST /api/logparse/{id}/callbacks` | 解析回调，`callback_id` 幂等；关闭后回调被拒绝 |
| `GET /api/logparse/exceptions` | 异常日志清单：只含解析失败与回调拒绝 |
| `GET /api/verify/exception-logs` | 采集校验读取异常日志清单 |
| `GET /api/verify/checklist` | 修复日志模板动作核对清单（动作 / 结构化输出 / 异常依据） |
| `GET /api/verify/repair-queue` | 修复日志模板动作队列 |
| `POST /api/verify/refresh` | 其它业务入口改动模板后重算清单 |

关闭模板与解析回调同时提交时共用一把锁，两种结果都是确定且可继续的：

- 关闭先行并拒绝回调：模板显示已关闭，异常日志清单出现一条「回调拒绝」记录；
- 回调先行后再关闭：异常日志清单包含本次结果，模板关闭时间晚于回调记录时间。

解析失败保留原始字段并进入异常清单；正常日志不进异常清单；重复回调只确认一次。
`VERI-0002` 绑定 `LOGP-0002`，模板关闭后只能看到上一批完整结构化结果。

领域：数据工程
子方向：数据采集、爬虫与RPA
