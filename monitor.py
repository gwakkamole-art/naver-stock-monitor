"""Fail-closed stock monitor. No proxy rotation, CAPTCHA solving or cookie export."""
import argparse
import asyncio
import json
import os
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

URL = 'https://smartstore.naver.com/moncolle_korea/products/13763561200'
TITLE = '포켓몬 카드 게임 MEGA 확장팩 30th CELEBRATION'


def classify(title_seen, unavailable, soldout, buy):
    if not title_seen:
        raise RuntimeError('상품명을 확인할 수 없습니다. 로그인/접속 오류/페이지 변경을 확인하세요.')
    if (unavailable or soldout) and not buy:
        return 'sold_out'
    if buy and not (unavailable or soldout):
        return 'in_stock'
    raise RuntimeError('재고 신호가 없거나 서로 충돌합니다. 품절로 처리하지 않습니다.')


def clean(message):
    for key in ('TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID'):
        value = os.environ.get(key)
        if value:
            message = message.replace(value, '[REDACTED]')
    return message


def notify(message):
    token, chat = os.getenv('TELEGRAM_BOT_TOKEN'), os.getenv('TELEGRAM_CHAT_ID')
    if not token or not chat:
        raise RuntimeError('TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID 설정이 필요합니다.')
    data = urllib.parse.urlencode({'chat_id': chat, 'text': message}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(
                f'https://api.telegram.org/bot{token}/sendMessage', data=data), timeout=30) as response:
            if not json.load(response).get('ok'):
                raise ValueError('API failure')
    except Exception:
        raise RuntimeError('텔레그램 전송 실패. 봇 /start 및 Secrets를 확인하세요.') from None


def transition(state, status, now, send):
    """Commit a stock change only after its alert was accepted by Telegram."""
    new = dict(state)
    if status == 'in_stock' and state.get('status') != 'in_stock':
        send('구매 가능 표시 감지! 상품 페이지에서 확인하세요.\n' + TITLE + '\n' + URL)
    if state.get('health_alerted'):
        send('재고 감시가 정상 복구됐습니다. 현재: ' + status + '\n' + URL)
    new.update(status=status, checked_at=now, failures=0, next_check=0,
               health_alerted=False, last_error=None)
    return new


def failure(state, error, now, send, retry_after=0):
    new = dict(state)
    failures = int(state.get('failures', 0)) + 1
    # Repeated access failures reduce traffic; the last known stock stays intact.
    delay = max(retry_after, min(21600, 900 * (2 ** min(failures - 1, 5))))
    new.update(failures=failures, next_check=now + delay, last_error=clean(str(error)),
               failed_at=now)
    if failures >= 3 and not state.get('health_alerted'):
        try:
            send('재고 감시가 3회 이상 실패했습니다. 재입고 알림을 놓칠 수 있어요.\n' +
                 clean(str(error))[:300] + '\n' + URL)
            new['health_alerted'] = True
        except RuntimeError:
            pass
    return new


class AccessFailure(RuntimeError):
    def __init__(self, message, retry_after=0):
        super().__init__(message)
        self.retry_after = retry_after


async def read_stock(args):
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        launch = dict(headless=not args.headed)
        if args.channel:
            launch['channel'] = args.channel
        if args.profile:
            context = await p.chromium.launch_persistent_context(args.profile, locale='ko-KR', **launch)
            browser = None
        else:
            browser = await p.chromium.launch(**launch)
            context = await browser.new_context(locale='ko-KR')
        try:
            page = await context.new_page()
            response = await page.goto(URL, wait_until='domcontentloaded', timeout=60000)
            if response and response.status >= 400:
                headers = await response.all_headers()
                retry = headers.get('retry-after', '')
                retry_seconds = int(retry) if retry.isdigit() else 0
                raise AccessFailure(f'네이버 응답 HTTP {response.status}: 상품을 읽지 못했습니다.', retry_seconds)
            if args.login:
                print('열린 전용 브라우저에서 필요한 로그인을 완료한 뒤 Enter를 누르세요.')
                await asyncio.to_thread(input)
                return None
            heading = page.get_by_role('heading', name=TITLE, exact=True)
            await heading.first.wait_for(state='visible', timeout=30000)
            # Let the client render purchase controls after the product heading.
            await page.wait_for_timeout(1500)
            async def any_visible(locator, enabled=False):
                for item in await locator.all():
                    if await item.is_visible() and (not enabled or await item.is_enabled()):
                        return True
                return False
            unavailable = await any_visible(page.get_by_text('이 상품은 현재 구매하실 수 없는 상품이며,', exact=False))
            soldout = await any_visible(page.get_by_role('button', name='품절되었습니다', exact=True))
            purchase = re.compile(r'^(구매하기|바로구매|바로 구매)$')
            buy = (await any_visible(page.get_by_role('button', name=purchase), True) or
                   await any_visible(page.get_by_role('link', name=purchase), True))
            return classify(await any_visible(heading), unavailable, soldout, buy)
        finally:
            await context.close()
            if browser:
                await browser.close()


def save(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    os.replace(temporary, path)
    if os.getenv('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
            output.write('changed=true\n')


def report(message):
    message = clean(message)
    print(message)
    if os.getenv('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as output:
            output.write('### 재고 감시 결과\n\n```text\n' + message.replace('```', '')[:3000] + '\n```\n')


async def check(args):
    path = Path(args.state)
    state = json.loads(path.read_text()) if path.exists() else {}
    now = time.time()
    if not args.probe and now < state.get('next_check', 0):
        when = datetime.fromtimestamp(state['next_check'], timezone.utc).isoformat()
        report('접속 오류 후 대기 중. 다음 확인: ' + when)
        return 0
    try:
        status = await read_stock(args)
    except Exception as error:
        if not args.probe:
            save(path, failure(state, error, now, notify, getattr(error, 'retry_after', 0)))
        report(str(error))
        return 1
    if args.login:
        return 0
    if args.probe:
        report('접속 테스트 성공. 현재 재고: ' + status + '\n알림 발송 및 예약 감시는 아직 활성화되지 않았습니다.')
        return 0
    try:
        updated = transition(state, status, now, notify)
    except RuntimeError as error:
        report(str(error))
        return 1
    save(path, updated)
    report('정상 확인: ' + status + '\n마지막 확인(UTC): ' + datetime.fromtimestamp(now, timezone.utc).isoformat())
    return 0


async def main(args):
    if args.test_telegram or os.getenv('TEST_TELEGRAM') == 'true':
        notify('재고 감시 테스트 알림입니다. 실제 재입고 알림은 아닙니다.\n' + URL)
        report('텔레그램 테스트 발송 성공')
        return 0
    while True:
        code = await check(args)
        if not args.loop:
            return code
        await asyncio.sleep(max(300, args.interval))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='네이버 상품 재고 감시 → 텔레그램')
    parser.add_argument('--probe', action='store_true', help='접속만 테스트; 상태 저장/알림 없음')
    parser.add_argument('--test-telegram', action='store_true')
    parser.add_argument('--loop', action='store_true')
    parser.add_argument('--interval', type=int, default=300)
    parser.add_argument('--headed', action='store_true')
    parser.add_argument('--channel', default=None, help='예: chrome. 설치된 공식 브라우저 사용')
    parser.add_argument('--profile', help='이 프로그램 전용 브라우저 프로필 디렉터리')
    parser.add_argument('--login', action='store_true', help='전용 브라우저에서 수동 로그인')
    parser.add_argument('--state', default='state/status.json')
    args = parser.parse_args()
    if args.login and (not args.headed or not args.profile):
        parser.error('--login은 --headed와 --profile이 필요합니다.')
    try:
        raise SystemExit(asyncio.run(main(args)))
    except KeyboardInterrupt:
        pass
    except Exception as error:
        report(str(error))
        raise SystemExit(1)
