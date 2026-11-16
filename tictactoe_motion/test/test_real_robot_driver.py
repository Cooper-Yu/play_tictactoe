"""Hardware-profile gates, without connecting to or moving a robot."""
import pytest
from tictactoe_motion.real_robot_driver import require_real_profile

NAMES = ['motion_planner', 'move_group', 'piper_ctrl_single_node', 'zenoh_bridge_ros2dds']


def test_real_profile_requires_explicit_real_clock_and_physical_graph():
    require_real_profile('real', False, NAMES)
    for environment, clock, names in [
        ('sim', False, NAMES), ('real', True, NAMES),
        ('real', False, NAMES+['gazebo']),
        ('real', False, NAMES+['motion_planner']),
        ('real', False, NAMES[1:]),
        ('real', False, ['motion_planner', 'move_group']),
    ]:
        with pytest.raises(ValueError):
            require_real_profile(environment, clock, names)
