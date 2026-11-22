"""Do not repeat completed grid lines or a partially executed draw stage."""
import pytest
from tictactoe_gui.grid_recovery import unstarted_grid_tail


def state(**changes):
    progress = dict(shape='canvas', stage='3_lower', completed_input_strokes=2,
        source_stroke=3, completed_parts=2, total_input_strokes=4)
    progress.update(changes)
    return dict(job=6, drawing_progress=progress)


def test_real_lowering_incident_keeps_first_two_lines():
    strokes = [[[.1,i/5],[.9,i/5]] for i in range(1,5)]
    tail, completed = unstarted_grid_tail(strokes, state(), 6)
    assert completed == 2 and tail == strokes[2:]
    tail[0][0][0] = .5
    assert strokes[2][0][0] == .1


@pytest.mark.parametrize('change', [dict(stage='3_draw'), dict(stage='3_lift'),
    dict(stage='exit_lift'), dict(completed_input_strokes=True),
    dict(total_input_strokes=16), dict(completed_parts=3), dict(source_stroke=2)])
def test_uncertain_draw_or_inconsistent_progress_rejected(change):
    with pytest.raises(RuntimeError): unstarted_grid_tail([[]]*4, state(**change), 6)


def test_another_job_cannot_supply_a_grid_checkpoint():
    with pytest.raises(RuntimeError): unstarted_grid_tail([[]]*4, state(), 7)


def test_verified_draw_at_raised_lift_skips_ink_without_replaying_lift():
    strokes = [[[.1,i/5],[.9,i/5]] for i in range(1,5)]
    w = state(stage='3_lift', total_parts=4)
    w.update(fresh=True, busy=False, pose={'z': .211})
    tail, complete = unstarted_grid_tail(strokes,w,6)
    assert complete == 3 and tail == strokes[3:]


@pytest.mark.parametrize('change', ['low','stale','busy','segmented','nonfinite'])
def test_lift_requires_measured_clearance_and_unsegmented_draw(change):
    w=state(stage='3_lift',total_parts=4)
    w.update(fresh=True,busy=False,pose={'z':.211})
    if change=='low': w['pose']['z']=.207
    if change=='stale': w['fresh']=False
    if change=='busy': w['busy']=True
    if change=='segmented': w['drawing_progress']['total_parts']=5
    if change=='nonfinite': w['pose']['z']=float('nan')
    with pytest.raises(RuntimeError):unstarted_grid_tail([[]]*4,w,6)


def test_last_verified_lift_needs_no_new_canvas_request():
    w=state(stage='4_lift',source_stroke=4,completed_input_strokes=3,
            completed_parts=3,total_parts=4)
    w.update(fresh=True,busy=False,pose={'z':.211})
    assert unstarted_grid_tail([[]]*4,w,6)==([],4)


def test_stage_number_must_match_recorded_source_stroke():
    with pytest.raises(RuntimeError):unstarted_grid_tail([[]]*4,state(stage='99_lower'),6)
