from __future__ import annotations

"""Fail-closed routing of the real Codex composer Enter gesture for H2."""

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import os
import queue
import threading
import time
from typing import Any, Callable

from r6o.host.codex.windows.binding import CodexBindingError, CodexSidecarBinding
from r6o.host.codex.windows.uia import composer_empty_observation


WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_QUIT = 0x0012
VK_RETURN = 0x0D
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12
VK_LWIN = 0x5B
VK_RWIN = 0x5C
KEY_DOWN_MESSAGES = {WM_KEYDOWN, WM_SYSKEYDOWN}
KEY_UP_MESSAGES = {WM_KEYUP, WM_SYSKEYUP}
MODIFIER_KEYS = (VK_SHIFT, VK_CONTROL, VK_MENU, VK_LWIN, VK_RWIN)
GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000


class _KeyboardHookStruct(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class CodexInputBindingError(RuntimeError):
    """A stable, machine-readable H2-E1 input-routing failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def build_host_composer_envelope(projection: dict[str, Any], text: str) -> dict[str, Any]:
    """Build the protected InputEnvelope shape without performing semantics."""

    try:
        session_id = projection["session_id"]
        model_revision = projection["model_revision"]
    except (KeyError, TypeError) as exc:
        raise CodexInputBindingError("ACTIVE_PROJECTION_CONTEXT_INVALID") from exc
    if not isinstance(session_id, str) or not session_id:
        raise CodexInputBindingError("ACTIVE_PROJECTION_CONTEXT_INVALID")
    if not isinstance(model_revision, str) or not model_revision:
        raise CodexInputBindingError("ACTIVE_PROJECTION_CONTEXT_INVALID")
    if not isinstance(text, str) or not text.strip():
        raise CodexInputBindingError("HOST_COMPOSER_TEXT_EMPTY")
    return {
        "schema_version": "r6o-input-envelope-1",
        "session_id": session_id,
        "source": "HOST_COMPOSER_TEXT",
        "model_revision": model_revision,
        "text": text,
        "action_id": None,
        "projection_id": None,
    }


def validate_active_projection_context(projection: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(projection, dict):
        raise CodexInputBindingError("ACTIVE_PROJECTION_CONTEXT_INVALID")
    if projection.get("schema_version") != "r6o-focus-projection-1":
        raise CodexInputBindingError("ACTIVE_PROJECTION_CONTEXT_INVALID")
    if not isinstance(projection.get("projection_id"), str) or not projection["projection_id"]:
        raise CodexInputBindingError("ACTIVE_PROJECTION_CONTEXT_INVALID")
    # Exercise the same validation used to build a text envelope before arming.
    try:
        build_host_composer_envelope(projection, "validation")
    except CodexInputBindingError as exc:
        raise CodexInputBindingError("ACTIVE_PROJECTION_CONTEXT_INVALID") from exc
    return dict(projection)


@dataclass(frozen=True)
class CapturedComposerSubmission:
    projection: dict[str, Any]
    text: str
    captured_monotonic: float
    delivery_token: int = 0


class CodexComposerInputBinding:
    """Intercept one native Enter while an H2 free-response projection is armed.

    The binding captures presentation input only. It emits an InputEnvelope to
    the supplied presentation-boundary callback and never imports or calls the
    ViewModel, Model Port, controller, worker, or workspace authority.
    """

    def __init__(
        self,
        host: CodexSidecarBinding,
        on_envelope: Callable[[dict[str, Any]], None],
        *,
        focus_probe: Callable[[], bool] | None = None,
        text_probe: Callable[[], str] | None = None,
    ) -> None:
        self.host = host
        self.on_envelope = on_envelope
        self._focus_probe = focus_probe or self._default_focus_probe
        self._text_probe = text_probe or self._default_text_probe
        self._state_lock = threading.Lock()
        # Lock order is composer mutation -> state. Cancellation paths never
        # wait for this lock while holding _state_lock, and _state_lock is never
        # held across the bounded UI/Win32 composer operation.
        self._composer_mutation_lock = threading.Lock()
        self._active_projection: dict[str, Any] | None = None
        self._armed = False
        self._delivery_pending = False
        self._delivery_cancelled = False
        self._delivery_token = 0
        self._pending_delivery_token: int | None = None
        self._failure_guard = False
        self._enter_down = False
        self._enter_pair_complete = threading.Event()
        self._enter_pair_complete.set()
        self._pressed_modifiers: set[int] = set()
        self._captures: queue.Queue[CapturedComposerSubmission | None] = queue.Queue()
        self._delivery_event = threading.Event()
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._hook_thread: threading.Thread | None = None
        self._dispatcher: Any | None = None
        self._hook_thread_id = 0
        self._hook = 0
        self._hook_user32: Any | None = None
        self._callback: Any | None = None
        self._teardown_pending = False
        self.last_error: str | None = None
        self.last_envelope: dict[str, Any] | None = None
        self.capture_count = 0
        self.delivery_count = 0
        self.suppressed_keydown_count = 0
        self.suppressed_keyup_count = 0
        self.empty_enter_suppressed_count = 0
        self.modified_enter_passthrough_count = 0
        self.focus_transaction_count = 0

    @property
    def armed(self) -> bool:
        with self._state_lock:
            return self._armed

    @property
    def delivery_pending(self) -> bool:
        with self._state_lock:
            return self._delivery_pending

    def _set_error(self, code: str) -> None:
        if self.last_error is None:
            self.last_error = code

    def _enter_fail_closed(self, code: str) -> None:
        self._set_error(code)
        with self._state_lock:
            self._armed = False
            self._active_projection = None
            self._failure_guard = True

    def assert_healthy(self) -> None:
        if self.last_error:
            raise CodexInputBindingError(self.last_error)

    def _default_focus_probe(self) -> bool:
        try:
            return bool(self.host.controls.composer.has_keyboard_focus())
        except Exception:
            return False

    def _default_text_probe(self) -> str:
        try:
            return str(self.host.controls.composer.iface_value.CurrentValue)
        except Exception as exc:
            raise CodexInputBindingError("HOST_COMPOSER_VALUE_UNAVAILABLE") from exc

    def start(self) -> None:
        if os.name != "nt":
            raise CodexInputBindingError("HOST_PLATFORM_UNSUPPORTED")
        if self._hook_thread is not None:
            if self._hook_thread.is_alive():
                with self._state_lock:
                    verified_active_hook = bool(self._hook) and not self._teardown_pending
                if verified_active_hook and not self._stop.is_set():
                    self.assert_healthy()
                    return
                raise CodexInputBindingError("HOST_INPUT_HOOK_RESTART_BLOCKED")
            self._hook_thread = None
        with self._state_lock:
            if self._teardown_pending:
                raise CodexInputBindingError("HOST_INPUT_HOOK_RESTART_BLOCKED")
        if self._hook:
            raise CodexInputBindingError("HOST_INPUT_HOOK_STILL_ACTIVE")
        if self.last_error:
            raise CodexInputBindingError(self.last_error)
        with self._composer_mutation_lock:
            with self._state_lock:
                self._armed = False
                self._active_projection = None
                self._delivery_pending = False
                self._delivery_cancelled = False
                self._delivery_token += 1
                self._pending_delivery_token = None
                self._failure_guard = False
                self._enter_down = False
                self._enter_pair_complete.set()
                self._pressed_modifiers.clear()
                self._delivery_event.clear()
                self._stop.clear()
        self.last_envelope = None
        self.capture_count = 0
        self.delivery_count = 0
        self.suppressed_keydown_count = 0
        self.suppressed_keyup_count = 0
        self.empty_enter_suppressed_count = 0
        self.modified_enter_passthrough_count = 0
        self.focus_transaction_count = 0
        self._ready.clear()
        self._install_dispatcher()
        self._hook_thread = threading.Thread(
            target=self._run_keyboard_hook,
            name="h2-e1-codex-enter-hook",
            daemon=True,
        )
        self._hook_thread.start()
        if not self._ready.wait(timeout=5.0):
            self.stop()
            raise CodexInputBindingError("HOST_INPUT_HOOK_START_TIMEOUT")
        try:
            self.assert_healthy()
            with self._state_lock:
                verified_hook = bool(self._hook)
            if not verified_hook or self._hook_thread is None or not self._hook_thread.is_alive():
                raise CodexInputBindingError("HOST_INPUT_HOOK_NOT_VERIFIED")
        except Exception:
            self.stop()
            raise

    def _install_dispatcher(self) -> None:
        try:
            from PySide6.QtCore import QObject, Qt, Signal, Slot
        except ImportError as exc:
            raise CodexInputBindingError("SIDECAR_DEPENDENCY_MISSING") from exc
        delivery_callback = self._deliver_capture

        class _InputDispatcher(QObject):
            submissionRequested = Signal(object)

            def __init__(self) -> None:
                super().__init__()
                self.submissionRequested.connect(self.deliver, Qt.QueuedConnection)

            @Slot(object)
            def deliver(self, capture: object) -> None:
                delivery_callback(capture)

        self._dispatcher = _InputDispatcher()

    def _transfer_focus_from_sidecar_to_host(self, user32: Any | None = None) -> None:
        """Perform one bounded, verified Win32 input-thread focus transaction."""

        user32 = user32 or ctypes.windll.user32
        style = int(user32.GetWindowLongW(self.host.sidecar_hwnd, GWL_EXSTYLE))
        user32.SetWindowLongW(
            self.host.sidecar_hwnd,
            GWL_EXSTYLE,
            style | WS_EX_NOACTIVATE,
        )
        sidecar_thread = int(user32.GetWindowThreadProcessId(self.host.sidecar_hwnd, None))
        host_thread = int(user32.GetWindowThreadProcessId(self.host.host_hwnd, None))
        if sidecar_thread <= 0 or host_thread <= 0 or sidecar_thread == host_thread:
            raise CodexInputBindingError("HOST_FOCUS_THREAD_ID_INVALID")
        attached = bool(user32.AttachThreadInput(sidecar_thread, host_thread, True))
        if not attached:
            raise CodexInputBindingError("HOST_THREAD_INPUT_ATTACH_FAILED")
        focus_calls_succeeded = False
        detach_succeeded = False
        try:
            user32.SetForegroundWindow(self.host.host_hwnd)
            user32.SetActiveWindow(self.host.host_hwnd)
            focus_calls_succeeded = True
        finally:
            detach_succeeded = bool(
                user32.AttachThreadInput(sidecar_thread, host_thread, False)
            )
        if not detach_succeeded:
            raise CodexInputBindingError("HOST_THREAD_INPUT_DETACH_FAILED")
        if not focus_calls_succeeded or int(user32.GetForegroundWindow() or 0) != self.host.host_hwnd:
            raise CodexInputBindingError("HOST_FOCUS_TRANSFER_FAILED")
        self.focus_transaction_count += 1

    def activate(self, projection: dict[str, Any], *, timeout: float = 5.0) -> None:
        """Focus the actual composer and arm exactly one text submission."""

        if self._hook_thread is None or self._teardown_pending:
            raise CodexInputBindingError("HOST_INPUT_HOOK_NOT_STARTED")
        context = validate_active_projection_context(projection)
        with self._state_lock:
            if self._delivery_pending:
                raise CodexInputBindingError("HOST_COMPOSER_DELIVERY_PENDING")
            if self._enter_down:
                raise CodexInputBindingError("HOST_ENTER_KEYUP_PENDING")
            # Enter suppression must be fail-closed before the first native
            # operation can make the actual composer usable.  Qt dispatch is
            # queued, so a capture during focus convergence cannot reach the
            # E3 session until activate() and its caller finish the handoff.
            self._active_projection = context
            self._armed = True
            self._delivery_cancelled = False
            self._failure_guard = False
            self._delivery_event.clear()
        # Revalidate the frozen D1 HWND before any native focus mutation. A
        # stale HWND may have been reused since the D2 attachment completed.
        self.host.refresh_controls()
        self._transfer_focus_from_sidecar_to_host()
        controls = self.host.refresh_controls()
        controls.composer.set_focus()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.assert_healthy()
            try:
                controls = self.host.refresh_controls()
                focused = bool(controls.composer.has_keyboard_focus())
                foreground = self.host.native.foreground() == self.host.host_hwnd
            except Exception:
                focused = False
                foreground = False
            with self._state_lock:
                delivery_pending = self._delivery_pending
            if delivery_pending:
                # The hook independently verified the foreground and composer
                # focus before accepting this earliest valid Enter gesture.
                self.assert_healthy()
                return
            if focused and foreground:
                self.assert_healthy()
                return
            time.sleep(0.025)
        # Keep the already-installed suppression boundary active until the
        # owner explicitly aborts/stops it.  Deactivating here would expose any
        # text typed during native focus convergence to Codex after this error.
        raise CodexInputBindingError("ACTUAL_COMPOSER_FOCUS_UNVERIFIED")

    def deactivate(self) -> None:
        with self._state_lock:
            self._armed = False
            self._active_projection = None
            # A swallowed keydown owns its matching keyup even after the
            # binding is deactivated. Only the keyup handler may complete the
            # pair; clearing it here would leak that keyup to the native host.
            if not self._enter_down:
                self._enter_pair_complete.set()

    def abort_handoff(self) -> None:
        """Clear an abandoned handoff while Enter suppression is still active."""

        failure: CodexInputBindingError | None = None
        with self._state_lock:
            delivery_pending = self._delivery_pending
            armed = self._armed
            failure_guard = self._failure_guard
        if delivery_pending:
            try:
                with self._composer_mutation_lock:
                    with self._state_lock:
                        still_pending = self._delivery_pending
                        self._delivery_cancelled = True
                        if still_pending:
                            self._delivery_pending = False
                            self._pending_delivery_token = None
                            self._delivery_token += 1
                    if still_pending:
                        # Invalidation and the one authorized destructive clear
                        # are one serialized transaction. A queued callback can
                        # no longer acquire mutation authority afterward.
                        self._clear_actual_composer()
            except Exception as exc:
                failure = (
                    exc
                    if isinstance(exc, CodexInputBindingError)
                    else CodexInputBindingError("HOST_COMPOSER_ABORT_CLEAR_FAILED")
                )
        elif armed or failure_guard:
            try:
                with self._composer_mutation_lock:
                    with self._state_lock:
                        should_clear = self._armed or self._failure_guard
                        self._delivery_cancelled = True
                    if should_clear:
                        self._clear_actual_composer()
            except Exception as exc:
                failure = (
                    exc
                    if isinstance(exc, CodexInputBindingError)
                    else CodexInputBindingError("HOST_COMPOSER_ABORT_CLEAR_FAILED")
                )
        self.deactivate()
        if failure is not None:
            raise failure

    def wait_for_delivery(self, timeout: float = 5.0) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not self._delivery_event.is_set():
            try:
                from PySide6.QtCore import QCoreApplication, QEventLoop

                app = QCoreApplication.instance()
                if app is not None:
                    app.processEvents(QEventLoop.AllEvents, 25)
            except ImportError:
                pass
            time.sleep(0.025)
        if not self._delivery_event.is_set():
            self.assert_healthy()
            raise CodexInputBindingError("HOST_COMPOSER_ENVELOPE_TIMEOUT")
        self.assert_healthy()
        if self.last_envelope is None:
            raise CodexInputBindingError("HOST_COMPOSER_ENVELOPE_MISSING")
        return dict(self.last_envelope)

    @staticmethod
    def _modifier_active(user32: Any) -> bool:
        return any(int(user32.GetAsyncKeyState(key)) & 0x8000 for key in MODIFIER_KEYS)

    def _handle_key_event(self, user32: Any, vk_code: int, message: int) -> bool:
        """Return True only when the native key event must be swallowed."""

        if vk_code in MODIFIER_KEYS:
            with self._state_lock:
                if message in KEY_DOWN_MESSAGES:
                    self._pressed_modifiers.add(vk_code)
                elif message in KEY_UP_MESSAGES:
                    self._pressed_modifiers.discard(vk_code)
            return False
        if vk_code != VK_RETURN:
            return False
        with self._state_lock:
            if message in KEY_UP_MESSAGES and self._enter_down:
                self._enter_down = False
                self._enter_pair_complete.set()
                self.suppressed_keyup_count += 1
                return True
            if message in KEY_DOWN_MESSAGES and self._enter_down:
                return True
            armed = self._armed
            delivery_pending = self._delivery_pending
            failure_guard = self._failure_guard
        if message not in KEY_DOWN_MESSAGES or not (
            armed or delivery_pending or failure_guard
        ):
            return False
        try:
            foreground_matches = int(user32.GetForegroundWindow() or 0) == self.host.host_hwnd
        except Exception:
            with self._state_lock:
                self._enter_down = True
                self._enter_pair_complete.clear()
                self.suppressed_keydown_count += 1
            self._enter_fail_closed("HOST_KEY_STATE_UNAVAILABLE")
            return True
        if not foreground_matches:
            # The active H2 binding never captures another application's Enter.
            return False
        if failure_guard:
            with self._state_lock:
                self._enter_down = True
                self._enter_pair_complete.clear()
                self.suppressed_keydown_count += 1
            return True
        if delivery_pending:
            with self._state_lock:
                # Recheck after foreground observation because GUI-thread
                # clearing may have completed while the hook was evaluating.
                if self._delivery_pending:
                    # The captured text is still present until the GUI-thread
                    # delivery clears the real composer. Swallow any later
                    # Enter gesture in Codex during that interval so it cannot
                    # escape to the native request path.
                    self._enter_down = True
                    self._enter_pair_complete.clear()
                    self.suppressed_keydown_count += 1
                    return True
                armed = self._armed
            if not armed:
                return False
        try:
            with self._state_lock:
                tracked_modifier = bool(self._pressed_modifiers)
            modified = tracked_modifier or self._modifier_active(user32)
        except Exception:
            with self._state_lock:
                self._enter_down = True
                self._enter_pair_complete.clear()
                self.suppressed_keydown_count += 1
            self._enter_fail_closed("HOST_KEY_STATE_UNAVAILABLE")
            return True
        if modified:
            self.modified_enter_passthrough_count += 1
            return False
        with self._state_lock:
            self._enter_down = True
            self._enter_pair_complete.clear()
        self.suppressed_keydown_count += 1
        try:
            focus_verified = bool(self._focus_probe())
        except Exception:
            focus_verified = False
        if not focus_verified:
            self._enter_fail_closed("ACTUAL_COMPOSER_FOCUS_UNVERIFIED_AT_ENTER")
            return True
        try:
            text = self._text_probe()
        except Exception:
            self._enter_fail_closed("HOST_COMPOSER_VALUE_UNAVAILABLE")
            return True
        if not isinstance(text, str) or not text.strip():
            self.empty_enter_suppressed_count += 1
            return True
        with self._state_lock:
            projection = dict(self._active_projection or {})
            self._armed = False
            self._active_projection = None
            self._delivery_token += 1
            delivery_token = self._delivery_token
            self._pending_delivery_token = delivery_token
            self._delivery_pending = True
        self.capture_count += 1
        capture = CapturedComposerSubmission(
            projection=projection,
            text=text,
            captured_monotonic=time.monotonic(),
            delivery_token=delivery_token,
        )
        if self._dispatcher is None:
            # Unit-level callers may exercise the decision function without a
            # Qt runtime. A started production binding always has a dispatcher.
            if self._hook_thread is not None:
                self._set_error("HOST_INPUT_DISPATCHER_UNAVAILABLE")
            self._captures.put(capture)
        else:
            self._dispatcher.submissionRequested.emit(capture)
        return True

    def _clear_actual_composer(self) -> None:
        try:
            from pywinauto.keyboard import send_keys
        except ImportError as exc:
            raise CodexInputBindingError("HOST_DEPENDENCY_MISSING") from exc
        empty_contract = self.host.selectors["reset_contract"]["composer_empty"]
        controls = self.host.refresh_controls()
        controls.composer.set_focus()
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            controls = self.host.refresh_controls()
            if (
                bool(controls.composer.has_keyboard_focus())
                and self.host.native.foreground() == self.host.host_hwnd
            ):
                break
            time.sleep(0.025)
        else:
            raise CodexInputBindingError("HOST_COMPOSER_CLEAR_FOCUS_UNVERIFIED")
        send_keys("^a{BACKSPACE}", pause=0.025)
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            controls = self.host.refresh_controls()
            if composer_empty_observation(controls.composer, empty_contract).get("empty") is True:
                return
            time.sleep(0.025)
        raise CodexInputBindingError("HOST_COMPOSER_CLEAR_UNVERIFIED")

    def _deliver_capture(self, capture: object) -> None:
        if not isinstance(capture, CapturedComposerSubmission):
            self._set_error("CAPTURE_RECORD_INVALID")
            self._delivery_event.set()
            return
        with self._state_lock:
            owns_pending_delivery = (
                self._delivery_pending
                and capture.delivery_token == self._pending_delivery_token
            )
            cancelled_current_delivery = (
                self._delivery_cancelled
                and not self._delivery_pending
                and capture.delivery_token == self._delivery_token
            )
        if not owns_pending_delivery:
            # A timed-out delivery, a replayed callback, or a callback from an
            # earlier start/stop cycle has no authority over the composer or
            # the current cycle's delivery event.
            if cancelled_current_delivery:
                self._delivery_event.set()
            return
        completes_current_event = False
        deliver_envelope = False
        try:
            envelope = build_host_composer_envelope(capture.projection, capture.text)
            with self._composer_mutation_lock:
                with self._state_lock:
                    owns_mutation = (
                        self._delivery_pending
                        and capture.delivery_token == self._pending_delivery_token
                    )
                    if owns_mutation:
                        completes_current_event = True
                if not owns_mutation:
                    return
                self._clear_actual_composer()
                with self._state_lock:
                    still_owned = (
                        self._delivery_pending
                        and capture.delivery_token == self._pending_delivery_token
                    )
                    if not still_owned:
                        return
                    deliver_envelope = not self._delivery_cancelled
                    self._delivery_pending = False
                    self._pending_delivery_token = None
            if deliver_envelope:
                self.on_envelope(dict(envelope))
                self.last_envelope = envelope
                self.delivery_count += 1
        except Exception as exc:
            with self._state_lock:
                completes_current_event = (
                    self._delivery_pending
                    and capture.delivery_token == self._pending_delivery_token
                )
            code = exc.code if isinstance(exc, CodexInputBindingError) else "ENVELOPE_DELIVERY_FAILED"
            self._set_error(code)
        finally:
            if completes_current_event:
                with self._state_lock:
                    event_still_current = capture.delivery_token == self._delivery_token
                if event_still_current:
                    self._delivery_event.set()

    def _run_keyboard_hook(self) -> None:
        user32 = ctypes.windll.user32
        self._hook_user32 = user32
        kernel32 = ctypes.windll.kernel32
        hook_proc = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t,
            ctypes.c_int,
            ctypes.c_size_t,
            ctypes.c_ssize_t,
        )
        user32.SetWindowsHookExW.argtypes = [ctypes.c_int, hook_proc, ctypes.c_void_p, wintypes.DWORD]
        user32.SetWindowsHookExW.restype = ctypes.c_void_p
        user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_size_t, ctypes.c_ssize_t]
        user32.CallNextHookEx.restype = ctypes.c_ssize_t
        user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
        user32.UnhookWindowsHookEx.restype = wintypes.BOOL
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        kernel32.GetModuleHandleW.restype = ctypes.c_void_p

        def callback(code: int, message: int, data_address: int) -> int:
            suppressed = False
            if code >= 0:
                try:
                    data = ctypes.cast(
                        data_address, ctypes.POINTER(_KeyboardHookStruct)
                    ).contents
                    suppressed = self._handle_key_event(user32, int(data.vkCode), int(message))
                except Exception:
                    self._set_error("HOST_INPUT_HOOK_RUNTIME_FAILED")
                    with self._state_lock:
                        suppress_fail_closed = (
                            self._armed
                            or self._delivery_pending
                            or self._failure_guard
                            or self._enter_down
                        )
                    suppressed = bool(suppress_fail_closed and message in KEY_DOWN_MESSAGES | KEY_UP_MESSAGES)
            if suppressed:
                return 1
            return int(
                user32.CallNextHookEx(ctypes.c_void_p(self._hook), code, message, data_address)
            )

        try:
            self._callback = hook_proc(callback)
            self._hook_thread_id = int(kernel32.GetCurrentThreadId())
            module = kernel32.GetModuleHandleW(None)
            with self._state_lock:
                self._hook = int(
                    user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._callback, module, 0) or 0
                )
            if not self._hook:
                self._set_error("HOST_INPUT_HOOK_INSTALL_FAILED")
                self._ready.set()
                return
            self._ready.set()
            message = wintypes.MSG()
            while not self._stop.is_set() and user32.GetMessageW(
                ctypes.byref(message), None, 0, 0
            ) > 0:
                user32.TranslateMessage(ctypes.byref(message))
                user32.DispatchMessageW(ctypes.byref(message))
        except Exception:
            self._set_error("HOST_INPUT_HOOK_RUNTIME_FAILED")
            self._ready.set()
        finally:
            if not self._remove_keyboard_hook(user32):
                self._set_error("HOST_INPUT_HOOK_REMOVE_FAILED")

    def _remove_keyboard_hook(self, user32: Any) -> bool:
        """Remove the low-level hook exactly once, including stop-time fallback."""

        with self._state_lock:
            hook = self._hook
            if not hook:
                return True
            removed = bool(user32.UnhookWindowsHookEx(ctypes.c_void_p(hook)))
            if removed:
                self._hook = 0
            return removed

    def stop(self) -> None:
        failures: list[CodexInputBindingError] = []
        with self._state_lock:
            self._teardown_pending = True
            delivery_pending = self._delivery_pending
        if delivery_pending:
            try:
                # A clean stop cannot discard a captured submission that is
                # queued to the GUI thread. Drain it before removing the hook
                # and dispatcher, or retain an explicit failure while cleanup
                # continues.
                self.wait_for_delivery(timeout=5.0)
            except CodexInputBindingError as exc:
                failures.append(exc)
        try:
            with self._composer_mutation_lock:
                with self._state_lock:
                    abandoned_delivery = self._delivery_pending
                    self._delivery_cancelled = True
                    if abandoned_delivery:
                        self._delivery_pending = False
                        self._pending_delivery_token = None
                        self._delivery_token += 1
                if abandoned_delivery:
                    # Once provenance is invalidated, only this synchronous cleanup
                    # may touch attempt-owned composer text. A queued Qt callback is
                    # now permanently stale, including across later start cycles.
                    self._clear_actual_composer()
        except Exception as exc:
            failures.append(
                exc
                if isinstance(exc, CodexInputBindingError)
                else CodexInputBindingError("HOST_COMPOSER_ABORT_CLEAR_FAILED")
            )
        self.deactivate()
        if not self._enter_pair_complete.wait(timeout=5.0):
            failures.append(CodexInputBindingError("HOST_ENTER_KEYUP_DRAIN_TIMEOUT"))
            thread = self._hook_thread
            if self._hook and thread is not None and thread.is_alive():
                # Removing a verified hook here would abandon the matching
                # native keyup for a keydown this binding swallowed. Return a
                # bounded failure while retaining pair ownership; keyup makes
                # a later stop retry safe and deterministic.
                self._dispatcher = None
                raise failures[0]
        self._stop.set()
        thread = self._hook_thread
        if thread is not None:
            if self._hook_thread_id:
                try:
                    ctypes.windll.user32.PostThreadMessageW(self._hook_thread_id, WM_QUIT, 0, 0)
                except Exception:
                    failures.append(CodexInputBindingError("HOST_INPUT_HOOK_STOP_SIGNAL_FAILED"))
            try:
                thread.join(timeout=5.0)
            except Exception:
                failures.append(CodexInputBindingError("HOST_INPUT_HOOK_STOP_FAILED"))
            if thread.is_alive():
                failures.append(CodexInputBindingError("HOST_INPUT_HOOK_STOP_TIMEOUT"))
                user32 = self._hook_user32
                if user32 is None:
                    windll = getattr(ctypes, "windll", None)
                    user32 = getattr(windll, "user32", None)
                if user32 is None or not self._remove_keyboard_hook(user32):
                    failures.append(CodexInputBindingError("HOST_INPUT_HOOK_REMOVE_FAILED"))
            else:
                self._hook_thread = None
        elif self._hook:
            user32 = self._hook_user32
            if user32 is None:
                windll = getattr(ctypes, "windll", None)
                user32 = getattr(windll, "user32", None)
            if user32 is None or not self._remove_keyboard_hook(user32):
                failures.append(CodexInputBindingError("HOST_INPUT_HOOK_REMOVE_FAILED"))
        with self._state_lock:
            self._delivery_pending = False
            self._pending_delivery_token = None
            self._failure_guard = False
            live_thread = self._hook_thread is not None and self._hook_thread.is_alive()
            self._teardown_pending = bool(self._hook or live_thread)
        self._dispatcher = None
        if failures:
            raise failures[0]
        self.assert_healthy()

    def __enter__(self) -> "CodexComposerInputBinding":
        self.start()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.stop()
