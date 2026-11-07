# 개인 샘플

## 설치
```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe download_model.py
```

## 실행
유튜브 영상을 연 상태에서 `run_gui.bat` 실행 (대상 영상은 자동 검색, 여러 개면 목록에서 선택)

- 테스트 모드(기본): 인식 결과와 보낼 명령만 표시
- 실제 제어 모드: 선택한 유튜브 창에 포커스를 주고 단축키 전송
- 인식 시작/종료: V 사인 1초 또는 `인식 시작` 버튼
  
## 제스처
| 동작 | 기능 |
|---|---|
| V 사인 1초 유지 | 인식 시작 / 종료 |
| 주먹 쥐었다 펴기 | 재생 / 일시정지 |
| 편 손을 위 / 아래로 | 볼륨 증가 / 감소 |
| 편 손을 오른쪽 / 왼쪽으로 | 10초 앞으로 / 뒤로 |

- 손 이동은 손을 잠깐 멈췄다가 빠르게 움직입니다.
- 시작·종료 제스처와 인식 기준값(`gesture_control/config.py`)은 팀에서 정하기 전의 임시값입니다.
