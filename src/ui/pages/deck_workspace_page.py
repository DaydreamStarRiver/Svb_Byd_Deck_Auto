"""统一卡牌库、卡组预设、运行时应用与分享界面。"""

from __future__ import annotations

import base64
import copy
import json
import os
import re
import shutil
import tempfile
import time
import zlib
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional

from PyQt5.QtCore import QMimeData, QSize, Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtGui import QDrag, QIcon
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.config.config_repository import ConfigRepository
from src.config.paths import get_app_root, get_card_cost_dir, get_config_path
from src.ui.card_catalog import (
    CARD_CATEGORIES,
    CardEntry,
    get_card_resource_root,
    load_card_catalog,
    resolve_card_entry,
)
from src.ui.card_library_update import (
    CardLibraryUpdatePlan,
    OfficialCardLibraryClient,
)
from src.ui.deck_qr import (
    DeckQrError,
    decode_qr_bgr,
    decode_qr_path,
    parse_official_deck_payload,
    qimage_to_bgr,
)
from src.ui.deck_io import (
    DECK_SCHEMA_VERSION,
    MAX_CARD_COPIES,
    MAX_DECK_SIZE,
    apply_strategy_config,
    build_card_source_index,
    build_card_variant_index,
    extract_deck_strategy_config,
    extract_strategy_config,
    filter_non_evo_cards,
    normalize_deck_card_records,
    normalize_derived_card_records,
    resolve_runtime_card_paths,
    save_deck_snapshot,
)


CARD_MIME = "application/x-svb-card-key"
ACTIVE_DECK_STATE_VERSION = 1
RUNTIME_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".webp")


def _safe_deck_name(value: str) -> str:
    name = re.sub(r'[<>:"/\\|?*]+', "_", str(value or "").strip())
    return name.strip(" .")[:80]


def _empty_strategy_config() -> Dict[str, Any]:
    return {
        "high_priority_cards": {},
        "evolve_priority_cards": {},
        "strategy": {"effects": {}},
    }


class CardLibraryUpdateWorker(QThread):
    progress_signal = pyqtSignal(str)
    checked_signal = pyqtSignal(object)
    applied_signal = pyqtSignal(object)
    failed_signal = pyqtSignal(str)

    def __init__(
        self,
        *,
        resource_root: str,
        plan: Optional[CardLibraryUpdatePlan] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.resource_root = str(resource_root or "")
        self.plan = plan

    def run(self) -> None:
        client = OfficialCardLibraryClient(
            progress=self.progress_signal.emit,
            cancelled=self.isInterruptionRequested,
        )
        try:
            if self.plan is None:
                self.checked_signal.emit(client.fetch_plan(self.resource_root))
            else:
                self.applied_signal.emit(client.apply_plan(self.plan))
        except Exception as exc:
            self.failed_signal.emit(str(exc))
        finally:
            client.close()


class CardLibraryList(QListWidget):
    viewport_resized = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setViewMode(QListWidget.IconMode)
        self.setResizeMode(QListWidget.Adjust)
        self.setMovement(QListWidget.Static)
        self.setWrapping(True)
        self.setWordWrap(True)
        self.setUniformItemSizes(True)
        self.setIconSize(QSize(92, 126))
        self.setGridSize(QSize(132, 174))
        self.setSpacing(4)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setDragEnabled(True)

    def startDrag(self, supported_actions) -> None:  # noqa: N802 - Qt API 命名
        item = self.currentItem()
        if item is None:
            return
        key = str(item.data(Qt.UserRole) or "")
        if not key:
            return
        if item.icon().isNull():
            source_path = str(item.data(Qt.UserRole + 4) or "")
            if source_path:
                item.setIcon(QIcon(source_path))
        mime = QMimeData()
        mime.setData(CARD_MIME, key.encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.setPixmap(item.icon().pixmap(64, 88))
        drag.exec_(Qt.CopyAction)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API 命名
        super().resizeEvent(event)
        self.viewport_resized.emit()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt API 命名
        super().showEvent(event)
        self.viewport_resized.emit()


class CurrentDeckList(QListWidget):
    card_dropped = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setAlternatingRowColors(True)

    def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt API 命名
        if event.mimeData().hasFormat(CARD_MIME):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # noqa: N802 - Qt API 命名
        if event.mimeData().hasFormat(CARD_MIME):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802 - Qt API 命名
        if event.mimeData().hasFormat(CARD_MIME):
            key = bytes(event.mimeData().data(CARD_MIME)).decode("utf-8", errors="ignore")
            if key:
                self.card_dropped.emit(key)
            event.acceptProposedAction()
            return
        super().dropEvent(event)


class DeckWorkspacePage(QWidget):
    log_requested = pyqtSignal(str)
    active_deck_changed = pyqtSignal(dict)
    data_changed = pyqtSignal()
    device_qr_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_widget = parent
        self.resource_root = get_card_resource_root()
        self.catalog: List[CardEntry] = load_card_catalog(self.resource_root)
        self.entry_by_key = {entry.key: entry for entry in self.catalog}
        self.selected_entries: Dict[str, CardEntry] = {}
        self.selected_counts: Dict[str, int] = {}
        self.derived_entries: Dict[str, CardEntry] = {}
        self.strategy_config: Dict[str, Any] = {}
        self.workspace_deck_file: Optional[str] = None
        self._workspace_is_applied = False
        # 优先级与效果编辑器将其作为当前已应用预设。
        self.current_deck_file: Optional[str] = None
        self._category_filter = "全部"
        self._cost_filter = "全部"
        self._card_set_filter = "全部"
        self._rarity_filter = "全部"
        self._search_filter = ""
        self._library_populated = False
        self._update_worker: Optional[CardLibraryUpdateWorker] = None
        self._checked_update_plan: Optional[CardLibraryUpdatePlan] = None
        self._card_update_result: Optional[Dict[str, Any]] = None
        self._card_update_error = ""
        self._card_update_operation = ""
        self.deck_store = getattr(parent, "deck_store", None)
        self._build_ui()
        self._visible_icon_timer = QTimer(self)
        self._visible_icon_timer.setSingleShot(True)
        self._visible_icon_timer.timeout.connect(self._load_visible_icons)
        self.library_list.verticalScrollBar().valueChanged.connect(
            lambda _value: self._schedule_visible_icon_load()
        )
        self.library_list.viewport_resized.connect(
            self._schedule_visible_icon_load
        )
        if self.deck_store is not None:
            try:
                self.deck_store.decks_changed.connect(self.refresh_saved_decks)
            except Exception:
                pass
        self.catalog_status.setText(f"资源库 {len(self.catalog)} 张卡牌")
        self.visible_count_label.setText("进入页面后加载卡牌图片")
        self.refresh_saved_decks()
        self.load_deck()

    @property
    def selected_cards(self) -> List[str]:
        cards: List[str] = []
        for key, entry in self.selected_entries.items():
            cards.extend([entry.filename] * self.selected_counts.get(key, 1))
        return cards

    @selected_cards.setter
    def selected_cards(self, values: Iterable[str]) -> None:
        entries = []
        for value in list(values or []):
            entry = resolve_card_entry(value, self.catalog, self.resource_root)
            if entry is not None:
                entries.append(entry)
        self._workspace_is_applied = False
        self._set_selected_entries(entries)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 24)
        root.setSpacing(14)
        title_row = QHBoxLayout()
        title = QLabel("卡组工作区")
        title.setObjectName("PageTitle")
        title_row.addWidget(title)
        title_row.addStretch()
        self.catalog_status = QLabel("")
        self.catalog_status.setObjectName("SubtleText")
        title_row.addWidget(self.catalog_status)
        root.addLayout(title_row)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.addTab(self._build_builder_tab(), "卡组构筑")
        self.tabs.addTab(self._build_share_tab(), "分享与导入")
        root.addWidget(self.tabs, 1)

    def _build_builder_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 12, 0, 0)
        layout.setSpacing(12)

        saved_bar = QFrame()
        saved_bar.setObjectName("SurfacePanel")
        saved_layout = QHBoxLayout(saved_bar)
        saved_layout.setContentsMargins(12, 10, 12, 10)
        saved_layout.addWidget(QLabel("已保存卡组"))
        self.saved_decks_combo = QComboBox()
        self.saved_decks_combo.setMinimumWidth(220)
        saved_layout.addWidget(self.saved_decks_combo)
        load_button = QPushButton("加载")
        load_button.setObjectName("SecondaryButton")
        load_button.clicked.connect(self.load_selected_deck)
        delete_button = QPushButton("删除")
        delete_button.setObjectName("DangerGhostButton")
        delete_button.clicked.connect(self.delete_selected_deck)
        saved_layout.addWidget(load_button)
        saved_layout.addWidget(delete_button)
        saved_layout.addStretch()
        refresh_button = QPushButton("重新扫描本地")
        refresh_button.setObjectName("SecondaryButton")
        refresh_button.clicked.connect(self.refresh_catalog)
        saved_layout.addWidget(refresh_button)
        self.card_update_button = QPushButton("检查官方更新")
        self.card_update_button.setObjectName("SecondaryButton")
        self.card_update_button.clicked.connect(self.check_card_library_updates)
        saved_layout.addWidget(self.card_update_button)
        layout.addWidget(saved_bar)

        category_bar = QFrame()
        category_bar.setObjectName("SurfacePanel")
        categories = QHBoxLayout(category_bar)
        categories.setContentsMargins(10, 4, 10, 4)
        self.category_buttons: List[QPushButton] = []
        for category in ("全部",) + tuple(CARD_CATEGORIES):
            button = QPushButton(category)
            button.setObjectName("FilterButton")
            button.setCheckable(True)
            button.setChecked(category == "全部")
            button.clicked.connect(lambda checked=False, value=category: self._set_category_filter(value))
            categories.addWidget(button)
            self.category_buttons.append(button)
        categories.addStretch()
        layout.addWidget(category_bar)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_library_panel())
        splitter.addWidget(self._build_current_panel())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([760, 420])
        layout.addWidget(splitter, 1)
        return page

    def _build_library_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("SurfacePanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        filters = QVBoxLayout()
        filters.setContentsMargins(14, 12, 14, 10)
        cost_row = QHBoxLayout()
        cost_row.addWidget(QLabel("费用"))
        self.cost_buttons: List[QPushButton] = []
        for value in ["全部", "0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10+"]:
            button = QPushButton(value)
            button.setObjectName("FilterButton")
            button.setCheckable(True)
            button.setChecked(value == "全部")
            button.clicked.connect(lambda checked=False, selected=value: self._set_cost_filter(selected))
            cost_row.addWidget(button)
            self.cost_buttons.append(button)
        cost_row.addStretch()
        filters.addLayout(cost_row)
        metadata_row = QHBoxLayout()
        metadata_row.addWidget(QLabel("卡包"))
        self.card_set_combo = QComboBox()
        self.card_set_combo.setMinimumWidth(170)
        self.card_set_combo.currentIndexChanged.connect(
            lambda _index: self._set_card_set_filter(
                str(self.card_set_combo.currentData() or "全部")
            )
        )
        metadata_row.addWidget(self.card_set_combo)
        metadata_row.addWidget(QLabel("稀有度"))
        self.rarity_combo = QComboBox()
        self.rarity_combo.setMinimumWidth(110)
        self.rarity_combo.currentIndexChanged.connect(
            lambda _index: self._set_rarity_filter(
                str(self.rarity_combo.currentData() or "全部")
            )
        )
        metadata_row.addWidget(self.rarity_combo)
        metadata_row.addStretch()
        self.card_update_status = QLabel("更新检查仅在手动点击时联网")
        self.card_update_status.setObjectName("SubtleText")
        metadata_row.addWidget(self.card_update_status)
        filters.addLayout(metadata_row)
        self._populate_metadata_filters()
        search_row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("搜索卡牌名称或 ID...")
        self.search_input.textChanged.connect(self._set_search_filter)
        search_row.addWidget(self.search_input)
        self.visible_count_label = QLabel("")
        self.visible_count_label.setObjectName("SubtleText")
        search_row.addWidget(self.visible_count_label)
        filters.addLayout(search_row)
        layout.addLayout(filters)

        self.library_list = CardLibraryList()
        self.library_list.itemDoubleClicked.connect(lambda item: self.add_card_by_key(item.data(Qt.UserRole)))
        layout.addWidget(self.library_list, 1)

        footer = QHBoxLayout()
        footer.setContentsMargins(12, 8, 12, 10)
        hint = QLabel("双击或拖拽卡牌到右侧当前标签，也可使用添加按钮")
        hint.setObjectName("SubtleText")
        footer.addWidget(hint)
        footer.addStretch()
        add_button = QPushButton("添加到当前标签")
        add_button.setObjectName("PrimaryButton")
        add_button.clicked.connect(self.add_selected_library_card)
        footer.addWidget(add_button)
        layout.addLayout(footer)
        return panel

    def _build_current_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("SurfacePanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)
        self.deck_name_input = QLineEdit("未命名卡组")
        self.deck_name_input.setObjectName("DeckNameInput")
        self.deck_name_input.textChanged.connect(lambda _text: self._emit_active_deck())
        layout.addWidget(self.deck_name_input)
        self.deck_list_tabs = QTabWidget()
        self.deck_list_tabs.setDocumentMode(True)
        self.deck_list_tabs.addTab(self._build_main_deck_tab(), "主卡组")
        self.deck_list_tabs.addTab(self._build_derived_deck_tab(), "衍生物")
        layout.addWidget(self.deck_list_tabs, 1)

        action_row = QHBoxLayout()
        save_button = QPushButton("保存卡组")
        save_button.setObjectName("SecondaryButton")
        save_button.clicked.connect(self.save_current_deck)
        apply_button = QPushButton("应用当前卡组")
        apply_button.setObjectName("PrimaryButton")
        apply_button.clicked.connect(self.apply_current_deck)
        action_row.addWidget(save_button)
        action_row.addWidget(apply_button)
        layout.addLayout(action_row)
        return panel

    def _build_main_deck_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(10)
        count_row = QHBoxLayout()
        self.selected_count_label = QLabel(f"已选择 0 / {MAX_DECK_SIZE} 张 · 0 种")
        self.selected_count_label.setObjectName("SubtleText")
        count_row.addWidget(self.selected_count_label)
        count_row.addStretch()
        clear_button = QPushButton("清空")
        clear_button.setObjectName("DangerGhostButton")
        clear_button.clicked.connect(self.clear_selected_cards)
        count_row.addWidget(clear_button)
        layout.addLayout(count_row)

        self.current_list = CurrentDeckList()
        self.current_list.card_dropped.connect(self.add_card_by_key)
        self.current_list.itemDoubleClicked.connect(lambda _item: self.remove_selected_current_card())
        layout.addWidget(self.current_list, 1)

        quantity_row = QHBoxLayout()
        decrease_button = QPushButton("−")
        decrease_button.setObjectName("SecondaryButton")
        decrease_button.setFixedWidth(38)
        decrease_button.setToolTip("减少一张选中卡牌")
        decrease_button.clicked.connect(self.remove_selected_current_card)
        increase_button = QPushButton("+")
        increase_button.setObjectName("SecondaryButton")
        increase_button.setFixedWidth(38)
        increase_button.setToolTip("增加一张选中卡牌")
        increase_button.clicked.connect(self.increase_selected_current_card)
        remove_button = QPushButton("移除全部")
        remove_button.setObjectName("SecondaryButton")
        remove_button.setToolTip("从卡组中移除选中的全部同名卡牌")
        remove_button.clicked.connect(self.remove_all_selected_current_card)
        quantity_row.addWidget(decrease_button)
        quantity_row.addWidget(increase_button)
        quantity_row.addWidget(remove_button)
        quantity_row.addStretch()
        layout.addLayout(quantity_row)
        return tab

    def _build_derived_deck_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(0, 10, 0, 0)
        layout.setSpacing(10)
        count_row = QHBoxLayout()
        self.derived_count_label = QLabel("已选择 0 种 · 无上限 · 不计入费用分布")
        self.derived_count_label.setObjectName("SubtleText")
        count_row.addWidget(self.derived_count_label)
        count_row.addStretch()
        clear_button = QPushButton("清空")
        clear_button.setObjectName("DangerGhostButton")
        clear_button.clicked.connect(self.clear_derived_cards)
        count_row.addWidget(clear_button)
        layout.addLayout(count_row)

        self.derived_list = CurrentDeckList()
        self.derived_list.card_dropped.connect(self.add_derived_card_by_key)
        self.derived_list.itemDoubleClicked.connect(
            lambda _item: self.remove_selected_derived_card()
        )
        layout.addWidget(self.derived_list, 1)

        action_row = QHBoxLayout()
        remove_button = QPushButton("移除")
        remove_button.setObjectName("SecondaryButton")
        remove_button.clicked.connect(self.remove_selected_derived_card)
        action_row.addWidget(remove_button)
        action_row.addStretch()
        layout.addLayout(action_row)
        return tab

    def _build_share_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 12, 0, 0)
        layout.setSpacing(14)

        generate_panel = QFrame()
        generate_panel.setObjectName("SurfacePanel")
        generate = QVBoxLayout(generate_panel)
        generate.setContentsMargins(18, 16, 18, 18)
        title = QLabel("导出当前工作区")
        title.setObjectName("SectionTitle")
        generate.addWidget(title)
        description = QLabel("分享码包含主卡组、衍生物以及对应策略配置。")
        description.setObjectName("SubtleText")
        generate.addWidget(description)
        self.share_output = QTextEdit()
        self.share_output.setReadOnly(True)
        self.share_output.setMaximumHeight(140)
        generate.addWidget(self.share_output)
        generate_actions = QHBoxLayout()
        generate_button = QPushButton("生成分享码")
        generate_button.setObjectName("PrimaryButton")
        generate_button.clicked.connect(self.generate_share_code)
        copy_button = QPushButton("复制")
        copy_button.setObjectName("SecondaryButton")
        copy_button.clicked.connect(self.copy_share_code)
        generate_actions.addWidget(generate_button)
        generate_actions.addWidget(copy_button)
        generate_actions.addStretch()
        generate.addLayout(generate_actions)
        layout.addWidget(generate_panel)

        import_panel = QFrame()
        import_panel.setObjectName("SurfacePanel")
        apply_layout = QVBoxLayout(import_panel)
        apply_layout.setContentsMargins(18, 16, 18, 18)
        import_title = QLabel("导入分享码或游戏二维码")
        import_title.setObjectName("SectionTitle")
        apply_layout.addWidget(import_title)
        self.share_input = QTextEdit()
        self.share_input.setPlaceholderText(
            "粘贴脚本分享码、官方卡组网址或 2.x.xxxx... 卡组 hash"
        )
        self.share_input.setMaximumHeight(140)
        apply_layout.addWidget(self.share_input)
        source_actions = QHBoxLayout()
        qr_file_button = QPushButton("选择二维码图片")
        qr_file_button.setObjectName("SecondaryButton")
        qr_file_button.clicked.connect(self.import_qr_image)
        clipboard_button = QPushButton("读取剪贴板")
        clipboard_button.setObjectName("SecondaryButton")
        clipboard_button.clicked.connect(self.import_qr_clipboard)
        device_button = QPushButton("读取游戏画面")
        device_button.setObjectName("SecondaryButton")
        device_button.clicked.connect(self.device_qr_requested.emit)
        source_actions.addWidget(qr_file_button)
        source_actions.addWidget(clipboard_button)
        source_actions.addWidget(device_button)
        source_actions.addStretch()
        apply_layout.addLayout(source_actions)
        apply_button = QPushButton("解析并应用")
        apply_button.setObjectName("PrimaryButton")
        apply_button.clicked.connect(self.apply_share_code)
        apply_layout.addWidget(apply_button, 0, Qt.AlignLeft)
        layout.addWidget(import_panel)
        layout.addStretch()
        return page

    def _populate_library(self) -> None:
        self._visible_icon_timer.stop()
        self.library_list.clear()
        initial_icon_count = 16
        for index, entry in enumerate(self.catalog):
            icon = QIcon(entry.source_path) if index < initial_icon_count else QIcon()
            item = QListWidgetItem(icon, f"{entry.cost}  {entry.name}\n{entry.category}")
            item.setSizeHint(self.library_list.gridSize())
            item.setData(Qt.UserRole, entry.key)
            item.setData(Qt.UserRole + 1, entry.category)
            item.setData(Qt.UserRole + 2, entry.cost)
            item.setData(Qt.UserRole + 3, f"{entry.name} {entry.card_id}".casefold())
            item.setData(Qt.UserRole + 4, entry.source_path)
            item.setData(Qt.UserRole + 5, entry.card_set_id or "其他")
            item.setData(Qt.UserRole + 6, entry.rarity_name or "其他")
            item.setToolTip(
                f"{entry.name}\n职业: {entry.category}\n费用: {entry.cost}\n"
                f"卡包: {entry.card_set_name or '其他'}\n"
                f"稀有度: {entry.rarity_name or '其他'}\n卡牌 ID: {entry.card_id}"
            )
            self.library_list.addItem(item)
        self.library_list.doItemsLayout()
        self._library_populated = True
        self.catalog_status.setText(f"资源库 {len(self.catalog)} 张卡牌")
        self._populate_metadata_filters()
        self._apply_library_filters()
        self._schedule_visible_icon_load()

    def ensure_library_populated(self) -> None:
        if not self._library_populated:
            self._populate_library()

    def _schedule_visible_icon_load(self) -> None:
        if self._library_populated:
            self._visible_icon_timer.start(25)

    def _load_visible_icons(self) -> None:
        viewport_rect = self.library_list.viewport().rect().adjusted(
            -self.library_list.gridSize().width(),
            -self.library_list.gridSize().height(),
            self.library_list.gridSize().width(),
            self.library_list.gridSize().height(),
        )
        for index in range(self.library_list.count()):
            item = self.library_list.item(index)
            if item.isHidden() or not item.icon().isNull():
                continue
            item_rect = self.library_list.visualItemRect(item)
            if not item_rect.isValid() or not item_rect.intersects(viewport_rect):
                continue
            source_path = str(item.data(Qt.UserRole + 4) or "")
            if source_path:
                item.setIcon(QIcon(source_path))
        self.library_list.viewport().update()

    def refresh_catalog(self) -> None:
        self.resource_root = get_card_resource_root()
        self.catalog = load_card_catalog(self.resource_root)
        self.entry_by_key = {entry.key: entry for entry in self.catalog}
        self._library_populated = False
        previous = list(self.selected_entries.values())
        previous_counts = dict(self.selected_counts)
        previous_derived = list(self.derived_entries.values())
        self.selected_entries = {}
        self.selected_counts = {}
        self.derived_entries = {}
        for old in previous:
            entry = resolve_card_entry(old.key, self.catalog, self.resource_root)
            if entry is not None:
                self.selected_entries[entry.key] = entry
                self.selected_counts[entry.key] = previous_counts.get(old.key, 1)
        for old in previous_derived:
            entry = resolve_card_entry(old.key, self.catalog, self.resource_root)
            if entry is not None:
                self.derived_entries[entry.key] = entry
        self._populate_library()
        self._refresh_current_list()
        self._log(f"[卡组] 卡牌资源库已刷新，共 {len(self.catalog)} 张")

    def _populate_metadata_filters(self) -> None:
        if not hasattr(self, "card_set_combo") or not hasattr(self, "rarity_combo"):
            return
        current_set = self._card_set_filter
        current_rarity = self._rarity_filter
        sets = {}
        for entry in self.catalog:
            key = str(entry.card_set_id or "其他")
            sets[key] = str(entry.card_set_name or "其他")
        self.card_set_combo.blockSignals(True)
        self.card_set_combo.clear()
        self.card_set_combo.addItem("全部卡包", "全部")
        for set_id, set_name in sorted(
            sets.items(),
            key=lambda item: (
                item[0] == "其他",
                int(item[0]) if item[0].isdigit() else 999999,
                item[1],
            ),
        ):
            self.card_set_combo.addItem(set_name, set_id)
        index = self.card_set_combo.findData(current_set)
        self.card_set_combo.setCurrentIndex(max(0, index))
        self.card_set_combo.blockSignals(False)

        rarities = {
            str(entry.rarity_name or "其他")
            for entry in self.catalog
        }
        rarity_order = {"青铜": 1, "白银": 2, "黄金": 3, "传说": 4, "其他": 99}
        self.rarity_combo.blockSignals(True)
        self.rarity_combo.clear()
        self.rarity_combo.addItem("全部稀有度", "全部")
        for rarity in sorted(rarities, key=lambda value: (rarity_order.get(value, 98), value)):
            self.rarity_combo.addItem(rarity, rarity)
        index = self.rarity_combo.findData(current_rarity)
        self.rarity_combo.setCurrentIndex(max(0, index))
        self.rarity_combo.blockSignals(False)

    def check_card_library_updates(self) -> None:
        if self._is_running():
            QMessageBox.warning(self, "运行中", "请先停止脚本后再更新卡牌库。")
            return
        if self._update_worker is not None and self._update_worker.isRunning():
            return
        self._start_card_update_worker(plan=None)

    def card_update_running(self) -> bool:
        return bool(self._update_worker is not None and self._update_worker.isRunning())

    def request_card_update_stop(self) -> None:
        if self._update_worker is not None and self._update_worker.isRunning():
            self._update_worker.requestInterruption()

    def _start_card_update_worker(
        self,
        *,
        plan: Optional[CardLibraryUpdatePlan],
    ) -> None:
        self._checked_update_plan = None
        self._card_update_result = None
        self._card_update_error = ""
        self._card_update_operation = "apply" if plan is not None else "check"
        self.card_update_button.setEnabled(False)
        self.card_update_status.setText(
            "正在下载并安装更新..." if plan is not None else "正在读取官方卡牌清单..."
        )
        worker = CardLibraryUpdateWorker(
            resource_root=self.resource_root,
            plan=plan,
            parent=self,
        )
        worker.progress_signal.connect(self.card_update_status.setText)
        worker.progress_signal.connect(lambda text: self._log(f"[卡牌库] {text}"))
        worker.checked_signal.connect(self._store_card_update_plan)
        worker.applied_signal.connect(self._store_card_update_result)
        worker.failed_signal.connect(self._store_card_update_error)
        worker.finished.connect(self._finish_card_update_worker)
        self._update_worker = worker
        worker.start()

    def _store_card_update_plan(self, plan: object) -> None:
        if isinstance(plan, CardLibraryUpdatePlan):
            self._checked_update_plan = plan

    def _store_card_update_result(self, result: object) -> None:
        self._card_update_result = dict(result) if isinstance(result, dict) else {}

    def _store_card_update_error(self, message: str) -> None:
        self._card_update_error = str(message or "卡牌库更新失败")

    def _finish_card_update_worker(self) -> None:
        worker = self._update_worker
        operation = self._card_update_operation
        error = self._card_update_error
        plan = self._checked_update_plan
        result = self._card_update_result
        self._update_worker = None
        self.card_update_button.setEnabled(True)
        if worker is not None:
            worker.deleteLater()

        if error:
            self.card_update_status.setText("更新检查失败")
            self._log(f"[卡牌库] {error}")
            QMessageBox.warning(self, "卡牌库更新失败", error)
            return
        if operation == "apply":
            self.refresh_catalog()
            downloaded = int((result or {}).get("downloaded", 0) or 0)
            rows = int((result or {}).get("metadata_rows", 0) or 0)
            self.card_update_status.setText(f"更新完成：{rows} 条元数据")
            QMessageBox.information(
                self,
                "卡牌库更新完成",
                f"已安装 {downloaded} 张新增/变更卡图，卡牌字典共 {rows} 条。",
            )
            return
        if plan is None:
            self.card_update_status.setText("未取得官方差异清单")
            return
        if not plan.has_updates:
            self.card_update_status.setText("本地卡牌库已是最新")
            QMessageBox.information(self, "无需更新", "本地卡牌库已与官方清单一致。")
            return

        new_set_text = "、".join(name for _set_id, name in plan.new_sets) or "无"
        message = (
            f"官方卡牌/异画条目：{plan.remote_card_count}\n"
            f"本地字典条目：{plan.local_row_count}\n"
            f"新增卡包：{new_set_text}\n"
            f"缺失卡图：{len(plan.missing_assets)}\n"
            f"发生变更的卡图：{len(plan.changed_assets)}\n\n"
            "是否下载差异并更新本地卡牌字典？"
        )
        answer = QMessageBox.question(
            self,
            "发现卡牌库更新",
            message,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if answer == QMessageBox.Yes:
            self._start_card_update_worker(plan=plan)
        else:
            self.card_update_status.setText("已取消安装，未修改本地卡牌库")

    def _set_category_filter(self, value: str) -> None:
        self._category_filter = str(value)
        for button in self.category_buttons:
            button.setChecked(button.text() == self._category_filter)
        self._apply_library_filters()

    def _set_cost_filter(self, value: str) -> None:
        self._cost_filter = str(value)
        for button in self.cost_buttons:
            button.setChecked(button.text() == self._cost_filter)
        self._apply_library_filters()

    def _set_card_set_filter(self, value: str) -> None:
        self._card_set_filter = str(value or "全部")
        self._apply_library_filters()

    def _set_rarity_filter(self, value: str) -> None:
        self._rarity_filter = str(value or "全部")
        self._apply_library_filters()

    def _set_search_filter(self, value: str) -> None:
        self._search_filter = str(value or "").strip().casefold()
        self._apply_library_filters()

    def _apply_library_filters(self) -> None:
        visible = 0
        for index in range(self.library_list.count()):
            item = self.library_list.item(index)
            category = str(item.data(Qt.UserRole + 1) or "")
            cost = int(item.data(Qt.UserRole + 2) or 0)
            search_value = str(item.data(Qt.UserRole + 3) or "")
            card_set_id = str(item.data(Qt.UserRole + 5) or "其他")
            rarity_name = str(item.data(Qt.UserRole + 6) or "其他")
            category_ok = self._category_filter == "全部" or category == self._category_filter
            if self._cost_filter == "全部":
                cost_ok = True
            elif self._cost_filter == "10+":
                cost_ok = cost >= 10
            else:
                cost_ok = cost == int(self._cost_filter)
            search_ok = not self._search_filter or self._search_filter in search_value
            card_set_ok = (
                self._card_set_filter == "全部"
                or card_set_id == self._card_set_filter
            )
            rarity_ok = (
                self._rarity_filter == "全部"
                or rarity_name == self._rarity_filter
            )
            hidden = not (
                category_ok and cost_ok and card_set_ok and rarity_ok and search_ok
            )
            item.setHidden(hidden)
            if not hidden:
                visible += 1
        self.visible_count_label.setText(f"显示 {visible} / {self.library_list.count()}")
        self._schedule_visible_icon_load()

    def add_selected_library_card(self) -> None:
        item = self.library_list.currentItem()
        if item is not None:
            self.add_card_by_key(str(item.data(Qt.UserRole) or ""))

    def add_card_by_key(self, key: str) -> None:
        if self.deck_list_tabs.currentIndex() == 1:
            self.add_derived_card_by_key(key)
            return
        entry = self.entry_by_key.get(str(key or ""))
        if entry is None:
            return
        current_count = self.selected_counts.get(entry.key, 0)
        if self._card_copy_group_count(entry.card_id) >= MAX_CARD_COPIES:
            QMessageBox.warning(
                self,
                "达到单卡上限",
                f"每张卡牌最多加入 {MAX_CARD_COPIES} 张。",
            )
            return
        if self._selected_total_count() >= MAX_DECK_SIZE:
            QMessageBox.warning(
                self,
                "达到卡组上限",
                f"卡组最多包含 {MAX_DECK_SIZE} 张卡牌。",
            )
            return
        self.selected_entries[entry.key] = entry
        self.selected_counts[entry.key] = current_count + 1
        self._workspace_is_applied = False
        self._refresh_current_list()

    def add_derived_card_by_key(self, key: str) -> None:
        """向衍生物区添加唯一卡牌；重复添加保持一条记录。"""

        entry = self.entry_by_key.get(str(key or ""))
        if entry is None or entry.key in self.derived_entries:
            return
        self.derived_entries[entry.key] = entry
        self._workspace_is_applied = False
        self._refresh_current_list()

    def increase_selected_current_card(self) -> None:
        item = self.current_list.currentItem()
        if item is not None:
            self.add_card_by_key(str(item.data(Qt.UserRole) or ""))

    def remove_selected_current_card(self) -> None:
        item = self.current_list.currentItem()
        if item is None:
            return
        key = str(item.data(Qt.UserRole) or "")
        count = self.selected_counts.get(key, 0)
        if count > 1:
            self.selected_counts[key] = count - 1
        else:
            self.selected_entries.pop(key, None)
            self.selected_counts.pop(key, None)
        self._workspace_is_applied = False
        self._refresh_current_list()

    def remove_all_selected_current_card(self) -> None:
        item = self.current_list.currentItem()
        if item is None:
            return
        key = str(item.data(Qt.UserRole) or "")
        self.selected_entries.pop(key, None)
        self.selected_counts.pop(key, None)
        self._workspace_is_applied = False
        self._refresh_current_list()

    def remove_selected_derived_card(self) -> None:
        item = self.derived_list.currentItem()
        if item is None:
            return
        self.derived_entries.pop(str(item.data(Qt.UserRole) or ""), None)
        self._workspace_is_applied = False
        self._refresh_current_list()

    def clear_derived_cards(self) -> None:
        if not self.derived_entries:
            return
        self.derived_entries.clear()
        self._workspace_is_applied = False
        self._refresh_current_list()

    def clear_selected_cards(self) -> None:
        if not self.selected_entries:
            return
        self.selected_entries.clear()
        self.selected_counts.clear()
        self.strategy_config = {}
        self.workspace_deck_file = None
        self._workspace_is_applied = False
        self._refresh_current_list()

    def _set_selected_entries(
        self,
        entries: Iterable[CardEntry],
        counts: Optional[Dict[str, int]] = None,
    ) -> None:
        self.selected_entries = {}
        self.selected_counts = {}
        for entry in entries:
            if not isinstance(entry, CardEntry):
                continue
            if counts is None:
                requested = self.selected_counts.get(entry.key, 0) + 1
            else:
                if entry.key in self.selected_entries:
                    continue
                try:
                    requested = int(counts.get(entry.key, 1))
                except (TypeError, ValueError):
                    requested = 1
            remaining = MAX_DECK_SIZE - self._selected_total_count()
            existing_count = self.selected_counts.get(entry.key, 0)
            other_art_count = self._card_copy_group_count(entry.card_id) - existing_count
            group_remaining = MAX_CARD_COPIES - max(0, other_art_count)
            # 替换已有数量时，先把当前条目的旧数量还给总卡组余量。
            deck_remaining = remaining + existing_count
            accepted = min(
                MAX_CARD_COPIES,
                max(0, requested),
                group_remaining,
                deck_remaining,
            )
            if accepted <= 0:
                continue
            self.selected_entries[entry.key] = entry
            self.selected_counts[entry.key] = accepted
        self._refresh_current_list()

    def _set_derived_entries(self, entries: Iterable[CardEntry]) -> None:
        self.derived_entries = {
            entry.key: entry
            for entry in entries
            if isinstance(entry, CardEntry)
        }
        self._refresh_current_list()

    def _selected_total_count(self) -> int:
        return sum(max(0, int(count or 0)) for count in self.selected_counts.values())

    def _card_copy_group_count(self, card_id: str) -> int:
        base_id = str(card_id or "").split("@", 1)[0]
        return sum(
            self.selected_counts.get(key, 1)
            for key, entry in self.selected_entries.items()
            if entry.card_id.split("@", 1)[0] == base_id
        )

    def _deck_card_records(self) -> List[Dict[str, Any]]:
        entries = sorted(
            self.selected_entries.values(),
            key=lambda card: (card.cost, card.category, card.name.casefold(), card.card_id),
        )
        return [
            {
                "card_id": entry.card_id,
                "count": self.selected_counts.get(entry.key, 1),
            }
            for entry in entries
        ]

    def _derived_card_records(self) -> List[Dict[str, str]]:
        entries = sorted(
            self.derived_entries.values(),
            key=lambda card: (card.cost, card.category, card.name.casefold(), card.card_id),
        )
        return [{"card_id": entry.card_id} for entry in entries]

    def _refresh_current_list(self) -> None:
        current_item = self.current_list.currentItem()
        current_key = (
            str(current_item.data(Qt.UserRole) or "")
            if current_item is not None
            else ""
        )
        self.current_list.clear()
        for entry in sorted(
            self.selected_entries.values(),
            key=lambda card: (card.cost, card.category, card.name.casefold(), card.card_id),
        ):
            count = self.selected_counts.get(entry.key, 1)
            item = QListWidgetItem(
                QIcon(entry.source_path),
                f"{entry.cost:>2}   {entry.name}  ·  {entry.category}    ×{count}",
            )
            item.setData(Qt.UserRole, entry.key)
            item.setData(Qt.UserRole + 1, count)
            item.setToolTip(
                f"{entry.name}\n卡牌 ID: {entry.card_id}\n数量: {count}\n{entry.relative_path}"
            )
            self.current_list.addItem(item)
            if entry.key == current_key:
                self.current_list.setCurrentItem(item)
        derived_item = self.derived_list.currentItem()
        derived_key = (
            str(derived_item.data(Qt.UserRole) or "")
            if derived_item is not None
            else ""
        )
        self.derived_list.clear()
        for entry in sorted(
            self.derived_entries.values(),
            key=lambda card: (card.cost, card.category, card.name.casefold(), card.card_id),
        ):
            item = QListWidgetItem(
                QIcon(entry.source_path),
                f"{entry.cost:>2}   {entry.name}  ·  {entry.category}",
            )
            item.setData(Qt.UserRole, entry.key)
            item.setToolTip(
                f"{entry.name}\n卡牌 ID: {entry.card_id}\n衍生物模板\n{entry.relative_path}"
            )
            self.derived_list.addItem(item)
            if entry.key == derived_key:
                self.derived_list.setCurrentItem(item)
        total = self._selected_total_count()
        self.selected_count_label.setText(
            f"已选择 {total} / {MAX_DECK_SIZE} 张 · {len(self.selected_entries)} 种"
        )
        self.derived_count_label.setText(
            f"已选择 {len(self.derived_entries)} 种 · 无上限 · 不计入费用分布"
        )
        self._emit_active_deck()
        self.data_changed.emit()

    def _active_deck_payload(self) -> Dict[str, Any]:
        costs = Counter()
        for key, entry in self.selected_entries.items():
            costs[entry.cost] += self.selected_counts.get(key, 1)
        return {
            "name": self.deck_name_input.text().strip() or "未命名卡组",
            "count": self._selected_total_count(),
            "distinct_count": len(self.selected_entries),
            "derived_count": len(self.derived_entries),
            "costs": dict(costs),
            "file": self.workspace_deck_file,
            "applied": self._workspace_is_applied,
        }

    def active_deck_summary(self) -> Dict[str, Any]:
        return dict(self._active_deck_payload())

    def workspace_is_applied(self) -> bool:
        return bool(self._workspace_is_applied)

    def _emit_active_deck(self) -> None:
        self.active_deck_changed.emit(self._active_deck_payload())

    def refresh_saved_decks(self, *args, **kwargs) -> None:
        current = self.workspace_deck_file
        self.saved_decks_combo.blockSignals(True)
        self.saved_decks_combo.clear()
        self.saved_decks_combo.addItem("选择已保存卡组...", None)
        decks = []
        if self.deck_store is not None:
            try:
                decks = self.deck_store.get_decks()
            except Exception:
                decks = []
        for display_name, filename in decks:
            self.saved_decks_combo.addItem(display_name, filename)
        if current:
            index = self.saved_decks_combo.findData(current)
            if index >= 0:
                self.saved_decks_combo.setCurrentIndex(index)
        self.saved_decks_combo.blockSignals(False)

    def save_current_deck(self) -> None:
        if self._is_running():
            QMessageBox.warning(self, "运行中", "请先停止脚本后再保存卡组。")
            return
        name = _safe_deck_name(self.deck_name_input.text())
        if not name:
            QMessageBox.warning(self, "缺少名称", "请输入卡组名称。")
            return
        if not self.selected_entries:
            QMessageBox.warning(self, "卡组为空", "请先选择卡牌。")
            return
        try:
            previous_workspace_file = self.workspace_deck_file
            strategy_config: Optional[Dict[str, Any]] = None
            if previous_workspace_file:
                try:
                    strategy_config = self._read_saved_strategy(previous_workspace_file)
                except Exception:
                    strategy_config = copy.deepcopy(self.strategy_config)
            elif self.strategy_config:
                strategy_config = copy.deepcopy(self.strategy_config)

            if self._workspace_is_applied:
                strategy_config = self._current_config_strategy(
                    require_valid=True
                )

            path = save_deck_snapshot(
                deck_name=name,
                cards=self._deck_card_records(),
                derived_cards=self._derived_card_records(),
                decks_dir=os.path.join(get_app_root(), "saved_decks"),
                config_path=get_config_path(),
                strategy_config=strategy_config,
            )
            self.workspace_deck_file = os.path.basename(path)
            if self._workspace_is_applied:
                self.current_deck_file = self.workspace_deck_file
            self.strategy_config = self._read_saved_strategy(self.workspace_deck_file)
            if self.deck_store is not None:
                self.deck_store.refresh()
            self._emit_active_deck()
            self._log(f"[卡组] 已保存卡组 '{name}'")
            QMessageBox.information(self, "保存成功", f"卡组 '{name}' 已保存。")
        except Exception as exc:
            QMessageBox.warning(self, "保存失败", str(exc))
            self._log(f"[卡组] 保存失败: {exc}")

    def save_named_deck(self, deck_name: str) -> None:
        self.deck_name_input.setText(str(deck_name or ""))
        self.save_current_deck()

    def load_selected_deck(self) -> None:
        filename = self.saved_decks_combo.currentData()
        if not filename:
            QMessageBox.warning(self, "未选择卡组", "请选择要加载的卡组。")
            return
        self._load_deck_file(str(filename))

    def _load_deck_file(self, filename: str) -> None:
        path = os.path.join(get_app_root(), "saved_decks", os.path.basename(filename))
        try:
            with open(path, "r", encoding="utf-8") as stream:
                data = json.load(stream)
            entries, counts, missing = self._entries_from_references(
                data.get("cards") or []
            )
            derived_entries, missing_derived = self._derived_entries_from_references(
                data.get("derived_cards") or []
            )
            self.workspace_deck_file = os.path.basename(filename)
            self.strategy_config = extract_deck_strategy_config(data)
            self._workspace_is_applied = False
            self.deck_name_input.setText(str(data.get("name") or os.path.splitext(filename)[0]))
            self._set_selected_entries(entries, counts)
            self._set_derived_entries(derived_entries)
            self._log(f"[卡组] 已载入卡组 '{self.deck_name_input.text()}'")
            if missing:
                self._log(f"[卡组] {len(missing)} 张卡牌在资源库中未找到")
            if missing_derived:
                self._log(f"[卡组] {len(missing_derived)} 个衍生物在资源库中未找到")
        except Exception as exc:
            QMessageBox.warning(self, "加载失败", str(exc))
            self._log(f"[卡组] 加载失败: {exc}")

    def delete_selected_deck(self) -> None:
        filename = self.saved_decks_combo.currentData()
        if not filename:
            QMessageBox.warning(self, "未选择卡组", "请选择要删除的卡组。")
            return
        if self._is_running():
            QMessageBox.warning(self, "运行中", "请先停止脚本后再删除卡组。")
            return
        name = self.saved_decks_combo.currentText()
        answer = QMessageBox.question(
            self,
            "删除卡组",
            f"确定删除 '{name}'？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            path = os.path.join(get_app_root(), "saved_decks", os.path.basename(str(filename)))
            if os.path.exists(path):
                os.remove(path)
            if self.workspace_deck_file == filename:
                self.workspace_deck_file = None
            if self.current_deck_file == filename:
                self.current_deck_file = None
            if self.deck_store is not None:
                self.deck_store.refresh()
            self._log(f"[卡组] 已删除卡组 '{name}'")
        except Exception as exc:
            QMessageBox.warning(self, "删除失败", str(exc))

    def apply_current_deck(self) -> bool:
        if self._is_running():
            QMessageBox.warning(self, "运行中", "请先停止脚本后再应用卡组。")
            return False
        if not self.selected_entries:
            QMessageBox.warning(self, "卡组为空", "请先选择或加载卡组。")
            return False
        try:
            if self.workspace_deck_file:
                loaded_strategy = self._read_saved_strategy(
                    self.workspace_deck_file
                )
                self.strategy_config = loaded_strategy or _empty_strategy_config()
            elif self._workspace_is_applied:
                self.strategy_config = self._current_config_strategy(
                    require_valid=True
                )
            applied_entries = {
                entry.key: entry
                for entry in (
                    *self.selected_entries.values(),
                    *self.derived_entries.values(),
                )
            }
            copied, missing = self._apply_entries(
                applied_entries.values(), self.strategy_config
            )
            self.current_deck_file = self.workspace_deck_file
            self._workspace_is_applied = True
            self._persist_active_deck_snapshot()
            self._notify_related_pages()
            self._emit_active_deck()
            self._log(
                f"[卡组] 已应用 {self._selected_total_count()} 张卡牌、"
                f"{len(self.selected_entries)} 种主卡、{len(self.derived_entries)} 种衍生物，"
                f"复制 {copied} 个运行模板"
            )
            if missing:
                self._log(f"[卡组] 未找到 {len(missing)} 张卡牌: {', '.join(missing[:5])}")
            QMessageBox.information(self, "应用成功", "当前卡组已应用到识别模板和策略配置。")
            return True
        except Exception as exc:
            QMessageBox.warning(self, "应用失败", str(exc))
            self._log(f"[卡组] 应用失败: {exc}")
            return False

    def _apply_entries(
        self,
        entries: Iterable[CardEntry],
        strategy_config: Optional[Dict[str, Any]] = None,
    ) -> tuple[int, List[str]]:
        target_dir = get_card_cost_dir(ensure=False)
        exact_index, stem_index = build_card_source_index(self.resource_root)
        variant_index = build_card_variant_index(self.resource_root)
        sources: List[str] = []
        destinations: Dict[str, str] = {}
        missing: List[str] = []
        for entry in entries:
            runtime_paths = resolve_runtime_card_paths(
                self.resource_root,
                entry.filename,
                exact_index=exact_index,
                stem_index=stem_index,
                variant_index=variant_index,
            )
            if not runtime_paths:
                missing.append(entry.name)
                continue
            for source in runtime_paths:
                if not os.path.isfile(source):
                    missing.append(entry.name)
                    continue

                destination_name = os.path.basename(source)
                existing_source = destinations.get(destination_name.casefold())
                if existing_source and os.path.normcase(existing_source) != os.path.normcase(source):
                    raise RuntimeError(f"卡牌模板文件名冲突: {destination_name}")
                destinations[destination_name.casefold()] = source
                sources.append(source)

        if missing:
            unique_missing = list(dict.fromkeys(missing))
            raise FileNotFoundError(
                "以下卡牌模板不完整，已保留当前运行卡组: "
                + ", ".join(unique_missing[:8])
            )

        parent_dir = os.path.dirname(target_dir)
        os.makedirs(parent_dir, exist_ok=True)
        stage_dir = tempfile.mkdtemp(prefix=".card-cost-stage-", dir=parent_dir)
        backup_dir: Optional[str] = None
        copied = 0
        try:
            copied_names = set()
            for source in sources:
                destination_name = os.path.basename(source)
                destination_key = destination_name.casefold()
                if destination_key in copied_names:
                    continue
                shutil.copy2(source, os.path.join(stage_dir, destination_name))
                copied_names.add(destination_key)
                copied += 1

            if os.path.exists(target_dir):
                if not os.path.isdir(target_dir):
                    raise RuntimeError(f"卡牌模板路径不是目录: {target_dir}")
                backup_dir = tempfile.mkdtemp(
                    prefix=".card-cost-backup-", dir=parent_dir
                )
                os.rmdir(backup_dir)
                os.replace(target_dir, backup_dir)

            os.replace(stage_dir, target_dir)
            stage_dir = ""

            try:
                if isinstance(strategy_config, dict) and strategy_config:
                    repo = ConfigRepository(get_config_path())
                    existing, _, parse_error = repo.load_existing(
                        allow_default_on_error=False
                    )
                    if existing is None:
                        raise RuntimeError(
                            "config.json 解析失败，已拒绝应用卡组: "
                            + str(parse_error or "未知错误")
                        )
                    merged = apply_strategy_config(
                        existing, strategy_config=strategy_config
                    )
                    result = repo.replace_with_snapshot(merged, indent=4, ensure_ascii=False)
                    if not result.ok:
                        raise RuntimeError(result.error or "策略配置写入失败")
            except Exception:
                shutil.rmtree(target_dir, ignore_errors=True)
                if backup_dir and os.path.exists(backup_dir):
                    os.replace(backup_dir, target_dir)
                    backup_dir = None
                raise

            if backup_dir and os.path.exists(backup_dir):
                shutil.rmtree(backup_dir, ignore_errors=True)
                backup_dir = None
        except Exception:
            if stage_dir and os.path.exists(stage_dir):
                shutil.rmtree(stage_dir, ignore_errors=True)
            if backup_dir and os.path.exists(backup_dir) and not os.path.exists(target_dir):
                os.replace(backup_dir, target_dir)
            raise

        return copied, []

    @staticmethod
    def _runtime_template_names(card_dir: str) -> List[str]:
        if not os.path.isdir(card_dir):
            return []
        return sorted(
            filename
            for filename in os.listdir(card_dir)
            if os.path.isfile(os.path.join(card_dir, filename))
            and filename.casefold().endswith(RUNTIME_IMAGE_EXTENSIONS)
        )

    def _persist_active_deck_snapshot(self) -> bool:
        """保存只供界面重启恢复使用的已应用卡组快照。"""

        card_dir = get_card_cost_dir(ensure=False)
        payload = {
            "version": ACTIVE_DECK_STATE_VERSION,
            "deck_schema_version": DECK_SCHEMA_VERSION,
            "name": self.deck_name_input.text().strip() or "未命名卡组",
            "cards": self._deck_card_records(),
            "derived_cards": self._derived_card_records(),
            "deck_file": self.workspace_deck_file,
            "runtime_templates": self._runtime_template_names(card_dir),
        }
        result = ConfigRepository(get_config_path()).update(
            {"ui": {"active_deck_snapshot": payload}},
            refuse_on_parse_error=True,
            indent=4,
            ensure_ascii=False,
        )
        if not result.ok:
            self._log(f"[卡组] 界面恢复快照保存失败: {result.error or '未知错误'}")
        return bool(result.ok)

    def _restore_active_deck_snapshot(self, card_dir: str) -> bool:
        """在运行模板未变化时恢复主卡数量与衍生物分区。"""

        config, _, _error = ConfigRepository(get_config_path()).load_existing(
            allow_default_on_error=False
        )
        if not isinstance(config, dict):
            return False
        ui_config = config.get("ui", {})
        snapshot = (
            ui_config.get("active_deck_snapshot", {})
            if isinstance(ui_config, dict)
            else {}
        )
        if not isinstance(snapshot, dict) or int(snapshot.get("version", 0) or 0) != ACTIVE_DECK_STATE_VERSION:
            return False

        expected_templates = sorted(
            os.path.basename(str(filename)).casefold()
            for filename in list(snapshot.get("runtime_templates") or [])
            if str(filename or "").strip()
        )
        actual_templates = sorted(
            filename.casefold() for filename in self._runtime_template_names(card_dir)
        )
        if not expected_templates or expected_templates != actual_templates:
            return False

        entries, counts, missing = self._entries_from_references(
            snapshot.get("cards") or []
        )
        derived_entries, missing_derived = self._derived_entries_from_references(
            snapshot.get("derived_cards") or []
        )
        if not entries or missing or missing_derived:
            return False

        deck_file = str(snapshot.get("deck_file") or "").strip()
        self.workspace_deck_file = os.path.basename(deck_file) if deck_file else None
        self.current_deck_file = self.workspace_deck_file
        self.strategy_config = self._current_config_strategy(entries)
        self._workspace_is_applied = True
        self.deck_name_input.setText(
            str(snapshot.get("name") or "未命名卡组")
        )
        self._set_selected_entries(entries, counts)
        self._set_derived_entries(derived_entries)
        return True

    def _runtime_names_for_entries(
        self,
        entries: Iterable[CardEntry],
        *,
        exact_index=None,
        stem_index=None,
        variant_index=None,
    ) -> set[str]:
        if exact_index is None or stem_index is None:
            exact_index, stem_index = build_card_source_index(self.resource_root)
        if variant_index is None:
            variant_index = build_card_variant_index(self.resource_root)
        names: set[str] = set()
        for entry in entries:
            paths = resolve_runtime_card_paths(
                self.resource_root,
                entry.filename,
                exact_index=exact_index,
                stem_index=stem_index,
                variant_index=variant_index,
            )
            if not paths:
                return set()
            names.update(os.path.basename(path).casefold() for path in paths)
        return names

    def _restore_matching_saved_deck(self, card_dir: str) -> bool:
        """旧版本没有快照时，按运行模板唯一匹配一个已保存卡组。"""

        actual_templates = {
            filename.casefold() for filename in self._runtime_template_names(card_dir)
        }
        if not actual_templates:
            return False
        decks_dir = os.path.join(get_app_root(), "saved_decks")
        if not os.path.isdir(decks_dir):
            return False

        exact_index, stem_index = build_card_source_index(self.resource_root)
        variant_index = build_card_variant_index(self.resource_root)
        matches = []
        for filename in sorted(os.listdir(decks_dir)):
            if not filename.casefold().endswith(".json"):
                continue
            path = os.path.join(decks_dir, filename)
            try:
                with open(path, "r", encoding="utf-8-sig") as stream:
                    data = json.load(stream)
                if not isinstance(data, dict):
                    continue
                entries, counts, missing = self._entries_from_references(
                    data.get("cards") or []
                )
                derived_entries, missing_derived = self._derived_entries_from_references(
                    data.get("derived_cards") or []
                )
                if not entries or missing or missing_derived:
                    continue
                unique_entries = {
                    entry.key: entry
                    for entry in (*entries, *derived_entries)
                }
                expected_templates = self._runtime_names_for_entries(
                    unique_entries.values(),
                    exact_index=exact_index,
                    stem_index=stem_index,
                    variant_index=variant_index,
                )
                if expected_templates == actual_templates:
                    matches.append(
                        (filename, data, entries, counts, derived_entries)
                    )
            except Exception:
                continue

        if len(matches) != 1:
            return False
        filename, data, entries, counts, derived_entries = matches[0]
        self.workspace_deck_file = filename
        self.current_deck_file = filename
        self.strategy_config = self._current_config_strategy(entries)
        self._workspace_is_applied = True
        self.deck_name_input.setText(
            str(data.get("name") or os.path.splitext(filename)[0])
        )
        self._set_selected_entries(entries, counts)
        self._set_derived_entries(derived_entries)
        self._persist_active_deck_snapshot()
        return True

    def load_deck(self) -> None:
        card_dir = get_card_cost_dir(ensure=False)
        if not os.path.isdir(card_dir):
            self.workspace_deck_file = self.current_deck_file
            self.strategy_config = self._current_config_strategy([])
            self._workspace_is_applied = True
            self._set_selected_entries([])
            self._set_derived_entries([])
            return
        if self._restore_active_deck_snapshot(card_dir):
            return
        if self._restore_matching_saved_deck(card_dir):
            return
        entries: List[CardEntry] = []
        for filename in filter_non_evo_cards(os.listdir(card_dir)):
            entry = resolve_card_entry(filename, self.catalog, self.resource_root)
            if entry is not None:
                entries.append(entry)
        self.workspace_deck_file = self.current_deck_file
        self.strategy_config = self._current_config_strategy(entries)
        self._workspace_is_applied = True
        self._set_selected_entries(entries)
        self._set_derived_entries([])

    def refresh_preview(self) -> None:
        self.load_deck()

    def generate_share_code(self) -> None:
        if not self.selected_entries:
            QMessageBox.warning(self, "卡组为空", "请先选择卡牌。")
            return
        if self._workspace_is_applied:
            self.strategy_config = self._current_config_strategy()
        elif self.workspace_deck_file:
            self.strategy_config = self._read_saved_strategy(
                self.workspace_deck_file
            )
        elif not self.strategy_config:
            self.strategy_config = self._current_config_strategy()
        data = {
            "version": DECK_SCHEMA_VERSION,
            "cards": self._deck_card_records(),
            "derived_cards": self._derived_card_records(),
            "strategy_config": dict(self.strategy_config or {}),
            "timestamp": int(time.time()),
        }
        encoded = base64.b64encode(
            zlib.compress(json.dumps(data, ensure_ascii=False).encode("utf-8"))
        ).decode("ascii")
        self.share_output.setPlainText(encoded)
        self._log("[分享] 分享码已生成")

    def copy_share_code(self) -> None:
        text = self.share_output.toPlainText().strip()
        if not text:
            return
        QApplication.clipboard().setText(text)
        self._log("[分享] 分享码已复制到剪贴板")

    def import_qr_image(self) -> None:
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "选择游戏生成的卡组二维码",
            "",
            "图片文件 (*.png *.jpg *.jpeg *.webp *.bmp);;所有文件 (*)",
        )
        if not path:
            return
        try:
            payload = decode_qr_path(path)
            self._load_qr_payload(payload, source_label=os.path.basename(path))
        except Exception as exc:
            QMessageBox.warning(self, "二维码读取失败", str(exc))

    def import_qr_clipboard(self) -> None:
        clipboard = QApplication.clipboard()
        mime = clipboard.mimeData()
        try:
            if mime is not None and mime.hasImage():
                image = clipboard.image()
                payload = decode_qr_bgr(qimage_to_bgr(image))
                self._load_qr_payload(payload, source_label="剪贴板图片")
                return
            text = clipboard.text().strip()
            if not text:
                raise DeckQrError("剪贴板中没有二维码图片或卡组网址")
            self._load_qr_payload(text, source_label="剪贴板文本")
        except Exception as exc:
            QMessageBox.warning(self, "剪贴板导入失败", str(exc))

    def import_qr_qimage(self, image: object) -> None:
        """由主窗口的设备截图线程回传游戏画面。"""

        try:
            payload = decode_qr_bgr(qimage_to_bgr(image))
            self._load_qr_payload(payload, source_label="当前游戏画面")
        except Exception as exc:
            QMessageBox.warning(self, "游戏二维码读取失败", str(exc))

    def _load_qr_payload(self, payload: str, *, source_label: str) -> None:
        parsed = parse_official_deck_payload(payload, require_full_deck=True)
        self.share_input.setPlainText(parsed.source or str(payload or ""))
        self._log(
            f"[二维码] 已从{source_label}读取官方构筑："
            f"{len(parsed.card_ids)} 张、{len(parsed.records)} 种"
        )
        self.apply_share_code()

    def apply_share_code(self) -> None:
        if self._is_running():
            QMessageBox.warning(self, "运行中", "请先停止脚本后再应用分享码。")
            return
        text = re.sub(r"#.*?#", "", self.share_input.toPlainText()).strip()
        if not text:
            QMessageBox.warning(self, "分享码为空", "请输入有效的分享码。")
            return
        legacy_error: Optional[Exception] = None
        try:
            compact = re.sub(r"\s+", "", text)
            compressed = base64.b64decode(compact.encode("ascii"), validate=True)
            data = json.loads(zlib.decompress(compressed).decode("utf-8"))
            if int(data.get("version", 0)) not in range(1, DECK_SCHEMA_VERSION + 1):
                raise ValueError("不支持的分享码版本")
            entries, counts, _missing = self._entries_from_references(
                data.get("cards") or []
            )
            derived_entries, _missing_derived = self._derived_entries_from_references(
                data.get("derived_cards") or []
            )
            strategy_config = data.get("strategy_config")
            if not isinstance(strategy_config, dict) and isinstance(data.get("config"), dict):
                strategy_config = extract_strategy_config(
                    data["config"],
                    cards=list(data.get("cards") or []),
                )
            self.strategy_config = strategy_config if isinstance(strategy_config, dict) else {}
        except Exception as exc:
            legacy_error = exc
            try:
                parsed = parse_official_deck_payload(text, require_full_deck=True)
                entries, counts, missing = self._entries_from_references(parsed.records)
                if missing:
                    raise DeckQrError(
                        "本地卡牌库缺少二维码中的卡牌: " + ", ".join(missing[:8])
                    )
                derived_entries = []
                self.strategy_config = {}
            except Exception as qr_exc:
                self._log(f"[分享] 压缩分享码解析失败: {legacy_error}")
                QMessageBox.warning(self, "解析失败", str(qr_exc))
                return
        if not entries:
            QMessageBox.warning(self, "解析失败", "分享码中没有可用卡牌。")
            return
        self.workspace_deck_file = None
        self._workspace_is_applied = False
        prefix = "二维码卡组" if legacy_error is not None else "分享卡组"
        self.deck_name_input.setText(f"{prefix}_{time.strftime('%Y%m%d_%H%M%S')}")
        self._set_selected_entries(entries, counts)
        self._set_derived_entries(derived_entries)
        if legacy_error is not None:
            try:
                self.strategy_config = _empty_strategy_config()
                path = save_deck_snapshot(
                    deck_name=self.deck_name_input.text().strip(),
                    cards=self._deck_card_records(),
                    derived_cards=[],
                    decks_dir=os.path.join(get_app_root(), "saved_decks"),
                    config_path=get_config_path(),
                    # 官方二维码只有构筑，不含自动出牌策略；禁止继承上一副卡组。
                    strategy_config=self.strategy_config,
                )
                self.workspace_deck_file = os.path.basename(path)
                if self.deck_store is not None:
                    self.deck_store.refresh()
                self._log(
                    f"[二维码] 已保存本地构筑 '{self.deck_name_input.text()}'，"
                    "策略保持为空，等待用户配置"
                )
            except Exception as exc:
                QMessageBox.warning(self, "二维码卡组保存失败", str(exc))
                self._log(f"[二维码] 保存本地构筑失败: {exc}")
                return
        if self.apply_current_deck():
            self.tabs.setCurrentIndex(0)

    def _entries_from_references(
        self,
        references: Iterable[Any],
    ) -> tuple[List[CardEntry], Dict[str, int], List[str]]:
        result: List[CardEntry] = []
        counts: Dict[str, int] = {}
        missing: List[str] = []
        total = 0
        copy_groups: Dict[str, int] = {}
        for record in normalize_deck_card_records(references):
            reference = str(record.get("card_id") or "")
            count = int(record.get("count") or 0)
            if count > MAX_CARD_COPIES:
                raise ValueError(
                    f"卡牌 {reference} 数量为 {count}，单卡最多 {MAX_CARD_COPIES} 张"
                )
            if total + count > MAX_DECK_SIZE:
                raise ValueError(f"卡组超过 {MAX_DECK_SIZE} 张上限")
            total += count
            entry = resolve_card_entry(reference, self.catalog, self.resource_root)
            if entry is None:
                missing.append(reference)
                continue
            base_id = entry.card_id.split("@", 1)[0]
            copy_groups[base_id] = copy_groups.get(base_id, 0) + count
            if copy_groups[base_id] > MAX_CARD_COPIES:
                raise ValueError(
                    f"卡牌 {base_id} 及其异画合计超过 {MAX_CARD_COPIES} 张上限"
                )
            if entry.key not in counts:
                result.append(entry)
                counts[entry.key] = 0
            counts[entry.key] += count
            if counts[entry.key] > MAX_CARD_COPIES:
                raise ValueError(
                    f"卡牌 {entry.name} 数量超过 {MAX_CARD_COPIES} 张上限"
                )
        return result, counts, missing

    def _derived_entries_from_references(
        self,
        references: Iterable[Any],
    ) -> tuple[List[CardEntry], List[str]]:
        result: List[CardEntry] = []
        missing: List[str] = []
        seen = set()
        for record in normalize_derived_card_records(references):
            reference = str(record.get("card_id") or "")
            entry = resolve_card_entry(reference, self.catalog, self.resource_root)
            if entry is None:
                missing.append(reference)
                continue
            if entry.key in seen:
                continue
            seen.add(entry.key)
            result.append(entry)
        return result, missing

    def _read_saved_strategy(self, filename: str) -> Dict[str, Any]:
        path = os.path.join(
            get_app_root(), "saved_decks", os.path.basename(str(filename or ""))
        )
        with open(path, "r", encoding="utf-8") as stream:
            return extract_deck_strategy_config(json.load(stream))

    def _current_config_strategy(
        self,
        entries: Optional[Iterable[CardEntry]] = None,
        *,
        require_valid: bool = False,
    ) -> Dict[str, Any]:
        repo = ConfigRepository(get_config_path())
        config, _, parse_error = repo.load_existing(allow_default_on_error=False)
        if config is None:
            if require_valid:
                raise RuntimeError(
                    "config.json 解析失败: " + str(parse_error or "未知错误")
                )
            return copy.deepcopy(self.strategy_config)
        cards = [
            entry.filename
            for entry in (entries if entries is not None else self.selected_entries.values())
            if isinstance(entry, CardEntry)
        ]
        return extract_strategy_config(config, cards=cards)

    def _notify_related_pages(self) -> None:
        parent = self.parent_widget
        try:
            page = getattr(parent, "card_priority_page", None)
            if page is not None:
                page.refresh_card_priority()
        except Exception:
            pass
        try:
            page = getattr(parent, "config_page", None)
            if page is not None:
                page.refresh_config_display()
        except Exception:
            pass

    def _is_running(self) -> bool:
        try:
            return bool(getattr(self.parent_widget, "is_script_running")())
        except Exception:
            return False

    def _log(self, message: str) -> None:
        self.log_requested.emit(str(message))
