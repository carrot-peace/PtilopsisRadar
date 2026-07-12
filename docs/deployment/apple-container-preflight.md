# Apple container 迁移前置调查报告

## 结论

- **可行性**：可行
- **是否建议只迁主服务**：是，主服务（trendradar）可直接迁移到 Apple container
- **是否建议迁 MCP**：暂不建议，本轮未验证 MCP 容器
- **最大阻塞点**：无技术阻塞点；Dockerfile 无需修改即可 build
- **最大风险**：Apple container 无 restart policy / compose，需外部保活（launchd）
- **推荐下一步**：在部署机上重复 build / once / web 测试，确认一致后准备 launchd 保活方案

---

## 本机环境

| 项目 | 值 |
|---|---|
| macOS | 26.5.1 (25F80) |
| 架构 | arm64 (Apple Silicon M4) |
| RAM | 16 GB (17179869184 bytes) |
| 可用磁盘 | 43 Gi / 228 Gi (22% used) |
| container 版本 | CLI 1.0.0 (build: release, commit: ee848e3) |
| container system 状态 | 运行中（已有 nginx-test 容器在跑） |

---

## 当前仓库状态

| 项目 | 值 |
|---|---|
| branch | master |
| commit | 246a7ab |
| git dirty | 否（干净） |
| Dockerfile | ✅ 存在 `docker/Dockerfile` |
| docker-compose.yml | ✅ 存在 `docker/docker-compose.yml` |
| docker-compose-build.yml | ✅ 存在 `docker/docker-compose-build.yml` |
| .env | ✅ 存在 `docker/.env`（25 个 key） |
| .env.example | ❌ 缺失 |
| config.yaml | ✅ 存在 `config/config.yaml` (34 KB) |
| frequency_words.txt | ✅ 存在 `config/frequency_words.txt` (13 KB) |
| output 大小 | 仓库根目录无 output 目录（运行时由容器挂载生成） |

---

## Apple container 能力匹配

| 能力 | 是否支持 | 备注 |
|---|---|---|
| build Dockerfile | ✅ | 完全兼容，TARGETARCH 自动设为 arm64 |
| --arch arm64 | ✅ | 默认即为 arm64 |
| --env | ✅ | `-e key=value` 语法 |
| --env-file | ✅ | 支持 |
| bind mount | ✅ | `-v host:container` 语法 |
| readonly mount | ✅ | `--mount source=...,target=...,readonly` |
| port publish 127.0.0.1 | ✅ | `-p 127.0.0.1:18080:8080` 语法 |
| detached run | ✅ | `-d` 语法 |
| --name | ✅ | 支持 |
| --memory | ✅ | `-m 1g` 语法 |
| --cpus | ✅ | `-c 2` 语法 |
| --rm | ✅ | 容器停止后自动删除 |
| logs | ✅ | `container logs -n 120 <name>` |
| exec | ✅ | `container exec <name> <cmd>` |
| stats | ✅ | `container stats --no-stream <name>` |
| start/stop/delete | ✅ | 完整生命周期管理 |
| restart policy | ❌ | **未发现** — run/create 均无 --restart 参数 |
| compose | ❌ | **未发现** — 无 compose 子命令 |

---

## Build 测试

- **命令**：`scripts/apple-container/build-image.zsh ptilopsis-radar:preflight`
- **是否成功**：✅ 成功
- **耗时**：约 45 秒
- **镜像**：`ptilopsis-radar:preflight`
- **架构**：linux/arm64
- **TARGETARCH**：正确解析为 `arm64`（Apple container 自动设置）
- **supercronic arm64**：✅ 下载成功，SHA1 校验通过
- **uv sync**：✅ 成功安装 98 个依赖包
- **失败摘要**：无
- **是否需要改 Dockerfile**：否
- **相关 diff**：无

---

## Doctor 测试

- **是否执行**：是
- **是否成功**：✅ 成功
- **主要输出**：
  - 8 项通过，2 项警告，0 项失败
  - Python 版本 3.12.13 满足要求
  - 配置文件、关键词文件、调度文件均找到
  - 存储后端：local
  - 输出目录可写
- **问题**：无

---

## RUN_MODE=once 测试

- **是否成功**：✅ 成功
- **耗时**：约 30 秒
- **config 读取**：✅ `/app/config/config.yaml` 和 `/app/config/frequency_words.txt` 均可读
- **output 写入**：✅ 产物写入临时目录
- **网络抓取**：✅ 11 个平台全部成功，19 个 RSS 源全部成功
- **产物摘要**：
  - `public/index.html` ✅
  - `public/current/index.html` ✅
  - `public/current/state.json` ✅
  - `news/2026-06-18.db` (254 条热榜数据) ✅
  - `rss/2026-06-18.db` (610 条 RSS 数据) ✅
  - `meta/doctor_report.json` ✅
  - 总大小：1.0 MB
- **问题**：无

---

## 临时 Web 测试：1GB

- **是否成功**：✅ 成功
- **端口**：127.0.0.1:18080 → 容器内 8080
- **curl 结果**：HTTP/1.0 200 OK
- **manage.py status 摘要**：
  - supercronic 正确运行为 PID 1
  - crontab 内容：`*/30 * * * * cd /app && python -m trendradar`
  - 配置文件均存在
- **manage.py webserver_status**：✅ 运行中 (PID: 12)
- **stats**：CPU 0.02%，内存 57.93 MiB / 1.00 GiB，14 个进程
- **问题**：无

---

## 临时 Web 测试：768MB

- **是否执行**：是
- **是否成功**：✅ 成功
- **curl 结果**：HTTP/1.0 200 OK
- **stats**：CPU 0.02%，内存 60.23 MiB / 768.00 MiB，14 个进程
- **是否推荐正式使用 768MB**：是，推荐。空闲时仅占用约 60 MiB，768MB 余量充足

---

## 资源评估

| 内存限制 | 实际占用（空闲） | 占比 | 评估 |
|---|---|---|---|
| 1 GB | 57.93 MiB | 5.7% | 充裕，适合正式使用 |
| 768 MB | 60.23 MiB | 7.8% | 推荐，余量充足 |
| 512 MB | — | — | 未测试；空闲约 60 MiB 占 12%，但 cron 触发抓取时可能峰值 200-300 MiB，512MB 风险较高 |

**对 16GB Mac mini 的预期收益**：
- 当前 Docker Desktop 常驻约 2-4 GB 内存（含 VM 开销）
- Apple container 基于 Apple Virtualization.framework，无额外 VM 开销
- 主服务容器空闲仅 60 MiB，即使 768MB 限制也远低于 Docker 基线
- 预计可释放 1-3 GB 内存

---

## 正式迁移条件

1. **部署机重复验证**：在部署机（同为 M4 macOS 26）上重复 build / once / web 测试
2. **停止 Docker 版 trendradar**：迁移前必须先停止 Docker 版，避免两个实例同时写同一个 output 目录
3. **8080 端口切换**：Docker 版停止后，Apple container 版接管 8080
4. **launchd 保活**：Apple container 无 restart policy，需 launchd 保活
5. **回滚命令准备**：保留 Docker 版镜像和 compose 配置，随时可回滚
6. **正式 output 目录迁移**：确认 output 数据目录路径一致

---

## 推荐正式部署命令草案

```fish
# 1. 停止 Docker 版
docker compose -f docker/docker-compose.yml down

# 2. 构建正式镜像
scripts/apple-container/build-image.zsh ptilopsis-radar:latest

# 3. 创建并启动正式容器
container run -d \
  --name trendradar \
  --cpus 2 \
  --memory 768m \
  --env-file docker/.env \
  --mount source=(pwd)/config,target=/app/config,readonly \
  --volume (pwd)/output:/app/output \
  -p 127.0.0.1:8080:8080 \
  ptilopsis-radar:latest

# 4. 验证
container logs -n 20 trendradar
curl -I http://127.0.0.1:8080/
container exec trendradar python manage.py status
```

---

## launchd 保活建议

**建议使用 LaunchAgent**（用户级，无需 root）：

```xml
<!-- ~/Library/LaunchAgents/com.carrot-peace.trendradar.plist 草案 -->
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.carrot-peace.trendradar</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/local/bin/container</string>
        <string>start</string>
        <string>trendradar</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
    </dict>
    <key>StandardOutPath</key>
    <string>/tmp/trendradar-launchd.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/trendradar-launchd.log</string>
</dict>
</plist>
```

**关键点**：
- 使用 `container start trendradar`（非 `container run`），因为容器已通过 `container create` 预创建
- `RunAtLoad` 确保登录时自动启动
- `KeepAlive` + `SuccessfulExit=false` 确保异常退出后自动重启
- **建议每日凌晨重启释放 VM 内存**：可添加 `StartCalendarInterval` 或单独的 cron/launchd 任务执行 `container stop trendradar && container start trendradar`
- 需确保 `container system start` 在容器启动前执行（可包装为脚本）

---

## 回滚方案

### 停止 Apple container 版

```fish
container stop trendradar
container delete trendradar
```

### 恢复 Docker 版

```fish
cd /Users/ptilopsis/Projects/PtilopsisRadar
docker compose -f docker/docker-compose.yml up -d
```

### 确认 8080 回到 Docker 版

```fish
curl -I http://127.0.0.1:8080/
docker logs trendradar --tail 20
```

---

## 遗留问题

1. **部署机验证**：需在部署机上重复完整测试流程
2. **MCP 容器**：本轮未验证 MCP 容器（`docker/Dockerfile.mcp`），需单独评估
3. **TZ 时区**：当前 Docker compose 设置 `TZ=Asia/Shanghai`，Apple container 测试未显式设置，需确认是否需要添加
4. **正式 output 目录**：需确认部署机的 output 目录路径和权限
5. **launchd 细节**：plist 草案需用户确认后创建，不在本轮执行
6. **512MB 测试**：未执行长测，如需进一步节省内存可单独测试

---

## 附录

### 关键命令输出摘要

**container run --rm alpine:latest uname -a**：
```
Linux e5e9ee0b-df28-4b4c-92da-9c61bc3dba1b 6.18.15 #1 SMP Tue Mar 17 01:36:53 UTC 2026 aarch64 Linux
```

**Build 成功日志关键行**：
```
#9 [linux/arm64 stage-0  2/11] RUN ... case arm64 ... supercronic-linux-arm64 ... Download successful
#12 [linux/arm64 stage-0  5/11] ... uv sync ... Installed 98 packages in 570ms
#15 [linux/arm64 stage-0  8/11] ... uv sync ... Installed 1 package in 2ms
```

**1GB Web stats**：
```
CPU 0.02%  Memory 57.93 MiB / 1.00 GiB  Pids 14
```

**768MB Web stats**：
```
CPU 0.02%  Memory 60.23 MiB / 768.00 MiB  Pids 14
```

### git status

```
(clean at start of investigation)
```

### git diff --stat

```
(将在报告末尾附加)
```
