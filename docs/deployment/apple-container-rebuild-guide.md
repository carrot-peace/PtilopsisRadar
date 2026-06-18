# Apple container 镜像更新操作指南

适用场景：代码变更、依赖更新、Dockerfile 修改后，需要重建镜像并更新正式运行容器。

---

## 快速流程

```fish
cd ~/PtilopsisRadar

# 1. 构建新镜像
container build --arch arm64 --tag ptilopsis-radar:latest --file docker/Dockerfile .

# 2. 停止旧容器（launchd 保活会自动重建，但建议显式操作以避免端口冲突）
container stop trendradar
container delete trendradar

# 3. 手动启动新容器（使用新镜像）
container run -d \
  --name trendradar \
  --cpus 2 \
  --memory 1g \
  --env-file ./docker/.env \
  --env TZ=Asia/Shanghai \
  --mount source=(pwd)/config,target=/app/config,readonly \
  --volume (pwd)/output:/app/output \
  -p 127.0.0.1:8080:8080 \
  ptilopsis-radar:latest

# 4. 验证
curl -I http://127.0.0.1:8080/
container exec trendradar python manage.py status
container stats --no-stream trendradar
```

> **为什么手动重建而不是等 supervisor？**
> supervisor 的巡检逻辑是"容器不存在则创建"，使用的是缓存的镜像名 `ptilopsis-radar:latest`。
> 如果不先 delete 旧容器，supervisor 不会触发重建；如果先 delete 再等 supervisor 重建，
> 会有一段 8080 不可用的空窗期。显式操作可以无缝衔接。

---

## 完整流程（含验证和回滚）

### Step 0：确认变更

```fish
cd ~/PtilopsisRadar
git status --short
git log --oneline -5
```

确认你要更新的内容已就绪（代码已 pull/checkout，依赖已更新等）。

### Step 1：构建新镜像

```fish
container build --arch arm64 --tag ptilopsis-radar:latest --file docker/Dockerfile .
```

- 首次构建或依赖变更：约 1-2 分钟
- 仅代码变更（无依赖变化）：几秒（大部分层缓存命中）
- 构建失败时**不会影响正在运行的容器**，可放心排查

验证镜像：

```fish
container image list
```

确认 `ptilopsis-radar latest` 的 DIGEST 已更新。

### Step 2：确认当前容器状态

```fish
container list --all
container stats --no-stream trendradar
curl -I http://127.0.0.1:8080/
```

### Step 3：停止并删除旧容器

```fish
container stop trendradar
container delete trendradar
```

此时 8080 释放，Web 短暂不可用。

### Step 4：启动新容器

```fish
container run -d \
  --name trendradar \
  --cpus 2 \
  --memory 1g \
  --env-file ./docker/.env \
  --env TZ=Asia/Shanghai \
  --mount source=(pwd)/config,target=/app/config,readonly \
  --volume (pwd)/output:/app/output \
  -p 127.0.0.1:8080:8080 \
  ptilopsis-radar:latest
```

### Step 5：验证

```fish
# HTTP
curl -I http://127.0.0.1:8080/
curl -I http://127.0.0.1:8080/index.html

# 容器内部状态
container exec trendradar python manage.py status
container exec trendradar python manage.py webserver_status

# 资源
container stats --no-stream trendradar

# 日志（检查有无报错）
container logs -n 60 trendradar

# supervisor 是否已识别新容器
tail -n 10 ~/Library/Logs/PtilopsisRadar/trendradar-supervisor.log
```

### Step 6：回滚（如验证失败）

```fish
# 停止有问题的新容器
container stop trendradar
container delete trendradar

# 如果旧镜像仍可用，用旧镜像重建
container run -d \
  --name trendradar \
  --cpus 2 \
  --memory 1g \
  --env-file ./docker/.env \
  --env TZ=Asia/Shanghai \
  --mount source=(pwd)/config,target=/app/config,readonly \
  --volume (pwd)/output:/app/output \
  -p 127.0.0.1:8080:8080 \
  ptilopsis-radar:latest
```

> 注意：`ptilopsis-radar:latest` 标签已被新镜像覆盖。如需精确回滚到旧版本，
> 需要在构建新镜像前先 tag 旧镜像（见下方"安全构建"小节）。

---

## 安全构建（推荐用于重大变更）

在覆盖 `latest` 标签前，先备份旧镜像标签：

```fish
# 查看当前镜像 digest
container image list

# 构建时先用临时标签
container build --arch arm64 --tag ptilopsis-radar:canary --file docker/Dockerfile .

# 验证 canary 正常后，再打 latest 标签
# （Apple container CLI 目前不支持 tag 命令，需重新 build 或直接使用 canary 标签启动）
```

如果 Apple container 不支持 `tag`，可以用两种方式处理：

1. **直接用 canary 标签启动**：修改 supervisor 脚本中的 `IMAGE` 变量
2. **重新 build 打 latest**：确认 canary 验证通过后，再执行一次 build（缓存命中，秒完成）

---

## 仅更新 config 的情况

如果只改了 `config/config.yaml`、`config/frequency_words.txt` 等配置文件：

**不需要重建镜像。** 配置是 bind mount 的，直接重启容器即可：

```fish
container stop trendradar
container start trendradar
```

或者等下一次 cron 周期自动生效（部分配置热加载，取决于具体字段）。

---

## 涉及 .env 变更的情况

`.env` 在 `container run` 时通过 `--env-file` 注入。修改 `.env` 后需要重建容器：

```fish
container stop trendradar
container delete trendradar
container run -d \
  --name trendradar \
  --cpus 2 \
  --memory 1g \
  --env-file ./docker/.env \
  --env TZ=Asia/Shanghai \
  --mount source=(pwd)/config,target=/app/config,readonly \
  --volume (pwd)/output:/app/output \
  -p 127.0.0.1:8080:8080 \
  ptilopsis-radar:latest
```

不需要重建镜像。

---

## 修改 supervisor 参数（内存/CPU/检查间隔）

编辑 plist 中的环境变量：

```fish
nano ~/Library/LaunchAgents/com.carrot-peace.ptilopsis-radar.plist
```

修改 `EnvironmentVariables` 中的值，然后重启 launchd：

```fish
bash -c 'launchctl kickstart -k gui/$(id -u)/com.carrot-peace.ptilopsis-radar'
```

> 注意：修改内存/CPU 需要删除并重建容器才能生效（Apple container 不支持热调整资源限制）。

---

## 排查清单

| 现象 | 检查 |
|------|------|
| 8080 无响应 | `container list --all`，`lsof -nP -iTCP:8080 -sTCP:LISTEN` |
| 容器反复重启 | `container logs -n 100 trendradar` |
| supervisor 不重建 | `tail -n 30 ~/Library/Logs/PtilopsisRadar/trendradar-supervisor.log` |
| launchd 不启动 | `bash -c 'launchctl print gui/$(id -u)/com.carrot-peace.ptilopsis-radar'` |
| 内存异常 | `container stats --no-stream trendradar` |
| 构建失败 | 检查 Dockerfile、网络、`container system start` |
