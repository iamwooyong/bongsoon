#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
아이센스(099190) 주가 알림봇
- 시작가/종가 알림
- 2% 이상 변동 시 알림
"""

import json
import os
import sys
import time
import logging
import requests
from datetime import datetime, timedelta
from pathlib import Path

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('stock_bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# 설정 파일 경로
CONFIG_PATH = Path(__file__).parent / 'config.json'
STATE_PATH = Path(__file__).parent / 'state.json'

# 아이센스 종목코드
STOCK_CODE = '099190'
STOCK_NAME = '아이센스'


def load_config():
    """설정 파일 로드"""
    if not CONFIG_PATH.exists():
        logger.error(f"설정 파일이 없습니다: {CONFIG_PATH}")
        sys.exit(1)

    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def load_state():
    """상태 파일 로드 (전일 종가, 당일 기준가 등)"""
    if STATE_PATH.exists():
        with open(STATE_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_state(state):
    """상태 파일 저장"""
    with open(STATE_PATH, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def get_stock_price():
    """네이버 금융에서 주가 정보 가져오기"""
    try:
        # 네이버 금융 API
        url = f"https://m.stock.naver.com/api/stock/{STOCK_CODE}/basic"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }

        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()

        # 현재가
        current_price = int(data.get('closePrice', '0').replace(',', ''))
        # 시가
        open_price = int(data.get('openPrice', '0').replace(',', ''))
        # 고가
        high_price = int(data.get('highPrice', '0').replace(',', ''))
        # 저가
        low_price = int(data.get('lowPrice', '0').replace(',', ''))
        # 전일 종가
        prev_close = int(data.get('compareToPreviousClosePrice', '0').replace(',', ''))
        prev_close = current_price - prev_close  # 전일종가 계산
        # 변동률
        change_rate = float(data.get('fluctuationsRatio', '0'))

        return {
            'current': current_price,
            'open': open_price,
            'high': high_price,
            'low': low_price,
            'prev_close': prev_close,
            'change_rate': change_rate,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
    except Exception as e:
        logger.error(f"주가 조회 실패: {e}")
        return None


def send_telegram(config, message):
    """텔레그램 메시지 전송"""
    try:
        token = config['telegram']['bot_token']
        chat_id = config['telegram']['chat_id']

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = {
            'chat_id': chat_id,
            'text': message,
            'parse_mode': 'HTML'
        }

        response = requests.post(url, data=data, timeout=10)
        response.raise_for_status()
        logger.info(f"텔레그램 전송 성공: {message[:50]}...")
        return True
    except Exception as e:
        logger.error(f"텔레그램 전송 실패: {e}")
        return False


def format_price(price):
    """가격 포맷팅 (천 단위 콤마)"""
    return f"{price:,}"


def is_market_open():
    """장 운영 시간 체크 (09:00 ~ 15:30, 평일)"""
    now = datetime.now()
    # 주말 체크
    if now.weekday() >= 5:
        return False

    # 시간 체크
    market_start = now.replace(hour=9, minute=0, second=0, microsecond=0)
    market_end = now.replace(hour=15, minute=30, second=0, microsecond=0)

    return market_start <= now <= market_end


def check_and_notify(config, state):
    """주가 확인 및 알림 전송"""
    price_data = get_stock_price()
    if not price_data:
        return state

    today = datetime.now().strftime('%Y-%m-%d')
    current_price = price_data['current']
    open_price = price_data['open']

    # 오늘 첫 조회인 경우 (시작가 알림)
    if state.get('last_date') != today:
        state['last_date'] = today
        state['open_price'] = open_price
        state['base_price'] = open_price  # 변동률 계산 기준가
        state['last_alert_price'] = open_price
        state['sent_open_alert'] = False
        state['sent_close_alert'] = False
        save_state(state)

    now = datetime.now()

    # 시작가 알림 (09:05 ~ 09:10 사이에 한 번만)
    if not state.get('sent_open_alert') and 9 <= now.hour < 10:
        if now.minute >= 5:
            change_from_prev = ((open_price - price_data['prev_close']) / price_data['prev_close']) * 100
            arrow = "🔺" if change_from_prev >= 0 else "🔻"

            message = f"""📊 <b>{STOCK_NAME} 장 시작</b>

🔔 시작가: {format_price(open_price)}원
📈 전일대비: {arrow} {change_from_prev:+.2f}%
⏰ {now.strftime('%Y-%m-%d %H:%M')}"""

            send_telegram(config, message)
            state['sent_open_alert'] = True
            save_state(state)

    # 2% 변동 알림
    base_price = state.get('base_price', open_price)
    last_alert_price = state.get('last_alert_price', base_price)

    if last_alert_price > 0:
        change_from_last = ((current_price - last_alert_price) / last_alert_price) * 100

        if abs(change_from_last) >= 2.0:
            direction = "상승" if change_from_last > 0 else "하락"
            emoji = "🚀" if change_from_last > 0 else "📉"

            # 시가 대비 변동률
            change_from_open = ((current_price - open_price) / open_price) * 100

            message = f"""{emoji} <b>{STOCK_NAME} {abs(change_from_last):.1f}% {direction}!</b>

💰 현재가: {format_price(current_price)}원
📊 시가대비: {change_from_open:+.2f}%
📍 알림기준: {format_price(last_alert_price)}원
⏰ {now.strftime('%H:%M:%S')}"""

            send_telegram(config, message)
            state['last_alert_price'] = current_price
            save_state(state)

    # 종가 알림 (15:30 이후 한 번만)
    if not state.get('sent_close_alert') and now.hour >= 15 and now.minute >= 30:
        change_from_open = ((current_price - open_price) / open_price) * 100
        change_from_prev = price_data['change_rate']

        if change_from_open >= 0:
            result_emoji = "📈"
            result_text = "상승"
        else:
            result_emoji = "📉"
            result_text = "하락"

        message = f"""🔔 <b>{STOCK_NAME} 장 마감</b>

💰 종가: {format_price(current_price)}원
{result_emoji} 등락: {result_text} {abs(change_from_open):.2f}%

📊 시가: {format_price(open_price)}원
📈 고가: {format_price(price_data['high'])}원
📉 저가: {format_price(price_data['low'])}원
📅 전일대비: {change_from_prev:+.2f}%

⏰ {now.strftime('%Y-%m-%d %H:%M')}"""

        send_telegram(config, message)
        state['sent_close_alert'] = True
        state['prev_close'] = current_price
        save_state(state)

    return state


def run_once():
    """한 번 실행 (cron용)"""
    config = load_config()
    state = load_state()

    # 평일 체크
    if datetime.now().weekday() >= 5:
        logger.info("주말에는 실행하지 않습니다.")
        return

    check_and_notify(config, state)


def run_daemon():
    """데몬 모드로 실행"""
    config = load_config()
    state = load_state()

    check_interval = config.get('check_interval', 60)  # 기본 60초

    logger.info(f"{STOCK_NAME} 주가 알림봇 시작 (간격: {check_interval}초)")

    while True:
        try:
            now = datetime.now()

            # 평일 장중에만 체크
            if now.weekday() < 5:  # 월~금
                if 9 <= now.hour < 16:  # 09:00 ~ 16:00
                    state = check_and_notify(config, state)

            time.sleep(check_interval)

        except KeyboardInterrupt:
            logger.info("봇 종료")
            break
        except Exception as e:
            logger.error(f"오류 발생: {e}")
            time.sleep(60)


def test_telegram():
    """텔레그램 연결 테스트"""
    config = load_config()
    message = f"""✅ <b>아이센스 알림봇 테스트</b>

봇이 정상적으로 연결되었습니다!
종목: {STOCK_NAME} ({STOCK_CODE})

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""

    if send_telegram(config, message):
        print("텔레그램 테스트 성공!")
    else:
        print("텔레그램 테스트 실패!")


def show_current_price():
    """현재 주가 표시"""
    price_data = get_stock_price()
    if price_data:
        print(f"\n{STOCK_NAME} ({STOCK_CODE}) 현재 주가")
        print(f"{'='*40}")
        print(f"현재가: {format_price(price_data['current'])}원")
        print(f"시가: {format_price(price_data['open'])}원")
        print(f"고가: {format_price(price_data['high'])}원")
        print(f"저가: {format_price(price_data['low'])}원")
        print(f"변동률: {price_data['change_rate']:+.2f}%")
        print(f"조회시간: {price_data['timestamp']}")
    else:
        print("주가 조회 실패")


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='아이센스 주가 알림봇')
    parser.add_argument('--daemon', '-d', action='store_true', help='데몬 모드로 실행')
    parser.add_argument('--test', '-t', action='store_true', help='텔레그램 테스트')
    parser.add_argument('--price', '-p', action='store_true', help='현재 주가 확인')

    args = parser.parse_args()

    if args.test:
        test_telegram()
    elif args.price:
        show_current_price()
    elif args.daemon:
        run_daemon()
    else:
        run_once()
