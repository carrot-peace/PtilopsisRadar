# Apple container 镜像更新操作指南

适用场景：代码变更、依赖更新、Dockerfile 修改后，需要重建镜像并更新正式运行容器。

---

## 我要做哪种更新？

```
改了代码 / 依赖 / Dockerfile      → 场景 A：重建镜像（本文主线）
只改了 config/*.yaml / *.txt      → 场景 B：仅重启容器
只改了 docker/.env                → 场景 C：重建容器，不重建镜像
改了内存 / CPU 限制               → 场景 D：调整资源
出了问题，要退回 Docker 版        → 场景 E：回滚
```

---

## 场景 A：重建镜像（快速流程）

```fish
cd ~/PtilopsisRadar

# 0. 记录旧镜像 digest（万一需要回滚用）
container image list | grep ptilopsis-radar
# 输出示例：ptilopsis-radar  latest  501c71bfc79d  ...

# 1. 构建新镜像
container build --arch arm64 --tag ptilopsis-radar:latest --file docker/Dockerfile .
# 成功标志：最后一行包含 "ptilopsis-radar:latest"，无 error / failed
# 耗时：仅代码变更约 5s（缓存命中）；依赖变更约 60-90s

# 2. 卸载 launchd 保活（避免 supervisor 在空窗期抢先用旧参数重建容器）
bash -c 'launchctl bootout gui/$(id -u)/com.carrot-peace.ptilopsis-radar'

# 3. 停止并删除旧容器
container stop trendradar
container delete trendradar

# 4. 用新镜像启动容器
container run -d \
  --name trendradar \
  --cpus 2 \
  --memory 768m \
  --env-file ./docker/.env \
  --env TZ=Asia/Shanghai \
  --mount source=(pwd)/config,target=/app/config,readonly \
  --volume (pwd)/output:/app/output \
  -p 127.0.0.1:8080:8080 \
  ptilopsis-radar:latest

# 5. 重新挂载 launchd 保活
bash -c 'launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.carrot-peace.ptilopsis-radar.plist'

# 6. 验证
curl -I http://127.0.0.1:8080/
# 期望：HTTP/1.0 200 OK

container exec trendradar python manage.py status
# 期望：包含 "supercronic 正确运行为 PID 1"

container stats --no-stream trendradar
# 期望：内存 < 200 MiB（空闲态），CPU < 5%
```

> **为什么要 bootout / bootstrap？**
> supervisor 每 60s 巡检一次：容器不存在就重建，停止就重启。
> 如果不先 bootout，步骤 3 删除容器后 supervisor 会用旧参数抢先重建，导致步骤 4 报 "container already exists"。

---

## 场景 A：完整流程（含逐步验证）

### Step 0：确认变更内容

```fish
cd ~/PtilopsisRadar
git status --short
git log --oneline -5
```

确认你要更新的内容已就绪。

### Step 1：记录旧镜像 digest

```fish
container image list | grep ptilopsis-radar
```

把 DIGEST 列的值记下来（如 `501c71bfc79d`），构建失败时可用于确认旧镜像仍在。

### Step 2：构建新镜像

```fish
container build --arch arm64 --tag ptilopsis-radar:latest --file docker/Dockerfile .
```

构建失败时**不影响正在运行的容器**，排查后重试即可。

验证镜像已更新：

```fish
container image list
# 确认 ptilopsis-radar latest 的 DIGEST 与刚才不同
```

### Step 3：确认当前容器状态（快照）

```fish
container list --all
curl -Is http://127.0.0.1:8080/ | head -1
# 期望：HTTP/1.0 200 OK（这是切换前的基线）
```

### Step 4：卸载 launchd 保活

```fish
bash -c 'launchctl bootout gui/$(id -u)/com.carrot-peace.ptilopsis-radar'
```

### Step 5：停止并删除旧容器

```fish
container stop trendradar
container delete trendradar
```

此时 8080 释放，Web 短暂不可用。

### Step 6：启动新容器

```fish
container run -d \
  --name trendradar \
  --cpus 2 \
  --memory 768m \
  --env-file ./docker/.env \
  --env TZ=Asia/Shanghai \
  --mount source=(pwd)/config,target=/app/config,readonly \
  --volume (pwd)/output:/app/output \
  -p 127.0.0.1:8080:8080 \
  ptilopsis-radar:latest
```

### Step 7：重新挂载 launchd 保活

```fish
bash -c 'launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.carrot-peace.ptilopsis-radar.plist'
```

### Step 8：验证

```fish
# HTTP 可达
curl -I http://127.0.0.1:8080/
curl -I http://127.0.0.1:8080/index.html
# 期望：HTTP/1.0 200 OK

# 容器内部状态
container exec trendradar python manage.py status
# 期望：包含 "supercronic 正确运行为 PID 1"，crontab "*/30 * * * *" 有效

container exec trendradar python manage.py webserver_status
# 期望：包含 "运行中"

# 资源
container stats --no-stream trendradar
# 期望：内存 < 200 MiB（空闲态）

# 日志（无报错）
container logs -n 60 trendradar
# 关注：有无 Traceback / FATAL / OOM

# launchd 状态
bash -c 'launchctl print gui/$(id -u)/com.carrot-peace.ptilopsis-radar' | grep state
# 期望：state = running

# supervisor 已识别新容器
tail -n 5 ~/Library/Logs/PtilopsisRadar/trendradar-supervisor.log
# 期望：包含 "container trendradar is running"
```

### Step 9：回滚（如验证失败）

见下方「场景 E：回滚」。

---

## 场景 B：仅更新 config

config 目录是 bind mount，不需要重建镜像，重启容器即可。

```fish
cd ~/PtilopsisRadar
git diff -- config/    # 确认只有 config 变更

container stop trendradar
container start trendradar

sleep 3
curl -Is http://127.0.0.1:8080/ | head -1
# 期望：HTTP/1.0 200 OK

container exec trendradar python manage.py status
```

> 如需 cron 周期内立即生效，可手动触发：
> `container exec trendradar python -m trendradar`

---

## 场景 C：仅更新 .env

`.env` 通过 `--env-file` 在 `container run` 时注入，**热更新无效**，需要重建容器（不需要重建镜像）。

```fish
cd ~/PtilopsisRadar

bash -c 'launchctl bootout gui/$(id -u)/com.carrot-peace.ptilopsis-radar'
container stop trendradar
container delete trendradar

container run -d \
  --name trendradar \
  --cpus 2 \
  --memory 768m \
  --env-file ./docker/.env \
  --env TZ=Asia/Shanghai \
  --mount source=(pwd)/config,target=/app/config,readonly \
  --volume (pwd)/output:/app/output \
  -p 127.0.0.1:8080:8080 \
  ptilopsis-radar:latest

bash -c 'launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.carrot-peace.ptilopsis-radar.plist'

curl -Is http://127.0.0.1:8080/ | head -1
# 期望：HTTP/1.0 200 OK
```

---

## 场景 D：调整内存 / CPU

Apple container 不支持热调整资源限制，需删除重建容器。

```fish
# 1. 修改 plist 中的参数
nano ~/Library/LaunchAgents/com.carrot-peace.ptilopsis-radar.plist
# 找到 EnvironmentVariables，修改 TREND_RADAR_MEMORY / TREND_RADAR_CPUS

# 2. 重启 launchd
bash -c 'launchctl kickstart -k gui/$(id -u)/com.carrot-peace.ptilopsis-radar'

# 3. 删除旧容器，手动用新参数重建
container stop trendradar
container delete trendradar

container run -d \
  --name trendradar \
  --cpus <新值> \
  --memory <新值> \
  --env-file ./docker/.env \
  --env TZ=Asia/Shanghai \
  --mount source=(pwd)/config,target=/app/config,readonly \
  --volume (pwd)/output:/app/output \
  -p 127.0.0.1:8080:8080 \
  ptilopsis-radar:latest

# 4. 验证资源限制已生效
container stats --no-stream trendradar
# 确认 Memory limit 列已变为新值
```

---

## 场景 E：回滚

### E.1 回滚到上一个镜像版本

新代码有问题，但只需回滚代码，不需要退回 Docker 版：

```fish
# 停止有问题的容器
bash -c 'launchctl bootout gui/$(id -u)/com.carrot-peace.ptilopsis-radar'
container stop trendradar
container delete trendradar

# ⚠️ 注意：latest 标签已被新镜像覆盖，无法直接用镜像回滚。
# 代码回滚选项：
#   git revert HEAD && container build ...（重建旧代码的镜像）
#   或通过 .env 旋钮关闭新功能（无需重建镜像），见各 PR 的"回滚开关"
```

> 如需精确镜像回滚，在下次重大变更前先用「安全构建」保留旧标签（见下节）。

### E.2 回滚到 Docker 版

Apple container 版出现无法解决的问题时使用：

```fish
# 1. 卸载 launchd 保活（必须先做，否则 supervisor 会与 Docker 版争抢 8080）
bash -c 'launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.carrot-peace.ptilopsis-radar.plist' 2>/dev/null

# 2. 停止 Apple container 版
container stop trendradar
container delete trendradar

# 3. 确认 8080 已释放
lsof -nP -iTCP:8080 -sTCP:LISTEN
# 期望：无输出

# 4. 恢复 Docker 版
docker compose -f docker/docker-compose.yml up -d trendradar

# 5. 验证
sleep 5
curl -Is http://127.0.0.1:8080/ | head -1
docker compose -f docker/docker-compose.yml ps
# 期望：HTTP 200，trendradar Up
```

---

## 安全构建（重大变更推荐）

在覆盖 `latest` 前先用临时标签构建，验证通过再正式切换：

```fish
# 1. 用 canary 标签构建
container build --arch arm64 --tag ptilopsis-radar:canary --file docker/Dockerfile .

# 2. 启动 canary 容器在测试端口验证
container run -d \
  --name trendradar-canary \
  --cpus 2 \
  --memory 768m \
  --env-file ./docker/.env \
  --env TZ=Asia/Shanghai \
  --mount source=(pwd)/config,target=/app/config,readonly \
  --volume (pwd)/output:/app/output \
  -p 127.0.0.1:18080:8080 \
  ptilopsis-radar:canary

curl -Is http://127.0.0.1:18080/ | head -1
container exec trendradar-canary python manage.py status

# 3. canary 验证通过后，清理测试容器，再走场景 A 正式切换
container stop trendradar-canary
container delete trendradar-canary

# 4. Apple container 不支持 tag，重新 build 打 latest（缓存命中，秒完成）
container build --arch arm64 --tag ptilopsis-radar:latest --file docker/Dockerfile .
# 然后继续场景 A 的步骤 2-8
```

---

## 排查清单

| 现象 | 检查命令 | 期望结果 |
|------|---------|---------|
| 8080 无响应 | `lsof -nP -iTCP:8080 -sTCP:LISTEN` | 有输出说明有进程在监听（若无说明容器未起） |
| 容器未启动 | `container list --all` | 确认 trendradar 是否存在及 STATE |
| 容器反复重启 | `container logs -n 100 trendradar` | 找 Traceback / FATAL / OOM |
| supervisor 不重建 | `tail -n 30 ~/Library/Logs/PtilopsisRadar/trendradar-supervisor.log` | 有无 "missing" 或 "not running" |
| launchd 未启动 | `bash -c 'launchctl print gui/$(id -u)/com.carrot-peace.ptilopsis-radar'` | `state = running`？ |
| 内存持续增长 | `container stats --no-stream trendradar` | 空闲态应 < 200 MiB |
| 构建失败 | `container system start` 是否正常 | `network error` 通常是网络问题 |

---

## 关键路径

| 项目 | 路径 |
|------|------|
| Dockerfile | `docker/Dockerfile` |
| 环境变量 | `docker/.env` |
| config 目录 | `config/`（bind mount 只读） |
| output 目录 | `output/`（volume 读写） |
| supervisor 脚本 | `scripts/apple-container/trendradar-supervisor.zsh` |
| launchd plist | `~/Library/LaunchAgents/com.carrot-peace.ptilopsis-radar.plist` |
| supervisor 日志 | `~/Library/Logs/PtilopsisRadar/trendradar-supervisor.log` |
| AI Agent 操作协议 | `docs/deployment/apple-container-rebuild-agent.md` |
