"""Real drawing requests validate before entering the motion queue."""
import pytest
from tictactoe_gui.workbench import validate_command


@pytest.mark.parametrize('shape',['x','o','grid'])
def test_real_drawing_request(shape):
    result=validate_command(dict(kind='draw',shape=shape,size=.012,speed=.05),'real')
    assert result['center'] == [.5,.5]
    assert result['shape'] == shape


@pytest.mark.parametrize('change',[
    {'shape':'chair'},{'size':True},{'size':.1},{'size':float('nan')},
    {'speed':.1},{'center':[2,.5]},{'center':[False,.5]},{'center':[.5]}])
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
    assert session.status()['last_stop']['source'] == 'caller'
