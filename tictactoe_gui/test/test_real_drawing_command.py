"""Real drawing requests validate before entering the motion queue."""
import pytest
from tictactoe_gui.workbench import validate_command


@pytest.mark.parametrize('shape',['x','o','grid'])
@pytest.mark.parametrize('speed',[.05,.1,.2,.4,1.0])
def test_real_drawing_request(shape,speed):
    result=validate_command(dict(kind='draw',shape=shape,size=.012,speed=speed),'real')
    assert result['center'] == [.5,.5]
    assert result['shape'] == shape


@pytest.mark.parametrize('change',[
    {'shape':'unknown'},{'size':True},{'size':.1},{'size':float('nan')},
    {'speed':1.01},{'center':[2,.5]},{'center':[False,.5]},{'center':[.5]}])
def test_invalid_request_rejected(change):
    data=dict(kind='draw',shape='x',size=.012,speed=.05);data.update(change)
    with pytest.raises(ValueError): validate_command(data,'real')


def test_real_profile_cannot_be_requested_in_simulation():
    with pytest.raises(ValueError): validate_command(dict(kind='draw',shape='x',speed=.05),'sim')


def test_first_stop_cause_survives_later_cleanup_requests(tmp_path):
    from tictactoe_gui.workbench import WorkbenchSession
    session=WorkbenchSession(tmp_path,'real')
    session.update(state='running',job=3,busy=True)
    session.request_stop('feedback age exceeded','feedback_guard')
    first=session.status()['last_stop']
    session.request_stop()
    assert session.status()['last_stop'] == first
    assert first['source'] == 'feedback_guard' and first['job'] == 3
    session.stop.clear()
    session.request_stop()
    assert session.status()['last_stop'] == first
    session.stop.clear()
    session.update(job=4)
    session.request_stop()
    assert session.status()['last_stop']['source'] == 'caller'


@pytest.mark.parametrize('command', [
    {'kind':'jog', 'axis':'x', 'distance':.001},
    {'kind':'preset', 'name':'clear'},
    {'kind':'return', 'name':'example'},
    {'kind':'canvas', 'strokes':[[[.2,.2],[.3,.3]]]},
])
def test_real_motion_accepts_full_scaling(command):
    assert validate_command(dict(command, speed=1.0), 'real')['speed'] == 1.0
    with pytest.raises(ValueError):
        validate_command(dict(command, speed=1.01), 'real')


def test_reset_keeps_its_own_speed_limit():
    assert validate_command({'kind':'reset', 'speed':.1}, 'real')['speed'] == .1
    with pytest.raises(ValueError):
        validate_command({'kind':'reset', 'speed':.2}, 'real')
