# Apple container 镜像更新 — AI Agent 操作协议

> 本文档供 AI Agent（如 Claude Code）执行镜像更新时遵循。
> 阅读对象不是人类。所有命令假设工作目录为 `~/PtilopsisRadar`。

---

## 前置约束

- **绝对不要** `docker compose down`，不要删除 Docker 镜像/volume/compose 文件
- **绝对不要** 删除 `output/` 目录中的数据
- **绝对不要** 打印 `docker/.env` 中的真实 secret
- **绝对不要** 提交 commit（除非用户明确要求）
- **绝对不要** 迁移 MCP（trendradar-mcp 仍归 Docker）
- Apple container CLI 是 `container`，不是 `docker`
- fish shell 不支持 `$(...)`，涉及子命令替换时用 `bash -c '...'`

---

## 场景判定

执行前先判定属于哪种场景，走不同分支：

```
用户请求
├─ "更新镜像" / "rebuild" / "代码改了"  →  场景 A：完整重建
├─ "改配置" / "更新 config"              →  场景 B：仅 config
├─ "改 .env" / "换 key"                  →  场景 C：仅环境变量
├─ "改内存" / "改 CPU"                   →  场景 D：资源调整
└─ "回滚" / "恢复 Docker"               →  场景 E：回滚
```

---

## 场景 A：完整重建（代码/依赖变更）

### A1. 确认变更内容

```fish
cd ~/PtilopsisRadar
git status --short
git diff --stat
git log --oneline -3
```

记录变更范围。如果 `docker/Dockerfile` 有改动，特别标注。

### A1.5. 记录旧镜像 digest（回滚用）

```fish
container image list | grep ptilopsis-radar
```

将 DIGEST 列的值记录在输出中。

### A2. 构建新镜像

```fish
scripts/apple-container/build-image.zsh ptilopsis-radar:latest 2>&1
```

**成功判定**：输出包含 `ptilopsis-radar:latest`，无 `error`/`failed`。

**失败处理**：停止整个流程。构建失败不影响正在运行的容器，报告错误即可。

**耗时参考**：
- 仅代码变更（依赖未变）：~5s（缓存命中）
- 依赖变更：~60-90s
- Dockerfile 变更：~60-90s

### A3. 确认镜像已就绪

```fish
container image list
```

确认 `ptilopsis-radar latest` 的 DIGEST 与构建输出一致。

### A4. 停止旧容器

```fish
container stop trendradar
container delete trendradar
```

**成功判定**：两条命令各输出容器名，无 error。

**异常处理**：如果 `stop` 报 "not found"，说明容器已不存在，跳过 stop 直接 delete。

### A5. 启动新容器

```fish
container run -d \
  --name trendradar \
  --cpus 2 \
  --memory 768m \
  --env-file ./docker/.env \
  --env TZ=Asia/Shanghai \
  --mount source=/Users/ptilopsis/PtilopsisRadar/config,target=/app/config,readonly \
  --volume /Users/ptilopsis/PtilopsisRadar/output:/app/output \
  -p 127.0.0.1:8080:8080 \
  ptilopsis-radar:latest
```

**成功判定**：输出容器 ID 或名称。

**失败处理**：
- "Address already in use" → `lsof -nP -iTCP:8080 -sTCP:LISTEN` 检查谁占了端口
- "image not found" → 回 A2 检查 build
- "container already exists" → 重新执行 A4

### A6. 验证

按顺序执行，每步必须通过才继续：

```fish
# 等待容器初始化
sleep 5

# 1. 容器列表
container list --all
# 判定：trendradar STATE 为 running

# 2. HTTP
curl -I http://127.0.0.1:8080/
curl -I http://127.0.0.1:8080/index.html
# 判定：HTTP/1.0 200 OK

# 3. 管理状态
container exec trendradar python manage.py status
# 判定：包含 "supercronic 正确运行为 PID 1"

# 4. Web 状态
container exec trendradar python manage.py webserver_status
# 判定：包含 "运行中"

# 5. 资源
container stats --no-stream trendradar
# 判定：内存 < 500MiB（正常空闲态），无异常 CPU

# 6. 日志无报错
container logs -n 40 trendradar 2>&1 | tail -20
# 判定：无 Traceback / Error / FATAL / OOM

# 6.5 lifecycle package preview（绝不在验证阶段执行 enforce）
container exec trendradar env PTILOPSIS_CR_LIFECYCLE_ENABLED=1 \
  PTILOPSIS_CR_LIFECYCLE_MODE=preview \
  python -m trendradar.cr.lifecycle_runner
# 判定：output/cr/latest/lifecycle_report.json 已生成且 mode 为 preview

# 7. supervisor 已识别
scripts/apple-container/trendradar-supervisor.zsh --once
# 判定：退出码 0，日志包含 "health check passed"
```

### A7. 输出结果

```
result: 镜像更新完成。trendradar 正在运行，8080 可访问，supervisor 已识别。
```

Lifecycle 回滚：从 `docker/.env` 移除
`PTILOPSIS_CR_LIFECYCLE_ENABLED` 以 disabled；或保留 enabled 并将
`PTILOPSIS_CR_LIFECYCLE_MODE=preview`。环境变量变更后按场景 C 重建容器。

---

## 场景 B：仅更新 config

不涉及镜像重建。

```fish
cd ~/PtilopsisRadar

# 确认变更
git diff -- config/

# 重启容器（config 是 bind mount，重启即可生效）
container stop trendradar
container start trendradar

# 验证
sleep 3
container exec trendradar python manage.py status
```

如果需要 cron 周期内立即生效，可手动触发一次：

```fish
container exec trendradar python -m trendradar
```

---

## 场景 C：仅更新 .env

`.env` 在 `container run` 时通过 `--env-file` 注入，不会热更新。需要重建容器（不需要重建镜像）。

```fish
cd ~/PtilopsisRadar

# 停止旧容器
bash -c 'launchctl bootout gui/$(id -u)/com.carrot-peace.ptilopsis-radar'
container stop trendradar
container delete trendradar

# 用同镜像重建（参数同 A5）
container run -d \
  --name trendradar \
  --cpus 2 \
  --memory 768m \
  --env-file ./docker/.env \
  --env TZ=Asia/Shanghai \
  --mount source=/Users/ptilopsis/PtilopsisRadar/config,target=/app/config,readonly \
  --volume /Users/ptilopsis/PtilopsisRadar/output:/app/output \
  -p 127.0.0.1:8080:8080 \
  ptilopsis-radar:latest

bash -c 'launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.carrot-peace.ptilopsis-radar.plist'

# 验证（同 A6）
```

---

## 场景 D：资源调整（内存/CPU）

需要两步：修改 plist 环境变量 + 删除重建容器。

```fish
# 1. 编辑 plist（用 Edit 工具修改 TREND_RADAR_MEMORY / TREND_RADAR_CPUS）
nano ~/Library/LaunchAgents/com.carrot-peace.ptilopsis-radar.plist

# 2. 重启 launchd 使新参数生效
bash -c 'launchctl kickstart -k gui/$(id -u)/com.carrot-peace.ptilopsis-radar'

# 3. 删除旧容器（supervisor 下一轮巡检会用新参数重建）
container stop trendradar
container delete trendradar

# 4. 等待 supervisor 自动重建（最多 60s）
sleep 70

# 5. 验证
container stats --no-stream trendradar
container list --all
```

或者手动立即重建（不等 supervisor）：

```fish
container run -d \
  --name trendradar \
  --cpus <新 cpus 值> \
  --memory <新 memory 值> \
  --env-file ./docker/.env \
  --env TZ=Asia/Shanghai \
  --mount source=/Users/ptilopsis/PtilopsisRadar/config,target=/app/config,readonly \
  --volume /Users/ptilopsis/PtilopsisRadar/output:/app/output \
  -p 127.0.0.1:8080:8080 \
  ptilopsis-radar:latest

bash -c 'launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.carrot-peace.ptilopsis-radar.plist'
```

---

## 场景 E：回滚到 Docker 版

仅在 Apple container 版出现无法解决的问题时执行。

### E1. 卸载 launchd 保活

```fish
bash -c 'launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.carrot-peace.ptilopsis-radar.plist' 2>/dev/null
```

**必须先卸载 launchd**，否则 supervisor 会在 Docker 版启动后抢夺 8080。

### E2. 停止 Apple container 版

```fish
container stop trendradar
container delete trendradar
```

### E3. 确认 8080 已释放

```fish
sleep 2
lsof -nP -iTCP:8080 -sTCP:LISTEN
# 判定：无输出
```

### E4. 恢复 Docker 版

```fish
docker compose -f docker/docker-compose.yml up -d trendradar
```

### E5. 验证

```fish
sleep 5
curl -I http://127.0.0.1:8080/
docker compose -f docker/docker-compose.yml ps
docker logs --tail 40 trendradar
# 判定：HTTP 200，容器 Up，日志无报错
```

### E6. 输出结果

```
result: 已回滚到 Docker 版 trendradar。Apple container 版已停止，launchd 保活已卸载。
```

---

## 异常速查表

| 症状 | 命令 | 判定 |
|------|------|------|
| 8080 无响应 | `lsof -nP -iTCP:8080 -sTCP:LISTEN` | 无输出 = 端口未被占用，检查容器是否 running |
| 容器反复重启 | `container logs -n 100 trendradar` | 查找 Traceback / Error |
| supervisor 诊断失败 | `scripts/apple-container/trendradar-supervisor.zsh --once` | 按 `code=` 修复；漂移诊断要求 recreate |
| launchd 不启动 | `bash -c 'launchctl print gui/$(id -u)/com.carrot-peace.ptilopsis-radar'` | `state = running`？ |
| 内存持续增长 | `container stats --no-stream trendradar` | > 500MiB 空闲态异常 |
| 构建失败 | 检查 `container system start` 是否正常 | network error = 网络问题 |
| port 8080 被其他进程占用 | `lsof -nP -iTCP:8080 -sTCP:LISTEN` | 找到 PID，判断是否为残留容器 |

---

## 关键路径速查

| 项目 | 路径 |
|------|------|
| 仓库根目录 | `~/PtilopsisRadar` |
| Dockerfile | `docker/Dockerfile` |
| .env | `docker/.env` |
| config 目录 | `config/`（bind mount，只读） |
| output 目录 | `output/`（volume，读写） |
| supervisor 脚本 | `scripts/apple-container/trendradar-supervisor.zsh` |
| launchd plist | `~/Library/LaunchAgents/com.carrot-peace.ptilopsis-radar.plist` |
| supervisor 日志 | `~/Library/Logs/PtilopsisRadar/trendradar-supervisor.log` |
| container 日志快照 | `~/Library/Logs/PtilopsisRadar/trendradar-container.log` |
| launchd stdout | `~/Library/Logs/PtilopsisRadar/launchd.out.log` |
| launchd stderr | `~/Library/Logs/PtilopsisRadar/launchd.err.log` |
| 迁移报告 | `docs/deployment/apple-container-cutover.md` |
| 本协议 | `docs/deployment/apple-container-rebuild-agent.md` |
