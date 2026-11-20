"""Request plans for joint targets and saved records."""

import xml.etree.ElementTree as ET

from rcl_interfaces.srv import GetParameters


def request(driver, joints, target_pose, name):
    driver.check_motion_guard()
    assert driver.node.request_joint_plan(joints, target_pose, name)
    driver.until(lambda: not driver.node.is_planning)


def replay(driver, name):
    driver.parameters(record_name=name)
    driver.recording.recorder.poses = {}
    driver.call('load_pose')
    driver.call('plan_return')
    driver.until(lambda: not driver.node.is_planning)


def named_target(driver, name):
    service = driver.client.create_client(GetParameters, '/move_group/get_parameters')
    driver.until(service.service_is_ready)
    request = GetParameters.Request(names=['robot_description_semantic'])
    xml = driver.result(service.call_async(request)).values[0].string_value
    state = ET.fromstring(xml).find(f"group_state[@group='arm'][@name='{name}']")
    assert state is not None, name
    joints = {joint.attrib['name']: float(joint.attrib['value']) for joint in state.findall('joint')}
    assert set(joints) == {f'joint{i}' for i in range(1, 7)}
    return joints, driver.fk(joints)
