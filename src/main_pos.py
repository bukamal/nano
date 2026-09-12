"""Flet entry — نانو نقطة البيع (standalone APK)."""

from __future__ import annotations

import flet as ft
from nano_offline.suite.pos_app import main

ft.app(target=main)
