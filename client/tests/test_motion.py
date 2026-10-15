"""Interaction regressions: motion must not queue input, steal focus, or outlive its page."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QAbstractAnimation, QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from focus_agent import motion


@pytest.fixture
def ui(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(motion, "animations_enabled", lambda: True)
    stack = motion.PageStack()
    stack.resize(600, 400)
    for _ in range(3):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(QLineEdit())
        layout.addWidget(motion.MotionCheckBox("选项"))
        stack.addWidget(page)
    stack.show()
    app.processEvents()
    yield app, stack
    stack.close()
    stack.deleteLater()
    app.processEvents()


def test_rapid_page_changes_show_latest_page_and_release_snapshots(ui):
    app, stack = ui
    for index in (1, 2, 0, 2):
        stack.setCurrentIndex(index)
        assert stack.currentIndex() == index
        stack.animation.setCurrentTime(60)
        app.processEvents()
        assert stack.frame.isVisible()
    stack.animation.setCurrentTime(stack.animation.duration())
    assert not stack.frame.isVisible()
    assert stack.frame.before.isNull() and stack.frame.after.isNull()
    assert stack.currentWidget().isVisible()


def test_input_during_page_transition_uses_live_control(ui):
    app, stack = ui
    stack.setCurrentIndex(1)
    edit = stack.currentWidget().findChild(QLineEdit)
    edit.setFocus()
    QTest.keyClicks(edit, "latest page")
    assert edit.text() == "latest page"
    assert edit.hasFocus()
    assert not stack.frame.isVisible()
    box = stack.currentWidget().findChild(motion.MotionCheckBox)
    box.setFocus()
    QTest.keyClick(box, Qt.Key.Key_Space)
    assert box.isChecked()
    assert box.selection.animation.state() == QAbstractAnimation.State.Running
    # A second press reverses the in-progress check without delaying the actual value.
    box.selection.animation.setCurrentTime(60)
    QTest.keyClick(box, Qt.Key.Key_Space)
    assert not box.isChecked()
    box.selection.animation.setCurrentTime(box.selection.animation.duration())
    assert box.selection.value == 0


@pytest.mark.parametrize("action", ["hide", "resize"])
def test_page_transition_cleanup_on_layout_or_visibility_change(ui, action):
    app, stack = ui
    stack.setCurrentIndex(2)
    if action == "hide":
        stack.hide()
    else:
        stack.resize(680, 460)
    app.processEvents()
    assert stack.animation.state() == QAbstractAnimation.State.Stopped
    assert stack.frame.before.isNull() and stack.frame.after.isNull()
    assert stack.currentIndex() == 2


def test_reduced_motion_and_hidden_controls_apply_immediately(ui, monkeypatch):
    app, stack = ui
    hidden_box = stack.widget(1).findChild(motion.MotionCheckBox)
    hidden_box.setChecked(True)
    assert hidden_box.selection.value == 1
    monkeypatch.setattr(motion, "animations_enabled", lambda: False)
    stack.setCurrentWidget(stack.widget(1))
    assert stack.currentIndex() == 1
    assert not stack.frame.isVisible()
    QTest.keyClick(hidden_box, Qt.Key.Key_Space)
    assert not hidden_box.isChecked()
    assert hidden_box.selection.value == 0
    assert hidden_box.selection.animation.state() == QAbstractAnimation.State.Stopped


def test_process_checks_keep_native_keyboard_behavior_and_clear_removed_rows(ui):
    app, _ = ui
    table = QTableWidget(2, 1)
    delegate = motion.CheckDelegate(table)
    table.setItemDelegateForColumn(0, delegate)
    for row in range(2):
        item = QTableWidgetItem()
        item.setCheckState(Qt.CheckState.Unchecked)
        table.setItem(row, 0, item)
    table.show()
    table.setCurrentCell(0, 0)
    app.processEvents()
    QTest.keyClick(table, Qt.Key.Key_Space)
    assert table.item(0, 0).checkState() == Qt.CheckState.Checked
    assert delegate.values[0].target == 1
    for row in range(2):
        table.item(row, 0).setCheckState(Qt.CheckState.Checked)
    assert all(table.item(row, 0).checkState() == Qt.CheckState.Checked for row in range(2))
    table.removeRow(0)
    assert not delegate.values
    app.processEvents()
    assert table.item(0, 0).checkState() == Qt.CheckState.Checked
    table.close()
    table.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
