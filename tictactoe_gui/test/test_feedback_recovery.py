"""Exercise loss, recovery and acknowledgement without robot motion."""
from types import SimpleNamespace

import pytest

from tictactoe_gui.feedback_recovery import FeedbackRecovery, recovery_sample
from tictactoe_gui.workbench import WorkbenchSession


def sample(stamp, change=0.):
    return (stamp, stamp), (change,)*6


def observe_from(clock, recovery, start, stop, change=0.):
    for index in range(start, stop):
        clock[0] = index/10
        recovery(clock[0], True, sample(clock[0]+1, change), .0001)


def test_feedback_stop_requires_confirmation_and_never_queues_replay(tmp_path, monkeypatch):
    clock = [0.]
    monkeypatch.setattr('tictactoe_gui.workbench.time.monotonic', lambda: clock[0])
    session = WorkbenchSession(tmp_path, 'real')
    session.active_operation = 'canvas'
    session.last_known_pose = {'z': .206}
    session.update(state='running', busy=True, fresh=True, job=17, plan={'old': True},
                   drawing_progress={'stage': '2_draw'})
    session.request_stop('lost', 'feedback_guard')
    incident = session.status()['feedback_recovery']
    assert incident['operation'] == 'canvas'
    assert incident['drawing_progress']['stage'] == '2_draw'
    assert incident['last_known_pose'] == {'z': .206}
    assert session.status()['plan'] is None
    # Live data on its own cannot unlock an unfinished cancellation.
    observe_from(clock, session.observe_recovery, 1, 30)
    assert session.status()['feedback_recovery']['phase'] == 'waiting'
    session.finish_stop()
    with pytest.raises(RuntimeError):
        session.submit({'kind':'jog', 'axis':'z', 'distance': .001})
    observe_from(clock, session.observe_recovery, 30, 52)
    assert session.status()['feedback_recovery']['phase'] == 'confirmation'
    for job in (16, True, None):
        with pytest.raises(RuntimeError):
            session.submit({'kind':'acknowledge_recovery', 'job':job})
    assert session.submit({'kind':'acknowledge_recovery', 'job':17}) == 17
    assert session.status()['state'] == 'ready'
    assert session.status()['last_stop']['source'] == 'feedback_guard'
    assert session.jobs.empty() and session.status()['plan'] is None
    with pytest.raises(RuntimeError):
        session.submit({'kind':'execute'})
    assert session.submit({'kind':'jog', 'axis':'z', 'distance': .001}) == 18


def test_feedback_timeout_stays_paused_even_if_feedback_returns(tmp_path):
    session = WorkbenchSession(tmp_path, 'real')
    session.update(job=4, busy=True)
    session.request_stop('lost', 'feedback_guard')
    until = session.status()['feedback_recovery']['deadline_s']
    session.observe_recovery(until + .1, False, sample(10), .0001)
    assert session.status()['feedback_recovery']['phase'] == 'timeout'
    session.finish_stop()
    session.observe_recovery(until+2, True, sample(12), .0001)
    with pytest.raises(RuntimeError):
        session.acknowledge_recovery(4)
    with pytest.raises(RuntimeError):
        session.submit({'kind':'reset','speed':.05})


def test_restored_gate_revokes_on_gap_or_motion():
    recovery = FeedbackRecovery(0, {})
    clock = [0.]
    observe_from(clock, recovery.observe, 0, 22)
    assert recovery.phase == 'confirmation'
    assert not recovery.can_acknowledge(clock[0]+.4)
    recovery.observe(2.5, True, sample(3.5), .0001)
    assert recovery.phase == 'waiting'
    observe_from(clock, recovery.observe, 26, 48)
    assert recovery.phase == 'confirmation'
    recovery.observe(4.8, True, sample(5.8, .01), .0001)
    assert recovery.phase == 'waiting'


def test_repeated_source_stamps_cannot_satisfy_window():
    recovery = FeedbackRecovery(0., {})
    for i in range(45):
        recovery.observe(i/10, True, sample(1.), .0001)
    assert recovery.phase == 'waiting'


def test_recovery_sample_requires_fresh_complete_joint_and_tf_data():
    header = lambda sec: SimpleNamespace(stamp=SimpleNamespace(sec=sec, nanosec=0))
    state = SimpleNamespace(header=header(100),
                            name=[f'joint{i}' for i in range(1,7)], position=[0.]*6)
    transform = SimpleNamespace(header=header(100), transform=SimpleNamespace(
        translation=SimpleNamespace(x=0., y=0., z=.2),
        rotation=SimpleNamespace(x=0., y=0., z=0., w=1.)))
    assert recovery_sample(10., 100.1, state, transform, 9.9, 1.) == sample(100)
    assert recovery_sample(10., 100.1, state, transform, 9.4, 1.) is None
    transform.header = header(98)
    assert recovery_sample(10., 100.1, state, transform, 9.9, 1.) is None
    transform.header = header(100)
    state.position.pop()
    assert recovery_sample(10., 100.1, state, transform, 9.9, 1.) is None


def test_ordinary_stop_keeps_existing_resume_contract(tmp_path):
    session = WorkbenchSession(tmp_path, 'real')
    session.update(job=1)
    session.request_stop()
    session.finish_stop()
    assert session.status()['state'] == 'ready'
    assert session.status().get('feedback_recovery') is None
