#!/usr/bin/env python3
"""스케일 검증용 타겟을 A4로 뽑는다 (인쇄해서 벽에 붙이고 같이 스캔한다).

**왜 필요한가.** 재구성의 실제 크기(스케일)는 depth에서 복원한다. 지금까지 그 값이
맞는지는 "복원된 카메라 궤적이 촬영 시 지시한 동선과 비슷하다"는 정도로만 확인했고,
치수 자체를 **아는 길이와 맞대본 적이 없다**. 측정 장비를 표방하면서 눈금을 한 번도
대조하지 않은 셈이다.

책상 스캔으로 대신할 수 없다. 거기 찍힌 건 모니터·키보드·상장인데 전부 모델마다
치수가 달라, 가정한 값으로 재면 **검증이 아니라 검증처럼 보이는 숫자**가 나온다.
그래서 크기를 아는 물체를 직접 만든다.

**무엇을 검증하는가 — 둘은 다른 문제다.**

1. **depth가 거리를 맞게 재는가** — 마커 한 변(한 프레임 안)을 재서 인쇄 치수와
   비교한다. 한 프레임 안의 치수는 depth와 내부파라미터만으로 정해지므로
   SfM 스케일과 무관하다.
2. **SfM 스케일이 맞는가** — 같은 마커를 서로 다른 위치의 두 프레임에서 보고
   각각 월드 좌표로 보냈을 때 **같은 자리에 떨어지는가**. 스케일이 k배 틀리면
   카메라 중심이 그만큼 어긋나 두 결과가 벌어지고, 그 벌어짐은 **두 촬영 지점
   사이 거리에 비례**한다. 이 기울기가 곧 스케일 오차다. 2번에는 마커의 실제
   크기가 필요 없다 — 같은 점이라는 사실만 있으면 된다.

**인쇄 배율 함정**: 프린터는 기본값이 "맞춤(fit to page)"이면 97% 정도로 줄여
인쇄한다. 그러면 타겟이 3% 작아지고, 검증 결과가 3% 오차로 나오는데 **틀린 건
재구성이 아니라 종이다.** 그래서 시트에 길이를 확인할 선을 같이 넣는다. 인쇄 후
자로 재서 160.0mm가 아니면 `--printed-mm`으로 실제 잰 값을 넘기면 된다.

쓰는 법:
    python3 scripts/make_scale_target.py --out ~/scale_target.png
    # 100% 배율(실제 크기)로 A4에 인쇄 → 검증선을 자로 확인 → 벽에 평평하게 붙임
    # → 0.6~0.8m 거리에서 평소처럼 스캔
"""

import argparse
import json
import os

import cv2
import numpy as np

A4_MM = (210.0, 297.0)
DPI = 300
MM = DPI / 25.4                 # 1mm가 몇 픽셀인가

# 치수는 **촬영 거리에서 역산해서** 정했다. 목표 대역은 0.6~0.8m이고 fx≈647,
# 1280폭이므로 0.7m에서 1mm는 약 0.92픽셀이다. ArUco는 셀 하나가 최소 5픽셀쯤
# 돼야 비트가 읽히는데, 4x4 딕셔너리는 테두리 포함 6칸이므로 마커 한 변이
# 최소 30픽셀(≈33mm)은 돼야 한다. 여유를 둬 60mm로 잡으면 0.7m에서 55픽셀,
# 셀당 9픽셀이라 흔들림이 좀 있어도 읽힌다.
#
# **처음엔 40mm/5x5로 만들었다가 합성 장면에서 한 장도 못 읽었다.** 사각형 후보는
# 잡히는데 비트 해독에서 전부 떨어졌다 — 0.7m에서 37픽셀, 5x5는 테두리 포함
# 7칸이라 셀당 5.3픽셀로 경계였다. 종이에서 크게 보인다고 카메라에서도 큰 게
# 아니다. 거리에서 역산할 것.
MARKER_MM = 60.0                # 마커 한 변
SPAN_X_MM = 120.0               # 마커 중심 사이 가로 거리
SPAN_Y_MM = 200.0               # 마커 중심 사이 세로 거리
CHECK_MM = 160.0                # 인쇄 배율 확인선 길이
DICT = cv2.aruco.DICT_4X4_50    # 비트가 적을수록 멀리서 읽힌다


def px(mm):
    return int(round(mm * MM))


def put_label(img, text, mm_xy, scale=0.7, thick=2):
    cv2.putText(img, text, (px(mm_xy[0]), px(mm_xy[1])),
                cv2.FONT_HERSHEY_SIMPLEX, scale, (90, 90, 90), thick, cv2.LINE_AA)


def main():
    ap = argparse.ArgumentParser(description='스케일 검증용 ArUco 타겟 생성(A4)')
    ap.add_argument('--out', default=os.path.expanduser('~/scale_target.png'))
    args = ap.parse_args()

    page = np.full((px(A4_MM[1]), px(A4_MM[0])), 255, np.uint8)
    aruco_dict = cv2.aruco.getPredefinedDictionary(DICT)

    cx, cy = A4_MM[0] / 2, A4_MM[1] / 2
    centers = {}
    for mid, (sx, sy) in enumerate(((-1, -1), (1, -1), (-1, 1), (1, 1))):
        mx = cx + sx * SPAN_X_MM / 2
        my = cy + sy * SPAN_Y_MM / 2
        centers[mid] = (mx, my)
        img = cv2.aruco.generateImageMarker(aruco_dict, mid, px(MARKER_MM))
        x0, y0 = px(mx - MARKER_MM / 2), px(my - MARKER_MM / 2)
        page[y0:y0 + img.shape[0], x0:x0 + img.shape[1]] = img
        put_label(page, 'id %d' % mid, (mx - MARKER_MM / 2, my + MARKER_MM / 2 + 7), 0.6)

    # 인쇄 배율 확인선 — 이게 160.0mm가 아니면 종이가 틀린 것이다
    ly = cy
    lx0, lx1 = cx - CHECK_MM / 2, cx + CHECK_MM / 2
    cv2.line(page, (px(lx0), px(ly)), (px(lx1), px(ly)), 40, 3)
    for x in (lx0, lx1):
        cv2.line(page, (px(x), px(ly - 5)), (px(x), px(ly + 5)), 40, 3)
    put_label(page, 'ruler check: this line = %.1f mm' % CHECK_MM, (lx0, ly - 9), 0.75)
    put_label(page, 'print at 100%% (do NOT "fit to page")', (lx0, ly + 16), 0.7)

    put_label(page, 'marker side %.1f mm   centers %.1f x %.1f mm'
              % (MARKER_MM, SPAN_X_MM, SPAN_Y_MM), (20, A4_MM[1] - 14), 0.7)

    cv2.imwrite(args.out, page)

    # 참값을 파일로 같이 남긴다 — 검증 스크립트가 이걸 읽으므로 둘이 어긋날 수 없다
    truth = {
        'dictionary': 'DICT_4X4_50',
        'marker_mm': MARKER_MM,
        'span_x_mm': SPAN_X_MM,
        'span_y_mm': SPAN_Y_MM,
        'check_line_mm': CHECK_MM,
        'centers_mm': {str(k): list(v) for k, v in centers.items()},
        'pair_mm': {},
    }
    for a in centers:
        for b in centers:
            if a < b:
                dx = centers[a][0] - centers[b][0]
                dy = centers[a][1] - centers[b][1]
                truth['pair_mm']['%d-%d' % (a, b)] = float(np.hypot(dx, dy))
    truth_path = os.path.splitext(args.out)[0] + '.json'
    with open(truth_path, 'w', encoding='utf-8') as f:
        json.dump(truth, f, indent=2)

    print('타겟: %s  (%dx%d px, 300dpi A4)' % (args.out, page.shape[1], page.shape[0]))
    print('참값: %s' % truth_path)
    print()
    print('  마커 한 변      %.1f mm' % MARKER_MM)
    for k, v in sorted(truth['pair_mm'].items()):
        print('  마커 %s 중심거리 %.2f mm' % (k, v))
    print()
    print('인쇄 후 할 일: 확인선을 자로 재서 %.1fmm인지 보고, 다르면' % CHECK_MM)
    print('verify_scale.py에 --printed-mm <실제로 잰 값> 으로 알려줄 것.')


if __name__ == '__main__':
    main()
