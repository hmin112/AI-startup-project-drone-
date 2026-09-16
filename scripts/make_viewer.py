#!/usr/bin/env python3
"""재구성한 포인트클라우드를 브라우저에서 보고 **거리를 잴 수 있는** 단일 HTML로 만든다.

왜 필요한가: 재구성 결과(PLY)는 수백만 점이라 터미널로는 확인할 방법이 없고,
젯슨은 헤드리스라 GUI 뷰어도 못 띄운다. 결과를 눈으로 확인하고 치수를 확인하는
수단이 계속 필요했다(2026-08-20에도 임시 뷰어를 만들어 썼는데 남겨두지 않아
2026-09-09에 다시 만들었다 — 이번엔 저장소에 둔다).

만들어지는 HTML 하나에 점 데이터까지 base64로 들어가므로 파일만 열면 동작한다.

측정 방식(중요): 첫 점을 클릭하면 그 자리 주변에 **평면을 자동으로 맞추고**,
그 면을 기준으로 거리를 "면 따라 / 면에서 수직"으로 나눠 보여준다.
세상 좌표축(높이/수평)으로 나누는 방식을 먼저 만들었다가 폐기했는데, 재려는
면이 축에 정렬돼 있을 이유가 없기 때문이다(교량 하부는 특히). 면 기준이라야
면이 어떤 각도로 기울어져 있든 뜻이 통한다.

정확도 한계: 점 하나의 depth 노이즈가 σ≈21mm라 클릭 자리 주변 점들의 중앙값을
쓰지만, 오차가 공간적으로 상관돼 있어 완전히 없어지진 않는다. 10cm 미만 측정은
신뢰하기 어렵고 1m 이상에서 가장 정확하다.

사용법:
    ./make_viewer.py --cloud ~/frames/desk1/colmap_cloud.ply \
        --poses ~/frames/desk1/colmap/sparse/0/images.txt --scale 0.158481 \
        --out desk_scan.html
"""

import argparse
import base64
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fuse_depth import read_colmap_images  # noqa: E402


def load_ply_xyzrgb(path):
    with open(path, 'rb') as f:
        if f.readline().strip() != b'ply':
            raise ValueError('PLY 파일이 아니다: %s' % path)
        count = None
        while True:
            t = f.readline().split()
            if t and t[0] == b'element' and t[1] == b'vertex':
                count = int(t[2])
            elif t and t[0] == b'end_header':
                break
        dt = np.dtype([('x', '<f4'), ('y', '<f4'), ('z', '<f4'),
                       ('r', 'u1'), ('g', 'u1'), ('b', 'u1')])
        a = np.frombuffer(f.read(dt.itemsize * count), dtype=dt, count=count)
    xyz = np.stack([a['x'], a['y'], a['z']], 1).astype(np.float32)
    rgb = np.stack([a['r'], a['g'], a['b']], 1)
    return xyz, rgb, count


def to_view_frame(p):
    """카메라 광학 좌표계(X=우, Y=하, Z=전방) -> Y-up 보기 좌표계.

    **축 하나만 반전하면 거울상이 된다**(행렬식 -1 = 반사). 2026-09-09에 실제로
    Y만 뒤집었다가 앞뒤가 바뀐 결과를 만들었다. 반드시 X축 기준 180° 회전
    (Y와 Z를 함께 반전, 행렬식 +1)을 써야 한다.
    """
    R = np.diag([1.0, -1.0, -1.0]).astype(np.float32)
    assert abs(np.linalg.det(R) - 1.0) < 1e-6, '반사가 아닌 회전이어야 한다'
    return p @ R.T


def voxel_average(xyz, rgb, voxel_m):
    """격자마다 점을 하나 고르는 대신 **평균**을 낸다.

    위치 노이즈가 줄어들 것을 기대할 수도 있지만 실제로는 거의 안 줄어든다 —
    2026-09-14 실측에서 셀당 187점을 평균내도 평면 잔차가 17.2mm → 16.6mm에
    그쳤다. 프레임 간 정합 오차가 상관돼 있어서 평균으로 상쇄되지 않기 때문이다
    (독립 노이즈였다면 1.3mm까지 떨어졌어야 한다). 그래도 평균을 쓰는 이유는
    **색이 눈에 띄게 깨끗해지고**, 임의의 한 점을 고르는 것보다 표면이 매끄럽게
    보이기 때문이다.
    """
    k = np.floor(xyz / voxel_m).astype(np.int64)
    key = (k[:, 0] * 73856093) ^ (k[:, 1] * 19349663) ^ (k[:, 2] * 83492791)
    order = np.argsort(key)
    ks = key[order]
    bounds = np.r_[0, np.flatnonzero(np.diff(ks)) + 1, len(ks)]
    cnt = np.diff(bounds).astype(np.float64)[:, None]
    pos = np.add.reduceat(xyz[order], bounds[:-1], axis=0) / cnt
    col = np.add.reduceat(rgb[order].astype(np.float64), bounds[:-1], axis=0) / cnt
    return pos.astype(np.float32), np.clip(col, 0, 255).astype(np.uint8)



def main():
    ap = argparse.ArgumentParser(description='포인트클라우드를 측정 가능한 HTML 뷰어로')
    ap.add_argument('--cloud', required=True, help='입력 .ply')
    ap.add_argument('--poses', help='COLMAP images.txt (카메라 궤적을 그리려면)')
    ap.add_argument('--scale', type=float, default=1.0, help='포즈에 곱할 스케일')
    ap.add_argument('--out', required=True, help='출력 .html')
    ap.add_argument('--voxel-mm', type=float, default=11.0,
                    help='다운샘플 격자(기본 11mm). 웹에서 돌릴 크기로 줄이는 용도 — '
                         '너무 촘촘하면 base64가 아티팩트 한도(16MB)를 넘는다')
    ap.add_argument('--title', default='포인트클라우드 스캔')
    ap.add_argument('--stats', help='패널에 넣을 스캔별 수치 JSON '
                                    '([{"title":"촬영","rows":[["해상도","1280x720",""]]}])')
    ap.add_argument('--crop-radius-m', type=float,
                    help='이 반경 안만 남긴다. 대상만 남기면 그만큼 촘촘하게 만들 수 있다. '
                         '중심은 기본적으로 카메라 궤적의 무게중심 — 대상을 빙 돌며 찍었을 때 '
                         '맞는 가정이다. 한 면만 찍었다면 카메라가 한쪽에 몰려 있어 중심이 '
                         '대상과 어긋나므로 --crop-center 로 직접 지정할 것')
    ap.add_argument('--crop-center', help='자를 중심 좌표 "x,y,z" (원본 클라우드 좌표계)')
    ap.add_argument('--trim-pct', type=float, default=97.0,
                    help='중심에서 먼 점 상위 몇 %%를 버릴지(먼 점은 오차가 커서 화면만 어지럽힘)')
    args = ap.parse_args()

    xyz, rgb, n_orig = load_ply_xyzrgb(args.cloud)
    xyz = to_view_frame(xyz)
    traj_raw = None
    if args.poses:
        poses_tmp = read_colmap_images(args.poses)
        traj_raw = to_view_frame(np.array(
            [poses_tmp[n][:3, 3] * args.scale for n in sorted(poses_tmp)], dtype=np.float32))

    if args.crop_radius_m:
        if args.crop_center:
            centre = to_view_frame(
                np.array([[float(v) for v in args.crop_center.split(',')]], dtype=np.float32))[0]
        elif traj_raw is not None:
            centre = traj_raw.mean(axis=0)
        else:
            raise SystemExit('--crop-radius-m 은 --poses 또는 --crop-center 가 필요하다')
        keep_c = np.linalg.norm(xyz - centre, axis=1) < args.crop_radius_m
        print('  관심 영역 자르기: %d -> %d점' % (len(xyz), int(keep_c.sum())))
        xyz, rgb = xyz[keep_c], rgb[keep_c]

    xyz, rgb = voxel_average(xyz, rgb, args.voxel_mm / 1000.0)

    c = np.median(xyz, axis=0)
    d = np.linalg.norm(xyz - c, axis=1)
    keep = d < np.percentile(d, args.trim_pct)
    xyz, rgb = xyz[keep], rgb[keep]

    traj = traj_raw if traj_raw is not None else np.zeros((0, 3), dtype=np.float32)

    lo = xyz.min(0) if not len(traj) else np.minimum(xyz.min(0), traj.min(0))
    hi = xyz.max(0) if not len(traj) else np.maximum(xyz.max(0), traj.max(0))
    rng = hi - lo

    q = ((xyz - lo) / rng * 65535).astype(np.uint16)
    raw = q.tobytes() + rgb.astype(np.uint8).tobytes()
    tq = ((traj - lo) / rng * 65535).astype(np.uint16) if len(traj) else np.zeros(0, np.uint16)

    stats = []
    if args.stats:
        with open(args.stats, encoding='utf-8') as f:
            stats = json.load(f)
    meta = dict(n=int(len(xyz)), lo=[float(v) for v in lo],
                rng=[float(v) for v in rng], nTraj=int(len(traj)),
                nOrig=int(n_orig), voxelMm=args.voxel_mm, title=args.title,
                stats=stats)

    html = (TEMPLATE
            .replace('__TITLE__', args.title)
            .replace('__META__', json.dumps(meta))
            .replace('__PTS__', base64.b64encode(raw).decode())
            .replace('__TRAJ__', base64.b64encode(tq.tobytes()).decode()))
    with open(args.out, 'w', encoding='utf-8') as f:
        f.write(html)

    size_mb = os.path.getsize(args.out) / 1e6
    print('%s — 점 %d개(원본 %d), %.1f MB' % (args.out, len(xyz), n_orig, size_mb))
    if size_mb > 15:
        print('경고: 아티팩트 한도(16MB)에 근접 — --voxel-mm 을 키울 것')


TEMPLATE = r'''<title>__TITLE__</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&display=swap">
<style>
  :root{
    --ground:#0d1214; --panel:#141d20; --panel-2:#192427; --line:#253438;
    --ink:#dce6e8; --muted:#7f9296; --accent:#5bc8b5; --warm:#e0904d; --rule:#f4f9fa;
    --sans:"IBM Plex Sans",ui-sans-serif,system-ui,sans-serif;
    --mono:"IBM Plex Mono",ui-monospace,"SF Mono",Menlo,monospace;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--ground);color:var(--ink);font-family:var(--sans);overflow:hidden}
  #stage{position:fixed;inset:0}
  canvas{display:block;width:100%;height:100%}
  #labels{position:fixed;inset:0;pointer-events:none;overflow:hidden}

  .panel{
    position:fixed;background:color-mix(in srgb,var(--panel) 88%,transparent);
    border:1px solid var(--line);border-radius:4px;
    backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);
  }
  #meta{top:16px;left:16px;width:300px;max-height:calc(100vh - 32px);overflow-y:auto}
  #meta header{padding:14px 16px 12px;border-bottom:1px solid var(--line)}
  h1{margin:0;font-size:15px;font-weight:600;letter-spacing:-.01em;text-wrap:balance}
  .sub{margin:5px 0 0;font-size:11.5px;color:var(--muted);line-height:1.5}

  .grp{padding:12px 16px;border-bottom:1px solid var(--line)}
  .grp:last-child{border-bottom:0}
  .eyebrow{
    font-size:9.5px;letter-spacing:.13em;text-transform:uppercase;
    color:var(--muted);margin:0 0 9px;font-weight:500;
  }
  dl{margin:0;display:grid;grid-template-columns:1fr auto;gap:6px 12px;align-items:baseline}
  dt{font-size:11.5px;color:var(--muted)}
  dd{margin:0;font-family:var(--mono);font-size:11.5px;font-variant-numeric:tabular-nums;text-align:right}
  dd .u{color:var(--muted);font-size:10px;margin-left:2px}
  dd.hi{color:var(--accent)}

  .ctl{display:flex;flex-direction:column;gap:11px}
  .row{display:flex;align-items:center;justify-content:space-between;gap:10px}
  label{font-size:11.5px;color:var(--muted)}
  input[type=range]{-webkit-appearance:none;appearance:none;width:112px;height:2px;
    background:var(--line);border-radius:2px;outline:none}
  input[type=range]::-webkit-slider-thumb{-webkit-appearance:none;width:11px;height:11px;
    border-radius:50%;background:var(--accent);cursor:pointer}
  input[type=range]::-moz-range-thumb{width:11px;height:11px;border:0;border-radius:50%;
    background:var(--accent);cursor:pointer}
  input[type=range]:focus-visible{box-shadow:0 0 0 2px var(--accent)}

  .seg{display:flex;border:1px solid var(--line);border-radius:3px;overflow:hidden}
  .seg button{flex:1;padding:5px 0;font:inherit;font-size:11px;color:var(--muted);
    background:transparent;border:0;cursor:pointer;transition:background .12s,color .12s}
  .seg button+button{border-left:1px solid var(--line)}
  .seg button[aria-pressed=true]{background:var(--panel-2);color:var(--accent)}
  .seg button:focus-visible{outline:2px solid var(--accent);outline-offset:-2px}

  .btn{flex:1;padding:6px 0;font:inherit;font-size:11.5px;color:var(--ink);
    background:var(--panel-2);border:1px solid var(--line);border-radius:3px;cursor:pointer}
  .btn:hover:not(:disabled){border-color:var(--accent)}
  .btn:disabled{opacity:.4;cursor:default}
  .btn:focus-visible{outline:2px solid var(--accent);outline-offset:1px}
  .btns{display:flex;gap:7px}

  .swatch{display:inline-block;width:8px;height:8px;border-radius:50%;
    background:var(--warm);margin-right:6px;vertical-align:1px}

  /* --- 측정 --- */
  #measHint{font-size:11px;color:var(--accent);margin:0 0 9px;line-height:1.45}
  #measHint.idle{color:var(--muted)}
  #measList{list-style:none;margin:0 0 10px;padding:0;display:flex;flex-direction:column;gap:5px;
    max-height:150px;overflow-y:auto}
  #measList:empty{display:none}
  #autoList{list-style:none;margin:0 0 10px;padding:0;display:flex;flex-direction:column;gap:5px}
  #autoList:empty{display:none}
  #autoList li{display:flex;align-items:baseline;gap:8px;padding:4px 7px;
    background:var(--panel-2);border-left:2px solid var(--accent);border-radius:0 3px 3px 0;font-size:11px}
  #autoList .k{color:var(--accent)}
  #autoList .v{margin-left:auto;font-family:var(--mono);font-variant-numeric:tabular-nums}
  .tag.auto{border-color:var(--accent)}
  #profile{margin:0 0 10px;padding:8px 9px;background:var(--panel-2);border-radius:3px}
  #profCap{font-size:10.5px;color:var(--muted);margin-bottom:4px}
  #profSvg{display:block;width:100%;height:auto}
  #profRead{margin:4px 0 0;font-family:var(--mono);font-size:10.5px;color:var(--muted);
    font-variant-numeric:tabular-nums;min-height:13px}
  #profSvg text{font-family:var(--mono);font-size:8px;fill:var(--muted)}
  #profSvg text.val{fill:var(--ink);font-size:9px}
  .tag.auto b{color:var(--accent)}
  #measList li{display:flex;align-items:baseline;gap:8px;
    padding:4px 5px 4px 7px;background:var(--panel-2);border-radius:3px;font-size:11px}
  #measList .n{color:var(--muted);font-family:var(--mono);font-size:10px}
  #measList .v{font-family:var(--mono);font-variant-numeric:tabular-nums;color:var(--ink);
    margin-left:auto}
  #measList .np{color:var(--muted);font-family:var(--mono);font-size:9.5px}
  #measList li{flex-wrap:wrap}
  #measList .comp{flex-basis:100%;color:var(--muted);font-family:var(--mono);
    font-size:9.5px;padding-top:2px;letter-spacing:.02em}
  #measList .x{border:0;background:transparent;color:var(--muted);cursor:pointer;
    font:inherit;font-size:13px;line-height:1;padding:0 3px;border-radius:2px}
  #measList .x:hover{color:var(--ink)}
  #measList .x:focus-visible{outline:1px solid var(--accent)}
  .note{margin:9px 0 0;font-size:10.5px;color:var(--muted);line-height:1.5}

  .tag{
    position:absolute;transform:translate(-50%,-50%);
    padding:4px 8px;border-radius:3px;white-space:nowrap;text-align:center;line-height:1.35;
    background:color-mix(in srgb,var(--panel) 92%,transparent);
    border:1px solid var(--line);
    font-family:var(--mono);font-size:11px;color:var(--rule);
    font-variant-numeric:tabular-nums;
    box-shadow:0 2px 10px rgba(0,0,0,.45);
  }
  .tag b{display:block;font-weight:500;font-size:12px;color:var(--accent)}
  .tag span{display:block;font-size:9.5px;color:var(--muted)}
  .tag.live{border-color:var(--accent);opacity:.92}

  #hint{right:16px;bottom:16px;padding:9px 13px;font-size:11px;color:var(--muted);
    display:flex;gap:14px}
  #hint b{color:var(--ink);font-weight:500}
  #load{position:fixed;inset:0;display:grid;place-content:center;gap:10px;justify-items:center;
    background:var(--ground);font-size:12px;color:var(--muted);z-index:5}
  #bar{width:150px;height:2px;background:var(--line);overflow:hidden}
  #bar i{display:block;height:100%;width:35%;background:var(--accent);
    animation:sweep 1.1s ease-in-out infinite}
  @keyframes sweep{0%{transform:translateX(-100%)}100%{transform:translateX(400%)}}
  @media (prefers-reduced-motion:reduce){#bar i{animation:none;width:100%}}
  @media (max-width:720px){#meta{width:calc(100vw - 32px)} #hint{display:none}}
</style>

<div id="stage"></div>
<div id="labels"></div>

<div id="meta" class="panel">
  <header>
    <h1 id="docTitle">스캔</h1>
    <p class="sub">D455F로 촬영한 프레임을 사진 기반 포즈 추정(SfM)과 depth 측정으로 3D 복원한 결과.</p>
  </header>

  <div class="grp">
    <p class="eyebrow">거리 재기</p>
    <div class="seg" role="group" aria-label="측정 방식" style="margin-bottom:9px">
      <button id="mdTwo" aria-pressed="false">두 점 거리</button>
      <button id="mdAuto" aria-pressed="true">단면 보기</button>
    </div>
    <ul id="autoList"></ul>
    <figure id="profile" hidden>
      <figcaption id="profCap">단면</figcaption>
      <svg id="profSvg" viewBox="0 0 268 132" role="img" aria-label="표면 단면 프로파일"></svg>
      <p id="profRead">&nbsp;</p>
    </figure>
    <p id="measHint" class="idle">결함을 가로지르는 두 점을 대충 찍으세요.</p>
    <ol id="measList"></ol>
    <div class="btns">
      <button class="btn" id="undo" disabled>마지막 취소</button>
      <button class="btn" id="clear" disabled>전체 지우기</button>
    </div>
    <p class="note"><b>첫 점을 찍으면 그 자리의 면을 자동으로 찾습니다.</b>
      면이 기울어져 있어도 상관없이, 그 면을 기준으로 두 값을 함께 보여줍니다 —
      <b>면 따라</b>(면 위에서의 거리)와 <b>면에서</b>(면과 수직으로 떨어진 거리).</p>
    <p class="note"><b>단면 보기</b>는 결함을 가로지르는 두 점을 <b>대충</b> 찍으면 그 선을 따라
      표면이 어떻게 파였는지 그려줍니다. 바깥 평평한 면을 0으로 잡으므로 <b>폭과 깊이를 직접
      읽을 수 있습니다.</b> 결함 가장자리를 정확히 집을 필요가 없습니다 —
      자동 검출은 그림자·모서리가 섞여 같은 결함이 36~122mm로 요동쳐 쓰지 않습니다.</p>
    <p class="note"><b>결함 자동</b> 모드는 클릭한 자리 주변에서 주변보다 어두운 부분을 결함으로 보고,
      그 <b>바깥 끝에서 끝까지</b>의 세로·가로 최대 길이를 재줍니다(강조색). 점구름에서 결함의
      가장자리를 손으로 정확히 집으면 클릭이 안쪽 점에 걸려 실제보다 짧게 재지기 때문입니다.</p>
    <p class="note">클릭 자리 주변 점들의 중앙값을 씁니다(괄호 안이 쓰인 점 개수).
      <b>10cm 미만은 오차가 커서 신뢰하기 어렵고</b> 1m 이상에서 가장 정확합니다.
      확대한 뒤 클릭하면 더 정확합니다.</p>
  </div>

  <div class="grp">
    <p class="eyebrow">복원 결과</p>
    <dl>
      <dt>표시 중인 점</dt><dd class="hi" id="nShown">—</dd>
      <dt>원본 점</dt><dd id="nOrig">—</dd>
      <dt>복셀 다운샘플</dt><dd id="vox">—</dd>
      <dt>공간 크기</dt><dd id="dims">—</dd>
    </dl>
  </div>

  <div id="statGroups"></div>

  <div class="grp">
    <p class="eyebrow">보기</p>
    <div class="ctl">
      <div class="seg" role="group" aria-label="색 표현 방식">
        <button id="mRgb" aria-pressed="true">사진 색</button>
        <button id="mBoost" aria-pressed="false">대비 강조</button>
        <button id="mHeight" aria-pressed="false">높이</button>
      </div>
      <div class="row">
        <label for="size">점 크기</label>
        <input id="size" type="range" min="1" max="10" value="4" step="1">
      </div>
      <div class="row">
        <label for="traj"><span class="swatch"></span>카메라 궤적</label>
        <input id="traj" type="checkbox" checked>
      </div>
      <div class="btns">
        <button class="btn" id="vFront">정면</button>
        <button class="btn" id="vSide">측면</button>
        <button class="btn" id="vTop">위에서</button>
      </div>
      <button class="btn" id="reset">시점 초기화</button>
    </div>
  </div>
</div>

<div id="hint" class="panel">
  <span><b>클릭</b> 거리 재기</span>
  <span><b>드래그</b> 회전</span>
  <span><b>휠</b> 확대</span>
  <span><b>Shift+드래그</b> 이동</span>
</div>

<div id="load"><div id="bar"><i></i></div><span>점 47만 개 불러오는 중…</span></div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
<script>
(function(){
  var META = __META__;
  var PTS_B64 = "__PTS__";
  var TRAJ_B64 = "__TRAJ__";

  function unb64(s){
    var bin = atob(s), n = bin.length, out = new Uint8Array(n);
    for (var i=0;i<n;i++) out[i] = bin.charCodeAt(i);
    return out;
  }

  var N = META.n, lo = META.lo, rng = META.rng;
  var bytes = unb64(PTS_B64);
  var quant = new Uint16Array(bytes.buffer, 0, N*3);
  var cols  = new Uint8Array(bytes.buffer, N*6, N*3);

  // 양자화 좌표 -> 실제 미터. 원점을 공간 중앙으로 옮겨 회전이 자연스럽게 한다.
  var pos = new Float32Array(N*3), colRgb = new Float32Array(N*3);
  var cx = lo[0]+rng[0]/2, cy = lo[1]+rng[1]/2, cz = lo[2]+rng[2]/2;
  var minY = Infinity, maxY = -Infinity;
  for (var i=0;i<N;i++){
    var x = lo[0] + quant[i*3]  /65535*rng[0] - cx;
    var y = lo[1] + quant[i*3+1]/65535*rng[1] - cy;
    var z = lo[2] + quant[i*3+2]/65535*rng[2] - cz;
    pos[i*3]=x; pos[i*3+1]=y; pos[i*3+2]=z;
    if (y<minY) minY=y; if (y>maxY) maxY=y;
    colRgb[i*3]   = Math.pow(cols[i*3]  /255, 2.2);
    colRgb[i*3+1] = Math.pow(cols[i*3+1]/255, 2.2);
    colRgb[i*3+2] = Math.pow(cols[i*3+2]/255, 2.2);
  }
  // 대비 강조: 표면의 얕은 결함은 색 차이가 아주 작다(실측: 255 중 6~19).
  // 밝기 분포의 20~80% 구간을 전체 범위로 펴서 그 차이를 눈에 보이게 만든다.
  // 점검 사진의 밝기/대비를 조정하는 것과 같은 일 — 형상이 아니라 **보기**를
  // 돕는 것이므로, 여기 보이는 얼룩이 곧 깊이 차이라는 뜻은 아니다.
  var lum = new Float32Array(N);
  for (var q=0;q<N;q++) lum[q] = 0.299*cols[q*3] + 0.587*cols[q*3+1] + 0.114*cols[q*3+2];
  var sortedL = Float32Array.from(lum).sort();
  var lo20 = sortedL[Math.floor(N*0.20)], hi80 = sortedL[Math.floor(N*0.80)];
  var lspan = Math.max(1e-3, hi80 - lo20);
  var colB = new Float32Array(N*3);
  for (var q2=0;q2<N;q2++){
    var t2 = Math.min(1, Math.max(0, (lum[q2]-lo20)/lspan));
    // 늘린 밝기를 원래 색조에 다시 입힌다(채도를 약간 살려 평평해 보이지 않게)
    var base = Math.max(1, lum[q2]);
    for (var ch=0; ch<3; ch++){
      var tint = cols[q2*3+ch]/base;
      colB[q2*3+ch] = Math.min(1, Math.pow(t2,0.85) * (0.65 + 0.35*tint));
    }
  }

  var colH = new Float32Array(N*3), spanY = (maxY-minY)||1;
  for (var j=0;j<N;j++){
    var t = (pos[j*3+1]-minY)/spanY;
    colH[j*3]   = 0.05 + 0.88*Math.pow(t,1.35);
    colH[j*3+1] = 0.34 + 0.52*t;
    colH[j*3+2] = 0.40 + 0.16*(1-t);
  }

  var stage = document.getElementById('stage');
  var labels = document.getElementById('labels');
  var scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0d1214);
  var camera = new THREE.PerspectiveCamera(52, 1, 0.02, 200);

  var geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.BufferAttribute(pos,3));
  geo.setAttribute('color', new THREE.BufferAttribute(colRgb,3));
  // 점 간격(복셀)의 약 1.3배가 면처럼 보이면서 뭉개지지 않는 크기다.
  // 고정값을 쓰면 촘촘한 클라우드에서 점이 서로 겹쳐 디테일이 사라진다.
  var PT = (META.voxelMm || 10) / 1000.0;
  var mat = new THREE.PointsMaterial({size:PT*1.3, vertexColors:true, sizeAttenuation:true});
  var cloud = new THREE.Points(geo, mat);
  scene.add(cloud);

  var tb = unb64(TRAJ_B64), tq = new Uint16Array(tb.buffer, 0, META.nTraj*3);
  var tp = new Float32Array(META.nTraj*3);
  for (var k=0;k<META.nTraj;k++){
    tp[k*3]   = lo[0] + tq[k*3]  /65535*rng[0] - cx;
    tp[k*3+1] = lo[1] + tq[k*3+1]/65535*rng[1] - cy;
    tp[k*3+2] = lo[2] + tq[k*3+2]/65535*rng[2] - cz;
  }
  var tgeo = new THREE.BufferGeometry();
  tgeo.setAttribute('position', new THREE.BufferAttribute(tp,3));
  var trajLine = new THREE.Line(tgeo, new THREE.LineBasicMaterial({color:0xe0904d}));
  scene.add(trajLine);

  var renderer = new THREE.WebGLRenderer({antialias:true});
  renderer.setPixelRatio(Math.min(devicePixelRatio,2));
  stage.appendChild(renderer.domElement);

  // ---- 궤도 조작 (회전/확대/이동만 필요해 직접 구현) ----
  var target = new THREE.Vector3(0,0,0);
  var radius0 = Math.max(rng[0],rng[1],rng[2])*1.15;
  var st = {theta:0.62, phi:1.18, r:radius0};
  function applyCam(){
    st.phi = Math.max(0.08, Math.min(Math.PI-0.08, st.phi));
    st.r   = Math.max(0.15, Math.min(60, st.r));
    camera.position.set(
      target.x + st.r*Math.sin(st.phi)*Math.sin(st.theta),
      target.y + st.r*Math.cos(st.phi),
      target.z + st.r*Math.sin(st.phi)*Math.cos(st.theta));
    camera.lookAt(target);
  }

  var autoDots = [], autoTags = [];
  var autoDots = [], autoTags = [];

  // ---- 단면 보기 ----
  // 결함을 가로지르는 두 점을 대충 찍으면, 그 선을 따라 표면이 어떻게 파였는지
  // 그려서 폭과 깊이를 직접 읽게 한다.
  //
  // 왜 자동 검출 대신 이 방식인가: 색만으로 결함을 분리하려 했더니 그림자와 보드
  // 모서리가 섞여 같은 결함이 프레임마다 36~122mm로 요동쳤다(2026-09-14 실측).
  // 사람이 선만 그어주면 나머지는 데이터를 그대로 보여주면 되므로 추정이 끼지 않는다.
  var SLICE_HALF = 0.004;   // 선에서 좌우 4mm 안의 점을 단면에 쓴다
  var SLICE_BIN  = 0.002;   // 2mm 간격으로 묶어 중앙값

  function crossSection(p1, p2){
    var axis = new THREE.Vector3().subVectors(p2, p1);
    var len = axis.length();
    if (len < 0.01) return null;
    axis.normalize();

    // 선 주변의 점을 모아 국소 평면을 잡는다
    var pad = 0.03, rel = new THREE.Vector3(), got = [];
    for (var i=0;i<N;i++){
      rel.set(pos[i*3]-p1.x, pos[i*3+1]-p1.y, pos[i*3+2]-p1.z);
      var t = rel.dot(axis);
      if (t < -pad || t > len+pad) continue;
      var perp = rel.clone().addScaledVector(axis, -t);
      if (perp.lengthSq() > 0.0025) continue;      // 선에서 50mm 이내
      got.push({i:i, t:t, rel:rel.clone()});
    }
    if (got.length < 60) return null;

    var mx=0,my=0,mz=0;
    got.forEach(function(g){ mx+=pos[g.i*3]; my+=pos[g.i*3+1]; mz+=pos[g.i*3+2]; });
    mx/=got.length; my/=got.length; mz/=got.length;
    var cxx=0,cyy=0,czz=0,cxy=0,cxz=0,cyz=0;
    got.forEach(function(g){
      var ax=pos[g.i*3]-mx, ay=pos[g.i*3+1]-my, az=pos[g.i*3+2]-mz;
      cxx+=ax*ax; cyy+=ay*ay; czz+=az*az; cxy+=ax*ay; cxz+=ax*az; cyz+=ay*az;
    });
    var tr=cxx+cyy+czz, M=[[tr-cxx,-cxy,-cxz],[-cxy,tr-cyy,-cyz],[-cxz,-cyz,tr-czz]];
    var nv=[0.577,0.577,0.577];
    for (var it=0; it<40; it++){
      var a0=M[0][0]*nv[0]+M[0][1]*nv[1]+M[0][2]*nv[2];
      var a1=M[1][0]*nv[0]+M[1][1]*nv[1]+M[1][2]*nv[2];
      var a2=M[2][0]*nv[0]+M[2][1]*nv[1]+M[2][2]*nv[2];
      var L=Math.hypot(a0,a1,a2); if (L<1e-12) return null;
      nv=[a0/L,a1/L,a2/L];
    }
    var nrm = new THREE.Vector3(nv[0],nv[1],nv[2]);
    // 카메라를 향하는 쪽을 바깥(+)으로
    if (nrm.dot(new THREE.Vector3(camera.position.x-mx, camera.position.y-my,
                                  camera.position.z-mz)) < 0) nrm.negate();

    var base = new THREE.Vector3(mx,my,mz);
    var samples = got.map(function(g){
      var q = new THREE.Vector3(pos[g.i*3]-base.x, pos[g.i*3+1]-base.y, pos[g.i*3+2]-base.z);
      return {t:g.t, w:q.dot(nrm)};
    });
    // 바깥 평평한 면을 0으로: 파인 곳에 끌려가지 않도록 **상위 60%의 중앙값**을 기준선으로
    var ws = samples.map(function(x){return x.w}).sort(function(a,b){return b-a});
    var refW = ws[Math.floor(ws.length*0.20)];

    var bins = {};
    samples.forEach(function(x){
      var b = Math.round(x.t/SLICE_BIN);
      (bins[b] || (bins[b]=[])).push(x.w);
    });
    var prof = Object.keys(bins).map(Number).sort(function(a,b){return a-b})
      .filter(function(b){ return bins[b].length >= 3; })
      .map(function(b){
        var arr = bins[b].sort(function(u,v){return u-v});
        return {x: b*SLICE_BIN*1000, d: (arr[arr.length>>1] - refW)*1000};
      });
    if (prof.length < 8) return null;
    return {prof:prof, p1:p1, p2:p2};
  }

  var profFig = document.getElementById('profile');
  var profSvg = document.getElementById('profSvg');
  var profCap = document.getElementById('profCap');
  var profRead = document.getElementById('profRead');

  function drawProfile(sec){
    var prof = sec.prof;
    var W=268, H=132, mL=30, mR=8, mT=10, mB=18;
    var xs=prof.map(function(p){return p.x}), ds=prof.map(function(p){return p.d});
    var x0=Math.min.apply(null,xs), x1=Math.max.apply(null,xs);
    var dMin=Math.min.apply(null,ds), dMax=Math.max.apply(null,ds);
    var pad=Math.max(1.5,(dMax-dMin)*0.15);
    var yTop=dMax+pad, yBot=dMin-pad;
    var X=function(v){ return mL+(v-x0)/Math.max(1e-6,x1-x0)*(W-mL-mR); };
    var Y=function(v){ return mT+(yTop-v)/Math.max(1e-6,yTop-yBot)*(H-mT-mB); };

    var deepest=prof.reduce(function(a,b){return b.d<a.d?b:a});
    // 폭: 가장 깊은 값의 25%보다 깊게 파인 구간
    var lvl=deepest.d*0.25, first=null, last=null;
    prof.forEach(function(p){ if(p.d<=lvl){ if(first===null)first=p.x; last=p.x; } });
    var width = (first!==null && last!==null) ? (last-first) : 0;

    var g='';
    // 격자는 뒤로 물린다 — 기준선(바깥 면)만 점선으로 강조
    [yTop, (yTop+yBot)/2, yBot].forEach(function(v){
      g+='<line x1="'+mL+'" y1="'+Y(v).toFixed(1)+'" x2="'+(W-mR)+'" y2="'+Y(v).toFixed(1)+
         '" stroke="#253438" stroke-width="1"/>';
      g+='<text x="'+(mL-4)+'" y="'+(Y(v)+3).toFixed(1)+'" text-anchor="end">'+v.toFixed(0)+'</text>';
    });
    g+='<line x1="'+mL+'" y1="'+Y(0).toFixed(1)+'" x2="'+(W-mR)+'" y2="'+Y(0).toFixed(1)+
       '" stroke="#7f9296" stroke-width="1" stroke-dasharray="3 3"/>';
    if (width>0){
      g+='<rect x="'+X(first).toFixed(1)+'" y="'+mT+'" width="'+(X(last)-X(first)).toFixed(1)+
         '" height="'+(H-mT-mB)+'" fill="#5bc8b5" opacity="0.10"/>';
    }
    var dpath=prof.map(function(p,i){ return (i?'L':'M')+X(p.x).toFixed(1)+' '+Y(p.d).toFixed(1); }).join(' ');
    g+='<path d="'+dpath+'" fill="none" stroke="#5bc8b5" stroke-width="2" stroke-linejoin="round"/>';
    g+='<circle cx="'+X(deepest.x).toFixed(1)+'" cy="'+Y(deepest.d).toFixed(1)+
       '" r="3" fill="#5bc8b5" stroke="#141d20" stroke-width="2"/>';
    g+='<text class="val" x="'+Math.min(W-mR-2,X(deepest.x)+6).toFixed(1)+'" y="'+
       Math.max(mT+9,Y(deepest.d)-5).toFixed(1)+'">'+deepest.d.toFixed(1)+' mm</text>';
    g+='<text x="'+mL+'" y="'+(H-5)+'">0</text>';
    g+='<text x="'+(W-mR)+'" y="'+(H-5)+'" text-anchor="end">'+(x1-x0).toFixed(0)+' mm</text>';
    g+='<rect id="profHit" x="'+mL+'" y="'+mT+'" width="'+(W-mL-mR)+'" height="'+(H-mT-mB)+
       '" fill="transparent"/>';
    g+='<line id="profCross" x1="0" y1="'+mT+'" x2="0" y2="'+(H-mB)+
       '" stroke="#dce6e8" stroke-width="1" opacity="0"/>';
    profSvg.innerHTML=g;
    profFig.hidden=false;
    profCap.textContent='단면 — 바깥 면을 0으로, 아래가 파인 쪽';
    profRead.textContent='최대 깊이 '+deepest.d.toFixed(1)+' mm'+
      (width>0 ? ' · 파인 폭 '+width.toFixed(0)+' mm' : '');

    // 호버 십자선: 임의 지점의 깊이를 읽을 수 있게
    var hit=profSvg.querySelector('#profHit'), cross=profSvg.querySelector('#profCross');
    hit.addEventListener('mousemove', function(e){
      var r=profSvg.getBoundingClientRect();
      var px=(e.clientX-r.left)/r.width*W;
      var mm=x0+(px-mL)/(W-mL-mR)*(x1-x0);
      var nearest=prof.reduce(function(a,b){return Math.abs(b.x-mm)<Math.abs(a.x-mm)?b:a});
      cross.setAttribute('x1',X(nearest.x).toFixed(1));
      cross.setAttribute('x2',X(nearest.x).toFixed(1));
      cross.setAttribute('opacity','0.5');
      profRead.textContent=(nearest.x-x0).toFixed(0)+' mm 지점 · 깊이 '+nearest.d.toFixed(1)+' mm';
    });
    hit.addEventListener('mouseleave', function(){
      cross.setAttribute('opacity','0');
      profRead.textContent='최대 깊이 '+deepest.d.toFixed(1)+' mm'+
        (width>0 ? ' · 파인 폭 '+width.toFixed(0)+' mm' : '');
    });
  }

  var autoDots = [], autoTags = [];

  // ---- 거리 재기 ----
  var raycaster = new THREE.Raycaster();
  var ndc = new THREE.Vector2();
  var markerGeo = new THREE.SphereGeometry(1, 12, 10);
  var markerMat = new THREE.MeshBasicMaterial({color:0xf4f9fa});
  var lineMat = new THREE.LineBasicMaterial({color:0xf4f9fa});
  var guideMat = new THREE.LineBasicMaterial({color:0x5c7076});

  // 첫 점 자리의 **면(평면)을 자동으로 찾는다**.
  // 세상 좌표축(높이/수평)으로 성분을 나누는 건 재려는 면이 기울어져 있으면
  // 아무 의미가 없다 — 교량 하부든 책상이든 면이 축에 정렬돼 있을 이유가 없기 때문.
  // 그래서 클릭한 자리 주변 점들에 평면을 맞추고, 그 면을 기준으로
  //   · 면 따라 (면 위에서의 거리)
  //   · 면에서  (면과 수직으로 떨어진 거리)
  // 두 성분으로 나눈다. 이러면 면의 방향과 무관하게 뜻이 통한다.
  var PLANE_R = 0.06;   // 평면을 맞출 반경 60mm
  function planeNormal(p){
    var r2 = PLANE_R*PLANE_R, sx=0,sy=0,sz=0, pts=[];
    for (var i=0;i<N;i++){
      var dx=pos[i*3]-p.x;   if (dx>PLANE_R||dx<-PLANE_R) continue;
      var dy=pos[i*3+1]-p.y; if (dy>PLANE_R||dy<-PLANE_R) continue;
      var dz=pos[i*3+2]-p.z; if (dz>PLANE_R||dz<-PLANE_R) continue;
      if (dx*dx+dy*dy+dz*dz > r2) continue;
      pts.push(pos[i*3],pos[i*3+1],pos[i*3+2]);
      sx+=pos[i*3]; sy+=pos[i*3+1]; sz+=pos[i*3+2];
    }
    var m = pts.length/3;
    if (m < 12) return null;                 // 점이 너무 적으면 면을 못 믿는다
    sx/=m; sy/=m; sz/=m;
    var cxx=0,cyy=0,czz=0,cxy=0,cxz=0,cyz=0;
    for (var k=0;k<m;k++){
      var ax=pts[k*3]-sx, ay=pts[k*3+1]-sy, az=pts[k*3+2]-sz;
      cxx+=ax*ax; cyy+=ay*ay; czz+=az*az; cxy+=ax*ay; cxz+=ax*az; cyz+=ay*az;
    }
    // 법선 = 공분산의 최소 고유벡터. tr·I − C 로 뒤집으면 그게 최대 고유벡터가 되므로
    // 거듭제곱 반복(power iteration)만으로 안정적으로 구할 수 있다.
    var tr = cxx+cyy+czz;
    var M = [[tr-cxx,-cxy,-cxz],[-cxy,tr-cyy,-cyz],[-cxz,-cyz,tr-czz]];
    var v = [0.577,0.577,0.577];
    for (var it=0; it<40; it++){
      var nx=M[0][0]*v[0]+M[0][1]*v[1]+M[0][2]*v[2];
      var ny=M[1][0]*v[0]+M[1][1]*v[1]+M[1][2]*v[2];
      var nz=M[2][0]*v[0]+M[2][1]*v[1]+M[2][2]*v[2];
      var L=Math.hypot(nx,ny,nz); if (L<1e-12) return null;
      v=[nx/L,ny/L,nz/L];
    }
    return new THREE.Vector3(v[0],v[1],v[2]);
  }

  // 면 기준 분해. 면을 못 찾으면 직선 거리만 돌려준다.
  function decompose(m){
    var d = new THREE.Vector3().subVectors(m.b, m.a);
    var line = d.length();
    if (!m.normal) return {line:line, along:null, off:null, corner:null};
    var off = d.dot(m.normal);
    var along = new THREE.Vector3().copy(d).addScaledVector(m.normal, -off);
    return {line:line, along:along.length(), off:Math.abs(off),
            corner:new THREE.Vector3().addVectors(m.a, along)};
  }
  var measures = [];     // {a,b,dots:[],line,el}
  var pending = null;    // 첫 점만 찍힌 상태
  var hintEl = document.getElementById('measHint');
  var listEl = document.getElementById('measList');
  var undoBtn = document.getElementById('undo');
  var clearBtn = document.getElementById('clear');

  function addDot(p){
    var m = new THREE.Mesh(markerGeo, markerMat);
    m.position.copy(p);
    m.scale.setScalar(Math.max(0.006, st.r*0.006));
    scene.add(m);
    return m;
  }
  function fmt(d){
    return d < 1 ? (d*1000).toFixed(0)+' mm' : d.toFixed(3)+' m';
  }
  // 클릭한 자리의 점 하나를 그대로 쓰면 그 점이 가진 depth 노이즈(σ≈21mm)를
  // 고스란히 뒤집어쓴다. 주변 반경 안의 점들을 모아 **중앙값**을 취하면 노이즈가
  // 크게 줄어든다(평균이 아니라 중앙값을 쓰는 이유는 다른 표면의 점이 섞여 들어와도
  // 끌려가지 않기 위해서 — crack_collector_node에서 크기를 낼 때와 같은 판단).
  var SNAP_R = 0.02;   // 20mm 반경
  function snap(p){
    var r2 = SNAP_R*SNAP_R, xs=[], ys=[], zs=[];
    for (var i=0;i<N;i++){
      var dx=pos[i*3]-p.x;     if (dx>SNAP_R||dx<-SNAP_R) continue;
      var dy=pos[i*3+1]-p.y;   if (dy>SNAP_R||dy<-SNAP_R) continue;
      var dz=pos[i*3+2]-p.z;   if (dz>SNAP_R||dz<-SNAP_R) continue;
      if (dx*dx+dy*dy+dz*dz > r2) continue;
      xs.push(pos[i*3]); ys.push(pos[i*3+1]); zs.push(pos[i*3+2]);
    }
    if (xs.length < 4) return {p:p, n:1};
    function med(a){ a.sort(function(u,v){return u-v}); var m=a.length>>1;
      return a.length%2 ? a[m] : (a[m-1]+a[m])/2; }
    return {p:new THREE.Vector3(med(xs),med(ys),med(zs)), n:xs.length};
  }
  function pick(ev){
    var rect = renderer.domElement.getBoundingClientRect();
    ndc.x = ((ev.clientX-rect.left)/rect.width)*2-1;
    ndc.y = -((ev.clientY-rect.top)/rect.height)*2+1;
    // 화면상 같은 굵기로 집히도록 거리에 비례한 허용반경을 쓴다
    raycaster.params.Points.threshold = Math.max(0.005, st.r*0.005);
    raycaster.setFromCamera(ndc, camera);
    var hits = raycaster.intersectObject(cloud);
    return hits.length ? snap(hits[0].point) : null;
  }
  function refreshUI(){
    listEl.innerHTML = '';
    measures.forEach(function(m,i){
      var li = document.createElement('li');
      var c = decompose(m);
      li.innerHTML = '<span class="n">'+(i+1)+'</span>'
                   + '<span class="np">('+m.n+'점)</span>'
                   + '<span class="v">'+fmt(c.line)+'</span>'
                   + '<span class="comp">'+(c.along===null ? '면을 못 찾음 — 직선만'
                       : '면 따라 '+fmt(c.along)+' · 면에서 '+fmt(c.off))+'</span>';
      var x = document.createElement('button');
      x.className='x'; x.textContent='×';
      x.title = (i+1)+'번 측정 지우기';
      x.setAttribute('aria-label', (i+1)+'번 측정 지우기');
      x.onclick = function(){ removeAt(i); };
      li.appendChild(x);
      listEl.appendChild(li);
    });
    measures.forEach(function(m){
      var c = decompose(m);
      m.el.innerHTML = '<b>'+fmt(c.line)+'</b>' + (c.along===null ? ''
        : '<span>면 따라 '+fmt(c.along)+' · 면에서 '+fmt(c.off)+'</span>');
    });
    undoBtn.disabled = !(measures.length || pending);
    clearBtn.disabled = measures.length === 0 && !pending;
    if (pending){
      hintEl.className = '';
      hintEl.textContent = '끝점을 클릭하세요. (Esc 취소)';
    } else if (measures.length){
      hintEl.className = 'idle';
      hintEl.textContent = '측정 ' + measures.length + '개. 계속 클릭해 더 잴 수 있습니다.';
    } else {
      hintEl.className = 'idle';
      hintEl.textContent = '점을 클릭하면 시작점이 찍힙니다.';
    }
  }
  var sectionMode = true;
  function onPick(ev){
    var p = pick(ev);
    if (sectionMode){
      if (!p){ hintEl.className=''; hintEl.textContent='표면 위를 클릭하세요.'; return; }
      if (!pending){
        pending = {a:p.p, n:p.n, dot:addDot(p.p), normal:null};
        hintEl.className=''; hintEl.textContent='결함 반대편을 클릭하세요. (Esc 취소)';
        undoBtn.disabled=false; clearBtn.disabled=false;
        return;
      }
      var sec = crossSection(pending.a, p.p);
      clearAuto();
      var lm=new THREE.LineBasicMaterial({color:0x5bc8b5});
      var line=new THREE.Line(new THREE.BufferGeometry().setFromPoints([pending.a,p.p]), lm);
      scene.add(line);
      autoTags.push({a:pending.a,b:p.p,el:document.createElement('div'),line:line,
                     dots:[pending.dot, addDot(p.p)]});
      pending=null;
      if (sec){ drawProfile(sec); hintEl.className='idle';
        hintEl.textContent='단면을 그렸습니다. 다시 두 점을 찍으면 갱신됩니다.'; }
      else { profFig.hidden=true; hintEl.className='';
        hintEl.textContent='그 선에서는 점이 부족합니다 — 표면 위를 가로지르게 찍어주세요.'; }
      refreshUI();
      return;
    }
    if (!p){
      hintEl.className = '';
      hintEl.textContent = '그 자리엔 점이 없습니다 — 표면 위를 클릭하세요.';
      return;
    }
    if (!pending){
      pending = {a:p.p, n:p.n, dot:addDot(p.p), normal:planeNormal(p.p)};
      refreshUI();
      return;
    }
    var a = pending.a, b = p.p;
    var rec = {a:a, b:b, normal:pending.normal, n:Math.min(pending.n, p.n)};
    var dc = decompose(rec);
    var line = new THREE.Line(new THREE.BufferGeometry().setFromPoints([a,b]), lineMat);
    scene.add(line);
    // 보조선: a -> (면을 따라 이동) -> (면과 수직으로 이동) -> b
    var guide = new THREE.Line(new THREE.BufferGeometry().setFromPoints(
      dc.corner ? [a, dc.corner, b] : [a, b]), guideMat);
    scene.add(guide);
    var el = document.createElement('div');
    el.className = 'tag';
    el.textContent = '';
    labels.appendChild(el);
    rec.dots=[pending.dot, addDot(b)]; rec.line=line; rec.guide=guide; rec.el=el;
    measures.push(rec);
    pending = null;
    refreshUI();
  }
  function removeAt(i){
    var m = measures.splice(i,1)[0];
    if (!m) return;
    m.dots.forEach(function(d){scene.remove(d)});
    scene.remove(m.line); scene.remove(m.guide); m.el.remove();
    refreshUI();
  }
  function dropLast(){
    if (pending){ scene.remove(pending.dot); pending = null; refreshUI(); return; }
    if (!measures.length) return;
    removeAt(measures.length-1);
  }
  undoBtn.onclick = dropLast;
  clearBtn.onclick = function(){ while(measures.length||pending) dropLast(); };
  addEventListener('keydown', function(e){ if(e.key==='Escape') dropLast(); });

  // 드래그와 클릭 구분 — 조금이라도 끌었으면 회전으로 본다
  var drag=null, moved=0;
  renderer.domElement.addEventListener('pointerdown',function(e){
    drag={x:e.clientX,y:e.clientY,pan:e.shiftKey||e.button===2}; moved=0;
    renderer.domElement.setPointerCapture(e.pointerId);
  });
  renderer.domElement.addEventListener('pointermove',function(e){
    if(!drag) return;
    var dx=e.clientX-drag.x, dy=e.clientY-drag.y;
    moved += Math.abs(dx)+Math.abs(dy);
    drag.x=e.clientX; drag.y=e.clientY;
    if(drag.pan){
      var right=new THREE.Vector3(), up=new THREE.Vector3();
      camera.matrixWorld.extractBasis(right,up,new THREE.Vector3());
      var s=st.r*0.0016;
      target.addScaledVector(right,-dx*s).addScaledVector(up,dy*s);
    } else { st.theta -= dx*0.005; st.phi -= dy*0.005; }
    applyCam();
  });
  function endDrag(e){
    if (drag && moved < 5 && !drag.pan) onPick(e);
    drag=null;
  }
  renderer.domElement.addEventListener('pointerup',endDrag);
  renderer.domElement.addEventListener('pointercancel',function(){drag=null});
  renderer.domElement.addEventListener('contextmenu',function(e){e.preventDefault()});
  renderer.domElement.addEventListener('wheel',function(e){
    e.preventDefault(); st.r *= Math.exp(e.deltaY*0.0012); applyCam();
  },{passive:false});

  function resize(){
    var w=stage.clientWidth, h=stage.clientHeight;
    camera.aspect=w/h; camera.updateProjectionMatrix(); renderer.setSize(w,h,false);
  }
  addEventListener('resize',resize);

  var bRgb=document.getElementById('mRgb'), bB=document.getElementById('mBoost'),
      bH=document.getElementById('mHeight');
  function setMode(k){
    geo.setAttribute('color', new THREE.BufferAttribute(
      k==='rgb'?colRgb : k==='boost'?colB : colH, 3));
    geo.attributes.color.needsUpdate=true;
    bRgb.setAttribute('aria-pressed', k==='rgb');
    bB.setAttribute('aria-pressed', k==='boost');
    bH.setAttribute('aria-pressed', k==='height');
  }
  bRgb.onclick=function(){setMode('rgb')};
  bB.onclick=function(){setMode('boost')};
  bH.onclick=function(){setMode('height')};
  var sizeEl = document.getElementById('size');
  sizeEl.value = 4;                       // 4 = 복셀의 1.3배
  sizeEl.oninput=function(e){ mat.size = PT*0.325*Number(e.target.value); };
  document.getElementById('traj').onchange=function(e){ trajLine.visible=e.target.checked; };
  document.getElementById('reset').onclick=function(){
    target.set(0,0,0); st.theta=0.62; st.phi=1.18; st.r=radius0; applyCam();
  };

  // 축에 정렬된 시점 — 비스듬히 보면 클릭이 어느 깊이에 걸릴지 예측하기 어렵다.
  function view(theta, phi){ st.theta=theta; st.phi=phi; applyCam(); }
  document.getElementById('vFront').onclick=function(){ view(0, Math.PI/2); };
  document.getElementById('vSide').onclick =function(){ view(Math.PI/2, Math.PI/2); };
  document.getElementById('vTop').onclick  =function(){ view(0, 0.09); };

  var bTwo=document.getElementById('mdTwo'), bSec=document.getElementById('mdAuto');
  function setMeasMode(sec){
    sectionMode=sec;
    bSec.setAttribute('aria-pressed', sec); bTwo.setAttribute('aria-pressed', !sec);
    if (pending){ scene.remove(pending.dot); pending=null; }
    hintEl.className='idle';
    hintEl.textContent = sec ? '결함을 가로지르는 두 점을 대충 찍으세요.'
                             : '점을 클릭하면 시작점이 찍힙니다.';
  }
  bSec.onclick=function(){setMeasMode(true)}; bTwo.onclick=function(){setMeasMode(false)};

  document.getElementById('docTitle').textContent = META.title;
  document.getElementById('nShown').textContent = N.toLocaleString();
  document.getElementById('nOrig').textContent = (META.nOrig||0).toLocaleString();
  document.getElementById('vox').innerHTML = META.voxelMm+'<span class="u">mm</span>';

  // 스캔마다 다른 수치(촬영 설정, SfM 통계 등)는 --stats 로 받아 여기서 그린다
  (META.stats||[]).forEach(function(g){
    var d = document.createElement('div'); d.className='grp';
    var rows = g.rows.map(function(r){
      return '<dt>'+r[0]+'</dt><dd>'+r[1]+(r[2]?'<span class="u">'+r[2]+'</span>':'')+'</dd>';
    }).join('');
    d.innerHTML = '<p class="eyebrow">'+g.title+'</p><dl>'+rows+'</dl>';
    document.getElementById('statGroups').appendChild(d);
  });
  document.getElementById('dims').textContent =
    rng[0].toFixed(2)+' × '+rng[1].toFixed(2)+' × '+rng[2].toFixed(2)+' m';

  resize(); applyCam(); refreshUI();

  var mid = new THREE.Vector3();
  (function loop(){
    requestAnimationFrame(loop);
    // 마커는 확대해도 화면상 크기가 비슷하게 유지되도록 매 프레임 조정
    var s = Math.max(0.006, st.r*0.006);
    measures.forEach(function(m){ m.dots.forEach(function(d){d.scale.setScalar(s)}) });
    if (pending) pending.dot.scale.setScalar(s);
    // 거리 라벨을 선 중점의 화면 좌표에 붙인다
    var w = stage.clientWidth, h = stage.clientHeight;
    autoTags.forEach(function(m){
      mid.copy(m.a).add(m.b).multiplyScalar(0.5).project(camera);
      if (mid.z > 1){ m.el.style.display='none'; return; }
      m.el.style.display='';
      m.el.style.left = ((mid.x*0.5+0.5)*w)+'px';
      m.el.style.top  = ((-mid.y*0.5+0.5)*h)+'px';
    });
    autoDots.forEach(function(d){ d.scale.setScalar(Math.max(0.003, st.r*0.005)); });
    measures.forEach(function(m){
      mid.copy(m.a).add(m.b).multiplyScalar(0.5).project(camera);
      if (mid.z > 1){ m.el.style.display='none'; return; }
      m.el.style.display='';
      m.el.style.left = ((mid.x*0.5+0.5)*w)+'px';
      m.el.style.top  = ((-mid.y*0.5+0.5)*h)+'px';
    });
    renderer.render(scene,camera);
  })();
  document.getElementById('load').remove();
})();
</script>'''


if __name__ == '__main__':
    main()
