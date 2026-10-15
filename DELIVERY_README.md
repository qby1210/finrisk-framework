# FinRisk 可运行项目成果交付说明

本交付包按“全部自产源码 + 可运行演示程序 + 工程设计文件 + 运行数据库 + 环境配置”组织。
压缩包不包含 Git 历史、虚拟环境、编译缓存、测试缓存、API 密钥、旧压缩包，也不复制
Python、Node.js 或其他开源软件及公共类库源码。

## 1. 最快运行方式

### Windows 10/11 x64

1. 安装 Python 3.11+、Node.js 22.19+ 与 npm，并确保命令可用；
2. 双击 `install.bat`，或在 PowerShell 中运行 `./install.ps1`；
3. 双击 `start.bat`；
4. 浏览器打开 <http://127.0.0.1:8000>。

安装脚本默认同时安装运行和测试依赖，以便评审直接执行完整测试。如只需演示，可运行：

```powershell
./install.ps1 -RuntimeOnly
./start.ps1
```

### Linux x64

```bash
bash install.sh
bash start.sh
```

系统启动后可访问：

- 工作台：<http://127.0.0.1:8000>
- OpenAPI 文档：<http://127.0.0.1:8000/docs>
- 健康检查：<http://127.0.0.1:8000/api/health>

健康检查应返回 `status: ok`，并显示 `case_count: 7628`。第一次执行案例检索会在内存中
构建 BM25/TF-IDF 索引，耗时会高于后续请求。

## 2. 运行环境与依赖

| 项目 | 要求 |
| --- | --- |
| 操作系统 | Windows 10/11 x64；或主流 Linux x64 |
| Python | 3.11+；本交付版本在 Python 3.13.5 验证 |
| Node.js / npm | Node.js 22.19+，用于运行 Pi Agent；安装脚本自动安装锁定的 npm 依赖 |
| 内存 | 建议 8 GB 或以上 |
| 磁盘 | 建议至少 2 GB 可用空间 |
| GPU/CUDA | 不需要 |
| 浏览器 | Edge、Chrome、Firefox 等现代浏览器 |
| 网络 | 首次安装第三方依赖时需要；本地回退演示和测试不需要 |

`requirements.lock.txt` 是精确锁定的运行依赖；`requirements-dev.lock.txt` 额外包含 pytest、
ruff、mypy 等测试工具；`uv.lock` 用于 uv 的完全可复现安装。安装脚本使用标准 `venv + pip`，
评审环境无需预装 uv。

`.env.example` 是运行配置模板，安装/启动脚本会在缺少 `.env` 时自动复制。交付包没有任何
真实 API Key。`DEEPSEEK_API_KEY` 留空时系统自动使用本地规则与案例检索流程，不会因外部
模型不可用而中断。若要启用 DeepSeek 完整流程，只需在本机 `.env` 中填写密钥。

## 3. 交付内容映射

| 要求 | 包内内容 |
| --- | --- |
| 全部自产源代码 | `src/`、`scripts/`、根目录安装/启动/验证脚本 |
| 可运行程序/演示包 | `src/api/`、`src/web/static/`、`start.bat`、`start.sh` |
| 工程设计文件 | `docs/architecture.md`、`docs/data_contracts.md`、`docs/query_pipeline.md` 等 |
| 模型与算法资产 | `src/query/`、`src/risk/`、`src/retrieval/`、`data/risk/keyword_db/` |
| 数据库文件 | `data/processed/knowledge/case_kb_v2_1_2026-08-23/`，共 7,628 条案例 |
| 样本与评测 | `data/raw/query/`、`tests/`、`outputs/query_test_set_160/` |
| 部署配置 | `.env.example`、`deploy/finrisk.service`、`deploy/nginx-finrisk.conf` |
| 依赖声明/安装包 | `pyproject.toml`、`uv.lock`、两个 requirements 锁定文件、安装脚本 |

本项目没有训练生成的独立专有模型权重，因此不存在应随包提交而缺失的 `models/` 或
`checkpoints/`。中文向量检索为自产 TF-IDF 实现，不需要下载权重或 CUDA；DeepSeek 是
可选外部服务；RapidOCR 等公共组件由依赖清单安装，其源码和虚拟环境不打入提交包。

## 4. 测试与完整性校验

Windows：

```powershell
./verify.ps1
```

或双击 `verify.bat`。Linux：

```bash
bash verify.sh
```

验证会依次检查交付必需文件、知识库字节数/SHA-256/行数、应用导入、Ruff、Mypy、Pytest、
前端 JavaScript 语法、原文位置映射测试和 Pi Agent 运行时测试。验证需要 Node.js。完整压缩包还包含
`PACKAGE_CONTENTS.txt` 与 `PACKAGE_MANIFEST.sha256`，可核对每个交付文件。

## 5. 明确未打包内容

- `.venv/`、`__pycache__/`、`*.pyc`、`.pytest_cache/`、`.mypy_cache/`、`.ruff_cache/`；
- `.git/` 与版本历史；
- 含真实密钥的 `.env`；
- 第三方公共类库及开源软件源码；
- 历史压缩包、临时目录、编译中间文件。

项目业务说明、API、指标与已知限制见根目录 `README.md`。
