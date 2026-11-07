# 개인 샘플

## 설치
1. https://www.python.org/downloads/windows/ 에서 Python 3.14 설치 (`Add python.exe to PATH` 체크)
2. 이 저장소에서 `Code` → `Download ZIP` → 압축 풀기
3. 압축 푼 폴더에서 빈 곳을 Shift + 오른쪽 클릭 → `터미널에서 열기`
4. 아래 명령을 차례로 입력
   ```powershell
   py -3.14 -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   .\.venv\Scripts\python.exe download_model.py
   ```
   - 마지막 명령은 손 인식 모델(약 8MB)을 `models` 폴더에 받습니다.
     안 되면 아래 주소에서 직접 받아 `models\hand_landmarker.task` 로 저장하세요.
     `https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task`
5. (선택) 설치 확인: `.\.venv\Scripts\python.exe -m unittest` → 마지막에 `OK`

## 실행
1. 유튜브에서 영상을 하나 엽니다.
2. 폴더의 **`run_gui.bat`** 을 더블클릭합니다. (설치를 먼저 해야 실행됩니다)
3. 오른쪽 `제어할 유튜브` 에 영상이 나타나는지 확인합니다. 여러 개면 목록에서 고릅니다.
4. 처음에는 **테스트 모드**(파란 띠)입니다. 실제로 제어하지 않고, 어떤 명령이 나갈지만 보여 줍니다.
5. 제스처가 잘 인식되면 맨 위에서 **실제 제어 모드**(빨간 띠)로 바꿉니다.
6. V 사인 1초(또는 `인식 시작` 버튼)로 인식을 켜고 제스처를 합니다.

## 제스처
| 동작 | 기능 |
|---|---|
| V 사인 1초 유지 | 인식 시작 / 종료 |
| 주먹 쥐었다 펴기 | 재생 / 일시정지 |
| 편 손을 위 / 아래로 | 볼륨 증가 / 감소 |
| 편 손을 오른쪽 / 왼쪽으로 | 10초 앞으로 / 뒤로 |

- 손 이동은 손을 잠깐 멈췄다가 빠르게 움직입니다.
- 시작·종료 제스처와 인식 기준값(`gesture_control/config.py`)은 팀에서 정하기 전의 임시값입니다.

## 안 될 때
- `run_gui.bat` 에 `[ERROR]` 가 나오면 → 설치 4번을 다시 확인
- 웹캠이 안 켜지면 → 줌·팀즈 등 카메라를 쓰는 프로그램 종료
- 목록에 `제어 불가` 가 보이면 (Chrome) → Chrome 주소창에 `chrome://accessibility` 를 열어
  `Native accessibility API support`, `Web accessibility` 가 체크돼 있는지 확인
- 그 밖의 오류는 `logs\app.log` 에 기록됩니다
