"""Wait for the owned Gazebo arm, repairing a stranded loader without motion goals."""
import argparse
import json
import os
from pathlib import Path
import time

import rclpy
from controller_manager_msgs.srv import ListControllers, ConfigureController, SwitchController
from simulation_session import owned_processes, simulator_processes


def arm_operation(state, grace_elapsed):
    """! @brief Allow only configure/activate after the original loader's grace period."""
    if not grace_elapsed:
        return None
    return {'unconfigured': 'configure', 'inactive': 'activate'}.get(state)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    args=parser.parse_args()
    tag=os.environ.get('PLAY_TICTACTOE_SESSION')
    assert tag and os.environ.get('ROS_LOCALHOST_ONLY')=='1', 'Managed local-only session required'
    rclpy.init(args=[])
    node=rclpy.create_node('gazebo_controller_readiness')
    clients={}
    deadline=time.monotonic()+60
    def rpc(kind,name,request):
        if name not in clients:clients[name]=node.create_client(kind,'/controller_manager/'+name)
        client=clients[name]
        if not client.wait_for_service(timeout_sec=min(5.,max(.1,deadline-time.monotonic()))):
            raise RuntimeError('Controller service unavailable: '+name)
        future=client.call_async(request)
        rclpy.spin_until_future_complete(node,future,timeout_sec=8.)
        if not future.done():
            future.cancel()
            raise RuntimeError('Unknown controller request outcome: '+name)
        return future.result()
    def check_owned_simulator():
        owners=set(owned_processes(tag))
        assert any(pid in owners and name.startswith('gzserver') for pid,name in simulator_processes()), 'Owned Gazebo server required'
        names={name for name,_ in node.get_node_names_and_namespaces()}
        assert 'gazebo' in names and not any('zenoh' in n or 'piper_ctrl' in n for n in names), 'Simulation-only graph required'
    operations=[]
    first_pending=None
    repairing=False
    try:
        while time.monotonic()<deadline:
            states={c.name:c.state for c in rpc(ListControllers,'list_controllers',ListControllers.Request()).controller}
            arm=states.get('arm_controller')
            if arm=='active' and states.get('joint_state_broadcaster')=='active':
                check_owned_simulator()
                Path(args.output).write_text(json.dumps({'states':states,'repairs':operations},indent=2))
                print('SIM_CONTROLLERS_READY '+json.dumps({'repairs':operations}),flush=True)
                return
            if first_pending is None and arm in ('unconfigured','inactive'):first_pending=time.monotonic()
            operation=arm_operation(arm,repairing or (first_pending is not None and time.monotonic()-first_pending>=15))
            if operation:
                check_owned_simulator()
                if operation=='configure':
                    request=ConfigureController.Request(name='arm_controller')
                    response=rpc(ConfigureController,'configure_controller',request)
                else:
                    request=SwitchController.Request(activate_controllers=['arm_controller'],strictness=2,activate_asap=True)
                    request.timeout.sec=5
                    response=rpc(SwitchController,'switch_controller',request)
                if not response.ok:raise RuntimeError('Arm '+operation+' rejected')
                operations.append(operation)
                repairing=True
            pause=time.monotonic()+.2
            while time.monotonic()<pause:rclpy.spin_once(node,timeout_sec=.05)
        raise TimeoutError('Arm controller did not become active')
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__=='__main__':main()
