"""Voice command hook — UI-ready, engine-pluggable.

Default engine is a no-op stub so the app stays fully offline and never
depends on a cloud STT service. Real engines (on-device Arabic model,
platform speech API, etc.) register themselves via ``set_engine``.

The dashboard mic button calls ``listen_once(page, on_text=...)``; when an
engine is available it streams partial/final text into the quick-command
parser.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol


class VoiceEngine(Protocol):
    """Minimal contract for a speech-to-text backend."""

    def is_available(self) -> bool:
        """True when the engine can start listening on this device/build."""
        ...

    def listen_once(
        self,
        *,
        language: str = "ar-SY",
        on_partial: Callable[[str], None] | None = None,
        on_final: Callable[[str], None] | None = None,
        on_error: Callable[[str], None] | None = None,
        timeout_sec: float = 8.0,
    ) -> None:
        """Start a single utterance capture (non-blocking preferred)."""
        ...

    def cancel(self) -> None:
        """Abort an in-flight listen, if any."""
        ...


@dataclass
class StubVoiceEngine:
    """Always available for UI demos; never captures real audio.

    Calls ``on_error`` with a clear Arabic message so the owner understands
    that the mic button is wired and waiting for a real engine.
    """

    def is_available(self) -> bool:
        return True

    def listen_once(
        self,
        *,
        language: str = "ar-SY",
        on_partial: Callable[[str], None] | None = None,
        on_final: Callable[[str], None] | None = None,
        on_error: Callable[[str], None] | None = None,
        timeout_sec: float = 8.0,
    ) -> None:
        if on_error:
            on_error(
                "الميكروفون جاهز — لم يُربط محرك تعرّف صوت محلي بعد. "
                "اكتب الأمر في الحقل أو ثبّت محركاً عبر set_engine()."
            )

    def cancel(self) -> None:
        return None


_engine: VoiceEngine = StubVoiceEngine()


def set_engine(engine: VoiceEngine) -> None:
    """Register a real STT backend (call once at app startup if available)."""
    global _engine
    _engine = engine


def get_engine() -> VoiceEngine:
    return _engine


def listen_once(
    *,
    language: str = "ar-SY",
    on_partial: Callable[[str], None] | None = None,
    on_final: Callable[[str], None] | None = None,
    on_error: Callable[[str], None] | None = None,
    timeout_sec: float = 8.0,
) -> None:
    """Convenience wrapper around the active engine."""
    eng = get_engine()
    if not eng.is_available():
        if on_error:
            on_error("محرك الصوت غير متاح على هذا الجهاز")
        return
    eng.listen_once(
        language=language,
        on_partial=on_partial,
        on_final=on_final,
        on_error=on_error,
        timeout_sec=timeout_sec,
    )


def cancel() -> None:
    get_engine().cancel()


__all__ = [
    "VoiceEngine",
    "StubVoiceEngine",
    "AndroidNativeVoiceEngine",
    "set_engine",
    "get_engine",
    "listen_once",
    "cancel",
]

# REMOVED: WebSpeechVoiceEngine — decision: DELETE, not complete.
# Reason: flet 0.28.3's Page exposes no ``run_javascript`` (verified against
# the installed package — only flet.core.webview has it), so the engine
# could start a browser recognizer it could never read results from, and
# ``poll_web_result`` always returned (None, None, True): it was an
# illusion of web support. Web builds now get the honest stub message, and
# Android builds get the real on-device engine (auto-registered by
# VoiceSessionController._register_native_engine).


@dataclass
class AndroidNativeVoiceEngine:
    """Uses NativeFiles.speech_listen (Android SpeechRecognizer channel).

    ``native_files`` must be the live Flet control already added to the page.
    listen_once schedules an asyncio task so the UI stays responsive.
    """

    native_files: object  # NativeFiles
    page: object | None = None  # ft.Page for page.run_task if available

    def is_available(self) -> bool:
        return self.native_files is not None

    def listen_once(
        self,
        *,
        language: str = "ar-SY",
        on_partial: Callable[[str], None] | None = None,
        on_final: Callable[[str], None] | None = None,
        on_error: Callable[[str], None] | None = None,
        timeout_sec: float = 8.0,
    ) -> None:
        import asyncio

        async def _run():
            try:
                # Optional availability probe
                try:
                    ok = await self.native_files.speech_is_available()
                    if not ok:
                        if on_error:
                            on_error("التعرّف على الكلام غير متاح على هذا الجهاز")
                        return
                except Exception:
                    pass
                text = await self.native_files.speech_listen(
                    language=language or "ar-SY",
                    timeout_ms=int(max(3.0, timeout_sec) * 1000),
                )
                if text:
                    if on_final:
                        on_final(text)
                else:
                    if on_error:
                        on_error("لم يُلتقط كلام")
            except Exception as exc:
                if on_error:
                    on_error(str(exc))

        page = self.page
        if page is not None and hasattr(page, "run_task"):
            page.run_task(_run)
        else:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(_run())
                else:
                    loop.run_until_complete(_run())
            except Exception as exc:
                if on_error:
                    on_error(str(exc))

    def cancel(self) -> None:
        import asyncio

        async def _cancel():
            try:
                await self.native_files.speech_cancel()
            except Exception:
                pass

        page = self.page
        if page is not None and hasattr(page, "run_task"):
            page.run_task(_cancel)
        else:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(_cancel())
            except Exception:
                pass


