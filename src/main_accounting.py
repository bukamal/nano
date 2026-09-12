"""Flet entry — نانو المحاسبة (standalone APK)."""

from __future__ import annotations

import flet as ft
from nano_offline.suite.accounting_app import main

ft.app(target=main)
