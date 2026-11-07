"""설정값 모음.

[확정]  = 제안서 + 교수님 피드백 + 팀 답변으로 정해진 내용
[임시]  = 이번 샘플을 돌려 보기 위해 임의로 정한 값 (테스트하며 조정)
"""
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------- 카메라
CAMERA_INDEX = 0          # [임시] 0 = 기본 웹캠. 외장 웹캠이면 1, 2 ... 로 바꿔 보기
FRAME_WIDTH = 640         # [임시]
FRAME_HEIGHT = 480        # [임시]
# 좌우 반전은 설정으로 두지 않습니다 (camera.py 설명 참고).
#   MediaPipe 입력 = 항상 카메라 원본 -> Left/Right = 사용자 실제 손
#   좌표·미리보기 = 항상 거울 기준   -> 사용자 오른쪽 = 화면 오른쪽 = x 증가 (이동 방향 고정)

# ---------------------------------------------------------------- 손 인식 (MediaPipe)
MODEL_PATH = PROJECT_DIR / "models" / "hand_landmarker.task"
NUM_HANDS = 2             # [확정] 교수님 피드백 1: 두 손 모두 인식
MIN_DETECTION_CONFIDENCE = 0.6   # [임시]
MIN_PRESENCE_CONFIDENCE = 0.5    # [임시]
MIN_TRACKING_CONFIDENCE = 0.5    # [임시]

# ---------------------------------------------------------------- 제스처 판별
# 거리 단위는 '손바닥 크기'(손목~중지 뿌리 길이)입니다.
# 카메라에서 멀어져 손이 작게 보여도 같은 기준이 적용되도록 하기 위함입니다.

CONFIRM_FRAMES = 3                # [임시] 같은 손 모양이 연속 N프레임 보여야 인정 (연속 프레임 확인)

# 인식 시작/종료 (교수님 피드백 2 — 동작 자체는 [임시])
ACTIVATION_HOLD_SEC = 1.0         # [임시] V 사인을 이 시간 동안 유지하면 시작 <-> 종료 전환
AUTO_DEACTIVATE_SEC = 10.0        # [임시] 손이 이 시간 동안 안 보이면 자동으로 인식 종료

# 재생/일시정지: 주먹 -> 손 펴기
FIST_TO_OPEN_WINDOW_SEC = 0.8     # [임시] 주먹을 쥔 뒤 이 시간 안에 펴야 인정

# 손 이동(볼륨, 10초 이동)
SWIPE_WINDOW_SEC = 0.5            # [임시] 이 시간 안에 움직인 거리로 판단
SWIPE_MIN_DIST_X = 1.5            # [임시] 좌/우 이동 최소 거리 (손바닥 크기 배수)
SWIPE_MIN_DIST_Y = 1.2            # [임시] 위/아래 이동 최소 거리 (손바닥 크기 배수)
SWIPE_AXIS_RATIO = 1.8            # [임시] 주 방향 이동이 다른 방향보다 이 배 이상 커야 함 (대각선 무시)
REARM_STILL_SEC = 0.3             # [임시] 다음 이동 명령 전에 손을 이 시간 동안 멈춰야 함 (중복·되돌림 방지)
REARM_MAX_MOVE = 0.3              # [임시] '멈춤'으로 볼 최대 움직임 (손바닥 크기 배수)

# 공통
COOLDOWN_SEC = 1.0                # [임시] 명령 실행 후 이 시간 동안 다른 명령 무시
HAND_LOST_RESET_SEC = 0.5         # [임시] 손이 이 시간 이상 사라지면 그 손의 진행 중이던 판별을 초기화

# ---------------------------------------------------------------- 유튜브 제어
# 대상 선택·자동 포커스는 youtube_target.py (Edge/Chrome 탭, Edge/Chrome 유튜브 앱 지원)
WINDOW_NAME = "Gesture Control"    # 미리보기 창 이름. 'YouTube'가 들어가면 안 됨
