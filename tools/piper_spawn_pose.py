"""Use a known Piper arm pose during managed Gazebo model initialization."""

import math
from pathlib import Path
import xml.etree.ElementTree as ET


def prepare_piper_description_overlay(state_dir):
    """Create a session-local piper_description with the SRDF clear start pose."""
    from ament_index_python.packages import get_package_share_directory
    import xacro

    description = Path(get_package_share_directory('piper_description')).resolve()
    semantic = Path(get_package_share_directory('piper_with_gripper_moveit'))
    srdf = ET.parse(semantic / 'config/piper.srdf')
    clear = srdf.find("./group_state[@name='clear'][@group='arm']")
    joints = {f'joint{i}' for i in range(1, 7)}
    if clear is None:
        raise ValueError('Piper SRDF arm clear pose is missing')
    positions = {joint.attrib['name']: float(joint.attrib['value']) for joint in clear}
    if positions.keys() != joints or not all(map(math.isfinite, positions.values())):
        raise ValueError('Piper SRDF arm clear pose must specify six finite joint positions')

    model = description / 'urdf/piper_description_gazebo.xacro'
    urdf = ET.fromstring(xacro.process_file(str(model)).toxml())
    for name, position in positions.items():
        initial = urdf.find(
            f"./ros2_control[@name='GazeboSystem']/joint[@name='{name}']"
            "/state_interface[@name='position']/param[@name='initial_value']"
        )
        limit = urdf.find(f"./joint[@name='{name}']/limit")
        if initial is None or limit is None:
            raise ValueError(f'Gazebo model is missing the joint initialization for {name}')
        if not float(limit.attrib['lower']) <= position <= float(limit.attrib['upper']):
            raise ValueError(f'Piper SRDF clear position exceeds the URDF limits for {name}')
        initial.text = str(position)

    # The course launch resolves this package through the ament index.
    # Shadow only the Gazebo xacro and keep the rest of the package files available.
    prefix = Path(state_dir) / 'spawn_overlay'
    prefix.mkdir(exist_ok=False)
    marker = prefix / 'share/ament_index/resource_index/packages/piper_description'
    marker.parent.mkdir(parents=True)
    marker.touch()
    share = prefix / 'share/piper_description'
    (share / 'urdf').mkdir(parents=True)
    for entry in description.iterdir():
        if entry.name != 'urdf':
            (share / entry.name).symlink_to(entry)
    for entry in model.parent.iterdir():
        if entry != model:
            (share / 'urdf' / entry.name).symlink_to(entry)
    ET.ElementTree(urdf).write(share / 'urdf' / model.name, encoding='utf-8')
    return prefix, positions
