#!/usr/bin/env python3
"""스캔 결과를 점검 리포트(단일 HTML)로 만든다.

왜 필요한가: 이 시스템의 실제 산출물은 점구름이나 JSON이 아니라 **"어디에 어떤
크기의 균열이 있는가"를 사람이 읽을 수 있는 보고서**다. 지금까지 파이프라인은
좌표와 수치를 뽑아내기만 했고, 그걸 보고서로 묶는 단계가 없었다.

설계 판단 — **증거 사진을 반드시 싣는다.** 2026-09-14 실측에서 균열이 하나도 없는
장면에 탐지 후보 6개가 나왔고 그중 하나는 9번이나 반복 관측되며 신뢰도 0.56을
기록했다(정체는 벽 포스터의 물결무늬). 즉 **숫자만으로는 진짜와 헛탐지를 구분할 수
없다.** 사람이 사진을 보고 최종 판단할 수 있어야 이 결과를 실제로 쓸 수 있다.

측정값의 의미(리포트에도 명시된다):
  · 길이/폭은 2D 사진에서 찾은 마스크를 depth로 mm 환산한 값 — 실측 오차 약 7%
  · 3D 위치는 SLAM/SfM 포즈로 변환한 지도 좌표
  · **3D 형상으로 잰 값이 아니다** — 얕은 결함은 depth 노이즈에 묻힌다

사용법:
    ./make_report.py --cracks cracks.json --out report.html
    ./make_report.py --cracks cracks.json --stamps ~/frames/scan1/stamps.txt \\
        --viewer-url https://... --out report.html
"""

import argparse
import base64
import datetime as _dt
import html
import json
import os

import cv2
import numpy as np

CROP_PAD = 60          # 증거 사진에서 결함 주변을 얼마나 더 보여줄지(px)
CROP_MAX_W = 420       # 리포트에 싣는 crop의 최대 폭


def load_stamps(path):
    """extract_frames.py가 남긴 프레임별 촬영 거리. 촬영 품질 요약에 쓴다."""
    if not path or not os.path.exists(path):
        return []
    out = []
    with open(path, encoding='utf-8') as f:
        for line in f:
            if line.startswith('#'):
                continue
            parts = line.split()
            if len(parts) >= 3:
                try:
                    d = float(parts[2])
                    if d == d:          # nan 제외
                        out.append(d)
                except ValueError:
                    pass
    return out


def crop_evidence(frames_dir, ev):
    """탐지된 결함 주변을 잘라 base64 JPEG로. 사람이 눈으로 확인할 증거."""
    if not ev or not ev.get('frame'):
        return None, None
    path = os.path.join(frames_dir, 'images', ev['frame'])
    img = cv2.imread(path)
    if img is None:
        return None, None
    h, w = img.shape[:2]
    x0, y0, x1, y1 = ev['bbox_px']
    cx0, cy0 = max(0, x0 - CROP_PAD), max(0, y0 - CROP_PAD)
    cx1, cy1 = min(w, x1 + CROP_PAD), min(h, y1 + CROP_PAD)
    if cx1 - cx0 < 10 or cy1 - cy0 < 10:
        return None, None

    marked = img.copy()
    # cv2는 BGR 순서 — 리포트 강조색 #5bc8b5(RGB 91,200,181)의 BGR 표기
    cv2.rectangle(marked, (x0, y0), (x1, y1), (181, 200, 91), 2)
    crop = marked[cy0:cy1, cx0:cx1]
    if crop.shape[1] > CROP_MAX_W:
        sc = CROP_MAX_W / crop.shape[1]
        crop = cv2.resize(crop, (CROP_MAX_W, int(crop.shape[0] * sc)),
                          interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode('.jpg', crop, [cv2.IMWRITE_JPEG_QUALITY, 88])
    if not ok:
        return None, None
    return base64.b64encode(buf).decode(), ev['frame']


def distance_summary(dists):
    """촬영 거리 분포. 목표 대역(0.6~0.8m)에 얼마나 들었는지가 품질의 선행지표다."""
    if not dists:
        return None
    d = np.array(dists)
    bands = [(0.0, 0.45, '너무 가까움'), (0.45, 0.60, '가까움'),
             (0.60, 0.80, '적정'), (0.80, 1.20, '멂'), (1.20, 99.0, '너무 멂')]
    rows = []
    for lo, hi, tag in bands:
        n = int(((d >= lo) & (d < hi)).sum())
        if n:
            rows.append((tag, '%.2f~%.2f m' % (lo, hi), n, 100.0 * n / len(d)))
    return {
        'n': len(d), 'median': float(np.median(d)),
        'p10': float(np.percentile(d, 10)), 'p90': float(np.percentile(d, 90)),
        'in_band_pct': 100.0 * float(((d >= 0.60) & (d < 0.80)).sum()) / len(d),
        'rows': rows,
    }


def build_html(data, crops, dist, viewer_url, title):
    e = html.escape
    cracks = data.get('cracks', [])
    now = _dt.datetime.now().strftime('%Y-%m-%d %H:%M')

    # --- 요약 타일 ---
    tiles = [('발견된 결함', str(len(cracks)), '건'),
             ('처리 프레임', '{:,}'.format(data.get('frames_processed', 0)), '장'),
             ('총 관측', '{:,}'.format(data.get('total_observations', 0)), '건')]
    if dist:
        tiles.append(('목표 거리 적중', '%.0f' % dist['in_band_pct'], '%'))
    tile_html = ''.join(
        '<div class="tile"><span class="tl">%s</span>'
        '<span class="tv">%s<small>%s</small></span></div>' % (e(a), e(b), e(c))
        for a, b, c in tiles)

    # --- 결함 목록 ---
    if cracks:
        rows = []
        for c in cracks:
            p = c['map_position_m']
            rows.append(
                '<tr><td class="id">%s</td>'
                '<td class="num">%.1f</td><td class="num">%.1f</td>'
                '<td class="num">%.2f</td><td class="num">%d</td>'
                '<td class="num">%.2f</td>'
                '<td class="pos">%.2f, %.2f, %.2f</td></tr>' % (
                    e(c['id']), c['length_mm_median'], c['width_mm_median'],
                    c.get('distance_m_median', 0.0), c['observations'],
                    c['confidence_max'], p[0], p[1], p[2]))
        table = (
            '<table class="list"><thead><tr>'
            '<th>ID</th><th>길이 (mm)</th><th>폭 (mm)</th><th>촬영거리 (m)</th>'
            '<th>관측</th><th>신뢰도</th><th>3D 위치 x, y, z (m)</th>'
            '</tr></thead><tbody>%s</tbody></table>' % ''.join(rows))
    else:
        table = ('<p class="none">이 스캔에서 탐지된 결함이 없습니다. '
                 '대상에 결함이 없거나, 탐지 임계값이 높거나, 촬영 품질이 부족했을 수 있습니다.</p>')

    # --- 증거 사진 ---
    cards = []
    for c in cracks:
        b64, frame = crops.get(c['id'], (None, None))
        img = ('<img src="data:image/jpeg;base64,%s" alt="%s 증거 사진">' % (b64, e(c['id']))
               if b64 else '<div class="noimg">원본 프레임을 찾지 못했습니다</div>')
        cards.append(
            '<figure class="ev"><figcaption><b>%s</b>'
            '<span>%.0f × %.0f mm · 신뢰도 %.2f · %d개 프레임에서 관측</span></figcaption>'
            '%s<span class="src">%s</span></figure>' % (
                e(c['id']), c['length_mm_median'], c['width_mm_median'],
                c['confidence_max'], c['observations'], img, e(frame or '')))
    evidence = ('<div class="evgrid">%s</div>' % ''.join(cards)) if cards else ''

    # --- 촬영 품질 ---
    if dist:
        drows = ''.join(
            '<tr><td>%s</td><td class="num">%s</td><td class="num">%d</td>'
            '<td class="num">%.0f%%</td></tr>' % (e(t), e(r), n, p)
            for t, r, n, p in dist['rows'])
        quality = (
            '<p class="lead">촬영 거리 중앙값 <b>%.2f m</b> '
            '(10~90%% 구간 %.2f~%.2f m). 목표 대역은 <b>0.60~0.80 m</b>입니다.</p>'
            '<table class="list"><thead><tr><th>구간</th><th>거리</th>'
            '<th>프레임</th><th>비율</th></tr></thead><tbody>%s</tbody></table>'
            % (dist['median'], dist['p10'], dist['p90'], drows))
    else:
        quality = '<p class="none">촬영 거리 기록이 없습니다 (stamps.txt 미제공).</p>'

    viewer = ('<p class="lead">3D 재구성 결과는 <a href="%s">여기</a>에서 '
              '돌려보고 직접 치수를 잴 수 있습니다.</p>' % e(viewer_url)) if viewer_url else ''

    meta_rows = [('스캔', data.get('scan_name', '-')),
                 ('생성 일시', now),
                 ('탐지 모델', data.get('model', '-')),
                 ('탐지 임계값', str(data.get('conf_threshold', '-'))),
                 ('병합 전 후보', str(data.get('clusters_before_filter', '-')))]
    if data.get('max_width_mm'):
        meta_rows.append(('폭 상한 필터', '%.0f mm' % data['max_width_mm']))
    meta = ''.join('<tr><td>%s</td><td>%s</td></tr>' % (e(a), e(str(b))) for a, b in meta_rows)

    return TEMPLATE.replace('__TITLE__', e(title)) \
                   .replace('__TILES__', tile_html) \
                   .replace('__TABLE__', table) \
                   .replace('__EVIDENCE__', evidence) \
                   .replace('__QUALITY__', quality) \
                   .replace('__VIEWER__', viewer) \
                   .replace('__META__', meta) \
                   .replace('__DATE__', e(now))


TEMPLATE = r'''<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans+KR:wght@400;500;600&display=swap">
<style>
  :root{
    --ground:#0d1214; --panel:#141d20; --panel2:#192427; --line:#253438;
    --ink:#dce6e8; --muted:#8b9a9e; --accent:#5bc8b5; --warn:#e0904d;
    --sans:"IBM Plex Sans KR",system-ui,-apple-system,sans-serif;
    --mono:"IBM Plex Mono",ui-monospace,Menlo,monospace;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--ground);color:var(--ink);font-family:var(--sans);
       line-height:1.65;-webkit-font-smoothing:antialiased}
  .wrap{max-width:960px;margin:0 auto;padding:48px 24px 80px}
  header{border-bottom:1px solid var(--line);padding-bottom:22px;margin-bottom:34px}
  .eyebrow{font-size:11px;letter-spacing:.16em;text-transform:uppercase;color:var(--accent);
           margin:0 0 8px;font-weight:500}
  h1{margin:0;font-size:27px;font-weight:600;letter-spacing:-.01em}
  .sub{margin:8px 0 0;color:var(--muted);font-size:13.5px}
  h2{font-size:17px;font-weight:600;margin:44px 0 14px;padding-bottom:8px;
     border-bottom:1px solid var(--line)}
  .lead{color:var(--muted);font-size:13.5px;margin:0 0 14px}
  .none{color:var(--muted);font-size:13.5px;background:var(--panel);padding:16px 18px;
        border-radius:4px;margin:0}
  a{color:var(--accent)}

  .tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;
         margin:0 0 8px}
  .tile{background:var(--panel);border:1px solid var(--line);border-radius:4px;padding:14px 16px}
  .tl{display:block;font-size:11.5px;color:var(--muted)}
  .tv{display:block;font-family:var(--mono);font-size:27px;font-weight:500;color:var(--accent);
      line-height:1.25;font-variant-numeric:tabular-nums}
  .tv small{font-size:13px;color:var(--muted);margin-left:3px}

  table.list{width:100%;border-collapse:collapse;font-size:13px;margin:0}
  table.list th{text-align:left;font-weight:500;font-size:11px;letter-spacing:.06em;
    text-transform:uppercase;color:var(--muted);padding:9px 10px;border-bottom:1px solid var(--line)}
  table.list td{padding:9px 10px;border-bottom:1px solid var(--line)}
  table.list tbody tr:hover{background:var(--panel)}
  .num,.pos{font-family:var(--mono);font-variant-numeric:tabular-nums;text-align:right}
  .pos{text-align:left;color:var(--muted);font-size:12px}
  td.id{font-family:var(--mono);color:var(--accent);font-weight:500}

  .evgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:16px}
  .ev{margin:0;background:var(--panel);border:1px solid var(--line);border-radius:4px;
      padding:12px;display:flex;flex-direction:column;gap:9px}
  .ev figcaption{display:flex;flex-direction:column;gap:2px}
  .ev figcaption b{font-family:var(--mono);color:var(--accent);font-size:13px}
  .ev figcaption span{font-size:11.5px;color:var(--muted)}
  .ev img{width:100%;border-radius:3px;display:block;background:#000}
  .ev .src{font-family:var(--mono);font-size:10px;color:var(--muted)}
  .noimg{padding:28px 10px;text-align:center;color:var(--muted);font-size:12px;
         background:var(--panel2);border-radius:3px}

  .note{background:var(--panel);border-left:3px solid var(--warn);border-radius:0 4px 4px 0;
        padding:14px 16px;font-size:13px;color:var(--muted);margin:16px 0 0}
  .note b{color:var(--ink)}
  table.meta{width:100%;border-collapse:collapse;font-size:12.5px;margin-top:8px}
  table.meta td{padding:7px 10px;border-bottom:1px solid var(--line);color:var(--muted)}
  table.meta td:first-child{width:170px}
  table.meta td:last-child{font-family:var(--mono);color:var(--ink)}
  footer{margin-top:52px;padding-top:18px;border-top:1px solid var(--line);
         font-size:11.5px;color:var(--muted)}
  @media print{
    body{background:#fff;color:#111}
    .wrap{max-width:none;padding:0}
    .tile,.ev,.note,.none{background:#f6f6f6;border-color:#ddd}
    .tv,td.id,.ev figcaption b,a{color:#0b7}
    h2{border-color:#ddd}
  }
</style></head><body><div class="wrap">

<header>
  <p class="eyebrow">교량 결함 점검 리포트</p>
  <h1>__TITLE__</h1>
  <p class="sub">AI 교량 결함 측정 드론 · 팀 전컴토 · __DATE__</p>
</header>

<section>
  <h2>요약</h2>
  <div class="tiles">__TILES__</div>
</section>

<section>
  <h2>탐지된 결함</h2>
  __TABLE__
  <div class="note">
    <b>측정값이 어떻게 나왔는지</b> — 길이와 폭은 사진에서 찾은 균열 윤곽을
    깊이 카메라가 잰 거리로 mm 환산한 값입니다(자를 이용한 실측 검증에서 오차 약 7%).
    3D 위치는 그 시점의 카메라 자세로 변환한 지도 좌표입니다.
    여러 프레임에서 반복 관측된 값의 <b>중앙값</b>을 대표값으로 씁니다.
  </div>
</section>

<section>
  <h2>증거 사진</h2>
  <p class="lead">각 결함이 가장 또렷하게 찍힌 프레임입니다. 상자가 탐지 영역입니다.</p>
  __EVIDENCE__
  <div class="note">
    <b>사람이 확인해야 하는 이유</b> — 균열이 전혀 없는 장면에서도 탐지 후보가 나올 수
    있습니다(실측: 벽에 붙은 포스터의 물결무늬 선이 신뢰도 0.56으로 탐지됨). 모델은
    "가늘고 어두운 선"에 반응하므로, <b>신뢰도 숫자만으로 진짜와 헛탐지를 구분할 수
    없습니다.</b> 위 사진으로 최종 판단해 주세요.
  </div>
</section>

<section>
  <h2>촬영 품질</h2>
  __QUALITY__
  <div class="note">
    깊이 측정 오차는 거리의 제곱에 비례합니다(실측 <b>σ ≈ 20.9 × z²</b> mm:
    0.5 m에서 5.3 mm, 1.0 m에서 20.7 mm). 또 결함이 화면에서 약 15~20픽셀보다 작으면
    깊이 영상에서 평활화돼 사라집니다. 두 조건을 함께 만족하는 구간이
    <b>0.6~0.8 m</b>이며, 이 범위를 벗어난 프레임이 많을수록 결과를 신뢰하기 어렵습니다.
  </div>
</section>

<section>
  <h2>3D 재구성</h2>
  __VIEWER__
  <div class="note">
    <b>3D는 위치를 보여주는 용도입니다.</b> 균열의 크기는 위 표의 2D 기반 측정값이
    정확하며, 3D 형상으로 직접 재면 오차가 훨씬 큽니다(같은 30 mm 균열 기준
    2D는 약 ±2 mm, 3D 직접 측정은 약 ±30 mm). 깊이 2 mm 수준의 얕은 결함은 3D
    형상에 아예 남지 않습니다.
  </div>
</section>

<section>
  <h2>스캔 정보</h2>
  <table class="meta">__META__</table>
</section>

<footer>
  이 리포트는 <code>scripts/make_report.py</code>가 스캔 데이터로부터 자동 생성했습니다.
  측정 원리와 검증 기록은 저장소의 <code>docs/</code>를 참고하세요.
</footer>

</div></body></html>
'''


def main():
    ap = argparse.ArgumentParser(description='스캔 결과를 점검 리포트(HTML)로')
    ap.add_argument('--cracks', required=True, help='detect_cracks_offline.py가 만든 JSON')
    ap.add_argument('--frames', help='프레임 디렉토리 (기본: JSON에 기록된 경로)')
    ap.add_argument('--stamps', help='stamps.txt — 촬영 거리 분포를 싣는다')
    ap.add_argument('--viewer-url', help='3D 뷰어 링크(아티팩트 URL 또는 파일 경로)')
    ap.add_argument('--title', help='리포트 제목')
    ap.add_argument('--out', required=True, help='출력 .html')
    args = ap.parse_args()

    with open(args.cracks, encoding='utf-8') as f:
        data = json.load(f)
    frames_dir = args.frames or data.get('frames_dir', '')
    title = args.title or ('%s 점검 결과' % data.get('scan_name', '스캔'))

    crops = {}
    missing = 0
    for c in data.get('cracks', []):
        b64, frame = crop_evidence(frames_dir, c.get('evidence'))
        crops[c['id']] = (b64, frame)
        if b64 is None:
            missing += 1

    stamps = args.stamps
    if not stamps and frames_dir:
        cand = os.path.join(frames_dir, 'stamps.txt')
        stamps = cand if os.path.exists(cand) else None
    dist = distance_summary(load_stamps(stamps))

    html_out = build_html(data, crops, dist, args.viewer_url, title)
    with open(args.out, 'w', encoding='utf-8') as f:
        f.write(html_out)

    print('%s — 결함 %d건, %.2f MB'
          % (args.out, len(data.get('cracks', [])), os.path.getsize(args.out) / 1e6))
    if missing:
        print('  경고: 증거 사진 %d건을 못 넣었습니다 (--frames 경로 확인)' % missing)
    if not dist:
        print('  참고: 촬영 거리 기록이 없어 품질 섹션이 비었습니다 (--stamps)')


if __name__ == '__main__':
    main()
