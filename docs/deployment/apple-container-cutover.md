# Apple container 正式更替报告

## 结论
- **是否切换成功**：✅ 是
- **当前正式运行时**：Apple container v1.0.0
- **当前 8080 归属**：Apple container 版 trendradar (`container` 进程 PID 8391)
- **是否已启用 launchd 保活**：✅ 是 (`com.carrot-peace.ptilopsis-radar`)
- **是否需要用户继续监看**：✅ 是，建议先监看一段时间再考虑调整内存至 768MB

## 环境
- **macOS**：26.5.1 (25F80)
- **架构**：arm64 (Apple Silicon M4)
- **container 版本**：1.0.0 (release, ee848e3)
- **Git 分支**：`feat/crawler-max-retries-config`
- **Git commit**：`07c067e`
- **未提交变更**：`docker/docker-compose.yml`（新增 CR_DISPATCH_MODE 环境变量）

## 切换前状态
- **Docker trendradar 状态**：Up 50 minutes，正常运行
- **8080 占用**：Docker 版 trendradar（com.docker proxy）
- **Docker 内存**：31.21 MiB / 7.75 GiB
- **output 路径**：`/Users/ptilopsis/PtilopsisRadar/output`

## Build
- **镜像**：`ptilopsis-radar:latest`
- **是否成功**：✅ 是
- **耗时**：~4.4s（全缓存命中）
- **日志摘要**：所有层 CACHED，无 TARGETARCH / supercronic / uv sync 问题

## 切换动作
- **Docker stop 是否成功**：✅ 是（`docker compose stop trendradar`）
- **8080 释放确认**：✅ 是（lsof 无输出）
- **Apple container run 是否成功**：✅ 是（`container run -d --name trendradar ...`）
- **launchd bootstrap 是否成功**：✅ 是

## 验证结果
- **curl /**：✅ HTTP 200 OK（1404 bytes）
- **curl /index.html**：✅ HTTP 200 OK（1404 bytes）
- **manage.py status**：✅ supercronic PID 1 正常，crontab `*/30 * * * *` 有效
- **webserver_status**：✅ Web 服务器运行中（PID 13），端口 8080
- **container stats**：176.71 MiB / 1.00 GiB，0.02% CPU，14 PIDs
- **launchd 状态**：`state = running`，`active count = 1`
- **supervisor 日志**：`container trendradar is running`

## 保活方案
- **plist 路径**：`~/Library/LaunchAgents/com.carrot-peace.ptilopsis-radar.plist`
- **supervisor 脚本路径**：`~/PtilopsisRadar/scripts/apple-container/trendradar-supervisor.zsh`
- **日志路径**：
  - supervisor: `~/Library/Logs/PtilopsisRadar/trendradar-supervisor.log`
  - launchd stdout: `~/Library/Logs/PtilopsisRadar/launchd.out.log`
  - launchd stderr: `~/Library/Logs/PtilopsisRadar/launchd.err.log`
- **检查间隔**：60 秒
- **内存限制**：1g
- **CPU 限制**：2 cores
- **保活机制**：巡检式——每 60s 检查容器状态，不存在则重建，停止则重启

## 回滚方案

如需回滚到 Docker 版：

```fish
# 1. 卸载 launchd 保活
bash -c 'launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.carrot-peace.ptilopsis-radar.plist'

# 2. 停止并删除 Apple container 版
container stop trendradar
container delete trendradar

# 3. 恢复 Docker 版
docker compose -f docker/docker-compose.yml up -d trendradar

# 4. 验证
curl -I http://127.0.0.1:8080/
docker compose -f docker/docker-compose.yml ps
```

## 遗留问题
- **是否后续改 768MB**：是，用户先监看一段时间后再调整
- **是否补 .env.example**：待办（当前缺失）
- **是否迁移 MCP**：暂不迁移，MCP 仍使用 Docker 版（如 Docker Desktop 可用）
- **是否清理 Docker Desktop 开机自启**：待用户决定

## 监看命令

```fish
# 容器状态
container stats --no-stream trendradar

# 容器日志
container logs -n 100 trendradar

# 管理状态
container exec trendradar python manage.py status
container exec trendradar python manage.py webserver_status

# HTTP 检查
curl -I http://127.0.0.1:8080/

# supervisor 日志
tail -n 100 ~/Library/Logs/PtilopsisRadar/trendradar-supervisor.log

# launchd 状态
bash -c 'launchctl print gui/$(id -u)/com.carrot-peace.ptilopsis-radar'

# 连续监看循环
while true
    date
    curl -Is http://127.0.0.1:8080/index.html | head -1
    container stats --no-stream trendradar
    tail -n 5 ~/Library/Logs/PtilopsisRadar/trendradar-supervisor.log
    sleep 300
end
```

## 附录
- **迁移日志目录**：`migration-logs/apple-container-20260618-201221/`
- **git status**：`docker/docker-compose.yml` 有未提交变更（CR_DISPATCH_MODE）
- **切换时间**：2026-06-18 20:17 (Asia/Shanghai)
