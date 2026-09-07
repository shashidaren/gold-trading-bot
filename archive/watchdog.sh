#!/bin/bash

# 1. Load Telegram credentials
ENV_FILE="/opt/gold/.env"
if [ ! -f "$ENV_FILE" ]; then
    exit 1
fi
source "$ENV_FILE"

# Define engines to check
ENGINES=("gold" "bitcoin")

for ENGINE in "${ENGINES[@]}"; do
    SERVICE_NAME="${ENGINE}bot.service" # Adjust if your BTC service is named differently (e.g., bitcoin-engine.service)
    if [ "$ENGINE" == "bitcoin" ]; then
        SERVICE_NAME="bitcoin-engine.service"
    fi

    ALERT_LOCK="/opt/${ENGINE}/.watchdog_alert_sent"
    UPPER_NAME=$(echo "$ENGINE" | tr '[:lower:]' '[:upper:]')

    # Check if the systemd service is actually active
    if ! systemctl is-active --quiet "$SERVICE_NAME"; then
        if [ ! -f "$ALERT_LOCK" ]; then
            MESSAGE="🚨 *${UPPER_NAME} ENGINE CRASHED*\n\nThe systemd service (*${SERVICE_NAME}*) is no longer running.\n\nPlease check the server immediately!"
            
            curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
                 -d "chat_id=${TELEGRAM_CHAT_ID}" \
                 -d "text=${MESSAGE}" \
                 -d "parse_mode=Markdown" > /dev/null
            
            touch "$ALERT_LOCK"
        fi
    else
        # Service is running fine, clear any old lock files
        rm -f "$ALERT_LOCK"
    fi
done
