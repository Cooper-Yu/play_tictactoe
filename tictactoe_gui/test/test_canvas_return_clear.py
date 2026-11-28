"""No hardware: exercise the successful-completion return boundary."""
from types import SimpleNamespace

import pytest

from tictactoe_gui.canvas_action import CanvasAction


def setup_return():
    action = CanvasAction.__new__(CanvasAction)
    action.stages = [{'stage': 'exit_lift', 'result': {'passed': True}}]
    action.drawings = [SimpleNamespace(transfer_z=.216)]
    calls = []
    driver = SimpleNamespace(
        node=SimpleNamespace(feedback_is_fresh=lambda: True),
        current_pose=lambda: SimpleNamespace(position=SimpleNamespace(z=.216)),
        named=lambda name: calls.append(name) or {'passed': True},
    )
    return action, driver, calls


def test_success_returns_to_clear_once_and_keeps_result():
    action, driver, calls = setup_return()
    assert action.return_to_clear(driver) == {'passed': True}
    assert calls == ['clear']
    assert action.stages[-1] == {'stage': 'return_clear', 'result': {'passed': True}}


@pytest.mark.parametrize('condition', ['cancelled', 'incomplete', 'lift_failed',
                                       'stale', 'low', 'nan'])
def test_no_return_on_failed_or_cancelled_drawing(condition):
    action, driver, calls = setup_return()
    if condition == 'incomplete':
        action.stages = [{'stage': '1_draw', 'result': {'passed': True}}]
    if condition == 'lift_failed':
        action.stages[-1]['result']['passed'] = False
    if condition == 'stale':
        driver.node.feedback_is_fresh = lambda: False
    if condition in ('low', 'nan'):
        driver.current_pose = lambda: SimpleNamespace(position=SimpleNamespace(
            z=.206 if condition == 'low' else float('nan')))
    with pytest.raises(RuntimeError):
        action.return_to_clear(driver, cancelled=lambda: condition == 'cancelled')
    assert calls == []


@pytest.mark.parametrize('result', [None, {'passed': False}])
def test_rejected_return_does_not_report_success(result):
    action, driver, calls = setup_return()
    driver.named = lambda name: calls.append(name) or result
    with pytest.raises(RuntimeError, match='failed verification'):
        action.return_to_clear(driver)
    assert calls == ['clear']
    assert action.stages[-1]['result'] == result


def test_cancellation_after_feedback_check_prevents_return():
    action, driver, calls = setup_return()
    checks = iter([False, True])
    with pytest.raises(RuntimeError, match='cancelled'):
        action.return_to_clear(driver, cancelled=lambda: next(checks))
    assert calls == []
