"""전체 실행 (시스템 연동 담당: 조하연 — 샘플 구현).

    python run.py            테스트 모드: 키를 보내지 않고 인식 결과와 예정 명령만 표시 (기본값)
    python run.py --live     실제 모드: 유튜브 창이 맨 앞에 있을 때 단축키를 보냄
    python run.py --camera 1 다른 웹캠 사용

종료: 미리보기 창을 클릭하고 q 또는 ESC / 미리보기 창 닫기(X) / 터미널에서 Ctrl+C

흐름 (한 프레임마다 반복)
    Camera.read()  ->  HandTracker.detect()  ->  GestureRecognizer.update()  ->  YouTubeController.execute()
      원본 프레임        손 관절 좌표 list[Hand]      이벤트 list[Event]              단축키 전송 / 테스트 표시
                         (원본으로 인식, 좌표는 거울 화면 기준)
    mirror_view(원본) -> 미리보기 화면 (반전은 여기서만)
"""
import argparse
import time

import cv2

from gesture_control import config
from gesture_control.camera import Camera, mirror_view
from gesture_control.common import EventType
from gesture_control.controller import YouTubeController, select_target
from gesture_control.gestures import GestureRecognizer
from gesture_control.hand_tracker import HandTracker
from gesture_control.overlay import GRAY, GREEN, RED, WHITE, YELLOW, draw_hand, draw_lines, put_text

MAX_READ_FAILS = 30  # 연속으로 이만큼 프레임을 못 읽으면 종료


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def make_backend():
    """유튜브 창을 다루는 UIA 백엔드. 준비할 수 없으면 None (그래도 손 인식·테스트 표시는 동작)."""
    try:
        from gesture_control.youtube_target import UIABackend
        return UIABackend()
    except Exception as e:  # Windows가 아니거나 uiautomation 미설치
        log(f"유튜브 창 제어 기능을 준비하지 못했습니다: {e}")
        return None


def choose_target(backend):
    if backend is None:
        return None
    print("\n[제어 대상 찾는 중] 이 단계는 창 목록을 읽기만 하고 포커스를 바꾸지 않습니다.")
    return select_target(backend)


def print_banner(live: bool) -> None:
    mode = ("실제 모드 (명령 때만 선택한 유튜브 창을 자동 활성화 + 플레이어 포커스 후 키 전송)" if live
            else "테스트 모드 (창 포커스를 바꾸지 않고 키도 보내지 않음)")
    print(f"""
==================== 손 제스처 동영상 제어 (샘플) ====================
 모드: {mode}
 [인식 시작/종료]  V 사인(검지+중지)을 1초 유지        * 샘플용 임시 동작
 [재생/일시정지]  주먹을 쥐었다가 펴기
 [볼륨 +/-]       편 손을 위 / 아래로 빠르게 이동
 [10초 뒤/앞]     편 손을 왼쪽 / 오른쪽으로 빠르게 이동
  - 손 이동 명령 뒤에는 손을 잠깐(0.3초) 멈춰야 다음 이동이 인식됩니다.
  - 명령 후 {config.COOLDOWN_SEC:.0f}초 동안은 다른 명령이 무시됩니다(쿨다운).
 대상 다시 선택: 미리보기 창에서 r (번호는 이 터미널에 입력)
 종료: 미리보기 창에서 q / ESC, 창 닫기, 또는 이 터미널에서 Ctrl+C
=====================================================================
""", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="손 제스처로 유튜브 제어 (샘플)")
    parser.add_argument("--live", action="store_true", help="실제로 유튜브에 키를 보냄 (기본: 테스트 모드)")
    parser.add_argument("--camera", type=int, default=config.CAMERA_INDEX, help="웹캠 번호 (기본 0)")
    args = parser.parse_args()

    print_banner(args.live)
    recognizer = GestureRecognizer()
    backend = make_backend()
    controller = YouTubeController(live=args.live, backend=backend, target=choose_target(backend))

    with Camera(args.camera, config.FRAME_WIDTH, config.FRAME_HEIGHT) as cam, \
         HandTracker(config.MODEL_PATH, config.NUM_HANDS, config.MIN_DETECTION_CONFIDENCE,
                     config.MIN_PRESENCE_CONFIDENCE, config.MIN_TRACKING_CONFIDENCE) as tracker:
        cv2.namedWindow(config.WINDOW_NAME)
        try:  # 미리보기 창을 항상 위에 (포커스는 뺏지 않음) — 유튜브를 보면서 인식 상태 확인용
            cv2.setWindowProperty(config.WINDOW_NAME, cv2.WND_PROP_TOPMOST, 1)
        except cv2.error:
            pass

        fps, last = 0.0, time.monotonic()
        read_fails = 0
        prev_hand_count = -1
        banner_text, banner_color, banner_until = "", WHITE, 0.0

        try:
            while True:
                # 1) 웹캠 프레임 (원본, 반전 안 함)
                raw = cam.read()
                if raw is None:
                    read_fails += 1
                    if read_fails >= MAX_READ_FAILS:
                        log("웹캠에서 영상을 계속 받지 못해 종료합니다. 연결 상태를 확인하세요.")
                        break
                    continue
                read_fails = 0
                now = time.monotonic()

                # 2) 손 인식: 원본을 넣어야 Left/Right가 사용자 실제 손 기준.
                #    돌려받는 좌표는 거울 화면 기준(사용자 오른쪽 = x 증가)
                hands = tracker.detect(raw, int(now * 1000))
                frame = mirror_view(raw)  # 미리보기용 거울 화면
                if len(hands) != prev_hand_count:
                    log(f"손 {len(hands)}개 인식" if hands else "손이 보이지 않습니다")
                    prev_hand_count = len(hands)

                # 3) 제스처 판별 (+ 오작동 방지)
                events = recognizer.update(hands, now)

                # 4) 유튜브 제어 / 테스트 표시
                for ev in events:
                    if ev.type == EventType.COMMAND:
                        result = controller.execute(ev.command)
                        log(f"{ev.message}  =>  {result.message}")
                        banner_text = ev.command.value + ("" if args.live else " (test)")
                        banner_color = GREEN if (result.sent or not args.live) else RED
                        banner_until = now + 1.5
                    else:
                        log(ev.message)
                        if ev.type in (EventType.ACTIVATED, EventType.DEACTIVATED):
                            banner_text = "START" if ev.type == EventType.ACTIVATED else "STOP"
                            banner_color, banner_until = YELLOW, now + 1.5

                # 5) 화면 표시
                fps = 0.9 * fps + 0.1 / max(now - last, 1e-6)
                last = now
                for key, hand in zip(GestureRecognizer._keys(hands), hands):
                    draw_hand(frame, hand, recognizer.hand_info.get(key, ""))
                lines = [
                    ("MODE: LIVE (sending keys)" if args.live else "MODE: TEST (no keys)", RED if args.live else GRAY),
                    ("ACTIVE" if recognizer.active else "INACTIVE - hold V sign 1s", GREEN if recognizer.active else YELLOW),
                    (f"TARGET: {controller.target.short()}" if controller.target else "TARGET: NONE (r: select)",
                     GRAY if controller.target else RED),
                ]
                cd = recognizer.cooldown_left(now)
                if cd > 0:
                    lines.append((f"cooldown {cd:.1f}s", GRAY))
                if not hands:
                    lines.append(("NO HAND", RED))
                lines.append((f"FPS {fps:4.1f}   q/ESC: quit", GRAY))
                draw_lines(frame, lines)
                if now < banner_until:
                    put_text(frame, banner_text, (10, frame.shape[0] - 20), banner_color, scale=1.2)

                cv2.imshow(config.WINDOW_NAME, frame)
                key = cv2.waitKey(1) & 0xFF
                if key in (ord("q"), 27):
                    break
                if key == ord("r"):
                    log("대상을 다시 찾습니다. 번호 입력은 터미널 창에서 하세요 (그동안 인식은 멈춤).")
                    controller.target = choose_target(backend)
                    last = time.monotonic()
                if cv2.getWindowProperty(config.WINDOW_NAME, cv2.WND_PROP_VISIBLE) < 1:
                    break
        except KeyboardInterrupt:
            pass
        finally:
            cv2.destroyAllWindows()
    log("종료했습니다.")


if __name__ == "__main__":
    main()
