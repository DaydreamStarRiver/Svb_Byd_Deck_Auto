"""Tabbed deck feature center: construction, strategy and rotation."""

from __future__ import annotations

from typing import Dict

from PyQt5.QtWidgets import QTabWidget, QVBoxLayout, QWidget


class DeckCenterPage(QWidget):
    def __init__(
        self,
        *,
        workspace_page: QWidget,
        priority_page: QWidget,
        rotation_page: QWidget,
        parent=None,
    ):
        super().__init__(parent)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("DeckCenterTabs")
        self.tabs.setDocumentMode(True)
        self._sections: Dict[str, QWidget] = {
            "deck": workspace_page,
            "cards": priority_page,
            "rotation": rotation_page,
        }
        self.tabs.addTab(workspace_page, "卡组构筑")
        self.tabs.addTab(priority_page, "卡牌策略")
        self.tabs.addTab(rotation_page, "自动轮换")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.tabs)
        self.tabs.currentChanged.connect(self._refresh_current)

    def select_section(self, section: str) -> None:
        page = self._sections.get(str(section or ""), self._sections["deck"])
        self.tabs.setCurrentWidget(page)
        self._refresh_page(section, page)

    def _refresh_current(self, _index: int) -> None:
        page = self.tabs.currentWidget()
        for section, candidate in self._sections.items():
            if candidate is page:
                self._refresh_page(section, candidate)
                return

    @staticmethod
    def _refresh_page(section: str, page: QWidget) -> None:
        try:
            if section == "deck":
                page.ensure_library_populated()
                page.refresh_saved_decks()
            elif section == "cards":
                page.refresh_card_priority()
            elif section == "rotation":
                page.refresh_config_display()
        except Exception:
            pass
