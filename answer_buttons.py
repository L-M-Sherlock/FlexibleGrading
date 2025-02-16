# Copyright: Ren Tatsumoto <tatsu at autistici.org>
# License: GNU AGPL, version 3 or later; http://www.gnu.org/licenses/agpl.html

import json
import re
from typing import Callable

from anki.cards import Card
from anki.hooks import wrap
from aqt import gui_hooks, tr
from aqt.reviewer import Reviewer
from anki.scheduler.v3 import Scheduler as V3Scheduler

from .config import config

_ans_buttons_default = Reviewer._answerButtons


def only_pass_fail(buttons: tuple, default_ease: int) -> tuple[tuple[int, str], ...]:
    def is_again_or_good(ease: int, _label: str) -> bool:
        return ease in (1, default_ease)

    return tuple(button for button in buttons if is_again_or_good(*button))


def apply_label_colors(buttons: tuple, default_ease: int) -> tuple[tuple[int, str], ...]:
    def color_label(ease: int, label: str) -> tuple[int, str]:
        return ease, f"<font color=\"{config.get_color(ease, default_ease)}\">{label}</font>"

    return tuple(color_label(*button) for button in buttons)


def filter_answer_buttons(buttons: tuple, self: Reviewer, _: Card) -> tuple[tuple[int, str], ...]:
    # Called by _answerButtonList, before _answerButtons gets called
    if config['pass_fail'] is True:
        buttons = only_pass_fail(buttons, self._defaultEase())

    if config['color_buttons'] is True:
        buttons = apply_label_colors(buttons, self._defaultEase())

    return buttons


def get_ease_row_css() -> str:
    return """
    <style>
    .ajt__ease_row {
        display: flex;
        flex-flow: row nowrap;
        justify-content: space-between;
        align-items: flex-start;
        max-width: 450px;
        min-width: 200px;
        user-select: none;
        margin: -3px auto 0;
    }
    .ajt__ease_row > * {
        white-space: nowrap;
        font-size: small;
        font-weight: normal;
    }
    .ajt__ease_row > .ajt__stat_txt:only-child {
        margin: 0 auto;
    }
    </style>
    """


def make_buttonless_ease_row(self: Reviewer, front: bool = False) -> str:
    """Returns ease row html when config.remove_buttons is true"""

    def button_time(ease: int) -> str:
        """Returns html with button-time text for the specified Ease."""

        if v3 := self._v3:
            assert isinstance(self.mw.col.sched, V3Scheduler)
            labels = self.mw.col.sched.describe_next_states(v3.states)
        else:
            labels = None

        # Get button time from the default function,
        # but remove `class="nobold"` since it introduces `position: absolute`
        # which prevents the text from being visible when there is no button.
        html = self._buttonTime(ease, v3_labels=labels).replace('class="nobold"', '')
        if config['color_buttons'] is True:
            html = html.replace('<span', f'<span style="color: {config.get_color(ease, self._defaultEase())};"', )
        return html

    def stat_txt():
        """Returns html showing remaining cards, e.g. 10+70+108"""
        return f'<div class="ajt__stat_txt">{self._remaining()}</div>'

    ease_row = []
    if front is False or config['flexible_grading'] is True:
        ease_row.extend(button_time(ease) for ease, label in self._answerButtonList())
    if front is True:
        ease_row.insert(len(ease_row) // 2, stat_txt())
    return get_ease_row_css() + f'<div class="ajt__ease_row">{"".join(ease_row)}</div>'


def disable_buttons(html: str) -> str:
    return html.replace('<button', '<button disabled')


def make_backside_answer_buttons(self: Reviewer, _old: Callable) -> str:
    if config['remove_buttons'] is True:
        return make_buttonless_ease_row(self)
    elif config['prevent_clicks'] is True:
        return disable_buttons(_old(self))
    else:
        return _old(self)


def make_show_ans_table_cell(self: Reviewer):
    """Creates html code with a table data-cell holding the "Show answer" button."""

    def make_show_ans_button() -> str:
        """Copypasted from Reviewer._showAnswerButton, removed id to fix margin-bottom."""
        return """
        <button title="{}" onclick='pycmd("ans");'>{}<span class=stattxt>{}</span></button>
        """.format(
            tr.actions_shortcut_key(val=tr.studying_space()),
            tr.studying_show_answer(),
            self._remaining(),
        )

    return f'<td align=center>{make_show_ans_button()}</td>'


def calc_middle_insert_pos(buttons_html_table: str) -> int:
    cell_positions = [m.start() for m in re.finditer(r'<td', buttons_html_table)]
    return cell_positions[:len(cell_positions) // 2 + 1][-1]


def make_flexible_front_row(self: Reviewer) -> str:
    ans_buttons = _ans_buttons_default(self)
    insert_pos = calc_middle_insert_pos(ans_buttons)
    html = ans_buttons[:insert_pos] + make_show_ans_table_cell(self) + ans_buttons[insert_pos:]
    return html


def make_frontside_answer_buttons(self: Reviewer) -> None:
    html = None
    if config['remove_buttons'] is True:
        html = make_buttonless_ease_row(self, front=True)
    elif config['flexible_grading'] is True:
        html = make_flexible_front_row(self)
        if config['prevent_clicks'] is True:
            html = disable_buttons(html)
    if html is not None:
        self.bottom.web.eval("showAnswer(%s);" % json.dumps(html))
        self.bottom.web.adjustHeightToFit()


def main():
    # (*) Create html layout for the answer buttons on the back side.
    # Buttons are either removed, disabled or left unchanged depending on config options.
    # noinspection PyProtectedMember
    Reviewer._answerButtons = wrap(Reviewer._answerButtons, make_backside_answer_buttons, "around")

    # Wrap front side button(s).
    # noinspection PyProtectedMember
    Reviewer._showAnswerButton = wrap(Reviewer._showAnswerButton, make_frontside_answer_buttons, "after")

    # Edit (ease, label) tuples which are used to create answer buttons.
    # If `color_buttons` is true, labels are colored.
    # If `pass_fail` is true, "Hard" and "Easy" buttons are removed.
    # This func gets called inside _answerButtonList, which itself gets called inside _answerButtons (*)
    gui_hooks.reviewer_will_init_answer_buttons.append(filter_answer_buttons)
