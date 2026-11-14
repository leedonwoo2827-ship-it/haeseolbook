# 가져온 코드

| 파일 | 출처 | 라이선스 |
|---|---|---|
| `wb.js` | lemomo-ai/lemo-opuscar `styles/whiteboard/demo/engine/wb.js` @ `b65efe6ea393fdc71212898ea4c57c754cfefa46` | MIT (`LICENSE-lemo-opuscar.txt`) |
| `lib.js` | 같은 레포 `core/lib.js` @ 같은 커밋 | MIT |

`wb.js`에서 바꾼 곳은 두 군데뿐이고, 둘 다 `[local]` 주석으로 표시해 두었다.
1. `import ... from '/core/lib.js'`를 `'./lib.js'`로 바꿨다. 이 폴더 안에서만 읽게 하려는 것이다.
2. `Board.render`의 잉크 루프에 `if (s.paint) { ... }`를 넣었다. `hangul.js`의 글자 획이 같은 잉크 층(multiply·마른 질감·지우개)에 그려지게 하려는 것이다.

`hangul.js`, `svgwb.js`, `../main.js`는 이 레포에서 새로 쓴 코드다.
폰트 `../fonts/NanumPenScript-Regular.ttf`는 NHN Nanum Pen Script이고 SIL OFL 1.1을 따른다(`../fonts/OFL.txt`).
