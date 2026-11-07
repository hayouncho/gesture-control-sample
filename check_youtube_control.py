"""유튜브 자동 포커스 직접 확인용 (웹캠 필요 없음).

실행: python check_youtube_control.py
- 볼륨 증가(↑) 후 볼륨 감소(↓)만 보내서 원래 볼륨으로 되돌립니다. 재생/정지·탐색 키는 보내지 않습니다.
- 각 단계 전에 카운트다운이 있으니 안내대로 다른 창이나 검색창을 클릭해 두세요.
"""
import sys
import time

from gesture_control.common import Command
from gesture_control.controller import YouTubeController, select_target
from gesture_control.youtube_target import UIABackend, foreground_hwnd


def countdown(msg: str, sec: int) -> None:
    print(msg)
    for i in range(sec, 0, -1):
        print(f"  {i}...", flush=True)
        time.sleep(1)


def run_pair(ctl: YouTubeController) -> None:
    for cmd in (Command.VOLUME_UP, Command.VOLUME_DOWN):
        r = ctl.execute(cmd)
        print("  ", r.message)
        if not r.sent:
            print("   -> 키를 보내지 않았습니다. 위 이유를 확인하세요.")
            return
        time.sleep(1.0)


def search_box(backend, target):
    win = backend.auto.ControlFromHandle(target.hwnd)
    box = win.Control(searchDepth=40, Compare=lambda c, d: c.ControlTypeName in ("EditControl", "ComboBoxControl")
                      and (c.Name or "").strip() in ("검색", "Search"))
    return box if box.Exists(1, 0.2) else None


def main() -> None:
    backend = UIABackend()
    target = select_target(backend)
    if target is None:
        sys.exit(1)
    ctl = YouTubeController(live=True, backend=backend, target=target)

    print("\n[확인 1] 다른 프로그램이 맨 앞에 있을 때 자동 활성화")
    countdown("메모장·탐색기 등 다른 창을 지금 클릭해 맨 앞에 두세요.", 6)
    print("   맨 앞 창이 유튜브 대상인가:", foreground_hwnd() == target.hwnd, "(False여야 제대로 된 시험)")
    run_pair(ctl)
    print("   => 유튜브 창이 앞으로 오고, 화면 볼륨 표시가 올라갔다 내려왔으면 성공. 페이지가 스크롤되면 실패.")

    print("\n[확인 2] 유튜브 검색창에 커서가 있을 때")
    countdown("유튜브 창 위쪽의 '검색' 칸을 클릭해서 커서를 두세요 (글자는 입력하지 마세요).", 8)
    box = search_box(backend, target)
    run_pair(ctl)
    if box is not None:
        try:
            print("   검색창 내용:", repr(box.GetValuePattern().Value), "(빈 값 '' 이어야 성공)")
        except Exception:
            pass
    print("   => 검색창에 글자가 들어가지 않고 볼륨만 바뀌었으면 성공.")

    print("\n끝났습니다. 결과(성공/실패 메시지)를 그대로 알려 주세요.")


if __name__ == "__main__":
    main()
