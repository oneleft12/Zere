"""Открытие стандартных папок Windows (порт Windows/FileController.cs)."""

from __future__ import annotations

import os
from pathlib import Path


class FileController:
    @staticmethod
    def _open(path: str) -> None:
        # Process.Start(new ProcessStartInfo { UseShellExecute = true })
        os.startfile(path)

    def open_downloads(self) -> None:
        # Environment.SpecialFolder.UserProfile + "Downloads"
        self._open(str(Path.home() / "Downloads"))

    def open_desktop(self) -> None:
        # Environment.SpecialFolder.Desktop
        self._open(str(Path.home() / "Desktop"))

    def open_documents(self) -> None:
        # Environment.SpecialFolder.MyDocuments
        self._open(str(Path.home() / "Documents"))
