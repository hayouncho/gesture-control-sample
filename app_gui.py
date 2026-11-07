"""손 제스처 유튜브 제어 — 데스크톱 프로그램 (Tkinter).

실행: run_gui.bat 더블클릭  또는  .venv\\Scripts\\python.exe app_gui.py

UI 스레드는 화면만 그립니다. 웹캠·손 인식은 CameraWorker, 유튜브 창 제어는 ControlWorker가
각자의 스레드에서 처리하므로 유튜브로 포커스가 옮겨 가도 인식과 화면이 멈추지 않습니다.
(손 인식·자동 포커스·제어 코드는 터미널 버전 run.py와 같은 모듈을 그대로 사용)
"""
from __future__ import annotations

import logging
import queue
import sys
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk

from PIL import Image, ImageTk

from gesture_control import config
from gesture_control.common import COMMAND_KO
from gesture_control.controller import TEST, UNVERIFIED, VERIFIED
from gesture_control.workers import CameraWorker, ControlWorker, DiscoveryWorker

LOG_DIR = config.PROJECT_DIR / "logs"
PREVIEW_W, PREVIEW_H = 560, 420
TICK_MS = 30

FONT = "맑은 고딕"
C = {
    "bg": "#f4f5f7", "panel": "#ffffff", "line": "#e2e4e8", "text": "#1f2328", "muted": "#6b7280",
    "test": "#1d4ed8", "test_bg": "#e8efff", "live": "#b91c1c", "live_bg": "#fdecec",
    "ok": "#15803d", "fail": "#b91c1c", "warn": "#b45309", "idle": "#6b7280",
}
HAND_KO = {"Left": "왼손", "Right": "오른손"}
POSE_KO = {
    "OPEN ready": "손 펴짐 · 이동 준비됨",
    "OPEN (hold still)": "손 펴짐 · 잠깐 멈추세요",
    "OPEN": "손 펴짐",
    "FIST": "주먹",
    "V": "V 사인",
    "V hold...": "V 사인 유지 중…",
    "OTHER": "그 밖의 손 모양",
}
USAGE = [
    ("V 사인(검지+중지) 1초 유지", "인식 시작 / 종료  *샘플용"),
    ("주먹을 쥐었다가 펴기", "재생 / 일시정지"),
    ("편 손을 위 / 아래로 빠르게", "볼륨 증가 / 감소"),
    ("편 손을 내 오른쪽 / 왼쪽으로 빠르게", "10초 앞으로 / 뒤로"),
]


def setup_logging() -> logging.Logger:
    LOG_DIR.mkdir(exist_ok=True)
    logging.basicConfig(filename=LOG_DIR / "app.log", level=logging.INFO, encoding="utf-8",
                        format="%(asctime)s %(levelname)s %(message)s")
    return logging.getLogger("gesture_gui")


class App:
    def __init__(self, root: tk.Tk, log: logging.Logger):
        self.root, self.log = root, log
        self.posts: queue.Queue = queue.Queue()
        self.control = ControlWorker(self._post)
        self.camera = CameraWorker(self._post, self.control.submit)
        self.discovery = DiscoveryWorker(self.control.offer_targets, self._post)  # 유튜브 자동 검색
        self._active = False
        self._live = False
        self._last_snap = None
        self._photo = None
        self._closing = False

        root.title("손 제스처 유튜브 제어 (샘플)")
        root.configure(bg=C["bg"])
        root.minsize(1020, 700)
        root.protocol("WM_DELETE_WINDOW", self.close)
        self._styles()
        self._build()

        self.control.start()
        self.camera.start()
        self.discovery.start()   # 시작하자마자 한 번, 이후 3초마다 검색
        self.root.after(TICK_MS, self._tick)

    # ------------------------------------------------------------------ 화면 구성
    def _styles(self) -> None:
        s = ttk.Style()
        s.configure("TCombobox", padding=4)
        self.root.option_add("*Font", (FONT, 10))

    def _section(self, parent, title: str):
        box = tk.Frame(parent, bg=C["panel"], highlightthickness=1, highlightbackground=C["line"])
        tk.Label(box, text=title, font=(FONT, 11, "bold"), bg=C["panel"], fg=C["text"]).pack(
            anchor="w", padx=14, pady=(10, 4))
        body = tk.Frame(box, bg=C["panel"])
        body.pack(fill="x", padx=14, pady=(0, 12))
        return box, body

    def _build(self) -> None:
        r = self.root
        # 제목 + 모드 선택
        head = tk.Frame(r, bg=C["bg"])
        head.pack(fill="x", padx=16, pady=(12, 6))
        tk.Label(head, text="손 제스처 유튜브 제어", font=(FONT, 16, "bold"), bg=C["bg"], fg=C["text"]).pack(side="left")
        tk.Label(head, text="  컴퓨터비전 1조 · 샘플", font=(FONT, 10), bg=C["bg"], fg=C["muted"]).pack(
            side="left", pady=(6, 0))
        self.mode_var = tk.StringVar(value="test")
        for text, val in (("실제 제어 모드", "live"), ("테스트 모드", "test")):
            tk.Radiobutton(head, text=text, value=val, variable=self.mode_var, command=self._on_mode,
                           bg=C["bg"], activebackground=C["bg"], font=(FONT, 10, "bold")).pack(side="right", padx=4)
        tk.Label(head, text="모드:", bg=C["bg"], fg=C["muted"]).pack(side="right")

        self.banner = tk.Label(r, font=(FONT, 11, "bold"), anchor="w", padx=16, pady=8)
        self.banner.pack(fill="x", padx=16)

        body = tk.Frame(r, bg=C["bg"])
        body.pack(fill="both", expand=True, padx=16, pady=10)

        # 왼쪽: 카메라 + 사용법
        left = tk.Frame(body, bg=C["bg"])
        left.pack(side="left", fill="y")
        holder = tk.Frame(left, width=PREVIEW_W, height=PREVIEW_H, bg="#111827")  # 픽셀 단위 고정 크기
        holder.pack()
        holder.pack_propagate(False)
        self.preview = tk.Label(holder, bg="#111827", fg="#e5e7eb", text="카메라 준비 중…", font=(FONT, 12))
        self.preview.pack(fill="both", expand=True)
        info = tk.Frame(left, bg=C["bg"])
        info.pack(fill="x", pady=(6, 8))
        self.cam_info = tk.Label(info, text="", bg=C["bg"], fg=C["muted"])
        self.cam_info.pack(side="left")
        self.topmost_var = tk.BooleanVar(value=True)
        tk.Checkbutton(info, text="항상 위에 표시", variable=self.topmost_var, command=self._on_topmost,
                       bg=C["bg"], activebackground=C["bg"]).pack(side="right")
        self._on_topmost()

        usage, ub = self._section(left, "제스처 사용법")
        usage.pack(fill="x")
        for i, (g, a) in enumerate(USAGE):
            tk.Label(ub, text=g, bg=C["panel"], fg=C["text"]).grid(row=i, column=0, sticky="w", pady=1)
            tk.Label(ub, text=a, bg=C["panel"], fg=C["muted"]).grid(row=i, column=1, sticky="w", padx=(18, 0))
        tk.Label(ub, text="손 이동은 '이동 준비됨'이 보일 때 빠르게. 명령 후 1초 동안은 다음 명령을 받지 않습니다.",
                 bg=C["panel"], fg=C["muted"], wraplength=520, justify="left").grid(
            row=len(USAGE), column=0, columnspan=2, sticky="w", pady=(6, 0))
        tk.Label(ub, text="※ 시작·종료 제스처(V 사인)와 인식 기준값(쿨다운, 이동 거리 등)은 팀에서 아직 확정하지 않은 "
                          "샘플용 설정입니다.", bg=C["panel"], fg=C["live"], wraplength=520, justify="left").grid(
            row=len(USAGE) + 1, column=0, columnspan=2, sticky="w", pady=(4, 0))

        # 오른쪽: 상태 패널
        right = tk.Frame(body, bg=C["bg"], width=400)
        right.pack(side="left", fill="both", expand=True, padx=(14, 0))

        sec, b = self._section(right, "인식 상태")
        sec.pack(fill="x")
        row = tk.Frame(b, bg=C["panel"])
        row.pack(fill="x")
        self.state_label = tk.Label(row, text="대기 중", font=(FONT, 15, "bold"), bg=C["panel"], fg=C["idle"])
        self.state_label.pack(side="left")
        self.toggle_btn = tk.Button(row, text="인식 시작", width=10, font=(FONT, 10, "bold"), relief="flat",
                                    bg="#111827", fg="white", activebackground="#374151", activeforeground="white",
                                    command=self._on_toggle)
        self.toggle_btn.pack(side="right")
        self.state_sub = tk.Label(b, text="버튼 또는 V 사인 1초로 시작/종료", bg=C["panel"], fg=C["muted"])
        self.state_sub.pack(anchor="w", pady=(4, 0))

        sec, b = self._section(right, "제어할 유튜브")
        sec.pack(fill="x", pady=(10, 0))
        row = tk.Frame(b, bg=C["panel"])
        row.pack(fill="x")
        self.target_box = ttk.Combobox(row, state="readonly", values=[])
        self.target_box.pack(side="left", fill="x", expand=True)
        self.target_box.bind("<<ComboboxSelected>>", self._on_select)
        tk.Button(row, text="새로고침", relief="flat", bg="#e5e7eb", activebackground="#d1d5db",
                  command=self._on_refresh).pack(side="left", padx=(6, 0))
        self.target_label = tk.Label(b, text="유튜브 창을 찾는 중…", bg=C["panel"], fg=C["muted"],
                                     wraplength=380, justify="left")
        self.target_label.pack(anchor="w", pady=(6, 0))

        sec, b = self._section(right, "현재 제스처")
        sec.pack(fill="x", pady=(10, 0))
        self.gesture_label = tk.Label(b, text="손이 보이지 않습니다", font=(FONT, 11), bg=C["panel"],
                                      fg=C["text"], justify="left")
        self.gesture_label.pack(anchor="w")

        sec, b = self._section(right, "최근 실행 명령")
        sec.pack(fill="both", expand=True, pady=(10, 0))
        self.result_title = tk.Label(b, text="아직 실행한 명령이 없습니다", font=(FONT, 12, "bold"),
                                     bg=C["panel"], fg=C["muted"])
        self.result_title.pack(anchor="w")
        self.result_detail = tk.Label(b, text="", bg=C["panel"], fg=C["muted"], wraplength=380, justify="left")
        self.result_detail.pack(anchor="w", pady=(2, 8))
        self.history = tk.Listbox(b, height=8, relief="flat", highlightthickness=1,
                                  highlightbackground=C["line"], activestyle="none")
        self.history.pack(fill="both", expand=True)

        self._show_mode(False)

    # ------------------------------------------------------------------ 사용자 조작
    def _on_mode(self) -> None:
        want_live = self.mode_var.get() == "live"
        if want_live == self._live:
            return
        if want_live and not messagebox.askyesno(
                "실제 제어 모드",
                "제스처로 선택한 유튜브를 실제로 제어합니다.\n명령이 나올 때 유튜브 창이 자동으로 앞으로 옵니다.\n\n전환할까요?"):
            self.mode_var.set("test")
            return
        self.control.set_live(want_live)   # 제어 스레드가 반영한 뒤 "live" 메시지로 화면 갱신

    def _on_toggle(self) -> None:
        self.camera.request_active(not self._active)  # 실제 상태 변경은 카메라 스레드 (V 사인과 같은 값)

    def _on_refresh(self) -> None:
        self.target_label.config(text="유튜브 창을 찾는 중…", fg=C["muted"])
        self.control.republish()   # 다음 검색 결과는 바뀌지 않았어도 화면에 다시 표시
        self.discovery.trigger()   # 자동 검색을 기다리지 않고 바로 검색

    def _on_select(self, _event=None) -> None:
        self.control.select(self.target_box.current())

    def _on_topmost(self) -> None:
        self.root.attributes("-topmost", bool(self.topmost_var.get()))

    # ------------------------------------------------------------------ 화면 갱신
    def _post(self, kind: str, value) -> None:   # 작업 스레드 -> UI (스레드 안전한 큐)
        self.posts.put((kind, value))

    def _tick(self) -> None:
        if self._closing:
            return
        try:
            while True:
                self._handle(*self.posts.get_nowait())
        except queue.Empty:
            pass
        self._update_from_snapshot(self.camera.latest())
        self.root.after(TICK_MS, self._tick)

    def _handle(self, kind: str, value) -> None:
        if kind == "event":
            self._add_history(value.message, C["muted"])
            self.log.info(value.message)
        elif kind == "result":
            self._show_result(*value)
        elif kind == "log":
            self._add_history(value, C["muted"])
            self.log.info(value)
        elif kind == "debug":   # 로그 파일에만 기록 (문제 분석용)
            self.log.info(value)
        elif kind == "targets":
            names, idx = value
            self.target_box.config(values=names)
            if idx is not None:
                self.target_box.current(idx)
            else:
                self.target_box.set("")
        elif kind == "target":
            desc, status, page, count = value
            if desc:
                head = "선택됨 (자동 선택됨)" if status == "auto" else "선택됨"
                note = {"no_video": "\n영상 선택 필요: 이 탭/창에서 영상을 연 뒤 제어하세요",
                        "unknown": "\n뒤에 있는 탭: 첫 명령 때 탭을 전환하며 영상 여부를 확인합니다",
                        "no_access": "\n제어 불가: 이 브라우저가 웹 페이지 정보를 제공하지 않습니다 "
                                     "(Chrome: chrome://accessibility 확인, README 6절)"
                        }.get(page, "")
                self.target_label.config(text=f"{head}: {desc}{note}",
                                         fg=C["text"] if page == "video" else C["warn"])
            elif status == "choose":
                self.target_label.config(text=f"유튜브 대상이 {count}개 있습니다. 목록에서 제어할 대상을 고르세요.",
                                         fg=C["fail"])
            elif status == "blocked":
                self.target_label.config(text="열린 유튜브가 있지만 제어할 수 없습니다: 브라우저가 웹 페이지 정보를 "
                                              "제공하지 않습니다.\nChrome이면 chrome://accessibility 에서 'Native accessibility "
                                              "API support'와 'Web accessibility' 체크 여부를 확인하세요 (README 6절).",
                                         fg=C["fail"])
            else:
                self.target_label.config(text="유튜브 영상을 열어 주세요. 열면 자동으로 찾아 선택합니다.\n"
                                              "(제어 확인: Edge·Firefox·Chrome 탭, Edge 유튜브 앱)", fg=C["fail"])
        elif kind == "live":
            self._show_mode(value)
        elif kind == "error":
            self._add_history(value, C["fail"])
            self.log.error(value)
        elif kind == "camera_stopped":
            snap = self.camera.latest()
            if snap.error and not self._closing:
                self.preview.config(image="", text=f"카메라를 사용할 수 없습니다\n\n{snap.error}")

    def _update_from_snapshot(self, snap) -> None:
        if snap is self._last_snap:
            return
        self._last_snap = snap
        if snap.frame_rgb is not None:
            img = Image.fromarray(snap.frame_rgb).resize((PREVIEW_W, PREVIEW_H))
            self._photo = ImageTk.PhotoImage(img)   # 참조를 유지해야 화면에서 사라지지 않음
            self.preview.config(image=self._photo, text="")
        if snap.running:
            self.cam_info.config(text=f"손 {len(snap.hands)}개 · {snap.fps:4.1f} FPS")

        self._active = snap.active  # 버튼 표시는 항상 카메라 스레드의 실제 상태(V 사인과 공통)를 따름
        self.state_label.config(text="인식 중" if snap.active else "대기 중",
                                fg=C["ok"] if snap.active else C["idle"])
        self.toggle_btn.config(text="인식 종료" if snap.active else "인식 시작")
        sub = "버튼 또는 V 사인 1초로 종료" if snap.active else "버튼 또는 V 사인 1초로 시작"
        if snap.cooldown > 0:
            sub += f"  ·  쿨다운 {snap.cooldown:.1f}초"
        self.state_sub.config(text=sub)

        if snap.hands:
            lines = []
            for key, info in snap.hands.items():
                base = key.split("#")[0]
                lines.append(f"{HAND_KO.get(base, base)}: {POSE_KO.get(info, info)}")
            self.gesture_label.config(text="\n".join(lines), fg=C["text"])
        else:
            self.gesture_label.config(text="손이 보이지 않습니다", fg=C["muted"])

    def _show_mode(self, live: bool) -> None:
        self._live = live
        self.mode_var.set("live" if live else "test")
        if live:
            self.banner.config(text="● 실제 제어 모드 — 제스처로 선택한 유튜브를 제어합니다 (명령 때 유튜브 창이 앞으로 옴)",
                               bg=C["live_bg"], fg=C["live"])
        else:
            self.banner.config(text="● 테스트 모드 — 유튜브에 키를 보내지 않고 창 포커스도 바꾸지 않습니다 (예정 동작만 표시)",
                               bg=C["test_bg"], fg=C["test"])

    def _show_result(self, cmd, result, ident: str) -> None:
        name = COMMAND_KO[cmd]
        if result.outcome == TEST:
            status, color = "테스트 (실행 안 함)", C["test"]
        elif result.outcome == VERIFIED:
            status, color = "성공", C["ok"]
        elif result.outcome == UNVERIFIED:
            status, color = "실행됨 · 결과 확인 못 함", C["warn"]
        else:
            status, color = f"실패 ({result.stage} 단계)" if result.stage else "실패", C["fail"]
        now = datetime.now().strftime("%H:%M:%S")
        self.result_title.config(text=f"{name} — {status}", fg=color)
        self.result_detail.config(text=result.message, fg=C["text"] if result.outcome == VERIFIED else color)
        self._add_history(f"{name} · {status}", color, now)
        self.log.info(f"{result.message} | 결과={result.outcome} 단계={result.stage or '-'} 대상={ident}")

    def _add_history(self, text: str, color: str, now: str | None = None) -> None:
        now = now or datetime.now().strftime("%H:%M:%S")
        self.history.insert(0, f"{now}  {text}")
        self.history.itemconfig(0, fg=color)
        if self.history.size() > 100:
            self.history.delete(100, "end")

    # ------------------------------------------------------------------ 종료
    def close(self) -> None:
        if self._closing:
            return
        self._closing = True
        self.preview.config(image="", text="종료 중…")
        self.camera.stop()
        self.control.stop()
        self.discovery.stop()
        self._wait_workers(deadline=50 * 100)  # 최대 약 5초

    def _wait_workers(self, deadline: int) -> None:
        alive = self.camera.is_alive() or self.control.is_alive() or self.discovery.is_alive()
        if alive and deadline > 0:
            self.root.after(50, self._wait_workers, deadline - 50)
            return
        if alive:
            self.log.warning("작업 스레드가 제때 끝나지 않아 강제 종료합니다")
        self.log.info("프로그램 종료")
        self.root.destroy()


def main() -> None:
    log = setup_logging()
    if sys.platform == "win32":
        try:  # 고해상도 화면에서 글자가 흐려지지 않게
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    root = tk.Tk()

    def report(exc, val, tb):
        log.exception("UI 오류", exc_info=(exc, val, tb))
        messagebox.showerror("오류", f"{val}\n\n자세한 내용: logs/app.log")

    root.report_callback_exception = report
    App(root, log)
    log.info("프로그램 시작")
    root.mainloop()


if __name__ == "__main__":
    main()
