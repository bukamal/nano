from __future__ import annotations

import json
from typing import Any, Iterable

from flet.core.control import Control

# Control.invoke_method()/invoke_method_async() in this Flet version default
# to wait_timeout=5 (seconds) -- fine for calls the native side answers
# immediately, but every method below waits on a real person: picking a
# file, aiming a camera at a barcode, or dismissing the OS share sheet.
# Flet's own bundled controls use exactly this override for the same reason
# (see PermissionHandler.check_permission_async's wait_timeout=25, and
# FilePicker's timeout=3600) -- a fixed 5s budget for a human interaction is
# an easy way to lose the result silently: the native side can finish and
# return its answer well after Python has already given up waiting for it.
_INTERACTIVE_TIMEOUT = 600.0  # 10 minutes -- effectively "wait for the user"
# schedule/cancel just (re)register a WorkManager task -- no human involved,
# so a short generous budget is enough and a hang there shouldn't block the
# rest of app startup for 10 minutes like a stuck file dialog might.
_QUICK_TIMEOUT = 15.0


class NativeFiles(Control):
    """Non-visual bridge for Android/iOS file picker, share sheet and printing.

    Flet 0.28.3's Android ``FilePicker.save_file`` can return a document URI
    that Python cannot reliably write to. Nano therefore shares already-created
    local files through the native share sheet and imports a selected file into
    the app from the native picker cache path.
    """

    def __init__(self, *, tooltip: str | None = None, visible: bool | None = None, data: Any = None):
        super().__init__(tooltip=tooltip, visible=visible, data=data)

    def _get_control_name(self):
        return "flet_native_files"

    async def pick_file(
        self,
        *,
        extensions: Iterable[str] | None = None,
        dialog_title: str = "اختر ملفًا",
    ) -> dict | None:
        cleaned = [str(x).lower().lstrip(".") for x in (extensions or []) if str(x).strip()]
        raw = await self.invoke_method_async(
            "pick_file",
            {
                "extensions": json.dumps(cleaned, ensure_ascii=False),
                "dialog_title": dialog_title,
            },
            wait_for_result=True,
            wait_timeout=_INTERACTIVE_TIMEOUT,
        )
        if not raw or raw == "cancelled":
            return None
        if str(raw).startswith("error:"):
            raise RuntimeError(str(raw)[6:])
        try:
            value = json.loads(str(raw))
            return dict(value) if value else None
        except Exception as exc:
            raise RuntimeError("تعذر قراءة نتيجة اختيار الملف") from exc

    async def share_file(
        self,
        path: str,
        *,
        mime_type: str = "application/octet-stream",
        text: str = "",
        subject: str = "",
    ) -> bool:
        raw = await self.invoke_method_async(
            "share_file",
            {"path": str(path), "mime_type": mime_type, "text": text, "subject": subject},
            wait_for_result=True,
            wait_timeout=_INTERACTIVE_TIMEOUT,
        )
        if str(raw).startswith("error:"):
            raise RuntimeError(str(raw)[6:])
        return raw == "ok"

    async def print_html(self, html: str, *, name: str = "nano-report") -> bool:
        raw = await self.invoke_method_async(
            "print_html", {"html": html, "name": name}, wait_for_result=True, wait_timeout=_INTERACTIVE_TIMEOUT
        )
        if str(raw).startswith("error:"):
            raise RuntimeError(str(raw)[6:])
        return raw == "ok"

    async def create_pdf(self, html: str, *, filename: str = "nano-report.pdf") -> str:
        if not filename.lower().endswith(".pdf"):
            filename += ".pdf"
        raw = await self.invoke_method_async("create_pdf", {"html": html, "filename": filename},
            wait_for_result=True, wait_timeout=_INTERACTIVE_TIMEOUT,
        )
        if str(raw).startswith("error:"):
            raise RuntimeError(str(raw)[6:])
        path = str(raw or "").strip()
        if not path:
            raise RuntimeError("تعذر إنشاء ملف PDF")
        return path

    async def scan_barcode(self) -> str | None:
        """Open a full-screen camera scanner and return the decoded code.

        Returns None if the user backs out of the scanner without a read
        (cancelled, or denied camera permission). Raises RuntimeError for
        any other native-side failure.

        wait_for_result/wait_timeout are explicit here on purpose: this is
        the call most exposed to the default-5-second timeout bug described
        above, since aiming a camera and getting a clean read realistically
        takes longer than that.
        """
        raw = await self.invoke_method_async(
            "scan_barcode", {}, wait_for_result=True, wait_timeout=_INTERACTIVE_TIMEOUT
        )
        if not raw or raw == "cancelled":
            return None
        if str(raw).startswith("error:"):
            raise RuntimeError(str(raw)[6:])
        return str(raw)

    async def schedule_notifications(
        self,
        *,
        db_path: str,
        config_json: str,
        interval_minutes: int = 360,
        initial_delay_minutes: int = 0,
    ) -> bool:
        """(Re)register the Android background check for closed-app alerts.

        Cancels and re-registers on every call (see the Dart side), so this
        is safe to call again whenever the config changes -- the previous
        schedule is always replaced, never stacked. No-op on iOS/desktop/web.
        """
        raw = await self.invoke_method_async(
            "schedule_notifications",
            {
                "db_path": db_path,
                "config_json": config_json,
                "interval_minutes": str(int(interval_minutes)),
                "initial_delay_minutes": str(max(0, int(initial_delay_minutes))),
            },
            wait_for_result=True,
            wait_timeout=_QUICK_TIMEOUT,
        )
        if str(raw).startswith("error:"):
            raise RuntimeError(str(raw)[6:])
        return raw == "ok"

    async def cancel_notifications(self) -> bool:
        raw = await self.invoke_method_async(
            "cancel_notifications", {}, wait_for_result=True, wait_timeout=_QUICK_TIMEOUT
        )
        return raw == "ok"

    async def request_notification_permission(self) -> bool:
        """Ask for Android 13+'s POST_NOTIFICATIONS runtime permission.

        Best called from a moment the user is already engaging with
        notification settings, not silently at every app launch -- an
        unexplained system permission dialog on first open is exactly the
        kind of prompt people reflexively deny.
        """
        raw = await self.invoke_method_async(
            "request_notification_permission", {}, wait_for_result=True, wait_timeout=_INTERACTIVE_TIMEOUT
        )
        return raw == "ok"

    async def send_test_notification(
        self,
        *,
        title: str = "",
        body: str = "",
    ) -> bool:
        """Fire one real Android notification right now, through the same
        channel the closed-app background check uses.

        Purely a "does the pipe work" check -- unlike schedule_notifications,
        nothing here touches WorkManager or the on-disk database, so it's
        safe to call directly from a settings-screen button. No-op (returns
        True) on iOS/desktop/web, same as the rest of this bridge.

        Fires while the app is still open/foregrounded -- it does not prove
        anything about delivery once the app is closed. For that, use
        :meth:`schedule_test_notification` instead.
        """
        raw = await self.invoke_method_async(
            "send_test_notification",
            {"title": title, "body": body},
            wait_for_result=True,
            wait_timeout=_QUICK_TIMEOUT,
        )
        if str(raw).startswith("error:"):
            raise RuntimeError(str(raw)[6:])
        return raw == "ok"

    async def schedule_test_notification(
        self,
        *,
        delay_seconds: int,
        title: str = "",
        body: str = "",
    ) -> bool:
        """Register a one-off WorkManager task that fires a real Android
        notification after ``delay_seconds`` -- the actual "close the app
        and wait" test. Unlike schedule_notifications' periodic task
        (clamped to a 15-minute floor by WorkManager), a one-off task's
        initial delay is not clamped that way, so short waits (seconds to
        a few minutes) genuinely test whether a notification lands while
        the app is fully closed, not just backgrounded for an instant.

        Only registers the task -- this call returns immediately once
        WorkManager has accepted the schedule; it does not wait for the
        notification to actually fire. No-op (returns True) on iOS/
        desktop/web, same as the rest of this bridge.
        """
        raw = await self.invoke_method_async(
            "schedule_test_notification",
            {
                "delay_seconds": str(max(1, int(delay_seconds))),
                "title": title,
                "body": body,
            },
            wait_for_result=True,
            wait_timeout=_QUICK_TIMEOUT,
        )
        if str(raw).startswith("error:"):
            raise RuntimeError(str(raw)[6:])
        return raw == "ok"

    async def cancel_test_notification(self) -> bool:
        """Cancel a pending delayed test scheduled via
        schedule_test_notification, e.g. if the admin changes their mind
        before leaving the app."""
        raw = await self.invoke_method_async(
            "cancel_test_notification", {}, wait_for_result=True, wait_timeout=_QUICK_TIMEOUT
        )
        return raw == "ok"

    async def init_sound(self) -> bool:
        """Warm up the four bundled sound-cue AudioPools (see
        sound_pool.dart) once, ideally right at app startup, so the very
        first toast of the session doesn't pay the one-time asset-decode
        delay before it can play its tone.

        Best-effort like everything else in this bridge: returns False on
        any native-side failure (including a completely missing Dart
        implementation on an older built APK) instead of raising --
        play_sound() below re-runs the same load lazily anyway, so a
        failed/skipped warm-up here never means sound stays broken for the
        rest of the session, just that the first play() call pays the
        decode cost play_preview()/play() calls after it won't.
        """
        try:
            raw = await self.invoke_method_async(
                "init_sound", {}, wait_for_result=True, wait_timeout=_QUICK_TIMEOUT
            )
        except Exception:
            return False
        return raw == "ok"

    async def play_sound(self, *, kind: str, volume: float) -> None:
        """Fire-and-forget playback of one bundled tone (success/error/
        warning/info) through the native AudioPool for ``kind``.

        Deliberately swallows every failure -- an unknown kind, an
        AudioPool that failed to load, a native playback error, or this
        method being called against an older built APK that predates it
        entirely. Sound is always a best-effort enhancement layered on top
        of the toast that already conveys the same information visually
        (see core/sound.py's play()), never something worth surfacing to
        the user or the flow that triggered it.
        """
        try:
            await self.invoke_method_async(
                "play_sound",
                {"kind": kind, "volume": f"{max(0.0, min(1.0, volume)):.3f}"},
                wait_for_result=True,
                wait_timeout=_QUICK_TIMEOUT,
            )
        except Exception:
            pass

    async def diagnose_sound(self, *, retry: bool = False) -> dict | None:
        """Backs the admin "تشخيص المشكلة" button (see views/admin_view.py).

        Unlike play_sound()/init_sound(), this one is *not* best-effort --
        a failure here (older APK predating this method, no native bridge
        reachable at all, malformed response) is meaningful diagnostic
        information in itself, so it's returned as ``None`` for the caller
        to report as its own diagnosis line rather than being swallowed.

        ``retry=True`` asks the native side to re-attempt any tone that
        failed to load earlier in this session (see sound_pool.dart's
        ensureSoundPoolsLoaded) instead of only re-reporting the same
        cached failure.
        """
        try:
            raw = await self.invoke_method_async(
                "diagnose_sound",
                {"retry": "1" if retry else "0"},
                wait_for_result=True,
                wait_timeout=_QUICK_TIMEOUT,
            )
        except Exception as exc:
            return {"bridge_error": repr(exc)}
        if raw is None or str(raw).startswith("error:"):
            return {"bridge_error": str(raw)}
        try:
            return json.loads(raw)
        except (TypeError, ValueError) as exc:
            return {"bridge_error": f"malformed response: {exc!r} raw={raw!r}"}

    async def share_pdf(self, html: str, *, filename: str = "nano-report.pdf") -> bool:
        """Create a real PDF file, then share it through share_file/shareXFiles.

        Backups and PDFs therefore use the same Android share-sheet code path.
        """
        path = await self.create_pdf(html, filename=filename)
        return await self.share_file(
            path,
            mime_type="application/pdf",
            subject=filename if filename.lower().endswith(".pdf") else f"{filename}.pdf",
        )

    async def push_home_widget(self, snapshot: dict) -> None:
        """Immediate home-screen-widget refresh (PHASE10), app-open path.

        Call this right after a sale/receipt/payment posts, from whichever
        service already has the fresh numbers in memory (DashboardService/
        InvoiceService) -- this intentionally does not re-query anything
        itself. No-op on iOS/desktop/web, and never raises: a widget that
        fails to refresh must not interrupt the accounting flow that
        triggered it. The closed-app fallback (periodic WorkManager pass,
        same DB path used by schedule_notifications) keeps the widget fresh
        the rest of the time without any further calls from here.
        """
        try:
            await self.invoke_method_async(
                "push_home_widget",
                {"snapshot_json": json.dumps(snapshot, ensure_ascii=False)},
                wait_for_result=False,
                wait_timeout=_QUICK_TIMEOUT,
            )
        except Exception:
            pass
