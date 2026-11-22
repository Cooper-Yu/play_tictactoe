"""A feedback gap during suspended approach cannot cause ink replay."""
from types import SimpleNamespace
import pytest
import requests
from tictactoe_gui.workstation_client import draw_canvas_with_feedback_recovery


def make_client(state):
    calls=[];recovered=[]
    def command(**kw):
        calls.append(kw)
        if len(calls)==1: raise RuntimeError('Feedback interrupted')
        return {'passed':True}
    client=SimpleNamespace(command=command,last_command_job=34,
        get=lambda *a,**k:state,diagnostic=lambda *a:None,
        recover_feedback=lambda:recovered.append(True) or dict(pose={'z':.216}))
    return client,calls,recovered


def baseline():
    return dict(job=34,pose={'z':.216},last_stop=dict(job=34,source='feedback_guard'),
        drawing_progress=dict(stage='approach',source_stroke=1,completed_input_strokes=0,
                              completed_parts=0,total_input_strokes=2))


def test_measured_initial_approach_gap_replans_only_after_recovery():
    client,calls,recovered=make_client(baseline())
    assert draw_canvas_with_feedback_recovery(client,[[],[]])['passed']
    assert len(calls)==2 and recovered==[True]


@pytest.mark.parametrize('change', ['draw','lower','second_stroke','caller','other_job'])
def test_contact_progress_or_unrelated_stop_never_replayed(change):
    s=baseline()
    if change=='draw': s['drawing_progress']['stage']='1_draw'
    if change=='lower': s['drawing_progress']['stage']='1_lower';s['pose']['z']=.206
    if change=='second_stroke': s['drawing_progress']['source_stroke']=2;s['drawing_progress']['completed_input_strokes']=1
    if change=='caller': s['last_stop']['source']='caller'
    if change=='other_job': s['job']=35
    client,calls,recovered=make_client(s)
    with pytest.raises(RuntimeError):draw_canvas_with_feedback_recovery(client,[[],[]])
    assert len(calls)==1 and not recovered


def test_unknown_transport_submission_is_never_retried():
    calls=[]
    def command(**kw):calls.append(kw);raise requests.Timeout('unknown POST outcome')
    client=SimpleNamespace(command=command,get=lambda *a,**k:pytest.fail('Do not infer a POST outcome'))
    with pytest.raises(requests.Timeout):draw_canvas_with_feedback_recovery(client,[[],[]])
    assert len(calls)==1
