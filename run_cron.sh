#!/bin/bash
# cron에서 실행할 스크립트 (1분마다 실행)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# 가상환경 활성화 (있는 경우)
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# 단일 실행 모드
python3 stock_bot.py
