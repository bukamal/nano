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


@dataclass
class WebSpeechVoiceEngine:
    """Progressive enhancement for Flet web builds via the browser SpeechRecognition API.

    Offline browsers may still refuse; failures surface through ``on_error``.
    """

    page: object  # ft.Page

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
        # Store callbacks on the page so JS can invoke them through a bridge
        # if/when the host exposes one. Until then, attempt run_javascript and
        # report a friendly fallback.
        self._on_final = on_final
        self._on_error = on_error
        self._on_partial = on_partial
        js = f"""
        (() => {{
          const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
          if (!SR) {{
            return JSON.stringify({{ok:false, error:"SpeechRecognition غير مدعوم في هذا المتصفح"}});
          }}
          const rec = new SR();
          rec.lang = {language!r};
          rec.interimResults = true;
          rec.maxAlternatives = 1;
          let finalText = "";
          rec.onresult = (ev) => {{
            let interim = "";
            for (let i = ev.resultIndex; i < ev.results.length; i++) {{
              const t = ev.results[i][0].transcript;
              if (ev.results[i].isFinal) finalText += t;
              else interim += t;
            }}
            window.__nano_voice_partial = interim || finalText;
            if (finalText) window.__nano_voice_final = finalText;
          }};
          rec.onerror = (e) => {{ window.__nano_voice_error = e.error || "error"; }};
          rec.onend = () => {{ window.__nano_voice_done = true; }};
          try {{
            rec.start();
            return JSON.stringify({{ok:true}});
          }} catch (e) {{
            return JSON.stringify({{ok:false, error: String(e)}});
          }}
        }})()
        """
        try:
            page = self.page
            if hasattr(page, "run_javascript"):
                page.run_javascript(js)
                # Poll is left to the UI layer via poll_web_result()
            elif on_error:
                on_error("تشغيل JavaScript غير متاح في هذه المنصة")
        except Exception as exc:
            if on_error:
                on_error(str(exc))

    def cancel(self) -> None:
        try:
            if hasattr(self.page, "run_javascript"):
                self.page.run_javascript(
                    "try{ if(window.__nano_rec) window.__nano_rec.stop(); }catch(e){}"
                )
        except Exception:
            pass

    def poll_web_result(self) -> tuple[str | None, str | None, bool]:
        """Return (final_text, error, done). Best-effort; may be empty."""
        # Without a JS→Python bridge that returns values reliably across Flet
        # versions, the UI treats web speech as best-effort and falls back.
        return None, None, True


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
    "WebSpeechVoiceEngine",
    "set_engine",
    "get_engine",
    "listen_once",
    "cancel",
]
