#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
아이센스(099190) 주가 알림봇
- 시작가/종가 알림
- 변동 알림 (사용자 설정 가능)
- 텔레그램 버튼 인터페이스
"""

import json
import sys
import os
import time
import logging
import requests
import subprocess
from datetime import datetime
from pathlib import Path
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

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


def save_config(config):
    """설정 파일 저장"""
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def load_state():
    """상태 파일 로드"""
    if STATE_PATH.exists():
        with open(STATE_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_state(state):
    """상태 파일 저장"""
    with open(STATE_PATH, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def format_price(price):
    """가격 포맷팅"""
    return f"{price:,}"


def get_stock_price():
    """네이버 금융에서 주가 정보 가져오기"""
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

        # 기본 정보 API
        basic_url = f"https://m.stock.naver.com/api/stock/{STOCK_CODE}/basic"
        basic_resp = requests.get(basic_url, headers=headers, timeout=10)
        basic_resp.raise_for_status()
        basic_data = basic_resp.json()

        current_price = int(basic_data.get('closePrice', '0').replace(',', ''))
        prev_diff = int(basic_data.get('compareToPreviousClosePrice', '0').replace(',', ''))
        prev_close = current_price - prev_diff
        change_rate = float(basic_data.get('fluctuationsRatio', '0'))

        # 통합 정보 API (시가, 고가, 저가, 거래량)
        integration_url = f"https://m.stock.naver.com/api/stock/{STOCK_CODE}/integration"
        integ_resp = requests.get(integration_url, headers=headers, timeout=10)
        integ_resp.raise_for_status()
        integ_data = integ_resp.json()

        # totalInfos에서 필요한 데이터 추출
        total_infos = {item['code']: item['value'] for item in integ_data.get('totalInfos', [])}

        open_price = int(total_infos.get('openPrice', '0').replace(',', ''))
        high_price = int(total_infos.get('highPrice', '0').replace(',', ''))
        low_price = int(total_infos.get('lowPrice', '0').replace(',', ''))
        volume = total_infos.get('accumulatedTradingVolume', '0')

        return {
            'current': current_price,
            'open': open_price,
            'high': high_price,
            'low': low_price,
            'prev_close': prev_close,
            'change_rate': change_rate,
            'volume': volume,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
    except Exception as e:
        logger.error(f"주가 조회 실패: {e}")
        return None


def get_orderbook():
    """호가 정보 가져오기"""
    try:
        url = f"https://m.stock.naver.com/api/stock/{STOCK_CODE}/askingPrice"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()

        sell_info = data.get('sellInfo', [])  # 매도호가
        buy_infos = data.get('buyInfos', [])  # 매수호가

        return {
            'ask': sell_info[:5],  # 매도 5호가
            'bid': buy_infos[:5],  # 매수 5호가
            'timestamp': datetime.now().strftime('%H:%M:%S')
        }
    except Exception as e:
        logger.error(f"호가 조회 실패: {e}")
        return None


# ============ 텔레그램 봇 핸들러 ============

def get_main_keyboard():
    """메인 메뉴 키보드"""
    keyboard = [
        [
            InlineKeyboardButton("💰 현재가", callback_data='price'),
            InlineKeyboardButton("📊 호가", callback_data='orderbook'),
        ],
        [
            InlineKeyboardButton("📈 차트", callback_data='chart'),
            InlineKeyboardButton("🔔 변동알림", callback_data='alert_menu'),
        ],
        [
            InlineKeyboardButton("⚙️ 설정", callback_data='settings'),
            InlineKeyboardButton("❓ 도움말", callback_data='help'),
        ],
    ]
    return InlineKeyboardMarkup(keyboard)


def get_alert_keyboard(current_threshold):
    """변동 알림 설정 키보드"""
    options = [1, 2, 3, 5]
    keyboard = []
    row = []
    for opt in options:
        label = f"{'✅ ' if current_threshold == opt else ''}{opt}%"
        row.append(InlineKeyboardButton(label, callback_data=f'alert_set_{opt}'))
    keyboard.append(row)

    # 알림 ON/OFF
    state = load_state()
    alert_enabled = state.get('alert_enabled', True)
    status = "🔔 알림 ON" if alert_enabled else "🔕 알림 OFF"
    keyboard.append([InlineKeyboardButton(status, callback_data='alert_toggle')])
    keyboard.append([InlineKeyboardButton("◀️ 뒤로", callback_data='back')])
    return InlineKeyboardMarkup(keyboard)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """시작 명령어"""
    message = f"""🤖 <b>{STOCK_NAME} 알림봇</b>

종목코드: {STOCK_CODE}
아래 버튼을 눌러 정보를 확인하세요."""

    await update.message.reply_text(
        message,
        parse_mode='HTML',
        reply_markup=get_main_keyboard()
    )


async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """메뉴 명령어"""
    await update.message.reply_text(
        "📋 메뉴를 선택하세요:",
        reply_markup=get_main_keyboard()
    )


async def restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """소스 업데이트 및 재시작 (관리자 전용)"""
    config = load_config()
    admin_chat_id = str(config['telegram']['chat_id'])
    user_chat_id = str(update.effective_chat.id)

    # 관리자만 사용 가능
    if user_chat_id != admin_chat_id:
        await update.message.reply_text("⛔ 권한이 없습니다.")
        return

    await update.message.reply_text("🔄 소스 업데이트 중...")

    try:
        # git pull 실행
        script_dir = Path(__file__).parent
        result = subprocess.run(
            ['git', 'pull'],
            cwd=script_dir,
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode == 0:
            output = result.stdout.strip() or "Already up to date."
            await update.message.reply_text(f"✅ 업데이트 완료:\n<code>{output}</code>\n\n🔄 재시작 중...", parse_mode='HTML')

            # 잠시 대기 후 프로세스 종료 (Docker가 자동 재시작)
            await asyncio.sleep(1)
            os._exit(0)
        else:
            await update.message.reply_text(f"❌ 업데이트 실패:\n<code>{result.stderr}</code>", parse_mode='HTML')

    except Exception as e:
        await update.message.reply_text(f"❌ 오류: {e}")


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """버튼 콜백 처리"""
    query = update.callback_query
    await query.answer()

    data = query.data

    if data == 'price':
        await show_price(query)
    elif data == 'orderbook':
        await show_orderbook(query)
    elif data == 'chart':
        await show_chart(query)
    elif data == 'alert_menu':
        await show_alert_menu(query)
    elif data.startswith('alert_set_'):
        threshold = int(data.split('_')[2])
        await set_alert_threshold(query, threshold)
    elif data == 'alert_toggle':
        await toggle_alert(query)
    elif data == 'settings':
        await show_settings(query)
    elif data == 'help':
        await show_help(query)
    elif data == 'back':
        await query.edit_message_text(
            "📋 메뉴를 선택하세요:",
            reply_markup=get_main_keyboard()
        )


async def show_price(query):
    """현재가 표시"""
    price_data = get_stock_price()
    if not price_data:
        await query.edit_message_text("❌ 주가 조회 실패", reply_markup=get_main_keyboard())
        return

    change = price_data['change_rate']
    arrow = "🔺" if change >= 0 else "🔻"

    message = f"""💰 <b>{STOCK_NAME} 현재가</b>

<b>{format_price(price_data['current'])}원</b> {arrow} {change:+.2f}%

📊 시가: {format_price(price_data['open'])}원
📈 고가: {format_price(price_data['high'])}원
📉 저가: {format_price(price_data['low'])}원
📅 전일: {format_price(price_data['prev_close'])}원
📦 거래량: {price_data['volume']}

⏰ {price_data['timestamp']}"""

    await query.edit_message_text(message, parse_mode='HTML', reply_markup=get_main_keyboard())


async def show_orderbook(query):
    """호가 표시"""
    orderbook = get_orderbook()
    price_data = get_stock_price()

    if not orderbook or not price_data:
        await query.edit_message_text("❌ 호가 조회 실패", reply_markup=get_main_keyboard())
        return

    lines = [f"📊 <b>{STOCK_NAME} 호가</b>\n"]
    lines.append("─" * 20)
    lines.append("<b>매도호가</b>")

    # 매도호가 (역순으로 - 높은 가격이 위로)
    for item in reversed(orderbook['ask']):
        price = int(item.get('price', '0').replace(',', ''))
        count = item.get('count', '0')
        lines.append(f"🔴 {format_price(price)}원 | {count}주")

    lines.append("─" * 20)
    lines.append(f"<b>현재가: {format_price(price_data['current'])}원</b>")
    lines.append("─" * 20)
    lines.append("<b>매수호가</b>")

    # 매수호가
    for item in orderbook['bid']:
        price = int(item.get('price', '0').replace(',', ''))
        count = item.get('count', '0')
        lines.append(f"🔵 {format_price(price)}원 | {count}주")

    lines.append("─" * 20)
    lines.append(f"⏰ {orderbook['timestamp']}")

    await query.edit_message_text('\n'.join(lines), parse_mode='HTML', reply_markup=get_main_keyboard())


async def show_chart(query):
    """차트 이미지 전송"""
    # 네이버 차트 URL
    chart_url = f"https://ssl.pstatic.net/imgfinance/chart/item/area/day/{STOCK_CODE}.png?sidcode={int(time.time())}"

    message = f"""📈 <b>{STOCK_NAME} 일봉 차트</b>

<a href="{chart_url}">📊 차트 보기</a>

🔗 <a href="https://m.stock.naver.com/domestic/stock/{STOCK_CODE}/total">네이버 금융</a>"""

    await query.edit_message_text(message, parse_mode='HTML', reply_markup=get_main_keyboard(), disable_web_page_preview=False)


async def show_alert_menu(query):
    """변동 알림 설정 메뉴"""
    config = load_config()
    threshold = config.get('alert_threshold', 2.0)
    state = load_state()
    alert_enabled = state.get('alert_enabled', True)
    status = "켜짐 🔔" if alert_enabled else "꺼짐 🔕"

    message = f"""🔔 <b>변동 알림 설정</b>

현재 설정: <b>{threshold}%</b> 변동 시 알림
알림 상태: <b>{status}</b>

원하는 변동률을 선택하세요:"""

    await query.edit_message_text(
        message,
        parse_mode='HTML',
        reply_markup=get_alert_keyboard(threshold)
    )


async def set_alert_threshold(query, threshold):
    """알림 임계값 설정"""
    config = load_config()
    config['alert_threshold'] = threshold
    save_config(config)

    # 상태 초기화 (새 기준으로 알림 재설정)
    state = load_state()
    price_data = get_stock_price()
    if price_data:
        state['last_alert_price'] = price_data['current']
        save_state(state)

    message = f"""✅ 변동 알림이 <b>{threshold}%</b>로 설정되었습니다.

현재가 기준으로 {threshold}% 이상 변동 시 알림을 보내드립니다."""

    await query.edit_message_text(
        message,
        parse_mode='HTML',
        reply_markup=get_alert_keyboard(threshold)
    )


async def toggle_alert(query):
    """알림 ON/OFF 토글"""
    state = load_state()
    current = state.get('alert_enabled', True)
    state['alert_enabled'] = not current
    save_state(state)

    config = load_config()
    threshold = config.get('alert_threshold', 2.0)

    status = "켜짐 🔔" if state['alert_enabled'] else "꺼짐 🔕"
    message = f"""🔔 <b>변동 알림 설정</b>

현재 설정: <b>{threshold}%</b> 변동 시 알림
알림 상태: <b>{status}</b>

원하는 변동률을 선택하세요:"""

    await query.edit_message_text(
        message,
        parse_mode='HTML',
        reply_markup=get_alert_keyboard(threshold)
    )


async def show_settings(query):
    """설정 표시"""
    config = load_config()
    state = load_state()

    alert_enabled = state.get('alert_enabled', True)
    alert_status = "🔔 켜짐" if alert_enabled else "🔕 꺼짐"
    threshold = config.get('alert_threshold', 2.0)
    interval = config.get('check_interval', 60)
    last_alert = state.get('last_alert_price', '-')

    message = f"""⚙️ <b>현재 설정</b>

📌 종목: {STOCK_NAME} ({STOCK_CODE})
🔔 알림 상태: {alert_status}
📊 변동 임계값: {threshold}%
⏱️ 체크 간격: {interval}초
📍 마지막 알림가: {format_price(last_alert) if isinstance(last_alert, int) else last_alert}원"""

    await query.edit_message_text(message, parse_mode='HTML', reply_markup=get_main_keyboard())


async def show_help(query):
    """도움말 표시"""
    message = f"""❓ <b>도움말</b>

<b>💰 현재가</b>
현재 주가 및 등락률 확인

<b>📊 호가</b>
매수/매도 호가 5단계 확인

<b>📈 차트</b>
일봉 차트 확인

<b>🔔 변동알림</b>
변동률 알림 설정 (1~5%)
알림 ON/OFF 전환

<b>자동 알림</b>
• 09:05 - 장 시작가 알림
• 15:30 - 장 마감 종가 알림
• 설정한 % 변동 시 즉시 알림"""

    await query.edit_message_text(message, parse_mode='HTML', reply_markup=get_main_keyboard())


# ============ 주가 모니터링 ============

async def send_alert(app, config, message):
    """알림 전송"""
    chat_id = config['telegram']['chat_id']
    try:
        await app.bot.send_message(
            chat_id=chat_id,
            text=message,
            parse_mode='HTML',
            reply_markup=get_main_keyboard()
        )
        logger.info(f"알림 전송: {message[:50]}...")
    except Exception as e:
        logger.error(f"알림 전송 실패: {e}")


async def price_monitor(app):
    """주가 모니터링 루프"""
    config = load_config()
    state = load_state()

    while True:
        try:
            now = datetime.now()

            # 평일 장중에만 체크
            if now.weekday() < 5 and 9 <= now.hour < 16:
                config = load_config()  # 설정 리로드
                state = load_state()

                # 알림이 꺼져있으면 스킵
                if not state.get('alert_enabled', True):
                    await asyncio.sleep(config.get('check_interval', 60))
                    continue

                price_data = get_stock_price()
                if price_data:
                    today = now.strftime('%Y-%m-%d')
                    current_price = price_data['current']
                    open_price = price_data['open']
                    threshold = config.get('alert_threshold', 2.0)

                    # 오늘 첫 조회
                    if state.get('last_date') != today:
                        state['last_date'] = today
                        state['open_price'] = open_price
                        state['last_alert_price'] = open_price
                        state['sent_open_alert'] = False
                        state['sent_close_alert'] = False
                        save_state(state)

                    # 시작가 알림
                    if not state.get('sent_open_alert') and now.hour == 9 and now.minute >= 5:
                        change = ((open_price - price_data['prev_close']) / price_data['prev_close']) * 100
                        arrow = "🔺" if change >= 0 else "🔻"

                        message = f"""📊 <b>{STOCK_NAME} 장 시작</b>

🔔 시작가: {format_price(open_price)}원
📈 전일대비: {arrow} {change:+.2f}%
⏰ {now.strftime('%Y-%m-%d %H:%M')}"""

                        await send_alert(app, config, message)
                        state['sent_open_alert'] = True
                        save_state(state)

                    # 변동 알림
                    last_alert_price = state.get('last_alert_price', open_price)
                    if last_alert_price > 0:
                        change = ((current_price - last_alert_price) / last_alert_price) * 100

                        if abs(change) >= threshold:
                            direction = "상승" if change > 0 else "하락"
                            emoji = "🚀" if change > 0 else "📉"
                            change_from_open = ((current_price - open_price) / open_price) * 100

                            message = f"""{emoji} <b>{STOCK_NAME} {abs(change):.1f}% {direction}!</b>

💰 현재가: {format_price(current_price)}원
📊 시가대비: {change_from_open:+.2f}%
📍 알림기준: {format_price(last_alert_price)}원
⏰ {now.strftime('%H:%M:%S')}"""

                            await send_alert(app, config, message)
                            state['last_alert_price'] = current_price
                            save_state(state)

                    # 종가 알림
                    if not state.get('sent_close_alert') and now.hour >= 15 and now.minute >= 30:
                        change_from_open = ((current_price - open_price) / open_price) * 100
                        result_emoji = "📈" if change_from_open >= 0 else "📉"
                        result_text = "상승" if change_from_open >= 0 else "하락"

                        message = f"""🔔 <b>{STOCK_NAME} 장 마감</b>

💰 종가: {format_price(current_price)}원
{result_emoji} 등락: {result_text} {abs(change_from_open):.2f}%

📊 시가: {format_price(open_price)}원
📈 고가: {format_price(price_data['high'])}원
📉 저가: {format_price(price_data['low'])}원

⏰ {now.strftime('%Y-%m-%d %H:%M')}"""

                        await send_alert(app, config, message)
                        state['sent_close_alert'] = True
                        save_state(state)

            await asyncio.sleep(config.get('check_interval', 60))

        except Exception as e:
            logger.error(f"모니터링 오류: {e}")
            await asyncio.sleep(60)


# ============ 메인 ============

import asyncio

async def main():
    """메인 함수"""
    config = load_config()
    token = config['telegram']['bot_token']

    # 봇 생성
    app = Application.builder().token(token).build()

    # 핸들러 등록
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu))
    app.add_handler(CommandHandler("restart", restart))
    app.add_handler(CallbackQueryHandler(button_callback))

    # 모니터링 태스크 시작
    asyncio.create_task(price_monitor(app))

    logger.info(f"{STOCK_NAME} 알림봇 시작")

    # 봇 실행
    await app.initialize()
    await app.start()
    await app.updater.start_polling()

    # 종료 대기
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()


def run_bot():
    """봇 실행"""
    asyncio.run(main())


def test_telegram():
    """텔레그램 연결 테스트"""
    config = load_config()
    token = config['telegram']['bot_token']
    chat_id = config['telegram']['chat_id']

    message = f"""✅ <b>아이센스 알림봇 테스트</b>

봇이 정상적으로 연결되었습니다!
종목: {STOCK_NAME} ({STOCK_CODE})

/start 또는 /menu 명령어로 시작하세요.

⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    response = requests.post(url, data={
        'chat_id': chat_id,
        'text': message,
        'parse_mode': 'HTML'
    })

    if response.ok:
        print("✅ 텔레그램 테스트 성공!")
    else:
        print(f"❌ 텔레그램 테스트 실패: {response.text}")


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='아이센스 주가 알림봇')
    parser.add_argument('--test', '-t', action='store_true', help='텔레그램 테스트')

    args = parser.parse_args()

    if args.test:
        test_telegram()
    else:
        run_bot()
