from __future__ import annotations

import json
from typing import Any, Iterable

from flet.core.control import Control


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
        )
        if str(raw).startswith("error:"):
            raise RuntimeError(str(raw)[6:])
        return raw == "ok"

    async def print_html(self, html: str, *, name: str = "nano-report") -> bool:
        raw = await self.invoke_method_async("print_html", {"html": html, "name": name})
        if str(raw).startswith("error:"):
            raise RuntimeError(str(raw)[6:])
        return raw == "ok"

    async def create_pdf(self, html: str, *, filename: str = "nano-report.pdf") -> str:
        if not filename.lower().endswith(".pdf"):
            filename += ".pdf"
        raw = await self.invoke_method_async("create_pdf", {"html": html, "filename": filename})
        if str(raw).startswith("error:"):
            raise RuntimeError(str(raw)[6:])
        path = str(raw or "").strip()
        if not path:
            raise RuntimeError("تعذر إنشاء ملف PDF")
        return path

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
