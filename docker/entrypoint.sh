#!/bin/bash
set -e

# 检查配置文件
if [ ! -f "/app/config/config.yaml" ] || [ ! -f "/app/config/frequency_words.txt" ]; then
    echo "[失败] 配置文件缺失"
    exit 1
fi

case "${RUN_MODE:-cron}" in
"once")
    echo "单次执行"
    exec python -m trendradar.deployment.run_with_heartbeat
    ;;
"cron")
    # 校验 CRON_SCHEDULE 格式（仅允许 cron 表达式合法字符）
    CRON_EXPR="${CRON_SCHEDULE:-*/30 * * * *}"
    if ! echo "$CRON_EXPR" | grep -qE '^[0-9*/,[:space:]-]+$'; then
        echo "[失败] CRON_SCHEDULE 格式非法: $CRON_EXPR"
        exit 1
    fi

    # 生成 crontab
    echo "$CRON_EXPR cd /app && python -m trendradar.deployment.run_with_heartbeat" > /tmp/crontab
    
    echo "生成的crontab内容:"
    cat /tmp/crontab

    if ! /usr/local/bin/supercronic -test /tmp/crontab; then
        echo "[失败] crontab格式验证失败"
        exit 1
    fi

    # 立即执行一次（如果配置了）
    if [ "${IMMEDIATE_RUN:-false}" = "true" ]; then
        echo "立即执行一次"
        python -m trendradar.deployment.run_with_heartbeat
    fi

    # 启动 Web 服务器
    echo "启动 Web 服务器..."
    if ! python manage.py start_webserver; then
        echo "[失败] Web 服务器未通过 PID/HTTP 启动验证"
        exit 1
    fi

    # Only cron is a long-running deployment. Notify owners after all checks
    # named in the message have actually passed. Notification state is
    # independent from CR cooldown/lifecycle state and delivery remains
    # non-fatal to the verified service startup.
    if ! python -m trendradar.deployment.notification \
        --health "config files present, cron syntax OK, web HTTP OK"; then
        echo "[警告] deployment owner notification failed; continuing startup"
    fi

    echo "启动supercronic: $CRON_EXPR"
    echo "supercronic 将作为 PID 1 运行"

    exec /usr/local/bin/supercronic -passthrough-logs /tmp/crontab
    ;;
*)
    exec "$@"
    ;;
esac
