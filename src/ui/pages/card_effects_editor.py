#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Card effects editor (Step3A 2nd-level UI).

This dialog edits `strategy.effects` using the Step3A op schema.
It only depends on lightweight config registries (no cv/u2/game imports).
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from PyQt5.QtCore import Qt as _Qt
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

import json
import os

from src.config.config_repository import ConfigRepository
from src.config.effects_registry import (
    CONTEXT_HAND_CARD,
    get_operation,
    get_operations,
    get_target_kind,
    get_target_kinds,
    get_triggers,
)
from src.config.paths import get_config_path
from src.config.strategy_effects import (
    convert_legacy_action_to_ops,
    convert_legacy_target_type_to_ops,
    get_card_effect_steps,
)
from src.utils.card_filename import normalize_card_base_name, split_enhance_key


# PyQt5 stubs vary across environments; keep Qt attribute access flexible.
Qt: Any = _Qt


def _safe_int(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return int(default)


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return float(default)


def _norm_select_option(v: Any) -> Optional[int]:
    if v in (1, "1", "选项1", "Option1", "option1"):
        return 1
    if v in (2, "2", "选项2", "Option2", "option2"):
        return 2
    return None


class TargetSpecEditor(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._param_widgets: Dict[str, Any] = {}

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        layout.addWidget(QLabel("目标:"))

        self.kind_combo = QComboBox()
        for kd in get_target_kinds():
            self.kind_combo.addItem(str(kd.get("label") or kd.get("kind") or ""), str(kd.get("kind") or ""))
        self.kind_combo.currentIndexChanged.connect(self._rebuild_selector)
        layout.addWidget(self.kind_combo)

        self.selector_combo = QComboBox()
        self.selector_combo.currentIndexChanged.connect(self._rebuild_params)
        layout.addWidget(self.selector_combo)

        self.params_container = QWidget()
        self.params_layout = QHBoxLayout(self.params_container)
        self.params_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.params_container)

        layout.addStretch()

        self._rebuild_selector()

    def _current_kind(self) -> str:
        return str(self.kind_combo.currentData() or "")

    def _current_selector(self) -> str:
        return str(self.selector_combo.currentData() or "")

    def _rebuild_selector(self) -> None:
        kind = self._current_kind()
        kd = get_target_kind(kind)
        selectors = []
        if isinstance(kd, dict):
            selectors = kd.get("selectors") or []

        self.selector_combo.blockSignals(True)
        self.selector_combo.clear()
        for sd in selectors:
            if not isinstance(sd, dict):
                continue
            self.selector_combo.addItem(str(sd.get("label") or sd.get("id") or ""), str(sd.get("id") or ""))
        self.selector_combo.blockSignals(False)

        self._rebuild_params()

    def _clear_params(self) -> None:
        while self.params_layout.count():
            item = self.params_layout.takeAt(0)
            w = item.widget() if item is not None else None
            if w is not None:
                w.deleteLater()
        self._param_widgets = {}

    def _rebuild_params(self) -> None:
        self._clear_params()

        kind = self._current_kind()
        selector = self._current_selector()
        kd = get_target_kind(kind)
        params_schema = []
        if isinstance(kd, dict):
            for sd in kd.get("selectors") or []:
                if not isinstance(sd, dict):
                    continue
                if str(sd.get("id") or "") == selector:
                    params_schema = sd.get("params_schema") or []
                    break

        for p in params_schema:
            if not isinstance(p, dict):
                continue
            w = _build_param_widget(p)
            if w is None:
                continue
            name = str(p.get("name") or "")
            if name:
                self._param_widgets[name] = (p, w)
            self.params_layout.addWidget(w)

        self.params_layout.addStretch()

    def load(self, target_spec: Any) -> None:
        if not isinstance(target_spec, dict):
            target_spec = {}
        kind = str(target_spec.get("kind") or "")
        selector = str(target_spec.get("selector") or "")
        params = target_spec.get("params")
        if not isinstance(params, dict):
            params = {}

        idx = self.kind_combo.findData(kind)
        if idx >= 0:
            self.kind_combo.setCurrentIndex(idx)
        else:
            self.kind_combo.setCurrentIndex(0)
        self._rebuild_selector()

        sidx = self.selector_combo.findData(selector)
        if sidx >= 0:
            self.selector_combo.setCurrentIndex(sidx)
        else:
            self.selector_combo.setCurrentIndex(0)
        self._rebuild_params()

        for name, (spec, w) in list(self._param_widgets.items()):
            if name in params:
                _set_param_widget_value(spec, w, params.get(name))

    def value(self) -> Dict[str, Any]:
        kind = self._current_kind()
        selector = self._current_selector()

        params: Dict[str, Any] = {}
        for name, (spec, w) in list(self._param_widgets.items()):
            params[name] = _get_param_widget_value(spec, w)

        return {"kind": kind, "selector": selector, "params": params}


def _build_param_widget(param_spec: Dict[str, Any]) -> Optional[QWidget]:
    ptype = str(param_spec.get("type") or "")
    label = str(param_spec.get("label") or param_spec.get("name") or "")

    if ptype == "bool":
        cb = QCheckBox(label)
        cb.setChecked(bool(param_spec.get("default", False)))
        return cb

    if ptype == "int":
        compact = bool(param_spec.get("compact", False))
        min_v = _safe_int(param_spec.get("min", -10**9), -10**9)
        max_v = _safe_int(param_spec.get("max", 10**9), 10**9)
        default_v = _safe_int(param_spec.get("default", 0), 0)

        if compact:
            w = QWidget()
            lay = QHBoxLayout(w)
            lay.setContentsMargins(0, 0, 0, 0)
            if label:
                lay.addWidget(QLabel(label))
            box = QSpinBox()
            box.setRange(min_v, max_v)
            box.setValue(default_v)
            box.setMaximumWidth(80)
            lay.addWidget(box)
            return w

        box = QSpinBox()
        box.setPrefix(f"{label}:" if label else "")
        box.setRange(min_v, max_v)
        box.setValue(default_v)
        box.setMaximumWidth(150)
        return box

    if ptype == "float":
        box = QDoubleSpinBox()
        box.setPrefix(f"{label}:" if label else "")
        box.setDecimals(3)
        box.setRange(_safe_float(param_spec.get("min", -10**9), -10**9), _safe_float(param_spec.get("max", 10**9), 10**9))
        box.setValue(_safe_float(param_spec.get("default", 0.0), 0.0))
        box.setMaximumWidth(170)
        return box

    if ptype == "str":
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        if label:
            lay.addWidget(QLabel(f"{label}:"))
        le = QLineEdit()
        le.setText(str(param_spec.get("default", "") or ""))
        le.setMaximumWidth(220)
        lay.addWidget(le)
        return w

    if ptype == "multiline_str":
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        if label:
            lay.addWidget(QLabel(f"{label}:"))
        edit = QPlainTextEdit()
        edit.setPlainText(str(param_spec.get("default", "") or ""))
        choices = [str(x).strip() for x in (param_spec.get("choices") or []) if str(x).strip()]
        hint = str(param_spec.get("hint") or "")
        if choices:
            edit.setPlaceholderText(hint or "每行一个卡名，越靠前优先级越高；可自行删除/调整顺序。")
            btn = QPushButton("填入卡组卡名")
            btn.clicked.connect(lambda _=False, e=edit, names=choices: e.setPlainText("\n".join(names)))
            lay.addWidget(btn)
        elif hint:
            edit.setPlaceholderText(hint)
        edit.setFixedHeight(80)
        lay.addWidget(edit)
        return w

    if ptype == "card_priority_list":
        choices = [str(x).strip() for x in (param_spec.get("choices") or []) if str(x).strip()]
        hint = str(param_spec.get("hint") or "")
        return CardPriorityListEditor(choices=choices, hint=hint)

    if ptype == "enum":
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        if label:
            lay.addWidget(QLabel(f"{label}:"))
        combo = QComboBox()
        for opt in param_spec.get("options") or []:
            if not isinstance(opt, dict):
                continue
            combo.addItem(str(opt.get("label") or opt.get("value") or ""), opt.get("value"))
        default = param_spec.get("default")
        didx = combo.findData(default)
        if didx >= 0:
            combo.setCurrentIndex(didx)
        lay.addWidget(combo)
        return w

    if ptype == "target_spec":
        return TargetSpecEditor()

    return None


def _find_inner_widget(container: QWidget, widget_type: Any) -> Optional[Any]:
    try:
        return container.findChild(widget_type)
    except Exception:
        return None


class CardPriorityListEditor(QWidget):
    def __init__(self, *, choices: List[str], hint: str = "", parent=None):
        super().__init__(parent)
        self.choices = [str(x).strip() for x in (choices or []) if str(x).strip()]
        self.choice_by_norm: Dict[str, str] = {}
        for name in self.choices:
            norm = self._normalize_name(name)
            if norm and norm not in self.choice_by_norm:
                self.choice_by_norm[norm] = name
        self.items: List[str] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        top = QHBoxLayout()
        self.combo = QComboBox()
        for name in self.choices:
            self.combo.addItem(name, name)
        self.combo.setEnabled(bool(self.choices))
        top.addWidget(self.combo)
        self.add_btn = QPushButton("添加")
        self.add_btn.setEnabled(bool(self.choices))
        self.add_btn.clicked.connect(self._add_current)
        top.addWidget(self.add_btn)
        layout.addLayout(top)

        self.hint_label = QLabel(hint or "越上方优先级越高；同一卡名只能添加一次。")
        self.hint_label.setStyleSheet("color: #6B7280;")
        layout.addWidget(self.hint_label)

        self.rows_container = QWidget()
        self.rows_layout = QVBoxLayout(self.rows_container)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.rows_container)

        if not self.choices:
            self.hint_label.setText("当前卡组没有可选卡名，无法添加。")

    @staticmethod
    def _normalize_name(name: Any) -> str:
        raw = str(name or "").strip()
        if not raw:
            return ""
        try:
            base, _cost = split_enhance_key(raw)
            raw = str(base or raw)
        except Exception:
            pass
        try:
            raw = normalize_card_base_name(raw) or raw
        except Exception:
            pass
        return raw.replace(" ", "").replace("　", "").replace("_", "").lower()

    def _add_current(self) -> None:
        name = str(self.combo.currentData() or self.combo.currentText() or "").strip()
        if name and name in self.choices and name not in self.items:
            self.items.append(name)
            self._rebuild_rows()

    def _move(self, index: int, delta: int) -> None:
        new_index = index + delta
        if new_index < 0 or new_index >= len(self.items):
            return
        self.items[index], self.items[new_index] = self.items[new_index], self.items[index]
        self._rebuild_rows()

    def _delete(self, index: int) -> None:
        if 0 <= index < len(self.items):
            del self.items[index]
            self._rebuild_rows()

    def _rebuild_rows(self) -> None:
        while self.rows_layout.count():
            item = self.rows_layout.takeAt(0)
            w = item.widget() if item is not None else None
            if w is not None:
                w.deleteLater()

        for i, name in enumerate(self.items):
            row = QWidget()
            lay = QHBoxLayout(row)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.addWidget(QLabel(name))
            lay.addStretch()
            up = QPushButton("↑")
            up.setMaximumWidth(30)
            up.setEnabled(i > 0)
            up.clicked.connect(lambda _=False, idx=i: self._move(idx, -1))
            lay.addWidget(up)
            down = QPushButton("↓")
            down.setMaximumWidth(30)
            down.setEnabled(i < len(self.items) - 1)
            down.clicked.connect(lambda _=False, idx=i: self._move(idx, 1))
            lay.addWidget(down)
            delete = QPushButton("删除")
            delete.setMaximumWidth(60)
            delete.clicked.connect(lambda _=False, idx=i: self._delete(idx))
            lay.addWidget(delete)
            self.rows_layout.addWidget(row)
        self.rows_layout.addStretch()

    def set_value(self, value: Any) -> None:
        raw = str(value or "")
        wanted = [x.strip() for x in raw.replace("，", "\n").replace("、", "\n").replace("|", "\n").replace(",", "\n").splitlines() if x.strip()]
        seen = set()
        self.items = []
        for name in wanted:
            standard_name = self.choice_by_norm.get(self._normalize_name(name))
            if standard_name and standard_name not in seen:
                seen.add(standard_name)
                self.items.append(standard_name)
        self._rebuild_rows()

    def value(self) -> str:
        return "\n".join(self.items)


def _set_param_widget_value(param_spec: Dict[str, Any], widget: QWidget, value: Any) -> None:
    ptype = str(param_spec.get("type") or "")
    if ptype == "bool" and isinstance(widget, QCheckBox):
        widget.setChecked(bool(value))
        return
    if ptype == "int" and isinstance(widget, QSpinBox):
        widget.setValue(_safe_int(value, widget.value()))
        return
    if ptype == "int":
        box = _find_inner_widget(widget, QSpinBox)
        if box is not None:
            box.setValue(_safe_int(value, box.value()))
        return
    if ptype == "float" and isinstance(widget, QDoubleSpinBox):
        widget.setValue(_safe_float(value, widget.value()))
        return
    if ptype == "str":
        le = _find_inner_widget(widget, QLineEdit)
        if le is not None:
            le.setText(str(value or ""))
        return
    if ptype == "multiline_str":
        edit = _find_inner_widget(widget, QPlainTextEdit)
        if edit is not None:
            edit.setPlainText(str(value or ""))
        return
    if ptype == "card_priority_list" and isinstance(widget, CardPriorityListEditor):
        widget.set_value(value)
        return
    if ptype == "enum":
        combo = _find_inner_widget(widget, QComboBox)
        if combo is not None:
            idx = combo.findData(value)
            if idx >= 0:
                combo.setCurrentIndex(idx)
        return
    if ptype == "target_spec" and isinstance(widget, TargetSpecEditor):
        widget.load(value)
        return


def _get_param_widget_value(param_spec: Dict[str, Any], widget: QWidget) -> Any:
    ptype = str(param_spec.get("type") or "")
    if ptype == "bool" and isinstance(widget, QCheckBox):
        return bool(widget.isChecked())
    if ptype == "int" and isinstance(widget, QSpinBox):
        return int(widget.value())
    if ptype == "int":
        box = _find_inner_widget(widget, QSpinBox)
        if box is not None:
            return int(box.value())
        return _safe_int(param_spec.get("default", 0), 0)
    if ptype == "float" and isinstance(widget, QDoubleSpinBox):
        return float(widget.value())
    if ptype == "str":
        le = _find_inner_widget(widget, QLineEdit)
        return str(le.text()) if le is not None else ""
    if ptype == "multiline_str":
        edit = _find_inner_widget(widget, QPlainTextEdit)
        return str(edit.toPlainText()) if edit is not None else ""
    if ptype == "card_priority_list" and isinstance(widget, CardPriorityListEditor):
        return widget.value()
    if ptype == "enum":
        combo = _find_inner_widget(widget, QComboBox)
        return combo.currentData() if combo is not None else None
    if ptype == "target_spec" and isinstance(widget, TargetSpecEditor):
        return widget.value()
    return None


class StepRow(QWidget):
    def __init__(
        self,
        *,
        context_kind: str,
        step: Dict[str, Any],
        on_move_up,
        on_move_down,
        on_delete,
        deck_card_names: Optional[List[str]] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.context_kind = str(context_kind or "")
        self._on_move_up = on_move_up
        self._on_move_down = on_move_down
        self._on_delete = on_delete
        self.deck_card_names = list(deck_card_names or [])

        self._param_widgets: Dict[str, Any] = {}

        self.op_spec: Dict[str, Any] = dict(step or {})
        if "op" not in self.op_spec:
            self.op_spec["op"] = ""

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        layout.addWidget(QLabel("操作:"))
        self.op_combo = QComboBox()
        for op_def in get_operations(context_kind=self.context_kind):
            self.op_combo.addItem(str(op_def.get("label") or op_def.get("op_id") or ""), str(op_def.get("op_id") or ""))

        layout.addWidget(self.op_combo)

        self.params_container = QWidget()
        self.params_layout = QHBoxLayout(self.params_container)
        self.params_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.params_container)
        layout.addStretch()

        btn_up = QPushButton("↑")
        btn_up.setMaximumWidth(30)
        btn_up.clicked.connect(lambda: self._on_move_up(self))
        layout.addWidget(btn_up)

        btn_down = QPushButton("↓")
        btn_down.setMaximumWidth(30)
        btn_down.clicked.connect(lambda: self._on_move_down(self))
        layout.addWidget(btn_down)

        btn_del = QPushButton("删除")
        btn_del.setMaximumWidth(60)
        btn_del.clicked.connect(lambda: self._on_delete(self))
        layout.addWidget(btn_del)

        # Init selection
        op_id = str(self.op_spec.get("op") or "")
        idx = self.op_combo.findData(op_id)
        if idx >= 0:
            self.op_combo.setCurrentIndex(idx)
        else:
            self.op_combo.setCurrentIndex(0)
            self.op_spec["op"] = str(self.op_combo.currentData() or "")

        self.op_combo.currentIndexChanged.connect(self._on_op_changed)
        self._rebuild_params()

    def _on_op_changed(self) -> None:
        self.op_spec["op"] = str(self.op_combo.currentData() or "")
        # Reset params to defaults when op changes.
        self.op_spec = {"op": self.op_spec["op"]}
        self._rebuild_params()

    def _clear_params(self) -> None:
        while self.params_layout.count():
            item = self.params_layout.takeAt(0)
            w = item.widget() if item is not None else None
            if w is not None:
                w.deleteLater()
        self._param_widgets = {}

    def _rebuild_params(self) -> None:
        self._clear_params()
        op_id = str(self.op_combo.currentData() or "")
        op_def = get_operation(op_id)
        params_schema = []
        if isinstance(op_def, dict):
            params_schema = op_def.get("params_schema") or []

        for p in params_schema:
            if not isinstance(p, dict):
                continue
            spec = dict(p)
            if op_id == "select_hand_card" and str(spec.get("name") or "") == "priority_cards":
                spec["choices"] = self.deck_card_names
                spec["hint"] = "从当前卡组卡名中添加；越上方优先级越高。"
            w = _build_param_widget(spec)
            if w is None:
                continue
            name = str(spec.get("name") or "")
            if name:
                self._param_widgets[name] = (spec, w)

            # Load default / current
            if name in self.op_spec:
                _set_param_widget_value(spec, w, self.op_spec.get(name))
            elif "default" in spec:
                _set_param_widget_value(spec, w, spec.get("default"))
            self.params_layout.addWidget(w)

        self.params_layout.addStretch()

    def value(self) -> Dict[str, Any]:
        op_id = str(self.op_combo.currentData() or "")
        out: Dict[str, Any] = {"op": op_id}
        for name, (spec, w) in list(self._param_widgets.items()):
            out[name] = _get_param_widget_value(spec, w)
        return out


class RawStepRow(QWidget):
    def __init__(self, *, raw_step: Dict[str, Any], on_delete, parent=None):
        super().__init__(parent)
        self.raw_step = dict(raw_step or {})
        self._on_delete = on_delete

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("未知Step:"))
        preview = json.dumps(self.raw_step, ensure_ascii=False, sort_keys=True)
        lab = QLabel(preview)
        lab.setToolTip(preview)
        lab.setStyleSheet("color: #7A4B00;")
        layout.addWidget(lab)
        layout.addStretch()

        btn_del = QPushButton("删除")
        btn_del.setMaximumWidth(60)
        btn_del.clicked.connect(lambda: self._on_delete(self))
        layout.addWidget(btn_del)

    def value(self) -> Dict[str, Any]:
        return dict(self.raw_step)


class TriggerEditor(QWidget):
    def __init__(self, *, trigger_id: str, context_kind: str, deck_card_names: Optional[List[str]] = None, parent=None):
        super().__init__(parent)
        self.trigger_id = str(trigger_id or "")
        self.context_kind = str(context_kind or "")
        self.deck_card_names = list(deck_card_names or [])
        self.rows: List[QWidget] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.rows_container = QWidget()
        self.rows_layout = QVBoxLayout(self.rows_container)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.rows_container)

        btn_add = QPushButton("添加步骤")
        btn_add.clicked.connect(self.add_step)
        layout.addWidget(btn_add)

    def _move_row(self, row: QWidget, delta: int) -> None:
        try:
            idx = self.rows.index(row)
        except Exception:
            return
        new_idx = idx + int(delta)
        if new_idx < 0 or new_idx >= len(self.rows):
            return
        self.rows[idx], self.rows[new_idx] = self.rows[new_idx], self.rows[idx]
        self._rebuild_layout()

    def _delete_row(self, row: QWidget) -> None:
        try:
            self.rows.remove(row)
        except Exception:
            return
        try:
            row.deleteLater()
        except Exception:
            pass
        self._rebuild_layout()

    def _rebuild_layout(self) -> None:
        while self.rows_layout.count():
            item = self.rows_layout.takeAt(0)
            w = item.widget() if item is not None else None
            if w is not None:
                w.setParent(None)

        for r in self.rows:
            self.rows_layout.addWidget(r)
        self.rows_layout.addStretch()

    def clear(self) -> None:
        for r in list(self.rows):
            try:
                r.deleteLater()
            except Exception:
                pass
        self.rows = []
        self._rebuild_layout()

    def add_step(self, step: Optional[Dict[str, Any]] = None) -> None:
        step = dict(step or {})
        op_id = str(step.get("op") or "")
        op_def = get_operation(op_id) if op_id else None
        if not op_id or not isinstance(op_def, dict):
            # default to first op for this context
            ops = get_operations(context_kind=self.context_kind)
            if ops:
                step = {"op": str(ops[0].get("op_id") or "")}
        row = StepRow(
            context_kind=self.context_kind,
            step=step,
            on_move_up=lambda r: self._move_row(r, -1),
            on_move_down=lambda r: self._move_row(r, 1),
            on_delete=self._delete_row,
            deck_card_names=self.deck_card_names,
        )
        self.rows.append(row)
        self._rebuild_layout()

    def add_raw_step(self, raw_step: Dict[str, Any]) -> None:
        row = RawStepRow(raw_step=raw_step, on_delete=self._delete_row)
        self.rows.append(row)
        self._rebuild_layout()

    def load_steps(self, steps: List[Dict[str, Any]]) -> None:
        self.clear()
        for step in steps or []:
            if not isinstance(step, dict):
                continue
            op_id = step.get("op")
            if isinstance(op_id, str) and op_id:
                if op_id == "legacy_target_type":
                    for c in convert_legacy_target_type_to_ops(step.get("target_type")):
                        self.add_step(c)
                    continue
                if op_id == "legacy_action":
                    for c in convert_legacy_action_to_ops(step.get("action")):
                        self.add_step(c)
                    continue
                op_def = get_operation(op_id)
                if isinstance(op_def, dict):
                    self.add_step(step)
                else:
                    self.add_raw_step(step)
                continue

            # Legacy Step2B dict: expand to ops but preserve unknown keys.
            used_any = False
            if "select_option" in step:
                opt = _norm_select_option(step.get("select_option"))
                if opt is not None:
                    self.add_step({"op": "select_option", "index": int(opt)})
                    used_any = True
            if "target_type" in step:
                converted = convert_legacy_target_type_to_ops(step.get("target_type"))
                for c in converted:
                    self.add_step(c)
                    used_any = True
            if "action" in step:
                converted = convert_legacy_action_to_ops(step.get("action"))
                for c in converted:
                    self.add_step(c)
                    used_any = True

            if not used_any:
                self.add_raw_step(step)

    def value(self) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for r in self.rows:
            try:
                out.append(r.value())
            except Exception:
                continue
        return [s for s in out if isinstance(s, dict) and s]


class CardEffectsDialog(QDialog):
    def __init__(
        self,
        parent=None,
        *,
        base_name: str,
        config_key: str,
        display_name: str,
        is_enhance: bool,
        deck_card_names: Optional[List[str]] = None,
    ):
        super().__init__(parent)
        self.parent_widget = parent
        self.base_name = str(base_name or "")
        self.config_key = str(config_key or base_name or "")
        self.display_name = str(display_name or base_name or "")
        self.is_enhance = bool(is_enhance)
        self.deck_card_names = list(deck_card_names or [])

        self.setWindowTitle(f"特殊效果 - {self.display_name}")
        self.resize(920, 520)
        self.setStyleSheet(
            """
            QLabel { color: #1F2937; }
            QCheckBox { color: #1F2937; }
            QGroupBox { color: #1F2937; }
            """
        )

        self.repo = ConfigRepository(get_config_path())

        main = QVBoxLayout(self)

        hint = QLabel(
            "选择触发时机，并为每个触发时机配置操作序列。\n"
            "提示：基础卡可配置通用触发；爆能档位可配置仅该档位生效的触发。\n"
            "提示：爆能档位默认继承本体同触发效果；若配置了同类效果（如同一BUFF类型）则以爆能档位覆盖。\n"
            "提示：身材BUFF与攻击次数BUFF已拆分为两个独立操作；请分别配置。"
        )
        hint.setStyleSheet("color: #38527A;")
        main.addWidget(hint)

        if self.is_enhance:
            enhance_notice = QLabel("当前为爆能档位配置：可设置该爆能档位专属的出牌/攻击/进化触发效果。")
            enhance_notice.setStyleSheet("color: #7A4B00;")
            main.addWidget(enhance_notice)

        # Trigger multi-select
        trig_bar = QHBoxLayout()
        trig_bar.addWidget(QLabel("触发时机:"))
        self.trig_checks: Dict[str, QCheckBox] = {}
        self.trig_groups: Dict[str, QGroupBox] = {}
        self.trig_editors: Dict[str, TriggerEditor] = {}

        allowed = []
        for t in get_triggers():
            if not isinstance(t, dict):
                continue
            tid = str(t.get("id") or "")
            if not tid:
                continue
            allowed.append(t)

        for t in allowed:
            tid = str(t.get("id") or "")
            cb = QCheckBox(str(t.get("label") or tid))
            cb.stateChanged.connect(lambda _v, x=tid: self._toggle_trigger(x))
            trig_bar.addWidget(cb)
            self.trig_checks[tid] = cb
        trig_bar.addStretch()
        main.addLayout(trig_bar)

        # Scroll content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_content = QWidget()
        self.scroll_layout = QVBoxLayout(scroll_content)
        scroll.setWidget(scroll_content)
        main.addWidget(scroll)

        # Build per-trigger editors
        for t in allowed:
            tid = str(t.get("id") or "")
            ck = str(t.get("context_kind") or "")

            group = QGroupBox(str(t.get("label") or tid))
            group_lay = QVBoxLayout(group)
            editor = TriggerEditor(trigger_id=tid, context_kind=ck, deck_card_names=self.deck_card_names)
            group_lay.addWidget(editor)

            self.scroll_layout.addWidget(group)
            self.trig_groups[tid] = group
            self.trig_editors[tid] = editor

        self.scroll_layout.addStretch()

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        main.addWidget(buttons)

        self._load_existing()

    def _key_for_trigger(self, trigger_id: str) -> str:
        if self.is_enhance:
            return self.config_key

        t = None
        for d in get_triggers():
            if str(d.get("id") or "") == str(trigger_id or ""):
                t = d
                break
        ck = str(t.get("context_kind") or "") if isinstance(t, dict) else ""
        if ck == CONTEXT_HAND_CARD:
            return self.config_key
        return self.base_name

    def _load_existing(self) -> None:
        cfg, parse_ok, err = self.repo.load_existing(allow_default_on_error=False)
        if cfg is None:
            QMessageBox.warning(self, "加载失败", f"config.json解析失败: {str(err or '')}")
            return

        effects = cfg.get("strategy", {}).get("effects", {})
        if not isinstance(effects, dict):
            effects = {}

        for tid, cb in list(self.trig_checks.items()):
            key = self._key_for_trigger(tid)
            card_eff = effects.get(key)
            if not isinstance(card_eff, dict):
                card_eff = {}
            steps = card_eff.get(tid)
            enabled = isinstance(steps, list) and any(isinstance(s, dict) for s in steps)
            cb.setChecked(bool(enabled))

            editor = self.trig_editors.get(tid)
            if editor is None:
                continue
            raw_steps = get_card_effect_steps(cfg, card_name=key, trigger=tid)
            editor.load_steps(list(raw_steps or []))

        for tid in list(self.trig_checks.keys()):
            self._toggle_trigger(tid)

    def _toggle_trigger(self, trigger_id: str) -> None:
        cb = self.trig_checks.get(trigger_id)
        group = self.trig_groups.get(trigger_id)
        if cb is None or group is None:
            return
        enabled = bool(cb.isChecked())
        group.setVisible(enabled)

        # UX: when a trigger is enabled, prefill one default step so users don't
        # have to manually click "添加步骤" every time.
        if enabled:
            editor = self.trig_editors.get(trigger_id)
            if editor is not None and not getattr(editor, "rows", None):
                try:
                    editor.add_step()
                except Exception:
                    pass

    def _save(self) -> None:
        # 1. 首先更新全局配置（保持原有行为）
        cfg, parse_ok, err = self.repo.load_existing(allow_default_on_error=False)
        if cfg is None:
            QMessageBox.warning(self, "保存失败", f"config.json解析失败: {str(err or '')}")
            return

        strategy = cfg.get("strategy")
        if not isinstance(strategy, dict):
            strategy = {}
            cfg["strategy"] = strategy
        effects = strategy.get("effects")
        if not isinstance(effects, dict):
            effects = {}
            strategy["effects"] = effects

        # 收集要保存的效果数据
        effects_to_save = {}
        for tid, cb in list(self.trig_checks.items()):
            key = self._key_for_trigger(tid)
            card_eff = effects.get(key)
            if not isinstance(card_eff, dict):
                card_eff = {}

            if cb.isChecked():
                editor = self.trig_editors.get(tid)
                steps = editor.value() if editor is not None else []
                # Clean empty
                steps = [s for s in steps if isinstance(s, dict) and s]
                if steps:
                    card_eff[tid] = steps
                elif tid in card_eff:
                    del card_eff[tid]
            else:
                if tid in card_eff:
                    del card_eff[tid]

            if card_eff:
                effects[key] = card_eff
                effects_to_save[key] = card_eff
            else:
                if key in effects:
                    del effects[key]

        # 2. 保存到全局配置
        res = self.repo.replace_with_snapshot(cfg, indent=4, ensure_ascii=False)
        if not res.ok:
            QMessageBox.warning(self, "保存失败", f"保存失败: {str(res.error or '')}")
            return

        # 3. 尝试保存到当前卡组文件
        self._save_to_current_deck(effects_to_save)

        QMessageBox.information(self, "成功", "特殊效果已保存")
        self.accept()

    def _save_to_current_deck(self, effects_to_save: dict) -> None:
        """将效果保存到当前卡组文件"""
        if not effects_to_save:
            return

        try:
            # 获取主窗口
            parent = self.parent_widget

            while parent:
                if hasattr(parent, "card_select_page"):
                    card_select_page = parent.card_select_page
                    break
                parent = getattr(parent, "parent_widget", None) or getattr(
                    parent, "parent", None
                )
            else:
                return

            # 获取当前选中的卡组文件（使用新的 current_deck_file 属性）
            deck_file = getattr(card_select_page, "current_deck_file", None)
            if not deck_file:
                return

            # 读取卡组文件
            decks_dir = os.path.join(os.path.dirname(get_config_path()), "saved_decks")
            deck_path = os.path.join(decks_dir, deck_file)

            if not os.path.exists(deck_path):
                return

            with open(deck_path, "r", encoding="utf-8") as f:
                deck_data = json.load(f)

            # 更新 strategy_config
            sc = deck_data.get("strategy_config")
            if not isinstance(sc, dict):
                sc = {}
                deck_data["strategy_config"] = sc

            # 获取或创建 strategy.effects
            strategy = sc.get("strategy")
            if not isinstance(strategy, dict):
                strategy = {}
                sc["strategy"] = strategy

            deck_effects = strategy.get("effects")
            if not isinstance(deck_effects, dict):
                deck_effects = {}
                strategy["effects"] = deck_effects

            # 合并效果数据
            for key, card_eff in effects_to_save.items():
                if card_eff:
                    deck_effects[key] = card_eff
                elif key in deck_effects:
                    del deck_effects[key]

            # 写回卡组文件
            with open(deck_path, "w", encoding="utf-8") as f:
                json.dump(deck_data, f, ensure_ascii=False, indent=2)

        except Exception:
            pass
