"""유튜브 창/탭 찾기, 창 활성화, 영상 플레이어 포커스 (담당: 조하연 — 샘플 구현).

Windows UI Automation(UIA, 화면 읽기 프로그램이 쓰는 접근성 기능)으로
Edge/Chrome 창 안의 탭 목록과 웹 페이지 요소(유튜브 플레이어)를 읽고 조작합니다.
화면 좌표를 클릭하지 않으므로 창 크기·위치가 바뀌어도 동작하고, 클릭으로 인한 재생/정지도 생기지 않습니다.

공통 처리와 브라우저별 처리
  공통: 유튜브 탭 판별(이름), 문서 주소로 영상 페이지 확인, 플레이어(id=movie_player) 포커스, 키 전송, 결과 확인
  브라우저별(BrowserProfile): 실행 파일, 창 종류(클래스), 주소창 찾는 방법, 탭 요소 클래스
    Edge     Chrome_WidgetWin_1 / 주소창 OmniboxViewViews / 탭 EdgeTab            (실제 확인)
    Firefox  MozillaWindowClass / 주소창 AutomationId=urlbar-input / 탭 tabbrowser-tab (실제 확인, Firefox 159)
    Chrome   Chrome_WidgetWin_1 / 주소창 OmniboxViewViews / 탭 Tab                (Edge와 같은 Chromium 구조로 구현, 미검증)
  주소창이 없는 창 = 설치형 앱(PWA) 창으로 처리 (Edge 유튜브 앱 확인)
지원하지 않음
  - 위 세 브라우저 외 / YouTube Music, YouTube Studio / 쇼츠(/shorts) 화면

유튜브 탭 판별 (재생 상태와 무관)
  Edge/Chrome은 탭 이름 뒤에 '메모리 사용량', 재생 중 표시 같은 부가 정보를 붙입니다.
  그래서 '이름이 YouTube로 끝나는지'가 아니라 '이름 안에 " - YouTube" 구분이 있는지'로 판별하고,
  그 앞부분을 영상 제목으로 씁니다. 지금 보이는 탭과 앱 창은 문서 주소(URL)로 영상 페이지인지 확인합니다.
"""
from __future__ import annotations

import ctypes
import os
import re
import sys
import time
from ctypes import wintypes
from dataclasses import dataclass

@dataclass(frozen=True)
class BrowserProfile:
    """브라우저마다 다른 창 구조 정보."""

    name: str
    exe: str
    window_class: str
    tab_class: str                 # 탭 표시줄의 탭 요소 클래스 (사이드바 버튼 등과 구분)
    address_class: str = ""        # 주소창 요소 클래스 (Chromium)
    address_id: str = ""           # 주소창 요소 AutomationId (Firefox)

    def is_address_bar(self, c) -> bool:
        if self.address_class and c.ClassName == self.address_class:
            return True
        return bool(self.address_id) and c.AutomationId == self.address_id

    def is_tab(self, c) -> bool:
        return self.tab_class in (c.ClassName or "").split()


PROFILES = (
    BrowserProfile("Edge", "msedge.exe", "Chrome_WidgetWin_1", "EdgeTab", address_class="OmniboxViewViews"),
    BrowserProfile("Chrome", "chrome.exe", "Chrome_WidgetWin_1", "Tab", address_class="OmniboxViewViews"),
    BrowserProfile("Firefox", "firefox.exe", "MozillaWindowClass", "tabbrowser-tab", address_id="urlbar-input"),
)
PROFILE_BY_NAME = {p.name: p for p in PROFILES}

PLAYER_ID = "movie_player"            # 유튜브 플레이어 <div id="movie_player">
VOLUME_SLIDER_CLASS = "ytp-volume-panel"
PROGRESS_SLIDER_CLASS = "ytp-progress-bar"

# " - YouTube" 다음에 끝 또는 구분 기호(- ( , · |)가 오는 경우만 인정 (YouTube Music / Studio 등은 제외)
_YOUTUBE_MARK = re.compile(r"(?:^|\s-\s)YouTube(?=$|\s*[-(,·|])")
_COUNT_PREFIX = re.compile(r"^\(\d+\)\s*")   # 제목 앞의 알림 개수 "(12) "

# 페이지 종류
VIDEO, NO_VIDEO, UNKNOWN = "video", "no_video", "unknown"
# 브라우저가 웹 페이지 내용(문서 주소·플레이어)을 접근성 정보로 제공하지 않음 → 플레이어 포커스를 확보할 수 없어 제어 불가
# (Chrome 156 기본 상태에서 확인. 탭 이름으로 대상 검색만 가능)
NO_ACCESS = "no_access"
NOT_CONTROLLABLE = (NO_VIDEO, NO_ACCESS)


def youtube_title(name: str) -> str | None:
    """탭/문서 이름에서 유튜브 페이지 제목을 꺼냅니다. 유튜브가 아니면 None, 'YouTube' 단독(홈)이면 ''.

    '(12) 영상 - YouTube - 메모리 사용량 - 710 MB' -> '영상'
    '(12) 영상 - YouTube - (재생 중 표시 등 무엇이든)' -> '영상'
    """
    name = (name or "").strip()
    last = None
    for m in _YOUTUBE_MARK.finditer(name):
        last = m
    if last is None:
        return None
    return _COUNT_PREFIX.sub("", name[: last.start()].strip())


def page_kind(url: str) -> str:
    """문서 주소로 페이지 종류 판단. 영상 재생 페이지(/watch)만 VIDEO."""
    if not url:
        return UNKNOWN
    if "youtube.com/watch" in url:
        return VIDEO
    return NO_VIDEO   # 홈, 검색 결과, 채널, 쇼츠 등


@dataclass
class Target:
    """제어 대상. 창 핸들(hwnd)과, 브라우저 탭이면 그 탭의 고유 번호(tab_id)로 구분합니다."""

    hwnd: int
    kind: str                 # "browser" (브라우저 탭) | "app" (유튜브 앱 창)
    browser: str              # "Edge" | "Chrome"
    title: str                # 영상 제목 (홈이면 '')
    tab_id: tuple | None = None
    selected: bool = True     # 브라우저 탭: 지금 보이는 탭인지
    page: str = UNKNOWN       # VIDEO / NO_VIDEO / UNKNOWN(뒤에 있는 탭이라 아직 모름)
    window_no: int = 0        # 목록 표시용 창 번호 (서로 다른 창 구분)
    tab_no: int = 0           # 목록 표시용 탭 번호 (같은 창 안의 탭 구분)

    def same_as(self, other: "Target | None") -> bool:
        return other is not None and self.hwnd == other.hwnd and self.tab_id == other.tab_id

    def describe(self) -> str:
        if self.kind == "app":
            where = f"[{self.browser} 유튜브 앱 · 창{self.window_no}]"
        else:
            where = (f"[{self.browser} 브라우저 · 창{self.window_no} · 탭{self.tab_no} · "
                     f"{'현재 탭' if self.selected else '뒤에 있는 탭'}]")
        title = self.title or "유튜브 홈"
        title = title if len(title) <= 40 else title[:37] + "..."
        note = {NO_VIDEO: " — 영상 선택 필요", UNKNOWN: " — 영상 여부는 전환할 때 확인",
                NO_ACCESS: " — 제어 불가: 웹 페이지 정보 없음"}.get(self.page, "")
        return f"{where} {title}{note}"

    def ident(self) -> str:
        """로그용 고유 표시 (창 핸들 + 탭 번호)."""
        tab = f" tab={self.tab_id[-1]}" if self.tab_id else ""
        return f"{self.kind} hwnd={self.hwnd}{tab}"

    def short(self) -> str:
        """미리보기 창용 영문 표시."""
        return f"{self.browser} {'app' if self.kind == 'app' else 'tab'}"


# ---------------------------------------------------------------- Win32 도우미
if sys.platform == "win32":
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.BringWindowToTop.argtypes = [wintypes.HWND]
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SwitchToThisWindow.argtypes = [wintypes.HWND, wintypes.BOOL]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                    ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

SW_RESTORE = 9
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def foreground_hwnd() -> int:
    return user32.GetForegroundWindow() or 0


def process_name(pid: int) -> str:
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(520)
        size = wintypes.DWORD(520)
        if not kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return ""
        return os.path.basename(buf.value).lower()
    finally:
        kernel32.CloseHandle(h)


def _wait(cond, timeout: float, interval: float = 0.05) -> bool:
    end = time.monotonic() + timeout
    while True:
        if cond():
            return True
        if time.monotonic() >= end:
            return False
        time.sleep(interval)


def activate_window(hwnd: int) -> tuple[bool, str]:
    """창을 맨 앞으로 가져오고 성공했는지 확인합니다. 키는 보내지 않습니다.

    Windows는 백그라운드 프로그램이 다른 창을 맨 앞으로 가져오는 것을 제한하므로
    여러 방법을 차례로 시도하고, 그래도 안 되면 실패를 돌려줍니다.
    """
    if foreground_hwnd() == hwnd:
        return True, "이미 맨 앞"
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)  # 최소화돼 있으면 복원

    user32.SetForegroundWindow(hwnd)
    if _wait(lambda: foreground_hwnd() == hwnd, 0.3):
        return True, "창 활성화"

    # 현재 맨 앞 창의 입력 스레드에 잠시 연결해서 다시 시도
    fg = foreground_hwnd()
    fg_thread = user32.GetWindowThreadProcessId(fg, None) if fg else 0
    me = kernel32.GetCurrentThreadId()
    attached = bool(fg_thread) and fg_thread != me and user32.AttachThreadInput(me, fg_thread, True)
    try:
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(me, fg_thread, False)
    if _wait(lambda: foreground_hwnd() == hwnd, 0.3):
        return True, "창 활성화(입력 연결)"

    user32.SwitchToThisWindow(hwnd, True)
    if _wait(lambda: foreground_hwnd() == hwnd, 0.4):
        return True, "창 활성화(전환)"
    return False, "Windows가 창 활성화를 허용하지 않았습니다(포커스 보호). 유튜브 창을 한 번 클릭한 뒤 다시 시도하세요."


# 준비 단계 이름 (실패 표시용)
STAGE_TARGET = "대상 확인"
STAGE_ACCESS = "웹 페이지 접근"
STAGE_ACTIVATE = "창 활성화"
STAGE_TAB = "탭 전환"
STAGE_PLAYER = "플레이어 찾기"
STAGE_FOCUS = "플레이어 포커스"
STAGE_FINAL = "최종 확인"


# ---------------------------------------------------------------- UIA 백엔드
class UIABackend:
    """실제 Windows 창을 다루는 부분. 테스트에서는 같은 함수를 가진 가짜 객체로 바꿔 끼웁니다."""

    def __init__(self) -> None:
        import uiautomation as auto  # Windows 전용이라 여기서 import

        self.auto = auto
        self._player_cache: dict[tuple, object] = {}

    def reset_cache(self) -> None:
        """대상이 바뀌면 이전에 찾아 둔 플레이어 정보를 버립니다."""
        self._player_cache.clear()

    # ---------------- 대상 찾기 (읽기 전용 — 포커스·탭·재생 상태를 바꾸지 않음)
    def find_targets(self) -> list[Target]:
        targets: list[Target] = []
        window_no = 0
        for win in self.auto.GetRootControl().GetChildren():
            profile = self._profile_for(win)
            if profile is None:
                continue
            browser = profile.name
            hwnd = win.NativeWindowHandle
            has_omnibox, tabs = self._scan_window(win, profile)
            if has_omnibox:
                found = []
                for tab_no, tab in enumerate(tabs, 1):
                    title = youtube_title(tab.Name)   # 재생 상태 표시가 붙어도 판별됨
                    if title is not None:
                        found.append((tab_no, tab, title))
                if not found:
                    continue
                window_no += 1
                url = ""
                if any(self._is_selected(tab) for _, tab, _ in found):
                    url = self._youtube_doc_url(win)   # 보이는 탭의 문서 주소 (읽기만)
                readable = bool(url) or self._web_readable(win)
                for tab_no, tab, title in found:
                    selected = self._is_selected(tab)
                    if not readable:
                        page = NO_ACCESS                 # 웹 내용을 읽을 수 없는 창
                    elif selected and url:
                        page = page_kind(url)
                    else:
                        page = NO_VIDEO if title == "" else UNKNOWN
                    targets.append(Target(hwnd, "browser", browser, title, tuple(tab.GetRuntimeId()),
                                          selected, page, window_no, tab_no))
            else:
                doc_name, url = self._youtube_doc(win)
                title = youtube_title(doc_name)
                if title is None:
                    title = youtube_title(win.Name)
                if title is None and "youtube.com" not in url:
                    continue
                window_no += 1
                if url:
                    page = page_kind(url)
                elif not self._web_readable(win):
                    page = NO_ACCESS
                else:
                    page = NO_VIDEO if title == "" else UNKNOWN
                targets.append(Target(hwnd, "app", browser, title or "", None, True, page, window_no))
        return targets

    @staticmethod
    def _profile_for(win) -> BrowserProfile | None:
        """지원하는 브라우저의 창이면 그 브라우저 설정 (실행 파일 + 창 종류가 모두 맞아야 함)."""
        cls = win.ClassName
        candidates = [p for p in PROFILES if p.window_class == cls]
        if not candidates:
            return None
        exe = process_name(win.ProcessId)
        return next((p for p in candidates if p.exe == exe), None)

    def _scan_window(self, win, profile: BrowserProfile, max_depth: int = 10):
        """창의 브라우저 UI 부분만 훑어 주소창 유무와 탭 목록을 얻습니다 (웹 페이지 내부는 건너뜀)."""
        has_omnibox, tabs, others, seen = False, [], [], set()
        stack = [(win, 0)]
        while stack:
            c, d = stack.pop()
            for ch in c.GetChildren():
                t = ch.ControlTypeName
                if t == "DocumentControl":
                    continue
                if profile.is_address_bar(ch):
                    has_omnibox = True
                if t == "TabItemControl":
                    rid = tuple(ch.GetRuntimeId())
                    if rid not in seen:
                        seen.add(rid)
                        (tabs if profile.is_tab(ch) else others).append(ch)
                if d + 1 < max_depth:
                    stack.append((ch, d + 1))
        if not tabs:   # 탭 클래스가 다른 버전이면 모든 탭 요소 사용 (유튜브 이름 판별로 다시 걸러짐)
            tabs = others
        def order(c):  # 화면 순서 (가로 탭은 왼쪽부터, 세로 탭은 위부터)
            try:
                r = c.BoundingRectangle
                return (r.left, r.top)
            except Exception:
                return (0, 0)

        tabs.sort(key=order)
        return has_omnibox, tabs

    def _documents(self, win, max_depth: int = 12):
        """창 안의 웹 문서(DocumentControl) 목록: (컨트롤, 이름, 주소)."""
        docs, stack = [], [(win, 0)]
        while stack:
            c, d = stack.pop()
            for ch in c.GetChildren():
                if ch.ControlTypeName == "DocumentControl":
                    try:
                        url = ch.GetValuePattern().Value or ""
                    except Exception:
                        url = ""
                    docs.append((ch, ch.Name or "", url))
                    continue
                if d + 1 < max_depth:
                    stack.append((ch, d + 1))
        return docs

    @staticmethod
    def _visible(ctrl) -> bool:
        try:
            r = ctrl.BoundingRectangle
            return r.width() > 0 and r.height() > 0 and not ctrl.IsOffscreen
        except Exception:
            return False

    def _visible_youtube_doc(self, win):
        """화면에 보이는 유튜브 문서 (컨트롤, 이름, 주소).

        Firefox는 뒤에 있는 탭이나 미리 만들어 둔 새 탭(about:newtab) 문서도 함께 보여 주므로
        '보이는' 문서만 고릅니다. 보이는 것이 없으면 None.
        """
        for ctrl, name, url in self._documents(win):
            if "youtube.com" in url and self._visible(ctrl):
                return ctrl, name, url
        return None, "", ""

    def _youtube_doc(self, win, retries: int = 2):
        """보이는 유튜브 문서의 (이름, 주소). 접근성 정보가 늦게 만들어질 수 있어 짧게 재시도."""
        for i in range(retries):
            _, name, url = self._visible_youtube_doc(win)
            if url:
                return name, url
            if i + 1 < retries:
                time.sleep(0.3)
        return "", ""

    def _web_readable(self, win, retries: int = 3) -> bool:
        """이 창의 웹 문서 중 하나라도 주소를 읽을 수 있는지 (브라우저가 웹 내용 접근성을 제공하는지).

        Edge도 처음 조회할 때는 정보가 잠깐 비어 있을 수 있어 짧게(약 1초) 다시 확인합니다.
        """
        for i in range(retries):
            if any(url for _, _, url in self._documents(win)):
                return True
            if i + 1 < retries:
                time.sleep(0.35)
        return False

    def _youtube_doc_url(self, win) -> str:
        return self._youtube_doc(win)[1]

    def _youtube_doc_control(self, win):
        ctrl, _, url = self._visible_youtube_doc(win)
        return ctrl, url

    @staticmethod
    def _is_selected(tab) -> bool:
        try:
            return bool(tab.GetSelectionItemPattern().IsSelected)
        except Exception:
            return False

    def _window(self, t: Target):
        return self.auto.ControlFromHandle(t.hwnd)

    def _find_tab(self, t: Target):
        _, tabs = self._scan_window(self._window(t), PROFILE_BY_NAME[t.browser])
        for tab in tabs:
            if tuple(tab.GetRuntimeId()) == t.tab_id:
                return tab
        return None

    def is_alive(self, t: Target) -> tuple[bool, str]:
        """대상이 아직 있는지 (읽기 전용). 재생 상태 때문에 실패하지 않음."""
        if not user32.IsWindow(t.hwnd):
            return False, "대상 창이 닫혔습니다"
        if t.kind == "browser":
            tab = self._find_tab(t)
            if tab is None:
                return False, "대상 탭이 닫혔습니다"
            title = youtube_title(tab.Name)
            if title is None:  # 판별 규칙 점검이 가능하도록 탭 이름 원문을 그대로 남김
                return False, f"대상 탭이 유튜브가 아닌 페이지로 바뀌었습니다(탭 이름 원문: {tab.Name!r})"
            t.title, t.selected = title, self._is_selected(tab)
        return True, "OK"

    # ---------------- 플레이어
    def _find_player(self, t: Target, timeout: float):
        """보이는 유튜브 문서 안에서만 플레이어를 찾습니다. (없으면 None, 이유)"""
        key = (t.hwnd, t.tab_id)
        cached = self._player_cache.get(key)
        if cached is not None and self._player_visible(cached):
            return cached, ""
        self._player_cache.pop(key, None)
        win = self._window(t)
        end = time.monotonic() + timeout
        reason = "유튜브 문서를 찾지 못했습니다"
        while True:
            doc, url = self._youtube_doc_control(win)
            if doc is not None:
                t.page = page_kind(url)
                if t.page != VIDEO:
                    reason = "영상 재생 페이지가 아닙니다(유튜브 홈/검색/쇼츠). 영상을 연 뒤 다시 시도하세요"
                else:
                    player = doc.Control(searchDepth=35, AutomationId=PLAYER_ID)
                    if player.Exists(0, 0) and self._player_visible(player):
                        self._player_cache[key] = player
                        return player, ""
                    reason = "영상 페이지인데 플레이어 요소를 찾지 못했습니다"
            if time.monotonic() >= end:
                return None, reason
            time.sleep(0.15)

    @staticmethod
    def _player_visible(player) -> bool:
        try:
            r = player.BoundingRectangle
            return player.Exists(0, 0) and r.width() > 0 and r.height() > 0 and not player.IsOffscreen
        except Exception:
            return False

    def _focus_in_player(self, player) -> bool:
        """지금 키보드 포커스가 플레이어(또는 그 안의 요소)에 있는지 UIA로 확인합니다."""
        try:
            target_id = player.GetRuntimeId()
            c = self.auto.GetFocusedControl()
            for _ in range(20):
                if c is None:
                    return False
                if c.AutomationId == PLAYER_ID and c.GetRuntimeId() == target_id:
                    return True
                c = c.GetParentControl()
        except Exception:
            return False
        return False

    # ---------------- 명령 전 준비 (포커스를 실제로 바꿈 — 실제 모드에서만 호출)
    def prepare(self, t: Target) -> tuple[bool, str, str]:
        """창 활성화 -> (필요하면) 탭 선택 -> 플레이어 포커스 -> 확인. 키는 보내지 않습니다.

        반환: (성공 여부, 단계 이름, 설명). 실패면 단계 이름이 실패한 단계입니다.
        """
        ok, why = self.is_alive(t)
        if not ok:
            return False, STAGE_TARGET, f"{why}. 대상을 다시 선택하세요."
        # 창을 앞으로 가져오기 전에 확인: 웹 내용을 못 읽으면 플레이어 포커스를 확보할 수 없으므로 포커스도 옮기지 않음
        if not self._web_readable(self._window(t)):
            t.page = NO_ACCESS
            hint = (" Chrome 주소창에 chrome://accessibility 를 열어 'Native accessibility API support'와 "
                    "'Web accessibility'가 체크돼 있는지 확인하세요." if t.browser == "Chrome" else "")
            return False, STAGE_ACCESS, (f"{t.browser}가 웹 페이지 정보(문서·플레이어)를 제공하지 않아 플레이어 포커스를 "
                                         "확보할 수 없습니다. 볼륨이 스크롤되거나 검색창에 입력될 수 있어 보내지 않았습니다."
                                         f"{hint}")
        steps = []

        ok, why = activate_window(t.hwnd)
        if not ok:
            return False, STAGE_ACTIVATE, why
        steps.append(why)

        switched = False
        if t.kind == "browser" and not t.selected:
            tab = self._find_tab(t)
            try:
                tab.GetSelectionItemPattern().Select()
            except Exception:
                try:
                    tab.GetLegacyIAccessiblePattern().DoDefaultAction()
                except Exception:
                    pass
            if not _wait(lambda: self._is_selected(tab), 1.0):
                return False, STAGE_TAB, "뒤에 있는 유튜브 탭으로 전환하지 못했습니다"
            t.selected, switched = True, True
            steps.append("탭 전환")

        player, why = self._find_player(t, timeout=4.0 if switched else 1.5)
        if player is None:
            return False, STAGE_PLAYER, why

        if not self._focus_in_player(player):
            try:
                player.SetFocus()   # 클릭이 아니라 포커스만 옮김 -> 재생/정지 변화 없음
            except Exception:
                pass
            if not _wait(lambda: self._focus_in_player(player), 0.7):
                self._player_cache.pop((t.hwnd, t.tab_id), None)  # 다음에는 새로 찾기
                return False, STAGE_FOCUS, "영상 플레이어에 입력 포커스를 주지 못했습니다"
            steps.append("플레이어 포커스")

        # 마지막 확인: 그 사이 다른 창이 앞으로 오지 않았는지
        if foreground_hwnd() != t.hwnd:
            return False, STAGE_FINAL, "포커스를 맞추는 중 다른 창이 앞으로 왔습니다"
        return True, "", " -> ".join(steps)

    def player_state(self, t: Target) -> dict | None:
        """재생 상태, 볼륨(0~100), 재생 위치를 읽습니다 (읽기 전용). 결과 확인용. 못 읽으면 None."""
        try:
            player, _ = self._find_player(t, timeout=0.5)
        except Exception:
            return None
        if player is None:
            return None
        state = {}
        cls = player.ClassName or ""
        state["paused"] = "paused-mode" in cls if ("paused-mode" in cls or "playing-mode" in cls) else None
        state["volume"] = state["position"] = None
        wanted = {VOLUME_SLIDER_CLASS: "volume", PROGRESS_SLIDER_CLASS: "position"}
        stack = [(player, 0)]
        while stack:   # 플레이어 아래를 얕게(6단계) 훑어서 볼륨/재생 위치 슬라이더 값 읽기
            c, d = stack.pop()
            for ch in c.GetChildren():
                if ch.ControlTypeName == "SliderControl":
                    for cls_name, key in wanted.items():
                        if cls_name in (ch.ClassName or "") and state[key] is None:
                            try:
                                state[key] = ch.GetRangeValuePattern().Value
                            except Exception:
                                pass
                if d + 1 < 6:
                    stack.append((ch, d + 1))
        return state
