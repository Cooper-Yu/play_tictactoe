"""A loading arm controller must not be mistaken for failed simulation readiness."""

from types import SimpleNamespace
from unittest.mock import Mock

from tictactoe_driver.simulation_driver import SimulationDriver


def test_preflight_waits_for_arm_controller(monkeypatch, tmp_path):
    monkeypatch.setenv('ROS_LOCALHOST_ONLY', '1')
    service = Mock()
    service.service_is_ready.return_value = True
    harness = SimulationDriver.__new__(SimulationDriver)
    harness.output = tmp_path
    harness.recording = SimpleNamespace(environment='sim', recorder=SimpleNamespace(poses_file=tmp_path/'poses.json'))
    harness.node = Mock()
    harness.node.get_parameter.return_value.value = True
    harness.node.feedback_is_fresh.return_value = True
    harness.node.tf_buffer.can_transform.return_value = True
    harness.client = Mock()
    harness.client.get_node_names_and_namespaces.return_value = [('gazebo','/'),('move_group','/')]
    harness.client.create_client.return_value = service
    controller = lambda name: SimpleNamespace(name=name, state='active')
    responses = iter([SimpleNamespace(controller=[controller('joint_state_broadcaster')]),
                      SimpleNamespace(controller=[controller('joint_state_broadcaster'),controller('arm_controller')])])
    harness.result = lambda future: next(responses)
    harness.until = Mock()
    states = harness.preflight()
    assert states['arm_controller'] == 'active'
    assert service.call_async.call_count == 2

def test_preflight_allows_delayed_graph_discovery(monkeypatch, tmp_path):
    monkeypatch.setenv('ROS_LOCALHOST_ONLY', '1')
    harness=SimulationDriver.__new__(SimulationDriver)
    harness.output=tmp_path
    harness.recording=SimpleNamespace(environment='sim',recorder=SimpleNamespace(poses_file=tmp_path/'p.json'))
    harness.node=Mock()
    harness.node.get_parameter.return_value.value=True
    harness.client=Mock()
    harness.client.get_node_names_and_namespaces.side_effect=[
        [('robot_state_publisher','/')], [('gazebo','/'),('move_group','/')],
        [('gazebo','/'),('move_group','/')]]
    def poll(predicate, timeout=20):
        for _ in range(5):
            if predicate():return
        raise TimeoutError('fixture not ready')
    harness.until=poll
    harness.result=lambda f: SimpleNamespace(controller=[SimpleNamespace(name='arm_controller',state='active')])
    assert harness.preflight()['arm_controller']=='active'
    assert harness.client.get_node_names_and_namespaces.call_count==3
