"""Flet entry — نانو المستودع (standalone APK)."""

from __future__ import annotations

import flet as ft
from nano_offline.suite.inventory_app import main

ft.app(target=main)
