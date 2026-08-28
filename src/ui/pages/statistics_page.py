"""展示持久化与实时对战指标的深色统计页面。"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Sequence

from PyQt5.QtCore import QRectF, QSize, Qt
from PyQt5.QtGui import QColor, QFont, QPainter, QPen
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.ui.statistics import (
    DailyBattleCount,
    PathLike,
    StatisticsSnapshot,
    load_statistics,
)


class DailyBattleChart(QWidget):
    """无额外依赖的轻量每日对战次数柱状图。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data: Sequence[DailyBattleCount] = ()
        self.setMinimumHeight(250)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def sizeHint(self) -> QSize:
        return QSize(720, 280)

    def set_data(self, data: Sequence[DailyBattleCount]) -> None:
        self._data = tuple(data)
        self.update()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        bounds = self.rect()
        if bounds.width() < 120 or bounds.height() < 120:
            return

        left = 48.0
        top = 22.0
        right = 18.0
        bottom = 42.0
        chart = QRectF(
            left,
            top,
            max(1.0, bounds.width() - left - right),
            max(1.0, bounds.height() - top - bottom),
        )

        data = self._data
        max_count = max((item.battle_count for item in data), default=0)
        scale_max = max(1, max_count)

        grid_pen = QPen(QColor("#2b3441"))
        grid_pen.setWidthF(1.0)
        painter.setPen(grid_pen)
        label_font = QFont(self.font())
        label_font.setPointSize(9)
        painter.setFont(label_font)

        grid_steps = min(4, scale_max)
        grid_steps = max(1, grid_steps)
        for step in range(grid_steps + 1):
            ratio = step / grid_steps
            y = chart.bottom() - ratio * chart.height()
            painter.drawLine(int(chart.left()), int(y), int(chart.right()), int(y))

            value = round(ratio * scale_max)
            painter.setPen(QColor("#8491a3"))
            painter.drawText(
                QRectF(0, y - 9, left - 9, 18),
                Qt.AlignRight | Qt.AlignVCenter,
                str(value),
            )
            painter.setPen(grid_pen)

        if not data:
            painter.setPen(QColor("#8491a3"))
            painter.drawText(chart, Qt.AlignCenter, "\u6682\u65e0\u5bf9\u6218\u6570\u636e")
            return

        slot_width = chart.width() / len(data)
        bar_width = min(48.0, max(14.0, slot_width * 0.52))
        bar_color = QColor("#45c7a4")
        value_color = QColor("#dce5ef")
        date_color = QColor("#8491a3")

        for index, item in enumerate(data):
            center_x = chart.left() + slot_width * (index + 0.5)
            height = chart.height() * item.battle_count / scale_max
            if item.battle_count > 0:
                height = max(4.0, height)
            bar = QRectF(
                center_x - bar_width / 2,
                chart.bottom() - height,
                bar_width,
                height,
            )
            painter.setPen(Qt.NoPen)
            painter.setBrush(bar_color)
            painter.drawRoundedRect(bar, 4.0, 4.0)

            painter.setPen(value_color)
            value_rect = QRectF(
                center_x - slot_width / 2,
                max(top, bar.top() - 22),
                slot_width,
                18,
            )
            painter.drawText(value_rect, Qt.AlignCenter, str(item.battle_count))

            painter.setPen(date_color)
            date_rect = QRectF(
                center_x - slot_width / 2,
                chart.bottom() + 10,
                slot_width,
                20,
            )
            painter.drawText(
                date_rect,
                Qt.AlignCenter,
                item.day.strftime("%m-%d"),
            )


class MetricCard(QFrame):
    def __init__(self, title: str, accent: str, parent=None):
        super().__init__(parent)
        self.setObjectName("MetricCard")
        self.setMinimumSize(170, 112)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(5)

        title_label = QLabel(title)
        title_label.setObjectName("MetricTitle")
        self.value_label = QLabel("--")
        self.value_label.setObjectName("MetricValue")
        self.value_label.setStyleSheet("color: %s;" % accent)
        self.detail_label = QLabel("")
        self.detail_label.setObjectName("MetricDetail")

        layout.addWidget(title_label)
        layout.addWidget(self.value_label)
        layout.addWidget(self.detail_label)

    def set_metric(self, value: str, detail: str = "") -> None:
        self.value_label.setText(value)
        self.detail_label.setText(detail)


class StatisticsPage(QWidget):
    """由 ``round_stats_*.json`` 文件驱动的统计视图。"""

    def __init__(
        self,
        parent=None,
        app_root: Optional[PathLike] = None,
        current_run_id: Optional[str] = None,
    ):
        super().__init__(parent)
        self._app_root = app_root
        self._current_run_id = current_run_id
        self._current_run_started_at: Optional[datetime] = None
        self._pending_run_id = False
        self._live_runtime_seconds = 0
        self._live_battle_count: Optional[int] = None
        self._snapshot: Optional[StatisticsSnapshot] = None
        self._build_ui()
        self.refresh_stats()

    def _build_ui(self) -> None:
        self.setObjectName("StatisticsPage")
        self.setProperty("pageRoot", True)

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(28, 24, 28, 24)
        root_layout.setSpacing(18)

        title = QLabel("\u7edf\u8ba1\u5206\u6790")
        title.setObjectName("PageTitle")
        subtitle = QLabel(
            "查看对战数量、胜负、胜率、局时和回合趋势"
        )
        subtitle.setObjectName("SubtleText")
        root_layout.addWidget(title)
        root_layout.addWidget(subtitle)

        metrics_layout = QGridLayout()
        metrics_layout.setHorizontalSpacing(12)
        metrics_layout.setVerticalSpacing(12)

        self.today_card = MetricCard("\u4eca\u65e5\u5bf9\u6218", "#45c7a4")
        self.duration_card = MetricCard("\u5e73\u5747\u5c40\u65f6", "#5aa9fa")
        self.rounds_card = MetricCard("\u5e73\u5747\u56de\u5408", "#f1b85b")
        self.run_card = MetricCard("\u672c\u6b21\u8fd0\u884c", "#ec7f86")
        self.win_card = MetricCard("胜利", "#45c7a4")
        self.loss_card = MetricCard("失败", "#ec7f86")
        self.win_rate_card = MetricCard("胜率", "#5aa9fa")
        self.unknown_card = MetricCard("未判定", "#9aa4b2")

        metrics_layout.addWidget(self.today_card, 0, 0)
        metrics_layout.addWidget(self.duration_card, 0, 1)
        metrics_layout.addWidget(self.rounds_card, 0, 2)
        metrics_layout.addWidget(self.run_card, 0, 3)
        metrics_layout.addWidget(self.win_card, 1, 0)
        metrics_layout.addWidget(self.loss_card, 1, 1)
        metrics_layout.addWidget(self.win_rate_card, 1, 2)
        metrics_layout.addWidget(self.unknown_card, 1, 3)
        for column in range(4):
            metrics_layout.setColumnStretch(column, 1)
        root_layout.addLayout(metrics_layout)

        deck_panel = QFrame()
        deck_panel.setObjectName("SurfacePanel")
        deck_layout = QVBoxLayout(deck_panel)
        deck_layout.setContentsMargins(18, 14, 18, 14)
        deck_layout.setSpacing(8)
        deck_header = QHBoxLayout()
        deck_header.addWidget(QLabel("各卡组战绩"))
        deck_header.addStretch(1)
        deck_hint = QLabel("按本地构筑汇总；旧记录会列为未标记")
        deck_hint.setObjectName("SubtleText")
        deck_header.addWidget(deck_hint)
        deck_layout.addLayout(deck_header)
        self.deck_stats_table = QTableWidget(0, 7)
        self.deck_stats_table.setHorizontalHeaderLabels(
            ["本地构筑", "游戏槽位", "对局", "胜", "负", "胜率", "未判定"]
        )
        self.deck_stats_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.deck_stats_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.deck_stats_table.setAlternatingRowColors(True)
        self.deck_stats_table.verticalHeader().setVisible(False)
        self.deck_stats_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch
        )
        for column in range(1, 7):
            self.deck_stats_table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeToContents
            )
        self.deck_stats_table.setMinimumHeight(155)
        self.deck_stats_table.setMaximumHeight(230)
        deck_layout.addWidget(self.deck_stats_table)

        chart_panel = QFrame()
        chart_panel.setObjectName("SurfacePanel")
        chart_layout = QVBoxLayout(chart_panel)
        chart_layout.setContentsMargins(18, 16, 18, 12)
        chart_layout.setSpacing(8)

        chart_header = QHBoxLayout()
        chart_title = QLabel("\u8fd1 7 \u65e5\u5bf9\u6218\u6b21\u6570")
        chart_title.setObjectName("SectionTitle")
        self.source_label = QLabel("")
        self.source_label.setObjectName("SubtleText")
        self.source_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        chart_header.addWidget(chart_title)
        chart_header.addStretch(1)
        chart_header.addWidget(self.source_label)
        chart_layout.addLayout(chart_header)

        self.daily_chart = DailyBattleChart()
        chart_layout.addWidget(self.daily_chart, 1)
        analysis_layout = QHBoxLayout()
        analysis_layout.setSpacing(12)
        analysis_layout.addWidget(deck_panel, 3)
        analysis_layout.addWidget(chart_panel, 2)
        root_layout.addLayout(analysis_layout, 1)

        run_panel = QFrame()
        run_panel.setObjectName("SurfacePanel")
        run_layout = QVBoxLayout(run_panel)
        run_layout.setContentsMargins(18, 14, 18, 14)
        run_layout.setSpacing(6)
        run_title = QLabel("\u8fd0\u884c\u6458\u8981")
        run_title.setObjectName("SectionTitle")
        self.run_summary_label = QLabel("")
        self.run_summary_label.setObjectName("SubtleText")
        self.run_summary_label.setWordWrap(True)
        run_layout.addWidget(run_title)
        run_layout.addWidget(self.run_summary_label)
        root_layout.addWidget(run_panel)

    def refresh_stats(self) -> StatisticsSnapshot:
        """重新加载持久化统计并更新全部指标。"""

        self._snapshot = load_statistics(
            app_root=self._app_root,
            current_run_id=self._current_run_id,
        )
        if self._pending_run_id and self._current_run_started_at is not None:
            new_run_records = [
                record
                for record in self._snapshot.records
                if record.run_id
                and record.occurred_at >= self._current_run_started_at
            ]
            if new_run_records:
                self._current_run_id = new_run_records[-1].run_id
                self._pending_run_id = False
                self._snapshot = load_statistics(
                    app_root=self._app_root,
                    current_run_id=self._current_run_id,
                )
        snapshot = self._snapshot
        self.today_card.set_metric(
            str(snapshot.today.battle_count),
            "\u5386\u53f2\u7d2f\u8ba1 %d \u5c40" % snapshot.overall.battle_count,
        )
        self.duration_card.set_metric(
            _format_duration(snapshot.overall.average_duration_seconds),
            "\u6837\u672c %d \u5c40" % snapshot.overall.duration_sample_count,
        )
        self.rounds_card.set_metric(
            "%.1f" % snapshot.overall.average_rounds,
            "\u6837\u672c %d \u5c40" % snapshot.overall.rounds_sample_count,
        )
        self.win_card.set_metric(
            str(snapshot.overall.wins),
            "今日 %d 胜" % snapshot.today.wins,
        )
        self.loss_card.set_metric(
            str(snapshot.overall.losses),
            "今日 %d 负" % snapshot.today.losses,
        )
        self.win_rate_card.set_metric(
            "%.1f%%" % (snapshot.overall.win_rate * 100.0),
            "已判定 %d 局" % snapshot.overall.decided_count,
        )
        self.unknown_card.set_metric(
            str(snapshot.overall.unknown_results),
            "含旧记录与中途停止",
        )
        self.daily_chart.set_data(snapshot.daily_counts)
        self._update_deck_table(snapshot)

        source_text = "\u5df2\u8bfb\u53d6 %d \u4e2a\u7edf\u8ba1\u6587\u4ef6" % snapshot.files_loaded
        if snapshot.files_failed:
            source_text += "\uff0c%d \u4e2a\u8bfb\u53d6\u5931\u8d25" % snapshot.files_failed
        self.source_label.setText(source_text)
        self._update_run_widgets()
        return snapshot

    def _update_deck_table(self, snapshot: StatisticsSnapshot) -> None:
        summaries = tuple(snapshot.deck_summaries or ())
        self.deck_stats_table.setRowCount(len(summaries))
        for row, summary in enumerate(summaries):
            aggregate = summary.aggregate
            slot_text = ", ".join(str(slot) for slot in summary.slots) or "--"
            values = (
                summary.deck_name,
                slot_text,
                str(aggregate.battle_count),
                str(aggregate.wins),
                str(aggregate.losses),
                "%.1f%%" % (aggregate.win_rate * 100.0),
                str(aggregate.unknown_results),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column >= 1:
                    item.setTextAlignment(Qt.AlignCenter)
                if column == 0 and summary.deck_file:
                    item.setToolTip(summary.deck_file)
                self.deck_stats_table.setItem(row, column, item)

    def set_live_stats(self, runtime_seconds: float, battle_count: int) -> None:
        """由控制器注入当前进程运行时长和对战次数。"""

        try:
            self._live_runtime_seconds = max(0, int(runtime_seconds))
        except (TypeError, ValueError):
            self._live_runtime_seconds = 0
        try:
            self._live_battle_count = max(0, int(battle_count))
        except (TypeError, ValueError):
            self._live_battle_count = 0
        self._update_run_widgets()

    def set_current_run_id(self, run_id: Optional[str]) -> None:
        self._current_run_id = str(run_id or "").strip() or None
        self._current_run_started_at = None
        self._pending_run_id = False
        self.refresh_stats()

    def begin_run(self, started_at: Optional[datetime] = None) -> None:
        """重置实时摘要，并等待首个持久化运行 ID。"""

        self._current_run_started_at = started_at or datetime.now()
        self._current_run_id = "__pending__"
        self._pending_run_id = True
        self._live_runtime_seconds = 0
        self._live_battle_count = 0
        self.refresh_stats()

    def _update_run_widgets(self) -> None:
        if self._snapshot is None:
            return

        aggregate = self._snapshot.current_run
        battle_count = (
            self._live_battle_count
            if self._live_battle_count is not None
            else aggregate.battle_count
        )
        self.run_card.set_metric(
            "%d \u5c40" % battle_count,
            "\u8fd0\u884c\u65f6\u957f %s" % _format_clock(self._live_runtime_seconds),
        )

        if aggregate.battle_count <= 0:
            self.run_summary_label.setText(
                "\u6682\u65e0\u672c\u6b21\u8fd0\u884c\u7684\u5df2\u4fdd\u5b58\u5bf9\u6218\u8bb0\u5f55"
            )
            return

        run_id = self._snapshot.current_run_id or "--"
        self.run_summary_label.setText(
            "Run ID: %s    \u5df2\u4fdd\u5b58 %d \u5c40    "
            "胜 %d / 负 %d    胜率 %.1f%%    "
            "\u5e73\u5747\u5c40\u65f6 %s    \u5e73\u5747\u56de\u5408 %.1f"
            % (
                run_id,
                aggregate.battle_count,
                aggregate.wins,
                aggregate.losses,
                aggregate.win_rate * 100.0,
                _format_duration(aggregate.average_duration_seconds),
                aggregate.average_rounds,
            )
        )


def _format_clock(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return "%02d:%02d:%02d" % (hours, minutes, seconds)


def _format_duration(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return "%d:%02d:%02d" % (hours, minutes, seconds)
    return "%d:%02d" % (minutes, seconds)
