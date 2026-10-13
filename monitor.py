import asyncio
import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path
from playwright.async_api import async_playwright

URL = 'https://smartstore.naver.com/moncolle_korea/products/13763561200'
TITLE = '포켓몬 카드 게임 MEGA 확장팩 30th CELEBRATION'
STATE = Path('state/status.json')


def notify(message):
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    chat = os.environ.get('TELEGRAM_CHAT_ID', '')
    if not token or not chat:
        raise RuntimeError('GitHub Secrets에 TELEGRAM_BOT_TOKEN과 TELEGRAM_CHAT_ID를 설정하세요.')
    payload = urllib.parse.urlencode({'chat_id': chat, 'text': message}).encode()
    request = urllib.request.Request(f'https://api.telegram.org/bot{token}/sendMessage', data=payload)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.load(response)
        if not result.get('ok'):
            raise RuntimeError('텔레그램 전송 실패')
    except Exception:
        # 토큰이 포함된 요청 URL이나 원본 예외는 로그에 출력하지 않습니다.
        raise RuntimeError('텔레그램 전송 실패. 봇 /start와 Secrets를 확인하세요.') from None


async def main():
    if os.environ.get('TEST_TELEGRAM') == 'true':
        notify('재고 감시 테스트 알림입니다. 아직 상품 재입고 알림은 아닙니다.\n' + URL)
        print('텔레그램 테스트 성공')
        return
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(locale='ko-KR')
        response = await page.goto(URL, wait_until='domcontentloaded', timeout=60000)
        if response and response.status >= 400:
            raise RuntimeError(f'네이버 접속 실패: HTTP {response.status}. 재고 상태를 변경하지 않습니다.')
        await page.get_by_role('heading', name=TITLE, exact=True).wait_for(timeout=30000)
        unavailable = page.get_by_text('이 상품은 현재 구매하실 수 없는 상품이며,', exact=False)
        soldout = page.get_by_role('button', name='품절되었습니다', exact=True)
        buy = page.get_by_role('button', name=re.compile(r'^(구매하기|바로구매|바로 구매)$'))
        buy_links = page.get_by_role('link', name=re.compile(r'^(구매하기|바로구매|바로 구매)$'))
        candidates = await buy.all() + await buy_links.all()
        purchasable = any([await item.is_visible() and await item.is_enabled() for item in candidates])
        is_soldout = await unavailable.is_visible() or (await soldout.is_visible() and not await soldout.is_enabled())
        if purchasable and not is_soldout:
            status = 'in_stock'
        elif is_soldout and not purchasable:
            status = 'sold_out'
        else:
            raise RuntimeError('재고를 확정할 수 없습니다. 페이지 구조나 로그인 필요 여부를 확인하세요.')
        await browser.close()
    previous = json.loads(STATE.read_text())['status'] if STATE.exists() else None
    if status == 'in_stock' and previous != 'in_stock':
        notify('구매 가능 표시가 감지됐어요! 상품 페이지에서 재고를 확인하세요.\n' + TITLE + '\n' + URL)
    changed = previous != status
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps({'status': status}))
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
            output.write(f'changed={str(changed).lower()}\n')
    print(f'확인 결과: {status}; 이전 상태: {previous}')


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except Exception as error:
        detail = str(error)
        for secret_name in ('TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID'):
            secret = os.environ.get(secret_name)
            if secret:
                detail = detail.replace(secret, '[REDACTED]')
        summary = os.environ.get('GITHUB_STEP_SUMMARY')
        if summary:
            with open(summary, 'a') as output:
                output.write('### Stock check failed\n\n```text\n' + detail[:3000] + '\n```\n')
        raise SystemExit('Stock check failed; see the job summary.')
