#!/usr/bin/env python3
"""젯슨 ↔ 비행 컨트롤러(FC) 통신 확인용 진단 도구.

배경: `drone_core`는 전부 MAVROS(`/mavros/*`) 기반인데, 이 프로젝트의 최종
FC는 **Betaflight**라 MAVLink 명령/제어를 하지 않는다(docs 8번 항목 3의
미해결 이슈). 그래서 비행 로직을 짜기 전에 "젯슨과 FC가 애초에 말이 통하는가"
부터 확인해야 하고, Betaflight가 쓰는 프로토콜이 **MSP**다.

Betaflight FC의 USB 포트는 CDC 시리얼(`/dev/ttyACM*`)로 잡히므로 USB 케이블
하나면 되고, 별도 USB-UART 변환기가 없어도 된다(비행 중 텔레메트리까지
쓰려면 그때 UART 배선이 필요).

**안전**: 이 스크립트는 읽기 전용 조회만 한다(arming/모터 명령 없음).
그래도 FC를 만지는 작업이므로 **프로펠러는 빼두고** 진행할 것.

사용법: python3 msp_probe.py [포트]
        포트를 안 주면 /dev/ttyACM* 를 자동 탐색.
"""
import glob
import struct
import sys
import time

try:
    import serial
except ImportError:
    print('에러: pyserial이 필요합니다 — pip3 install --user pyserial', file=sys.stderr)
    sys.exit(1)

# MSP v1 명령 코드 (Betaflight 공통)
MSP_API_VERSION = 1
MSP_FC_VARIANT = 2
MSP_FC_VERSION = 3
MSP_BOARD_INFO = 4
MSP_BUILD_INFO = 5
MSP_STATUS = 101
MSP_RC = 105
MSP_ATTITUDE = 108
MSP_ALTITUDE = 109
MSP_ANALOG = 110


def encode_request(cmd, payload=b''):
    """MSP v1 요청 프레임: '$M<' + 길이 + 명령 + 페이로드 + 체크섬(XOR)."""
    size = len(payload)
    body = bytes([size, cmd]) + payload
    checksum = 0
    for b in body:
        checksum ^= b
    return b'$M<' + body + bytes([checksum])


def read_response(ser, timeout=1.5):
    """응답 프레임 하나를 읽어 (cmd, payload, is_error)로 반환. 실패 시 None."""
    deadline = time.time() + timeout
    # 헤더('$M')를 찾을 때까지 흘려보냄 — FC가 부팅 메시지 등을 섞어 보낼 수 있음
    while time.time() < deadline:
        b = ser.read(1)
        if not b:
            continue
        if b != b'$':
            continue
        if ser.read(1) != b'M':
            continue
        direction = ser.read(1)
        if direction not in (b'>', b'!'):
            continue
        header = ser.read(2)
        if len(header) < 2:
            return None
        size, cmd = header[0], header[1]
        payload = ser.read(size) if size else b''
        ser.read(1)  # 체크섬 — 진단 목적이라 검증까지는 하지 않음
        return cmd, payload, direction == b'!'
    return None


def query(ser, cmd, payload=b''):
    ser.reset_input_buffer()
    ser.write(encode_request(cmd, payload))
    ser.flush()
    result = read_response(ser)
    if result is None:
        return None
    resp_cmd, resp_payload, is_error = result
    if is_error:
        return None
    return resp_payload


def describe(ser):
    ok = True

    payload = query(ser, MSP_API_VERSION)
    if payload and len(payload) >= 3:
        print(f'  MSP 프로토콜   : v{payload[0]}, API {payload[1]}.{payload[2]}')
    else:
        print('  MSP 프로토콜   : 응답 없음')
        ok = False

    payload = query(ser, MSP_FC_VARIANT)
    if payload:
        # 'BTFL'=Betaflight, 'INAV'=INAV, 'ARDU'=ArduPilot 계열
        variant = payload[:4].decode('ascii', errors='replace')
        print(f'  펌웨어 종류    : {variant}', end='')
        print({'BTFL': '  (Betaflight)', 'INAV': '  (INAV)', 'ARDU': '  (ArduPilot)'}.get(variant, ''))

    payload = query(ser, MSP_FC_VERSION)
    if payload and len(payload) >= 3:
        print(f'  펌웨어 버전    : {payload[0]}.{payload[1]}.{payload[2]}')

    payload = query(ser, MSP_BOARD_INFO)
    if payload and len(payload) >= 4:
        print(f'  보드           : {payload[:4].decode("ascii", errors="replace")}')

    payload = query(ser, MSP_STATUS)
    if payload and len(payload) >= 11:
        cycle_time, i2c_errors, sensors, flight_mode_flags = struct.unpack('<HHHI', payload[:10])
        print(f'  루프 주기      : {cycle_time} us')
        print(f'  센서 비트      : 0x{sensors:04x}  (bit0=가속도 bit1=기압계 bit2=지자기 bit3=GPS)')
        print(f'  ARM 상태       : {"ARMED" if flight_mode_flags & 1 else "disarmed"}')

    payload = query(ser, MSP_ATTITUDE)
    if payload and len(payload) >= 6:
        roll, pitch, yaw = struct.unpack('<hhh', payload[:6])
        # roll/pitch는 0.1도 단위, yaw는 도 단위
        print(f'  자세           : roll {roll/10:+.1f}°  pitch {pitch/10:+.1f}°  yaw {yaw}°')

    payload = query(ser, MSP_ANALOG)
    if payload and len(payload) >= 7:
        vbat_legacy = payload[0]  # 0.1V 단위(구형 필드)
        mah, rssi = struct.unpack('<HH', payload[1:5])
        amperage = struct.unpack('<h', payload[5:7])[0]
        voltage = vbat_legacy / 10.0
        if len(payload) >= 9:  # 신형 펌웨어는 0.01V 단위 전압을 뒤에 덧붙임
            voltage = struct.unpack('<H', payload[7:9])[0] / 100.0
        print(f'  배터리         : {voltage:.2f} V, {amperage/100:.2f} A, {mah} mAh, RSSI {rssi}')

    payload = query(ser, MSP_RC)
    if payload and len(payload) >= 8:
        count = len(payload) // 2
        channels = struct.unpack(f'<{count}H', payload[:count*2])
        print(f'  RC 채널({count}) : {list(channels[:8])}')
        if all(c == 0 for c in channels[:4]):
            print('                   → 전부 0: 조종기가 꺼져 있거나 바인딩 안 된 상태')

    return ok


def main():
    ports = [sys.argv[1]] if len(sys.argv) > 1 else sorted(
        glob.glob('/dev/ttyACM*') + glob.glob('/dev/ttyUSB*')
    )
    if not ports:
        print('시리얼 포트를 찾지 못했습니다 (/dev/ttyACM*, /dev/ttyUSB*).')
        print('FC의 USB를 젯슨에 꽂았는지, dmesg에 장치가 잡히는지 확인하세요.')
        return 1

    print(f'후보 포트: {ports}\n')
    for port in ports:
        print(f'[{port}] 연결 시도...')
        try:
            # CDC 시리얼이라 보드레이트는 사실상 무의미하지만 pyserial이 요구함
            with serial.Serial(port, 115200, timeout=0.3) as ser:
                time.sleep(0.3)  # 포트 열자마자 보내면 FC가 놓치는 경우가 있음
                if describe(ser):
                    print(f'\n=> {port} 에서 FC와 통신 성공')
                    return 0
                print('   응답이 없습니다 (이 포트는 FC가 아닐 수 있음)\n')
        except serial.SerialException as exc:
            print(f'   열기 실패: {exc}\n')

    print('어느 포트에서도 MSP 응답을 받지 못했습니다.')
    return 1


if __name__ == '__main__':
    sys.exit(main())
