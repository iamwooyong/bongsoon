#!/bin/bash
# 아이센스 주가 알림봇 실행 스크립트

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# 가상환경 활성화 (있는 경우)
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# 데몬 모드로 실행
python3 stock_bot.py --daemon
