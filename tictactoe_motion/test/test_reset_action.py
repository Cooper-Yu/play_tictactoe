"""Exercise Reset sequence order, vertical movement, rejection and cancellation."""
import copy
from types import SimpleNamespace as S
from unittest.mock import Mock
import pytest
from tictactoe_motion.reset_action import ResetAction


def record(z):
    return dict(environment='real', tip_link='link6',
        pose_stamped={'header':{'frame_id':'base_link'}, 'pose':{
        'position':dict(x=.22684,y=-.10757,z=z),
        'orientation':dict(x=0.,y=1.,z=0.,w=0.)}})


class Driver:
    def __init__(self, z=.25):
        self.pose=S(position=S(x=.2,y=-.05,z=z))
        self.records={'reset悬空预备':record(.214),'Reset':record(.208)}
        self.recording=S(_reload=lambda:None, environment='real',
                         recorder=S(get_pose=lambda name:self.records[name]))
        self.node=S(is_planning=False)
        self.calls=[]
        self.stopped=False
        self.fail=False
        self.cancel_on_press=False
    def check_motion_guard(self):
        if self.stopped: raise RuntimeError('Stopped')
    def current_pose(self): return copy.deepcopy(self.pose)
    def parameters(self, **kw): self.calls.append(('parameters',kw))
    def linear(self, target):
        self.check_motion_guard()
        self.calls.append(('linear',copy.deepcopy(target)))
        self.pose.position=copy.deepcopy(target)
        if target.z==.208 and self.cancel_on_press:self.stopped=True
    def call(self, name):self.calls.append(('call',name))
    def guard(self, limit):self.calls.append(('guard',limit))
    def execute(self):
        self.check_motion_guard()
        self.pose.position=S(x=.22684,y=-.10757,z=.214)
        return {'passed':not self.fail}
    def until(self, predicate, timeout):
        # Spin only the bounded dwell; planning is immediately ready in this fake.
        import time
        deadline=time.monotonic()+timeout
        while not predicate():
            assert time.monotonic()<deadline
            time.sleep(.001)


def test_cycle_lifts_before_travel_then_press_and_retreat():
    d=Driver(.202)
    stages=[]
    result=ResetAction(d,stages.append).run(.1)
    targets=[v for k,v in d.calls if k=='linear']
    assert [p.z for p in targets]==[.214,.208,.214]
    assert targets[0].x==.2  # Lift at current XY before lateral travel.
    assert targets[1].x==targets[2].x==.22684
    assert targets[1].y==targets[2].y==-.10757
    assert ('parameters',dict(velocity_scaling=.05,acceleration_scaling=.05)) in d.calls
    assert result['motion_completed'] and result['clear_confirmed'] is None


def test_cancellation_after_press_does_not_retreat_automatically():
    d=Driver();d.cancel_on_press=True
    with pytest.raises(RuntimeError,match='Stopped'):ResetAction(d).run()
    assert [p.z for k,p in d.calls if k=='linear']==[.208]


def test_failed_hover_verification_never_presses():
    d=Driver();d.fail=True
    with pytest.raises(RuntimeError,match='verification'):ResetAction(d).run()
    assert not any(k=='linear' for k,_ in d.calls)


@pytest.mark.parametrize('problem',['xy','height','orientation','environment','frame','missing'])
def test_invalid_records_rejected_before_moving(problem):
    d=Driver(.202)
    h,p=d.records.values()
    if problem=='xy':p['pose_stamped']['pose']['position']['x']+=.01
    elif problem=='height':p['pose_stamped']['pose']['position']['z']=.22
    elif problem=='orientation':p['pose_stamped']['pose']['orientation']=dict(x=0,y=0,z=0,w=1)
    elif problem=='environment':p['environment']='sim'
    elif problem=='frame':p['pose_stamped']['header']['frame_id']='world'
    else:del d.records['Reset']
    with pytest.raises((ValueError,KeyError)):ResetAction(d).run()
    assert not d.calls


def test_new_press_xy_is_reached_at_hover_and_original_prep_is_restored():
    driver = Driver()
    press = driver.records['Reset']['pose_stamped']['pose']['position']
    press.update(x=.22885, y=-.10756, z=.20697)

    result = ResetAction(driver).run()

    targets = [target for operation, target in driver.calls if operation == 'linear']
    assert [(p.x, p.y, p.z) for p in targets] == [
        (.22885, -.10756, .214),
        (.22885, -.10756, .20697),
        (.22885, -.10756, .214),
        (.22684, -.10757, .214),
    ]
    assert result['vertical_distance_m'] == pytest.approx(.00703)


def test_missed_hover_alignment_never_lowers_to_press():
    driver = Driver()
    driver.records['Reset']['pose_stamped']['pose']['position']['x'] += .002
    driver.linear = Mock()

    with pytest.raises(RuntimeError, match='horizontal alignment verification failed'):
        ResetAction(driver).run()

    assert driver.linear.call_count == 1
    assert driver.linear.call_args.args[0].z == .214


def test_direct_reset_uses_only_full_speed_button_legs():
    driver = Driver(.216)
    driver.records = {'reset悬空预备': record(.216), 'Reset': record(.2069714381)}
    driver.node.cartesian_planner = S(canvas_native_timing=False)

    def execute():
        driver.pose.position = S(x=.22684, y=-.10757, z=.216)
        return {'passed': True}

    original_linear = driver.linear
    legs = []

    def linear(target):
        last_setting = next(value for kind, value in reversed(driver.calls) if kind == 'parameters')
        legs.append((target.z, last_setting['velocity_scaling'],
                     driver.node.cartesian_planner.canvas_native_timing))
        return original_linear(target)

    driver.execute = execute
    driver.linear = linear
    result = ResetAction(driver).run(direct_native=True)

    assert legs == [(.2069714381, 1.0, True), (.216, 1.0, True)]
    assert result['direct_native'] is True
    assert driver.node.cartesian_planner.canvas_native_timing is False
