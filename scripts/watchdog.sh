#!/usr/bin/env bash
# 학습/무거운 작업이 젯슨 메모리를 다 먹고 시스템을 멈추는 걸 막는 안전장치.
#
# 왜 필요한가(2026-07-12 실제 사고): YOLO 세그멘테이션 학습이 RAM+swap을 전부
# 소진해 젯슨이 SSH에도 응답하지 않게 됐고, 학교에 직접 가서 전원을 뽑아야만
# 복구할 수 있었다. 원격 작업이 대부분인 이 프로젝트에서 이건 치명적이다.
#
# 동작: 30초마다 swap 사용률을 보고 임계값을 넘으면 감시 대상 프로세스에
# SIGTERM을 보낸다(15초 뒤에도 살아있으면 SIGKILL). 시스템 전체가 멎기 전에
# **원인 프로세스만 먼저 죽여서** 젯슨은 살려두는 게 목적.
#
# 실전 발동 이력: 2026-07-13에 `ros-humble-slam-toolbox` apt 설치가 의존성을
# 대거 끌어오면서 swap이 2분 만에 54%→80%로 치솟았고, 이 watchdog이 학습
# 프로세스를 SIGTERM으로 안전 정지시켜 epoch 43 체크포인트를 보존했다.
# (2026-09-09: 젯슨 초기화로 원본이 소실돼 재작성 — 이번엔 저장소에 둔다.)
#
# 사용법:
#   ./watchdog.sh 'yolo'              # 이름에 yolo가 들어간 프로세스를 감시
#   THRESHOLD=70 ./watchdog.sh 'yolo' # 임계값 조정(기본 80%)
#
# 학습과 함께 띄우는 법(SSH 끊겨도 유지):
#   nohup setsid ./watchdog.sh 'yolo' > ~/watchdog.log 2>&1 &

set -uo pipefail

PATTERN="${1:?사용법: watchdog.sh <감시할 프로세스 이름 패턴>}"
THRESHOLD="${THRESHOLD:-80}"       # swap 사용률 임계값(%)
INTERVAL="${INTERVAL:-30}"         # 확인 주기(초)
GRACE="${GRACE:-15}"               # SIGTERM 후 SIGKILL까지 유예(초)

echo "[watchdog] 감시 시작 — 패턴='$PATTERN' 임계값=${THRESHOLD}% 주기=${INTERVAL}s"

swap_percent() {
  # free 출력의 Swap 행에서 사용률을 정수 %로. swap이 0이면 0을 돌려준다.
  free | awk '/^Swap:/ {if ($2 > 0) printf "%d", $3 * 100 / $2; else print 0}'
}

while true; do
  used="$(swap_percent)"
  # shellcheck disable=SC2009  # pgrep -f 대신 ps를 쓰는 이유는 자기 자신 제외를 명시하기 위함
  pids="$(pgrep -f "$PATTERN" | grep -v "^$$\$" || true)"

  if [ -z "$pids" ]; then
    echo "[watchdog] $(date '+%F %T') swap ${used}% — 감시 대상 없음, 종료"
    exit 0
  fi

  echo "[watchdog] $(date '+%F %T') swap ${used}% (대상 PID: $(echo "$pids" | tr '\n' ' '))"

  if [ "$used" -ge "$THRESHOLD" ]; then
    echo "[watchdog] !!! swap ${used}% >= ${THRESHOLD}% — 대상에 SIGTERM 전송"
    # shellcheck disable=SC2086
    kill -TERM $pids 2>/dev/null || true
    sleep "$GRACE"
    still="$(pgrep -f "$PATTERN" | grep -v "^$$\$" || true)"
    if [ -n "$still" ]; then
      echo "[watchdog] 유예 후에도 살아있음 — SIGKILL"
      # shellcheck disable=SC2086
      kill -9 $still 2>/dev/null || true
    fi
    echo "[watchdog] 정지 완료. swap 현재 $(swap_percent)%"
    exit 1
  fi

  sleep "$INTERVAL"
done
