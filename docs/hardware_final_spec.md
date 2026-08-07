# 하드웨어 최종 사양 (2026-08-07)

팀 전컴토 — AI 교량 결함 측정 드론. Original 스펙 대비 변경사항 반영. `bridge_drone_project_summary.md`의 하드웨어 구성(2번)/무선 통신(3번)/열린 이슈(8번)에도 이 변경이 반영돼 있음.

## 1. 원래 스펙에서 변경된 것들

| 항목 | 원래 계획 | 최종 변경 | 이유 |
|---|---|---|---|
| RC 수신기 | ELRS 915MHz | **ELRS 2.4GHz** | RadioMaster Pocket 조종기 내장 RF가 2.4GHz 전용이라 915MHz와 주파수 자체가 안 맞음 (외장 모듈 없이 해결하려 교체) |
| LiDAR (RPLIDAR A3) | 탑재 예정 | **제외** | D455F(RealSense RGB-D 카메라) 단독으로 Visual SLAM(RTAB-Map 등) 처리, 무게/비용 절감 |
| TFmini | 탑재 예정 | **제외** | 고도유지=FC 내장 기압계(BMP280)로 대체, 근접 경고=D455F depth 데이터로 소프트웨어 처리, Failsafe=GPS 불필요한 "착륙(Land)" 모드로 이미 해결됨 |
| GPS 모듈 | 미정 | **미사용 확정** | 다리 하부는 GPS 음영구역이라 실효성 없음. 위치추정은 SLAM이 전담 |
| Jetson 전원 | 미정 | **MATEK BEC12S-PRO 추가** | 6S 배터리(22~25V) → 12V로 강압, Jetson DC 배럴잭(9~20V 허용)에 공급 |

## 2. 최종 확정 하드웨어 목록

**비행 코어**
- 프레임: Mark4 7inch 295mm (Y7S 키트)
- FC/ESC: YSIDO F405 V3 + 60A 4-in-1 ESC 스택 (Betaflight 2025.12.5로 최신화)
- 모터: 2806.5 1300KV × 4
- 프로펠러: 7040R 계열 (CW/CCW 세트)
- 배터리: HRB 6S 5000mAh 50C (22.2V 정격)

**RF/영상**
- RC 수신기: ExpressLRS Nano RX **2.4GHz**
- 조종기: RadioMaster Pocket (내장 2.4GHz ELRS, EdgeTX)
- VTX: 2.5W, 4.9/5.8GHz (FlyTop 방열판)
- FPV 카메라: 별도 모듈 (조종용, D455F와 별개)

**AI/센서 (비행 스택과 별도)**
- Jetson Orin Nano — 전원: MATEK BEC12S-PRO(12V 출력)로 메인 배터리 공유
- RealSense D455F — AI 균열 탐지 + SLAM 겸용 (LiDAR 대체)

**안전**
- 피에조 버저 장착 완료 (BZ+/GND)
- Failsafe: Land 모드 (GPS 불필요)

## 3. 남은 하드웨어 이슈 (완성 후에도 확인 필요)
- [ ] 프로펠러 너트 풀림 문제 — 세트 스크류 나사 없음, 스레드락(나사 고정제) 구매 필요. 현재는 접착제 없이 손으로 최대한 꽉 조인 상태로 임시 운용 중
- [ ] 비행 전마다 프로펠러 너트 조임 상태 육안/촉각 확인 습관화 (스레드락 적용 전까지 필수)
- [ ] Jetson BEC 연결 후 실측: YOLO 추론 시 전압 흔들림(브라운아웃) 여부 확인, 필요시 BEC 출력단에 필터 커패시터 추가

## 4. 소프트웨어/설정 (참고, 이전 정리와 연결)
- Betaflight ARM(SC/AUX3), ANGLE(SB/AUX2) 매핑 완료
- Arm/모터 회전방향 전부 정상 확인됨
- 조종기 바인딩 완료 (2.4GHz)
