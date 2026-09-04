"""Scripted hover / selection animation for widgets.

QSS :hover works but jumps instantly and gives no way to animate color or
opacity. This module attaches an event filter to a widget, listens for
mouse enter/leave and press, and drives a QPropertyAnimation on the
widget's background color and border via a per-instance stylesheet.

The widget must not compete with these rules by re-setting stylesheet
elsewhere — call `HoverAnimator.attach(widget, ...)` after the widget
has its base stylesheet applied.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from PyQt6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPropertyAnimation,
    QVariantAnimation,
    Qt,
)
from PyQt6.QtGui import QColor, QEnterEvent
from PyQt6.QtWidgets import QGraphicsOpacityEffect, QWidget


@dataclass
class HoverStyle:
    """The background/border pair for one interaction state."""
    background: QColor
    border: QColor
    radius: int = 8
    border_width: int = 1


@dataclass
class HoverStates:
    idle: HoverStyle
    hover: HoverStyle
    selected: HoverStyle | None = None
    pressed: HoverStyle | None = None
    duration_ms: int = 140

    def state_for(self, hovered: bool, selected: bool, pressed: bool) -> HoverStyle:
        if pressed and self.pressed is not None:
            return self.pressed
        if selected and self.selected is not None:
            return self.selected
        if hovered:
            return self.hover
        return self.idle


class _AnimatedStyle(QVariantAnimation):
    """Animates over an interpolated (bg, border) pair, then applies it via
    the widget's stylesheet. We use QVariantAnimation instead of a Qt
    property because QWidget has no first-class 'background color' property."""

    def __init__(self, widget: QWidget, extra_selector: str, radius: int) -> None:
        super().__init__(widget)
        self._widget = widget
        self._selector = extra_selector  # e.g. "QFrame#Card"
        self._radius = radius
        self._start_bg = QColor(0, 0, 0, 0)
        self._end_bg = QColor(0, 0, 0, 0)
        self._start_border = QColor(0, 0, 0, 0)
        self._end_border = QColor(0, 0, 0, 0)
        self._border_width = 1
        self.setDuration(140)
        self.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.valueChanged.connect(self._on_value)

    def snap_to(self, style: HoverStyle) -> None:
        self._start_bg = QColor(style.background)
        self._end_bg = QColor(style.background)
        self._start_border = QColor(style.border)
        self._end_border = QColor(style.border)
        self._border_width = style.border_width
        self._radius = style.radius
        self._apply(style.background, style.border)

    def animate_to(self, style: HoverStyle, duration_ms: int) -> None:
        self.stop()
        # Sample the current values from the widget's stylesheet source of truth.
        self._start_bg = QColor(self._end_bg)
        self._start_border = QColor(self._end_border)
        self._end_bg = QColor(style.background)
        self._end_border = QColor(style.border)
        self._border_width = style.border_width
        self._radius = style.radius
        self.setStartValue(0.0)
        self.setEndValue(1.0)
        self.setDuration(duration_ms)
        self.start()

    def _on_value(self, value) -> None:
        t = float(value)
        bg = _blend(self._start_bg, self._end_bg, t)
        border = _blend(self._start_border, self._end_border, t)
        self._apply(bg, border)

    def _apply(self, bg: QColor, border: QColor) -> None:
        rule = (
            f"{self._selector}{{"
            f"background:{bg.name(QColor.NameFormat.HexArgb)};"
            f"border:{self._border_width}px solid {border.name(QColor.NameFormat.HexArgb)};"
            f"border-radius:{self._radius}px;"
            f"}}"
        )
        self._widget.setStyleSheet(rule)


def _blend(a: QColor, b: QColor, t: float) -> QColor:
    return QColor(
        int(a.red() + (b.red() - a.red()) * t),
        int(a.green() + (b.green() - a.green()) * t),
        int(a.blue() + (b.blue() - a.blue()) * t),
        int(a.alpha() + (b.alpha() - a.alpha()) * t),
    )


class HoverAnimator(QObject):
    """Attach to a widget to animate its background/border through
    idle / hover / pressed / selected states."""

    def __init__(
        self,
        widget: QWidget,
        states: HoverStates,
        *,
        selector: str | None = None,
    ) -> None:
        super().__init__(widget)
        self._widget = widget
        self._states = states
        self._hovered = False
        self._pressed = False
        self._selected = False
        # Selector defaults to the widget's class + objectName so we don't
        # accidentally style children.
        cls = type(widget).__name__
        obj = widget.objectName()
        chosen = selector or (f"{cls}#{obj}" if obj else cls)
        self._anim = _AnimatedStyle(widget, chosen, states.idle.radius)
        # A plain QWidget won't paint `background:` from a stylesheet without
        # this attribute. QFrame turns it on by default; we do it here so any
        # widget class works with HoverAnimator.
        widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        widget.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self._anim.snap_to(states.idle)
        widget.installEventFilter(self)

    @classmethod
    def attach(cls, widget: QWidget, states: HoverStates, *, selector: str | None = None) -> "HoverAnimator":
        return cls(widget, states, selector=selector)

    def set_selected(self, selected: bool, *, instant: bool = False) -> None:
        if selected == self._selected:
            return
        self._selected = selected
        self._transition(instant=instant)

    def set_states(self, states: HoverStates) -> None:
        self._states = states
        self._transition(instant=True)

    def eventFilter(self, obj, event: QEvent | None) -> bool:  # type: ignore[override]
        if event is None or obj is not self._widget:
            return False
        t = event.type()
        if t == QEvent.Type.Enter or t == QEvent.Type.HoverEnter:
            self._hovered = True
            self._transition()
        elif t == QEvent.Type.Leave or t == QEvent.Type.HoverLeave:
            self._hovered = False
            self._pressed = False
            self._transition()
        elif t == QEvent.Type.MouseButtonPress:
            self._pressed = True
            self._transition()
        elif t == QEvent.Type.MouseButtonRelease:
            self._pressed = False
            self._transition()
        return False

    def _transition(self, *, instant: bool = False) -> None:
        target = self._states.state_for(self._hovered, self._selected, self._pressed)
        if instant:
            self._anim.snap_to(target)
        else:
            self._anim.animate_to(target, self._states.duration_ms)


class FadeInController(QObject):
    """Fade a widget in/out via QGraphicsOpacityEffect. Used to reveal a
    row's action bar only on hover — simpler than juggling `hidden` +
    reflow because the widget still occupies its slot."""

    def __init__(self, target: QWidget, *, duration_ms: int = 120) -> None:
        super().__init__(target)
        self._effect = QGraphicsOpacityEffect(target)
        self._effect.setOpacity(0.0)
        target.setGraphicsEffect(self._effect)
        self._anim = QPropertyAnimation(self._effect, b"opacity", self)
        self._anim.setDuration(duration_ms)
        self._anim.setEasingCurve(QEasingCurve.Type.OutQuad)

    def show(self) -> None:
        self._to(1.0)

    def hide(self) -> None:
        self._to(0.0)

    def _to(self, end: float) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._effect.opacity())
        self._anim.setEndValue(end)
        self._anim.start()
