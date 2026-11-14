"""발음 규칙 회귀 — 음성 체크에서 사용자가 직접 고쳐 준 발음(2026-11-04)을 그대로 만들어 내는지.

    .venv\\Scripts\\python tests\\test_read_rules.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from longform.s2_manuscript import fix_counters  # noqa: E402
from longform.voice import DEFAULT_DICT, apply_dict  # noqa: E402
from longform.util import read_json  # noqa: E402

# 기본 발음 사전(longform/voice_dict.json)까지 거친 결과 — 렌더·음성 체크가 실제로 TTS 에 넣는 글
DICT_CASES = [
    ("Windows 11에서 마우스의 주 단추를 바꾸는 곳은 설정의 Bluetooth 및 장치 아래 마우스 항목입니다.",
     "윈도우즈 십일에서 마우스의 주 단추를 바꾸는 곳은 설정의 블루투스 및 장치 아래 마우스 항목입니다."),
    ("Ctrl을 누르면 드라이브와 상관없이 항상 복사, Shift를 누르면 항상 이동입니다.",
     "컨트롤을 누르면 드라이브와 상관없이 항상 복사, 시프트를 누르면 항상 이동입니다."),
    ("ROM은 전원이 꺼져도 내용이 남는다. 주로 SRAM으로 구성한다. EEPROM은 다르다.",
     "롬은 전원이 꺼져도 내용이 남는다. 주로 에스램으로 구성한다. 이이피롬은 다르다."),
]

CASES = [
    # 사용자 지정 발음
    ("컴활 2급 필기 모의고사 01회, 컴퓨터 일반 스무 문항을 처음부터 끝까지 풀어 보겠습니다.",
     "컴활 2급 필기 모의고사 일 회, 컴퓨터 일반 스무 문항을 처음부터 끝까지 풀어 보겠습니다."),
    ("8비트 2의 보수 방식으로 -20을 표현한 뒤, 그 비트열을 16진수로 나타낸 것은?",
     "팔비트 이의 보수 방식으로 마이너스 이십을 표현한 뒤, 그 비트열을 십육진수로 나타낸 것은?"),
    ("먼저 양수 20을 8비트 2진수로 쓰면 00010100입니다.",
     "먼저 양수 이십을 팔비트 이진수로 쓰면 영 영 영 일 영 일 영 영입니다."),
    ("첫째, 모든 비트를 뒤집어 1의 보수 11101011을 만들고, 둘째, 여기에 1을 더해 11101100을 얻습니다.",
     "첫째, 모든 비트를 뒤집어 일의 보수 일 일 일 영 일 영 일 일을 만들고, 둘째, 여기에 일을 더해 일 일 일 영 일 일 영 영을 얻습니다."),
    ("이 값을 앞 4비트와 뒤 4비트로 끊으면 1110은 E, 1100은 C가 되어 16진수 EC입니다.",
     "이 값을 앞 사비트와 뒤 사비트로 끊으면 일 일 일 영은 이, 일 일 영 영은 씨가 되어 십육진수 이 씨입니다."),
    ("Windows 11에서 ⊞+A를 누르면 빠른 설정이 열립니다.",
     "Windows 십일에서 윈도우 단축키와 A를 누르면 빠른 설정이 열립니다."),   # Windows→윈도우즈 는 사전(voice_dict.json)
    ("⊞+D는 바탕 화면을, ⊞+Shift+S는 화면의 원하는 부분을 골라 캡처합니다.",
     "윈도우 단축키와 D는 바탕 화면을, 윈도우 단축키와 시프트 그리고 S는 화면의 원하는 부분을 골라 캡처합니다."),
    ("Ctrl+C로 복사하고 Ctrl+Shift+Esc로 작업 관리자를 엽니다.",
     "컨트롤 C로 복사하고 컨트롤 시프트 이에스씨로 작업 관리자를 엽니다."),
    # 건드리면 안 되는 것
    ("A1 셀에 C를 입력합니다", "A1 셀에 C를 입력합니다"),
    ("16진수 2D와 CPU", "십육진수 이 디와 CPU"),
    ("1000원을 냈다", "1000원을 냈다"),
    ("값 3.5를 넣고 1,000을 더한다", "값 3.5를 넣고 1,000을 더한다"),
    ("A1을 참조, $A$1을 고정", "A1을 참조, $A$1을 고정"),
    ("3-2=1", "3-2=1"),
    ("3개의 사과", "3개의 사과"),
    ("결과는 일공공일 번째", "결과는 일공공일 번째"),
]


def main() -> int:
    bad = 0
    for src, want in CASES:
        got = fix_counters(src)
        if got != want:
            bad += 1
            print(f"✗ {src}\n   기대: {want}\n   결과: {got}")
    rows = [d for d in read_json(DEFAULT_DICT, []) if d.get("from")]
    for src, want in DICT_CASES:
        got = apply_dict(fix_counters(src), rows)
        if got != want:
            bad += 1
            print(f"✗ {src}\n   기대: {want}\n   결과: {got}")
    n =len(CASES) + len(DICT_CASES)
    print(f"{n - bad}/{n} 통과")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
