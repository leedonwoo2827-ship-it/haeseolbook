"""샘플 시험지(make_sample.py)용 해설 — 리더 확인용 자체 작성 해설

  python -I tools/pipeline/sample_solutions.py content/build/sample-electric
"""
import json
import sys
from pathlib import Path

SOL = {
    1: r"**정답 ②**" "\n\n### 핵심 개념\n" r"소비전력 $P = I^2R$" "\n\n### 풀이\n" r"$P = 2^2 \times 10 = 40$ W",
    2: r"**정답 ②**" "\n\n### 핵심 개념\n" r"직렬 합성저항은 단순 합 $R = R_1 + R_2$" "\n\n### 풀이\n" r"$4 + 6 = 10\,\Omega$",
    3: r"**정답 ③**" "\n\n### 핵심 개념\n" r"병렬 합성저항 $R = \dfrac{R_1R_2}{R_1+R_2}$" "\n\n### 풀이\n" r"$\dfrac{6\times3}{6+3} = 2\,\Omega$",
    4: r"**정답 ①**" "\n\n### 핵심 개념\n" r"$Q = CV$" "\n\n### 풀이\n" r"$2\times10^{-6} \times 100 = 2\times10^{-4}$ C",
    5: r"**정답 ②**" "\n\n### 핵심 개념\n" r"주기 $T = 1/f$" "\n\n### 풀이\n" r"$1/60 \approx 0.0167$ s $= 16.7$ ms",
    6: r"**정답 ②**" "\n\n### 핵심 개념\n" r"코일 에너지 $W = \tfrac12 LI^2$" "\n\n### 풀이\n" r"$\tfrac12 \times 0.5 \times 2^2 = 1$ J",
    7: r"**정답 ③**" "\n\n### 핵심 개념\n" r"정현파 최댓값 $V_m = \sqrt2\,V$" "\n\n### 풀이\n" r"$\sqrt2 \times 100 \approx 141.4$ V",
    8: r"**정답 ②**" "\n\n### 핵심 개념\n" r"유효전력 $P = S\cos\theta$" "\n\n### 풀이\n" r"$10 \times 0.8 = 8$ kW",
}

out = Path(sys.argv[1]) / "solutions.json"
out.write_text(json.dumps([{"no": k, "markdown": v} for k, v in SOL.items()], ensure_ascii=False, indent=1), encoding="utf-8")
print(f"→ {out}")
