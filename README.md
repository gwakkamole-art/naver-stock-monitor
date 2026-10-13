# 네이버 상품 재고 감시

대상: 포켓몬 카드 게임 MEGA 확장팩 30th CELEBRATION
https://smartstore.naver.com/moncolle_korea/products/13763561200

공개 GitHub 저장소의 표준 Ubuntu 실행 환경에서 예약 확인 후 텔레그램으로 알려주는 코드입니다. **실제 GitHub 실행 및 네이버 접근은 아직 검증되지 않았습니다.** 로컬 HTTP 요청은 429 차단을 받았습니다. 브라우저 방식도 차단될 수 있습니다. 차단을 우회하지 않으며, 오류를 재입고로 처리하지 않습니다.

## 설정 순서

1. 새 공개 저장소에 `monitor.py`, `requirements.txt`, `.github/workflows/stock.yml`을 동일한 경로로 올립니다. 공개되는 내용은 코드와 상품 URL입니다. 토큰과 채팅 ID를 코드에 넣지 마세요.
2. 텔레그램 공식 `@BotFather`에서 `/newbot`으로 봇을 만듭니다. 발급된 토큰을 GitHub 저장소 Settings → Secrets and variables → Actions → Secrets에 `TELEGRAM_BOT_TOKEN` 이름으로 저장합니다. 토큰은 채팅에 보내지 마세요.
3. 만든 봇과의 대화에서 `/start`를 보냅니다. Telegram Bot API의 `getUpdates` 결과에서 본인 대화의 `message.chat.id`를 확인해 `TELEGRAM_CHAT_ID` Secret으로 저장합니다. 토큰을 외부 chat-ID 조회 봇에 전달하지 마세요. getUpdates 조회가 필요하면 토큰이 로그에 나오지 않도록 별도 도움을 요청하세요.
4. 저장소 Actions → Naver stock monitor → Run workflow에서 `test_telegram`을 체크해 실행합니다. 휴대폰 알림이 오는지 확인합니다.
5. 다시 Run workflow를 실행하되 `test_telegram`을 체크하지 않습니다. 로그에 `sold_out` 또는 `in_stock`이 출력되는지 확인합니다. HTTP 오류나 구조 판별 오류가 나면 예약 감시를 켜지 마세요.
6. 성공하면 Settings → Secrets and variables → Actions → Variables에 `MONITOR_ENABLED`를 `true`로 추가합니다. 약 5분 간격으로 예약 실행합니다. 정지하려면 값을 `false`로 바꾸세요.

## 동작과 한계

- 상품명이 맞는지 확인하고, 명시적인 품절 표시 또는 활성 구매 버튼으로 판정합니다. 화면 구조가 바뀌면 실패로 처리합니다.
- 처음 확인했을 때 구매 가능하면 알립니다. 이후 품절에서 구매 가능으로 바뀔 때 알립니다. 텔레그램 전송 실패 시 상태를 저장하지 않아 다음 확인에서 재시도합니다.
- 마지막 상태는 GitHub Actions 캐시에 저장합니다. 캐시가 만료 또는 삭제되면 구매 가능한 상품에 중복 알림이 올 수 있습니다.
- 네이버가 서버 접근을 차단하거나 로그인을 요구하면 작동하지 않을 수 있습니다. 실제 구매 가능 여부는 상품 페이지에서 확인해야 합니다.
- GitHub 예약 실행은 지연되거나 누락될 수 있습니다. 60일간 저장소 활동이 없으면 공개 저장소의 예약이 자동 중지됩니다. 재입고 사이에 다시 품절되면 놓칠 수 있습니다.
- GitHub 예약은 컴퓨터가 꺼져도 실행됩니다. 공개 저장소의 표준 GitHub-hosted runner는 무료입니다. 큰 실행 환경이나 비공개 저장소로 변경하면 별도 과금 조건을 확인하세요.
- 예약 실행 실패는 Actions에서 확인하세요. 오류 때 텔레그램 알림이 자동 발송되는 구조는 아닙니다.

공식 자료:
- https://docs.github.com/en/actions/concepts/billing-and-usage
- https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows
- https://core.telegram.org/bots/tutorial
