# 私有 DecisionDesk 的部署交接

新研究台由同一 Python 进程提供静态页面与 `/desk/discover`、`/desk/compare`、`/desk/review`。
它不是一个只需上传静态文件的站点。现有暂停的公共证据发布流程不负责这套私有服务，不能通过取消暂停来部署它。

## 指定目标后运行原后端

需要已有、允许用于本项目的 Python ≥3.12 或 Docker 主机，以及最终的私有 HTTPS 域名。
部署前核实可用目录、现有 TLS/身份访问网关、进程管理与其他服务。只使用被明确指定的目标，不重用其他项目的站点或访问范围。

安装本分支构建出的 wheel（没有运行时依赖），在 TLS/私有访问网关后运行：

```sh
crypto-options-report-api \
  --runtime-profile production \
  --host 127.0.0.1 \
  --port 8000 \
  --allow-desk-live-fetch
```

配置 `CRYPTO_OPTIONS_API_ALLOWED_HOSTS` 为最终 Host，并把
`CRYPTO_OPTIONS_API_TRUSTED_ORIGINS` 设为同一完整 HTTPS origin。
已有 bearer 认证可通过 `CRYPTO_OPTIONS_API_BEARER_TOKEN_FILE` 沿用；token 不进入源码、浏览器、截图或 PR。
TLS 网关保留 Host/Origin，并为已认证请求在服务器端提供后端所需认证。页面和 API 保持同一 origin。
不要打开 CORS、放宽 Host 检查，或把本机 loopback 服务直接公开。

原 Dockerfile 同样包含新服务。使用镜像时可覆盖启动命令，增加上述 `--allow-desk-live-fetch`；
Python/socket/线程后端不能直接当作 Workers 服务器上传。
如果目标需要新账户、凭证、收费资源或访问权限变更，应先把具体需求交给所有者决定。

## 生命周期与数据

- 健康检查使用 `/livez`；它只证明进程存活。旧 `/readyz` 包含历史模型准备状态，不代表新研究台中某个结构可比较。
- 实时采集有一次 60 秒预算、进程共享限速、有限缓存和最多 24 条深层合约报价；快照不会因读取缓存而延长原始期限。
- 对比依赖仍存于该进程内的冻结分析。进程重启后先重新发现，不把浏览器旧快照当作新的对比输入。
- 观察原始记录只保存在用户浏览器；服务器不持久写入观察、笔记或用户交易资料。
- 不把原始行情、个人观察或私有证据打包成公共 fixture。线上访问应保持个人受限研究范围；公开行情 API 不自动授予再分发许可。

## 线上验收

先从服务外部核对 HTTPS、私有访问边界、静态资源和 `/livez`，再完成真实的发现 → 同到期比较 → 保存 → 刷新恢复 → 精确腿复核。
检查所有时间、币种、费用口径及分析身份；到期或缺失报价必须撤下当前使用资格。
最后从桌面与 390px 手机视口检查主流程。合成演示须持续标明合成来源，实际行情截图仅交给获授权的使用者。

当前仓库没有登记可用的 Option 主机、部署项目或线上域名。本文件是部署交接说明，不是已上线的证明。
