# 首次试用与反馈

[English](first-run-review.en.md) · [项目首页](../../README.md) · [维护与公开价值](../maintainer-impact.md)

目标是确认陌生用户能否独立安装、理解教学与研究的区别，并准确描述一次失败或成功。
**不需要交易所账户、钱包、API Key、资金或付费服务。** 下载及安装准备需要网络；安装后的
内置演示和固定案例复现不需要联网。无需部署服务器，也无需开启交易执行。

## 路径 A：只体验已发布安装包

从 [v0.5.0 官方仓库 Release](https://github.com/Lens-less/LensOS-Option/releases/tag/v0.5.0)
下载 `crypto_options_research_console-0.5.0-py3-none-any.whl` 和 `SHA256SUMS` 到一个新目录。
这不是 PyPI 安装，也不需要源码、Node 或 Chrome 扩展。使用 Python 3.12 或更高版本及普通浏览器。
当前 CI 覆盖 Windows/Linux 的 Python 3.12–3.14；macOS 不在该 CI 矩阵内。

在下载目录打开终端。先核对 wheel 的 SHA-256 与 `SHA256SUMS` 对应行一致；不一致就停止。

**Windows PowerShell：**

```powershell
python --version
Get-FileHash -Algorithm SHA256 .\crypto_options_research_console-0.5.0-py3-none-any.whl
Get-Content .\SHA256SUMS
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --no-index --no-deps .\crypto_options_research_console-0.5.0-py3-none-any.whl
.\.venv\Scripts\python.exe -m crypto_options_report.cli demo
```

**Linux/macOS 终端：**

```bash
python3 --version
# Linux 通常使用 sha256sum；macOS 可改用 shasum -a 256。
sha256sum ./crypto_options_research_console-0.5.0-py3-none-any.whl
cat ./SHA256SUMS
python3 -m venv .venv
.venv/bin/python -m pip install --no-index --no-deps ./crypto_options_research_console-0.5.0-py3-none-any.whl
.venv/bin/python -m crypto_options_report.cli demo
```

先确认所选 `python`/`python3` 至少为 3.12，再继续。无需激活虚拟环境；上述命令直接使用其 Python。
打开终端打印的本地地址，完成“选择示例 → 理解风险 → 查看依据”。拖动教学价格，观察损益，
然后选择“查看真实快照”。教学点数不是当前行情；研究快照应保留自己的时间与证据限制。
结束时在终端按 `Ctrl+C`，不要把本地服务暴露到公网。

## 路径 B：额外复现固定研究案例

这一步是可选的，需要 Git 和源码中的 `tools/reproduce_research.py`，不能把它当作 wheel 内置命令。
为避免混用构建，请另建目录，使用固定标签和新的虚拟环境：

```bash
git clone --branch v0.5.0 --depth 1 https://github.com/Lens-less/LensOS-Option.git LensOS-Option-v0.5.0
cd LensOS-Option-v0.5.0
git rev-parse HEAD
```

Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --no-deps .
.\.venv\Scripts\python.exe tools/reproduce_research.py --check
```

Linux/macOS：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --no-deps .
.venv/bin/python tools/reproduce_research.py --check
```

源码安装的构建工具准备可能访问包索引；不要把“复现离线”理解成“首次安装完全不联网”。
命令应报告 `repeatability=PASS`，并保留 `trust=untrusted`、`action=NO_TRADE`、
`admission=BLOCKED_BY_EVIDENCE` 和 `execution_allowed=false`。这是固定案例的预期阻断，
**不是要求你补账户、解锁交易，也不是盈利证明**。实际结果不同时记录原样差异，不修改数据制造通过。
更多说明见 [离线案例](reproducible-case.md)。

## 留下真实反馈

打开 [首次试用反馈](https://github.com/Lens-less/LensOS-Option/issues/new?template=first_run.yml)，
记录实际版本/提交、系统与 Python 版本、选择的路径、卡住步骤和期望行为。
未运行的步骤写“未运行”，不要把别人的结果复制为自己的体验。成功、失败和看不懂都欢迎；
不要求星标、好评或实盘使用。

只粘贴必要且脱敏的错误摘要。不要上传原始日志、私有快照、账户信息、邮箱、钱包地址、
密钥、Cookie、session、组织 ID 或包含这些信息的截图；移除用户名和本机绝对路径。
漏洞走 [私下安全报告](../../SECURITY.md)，不要公开利用步骤或敏感材料。

## 常见阻塞

| 现象 | 下一步 |
| --- | --- |
| Python 版本低于 3.12 | 选择已安装的较新解释器，再创建虚拟环境 |
| 找不到命令 | 用上面的虚拟环境 Python 和 `-m crypto_options_report.cli`，不要依赖全局 PATH |
| 本地端口被占用 | 关闭自己启动的旧实例后重试；不要随意终止不明进程 |
| Linux 缺少 venv 支持 | 按系统发行版说明安装对应 Python 的 venv 支持，记录为环境前置条件 |
| 页面显示证据不足或 `NO_TRADE` | 先查看快照时间与阻断原因；固定案例中这是预期行为 |
| 固定输入重复计算不同或页面错误 | 保留版本、步骤与脱敏摘要，提交反馈，不放宽校验 |

维护者会将已复现问题关联到修复 PR 或已知限制；一个反馈 Issue 不自动等于独立采用人数。
