"""Gazebo-only canvas mapping, measured virtual ink and Reset gesture acceptance."""
import argparse
import copy
import math
from pathlib import Path
import sys
import time
import yaml
import cv2
from cv_bridge import CvBridge
from sensor_msgs.msg import Image
from rclpy.qos import qos_profile_sensor_data
from rclpy.utilities import remove_ros_args
from gazebo_msgs.srv import GetModelList
from simulation_support import SimulationHarness,write_report
from board_scene_support import verify_scene
from tictactoe_motion.canvas.board_canvas import BoardCanvas
from tictactoe_motion.canvas.canvas_drawing import CanvasDrawing
from tictactoe_motion.simulation.simulated_board import SimulatedBoard


def circle(canvas,center,radius=.01,count=128):
    points=[(center[0]+radius/(canvas.x1-canvas.x0)*math.cos(2*math.pi*i/count),
             center[1]+radius/(canvas.y1-canvas.y0)*math.sin(2*math.pi*i/count)) for i in range(count)]
    return points+[points[0]]


def radial_error(points,center,radius=.01):
    samples=[]
    for a,b in zip(points,points[1:]):
        for i in range(11):samples.append((a[0]+(b[0]-a[0])*i/10,a[1]+(b[1]-a[1])*i/10))
    return max(abs(math.dist(p,center)-radius) for p in samples)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True)
    p.add_argument('--test-stop',action='store_true')
    args=p.parse_args(remove_ros_args(sys.argv)[1:]);profile=yaml.safe_load((Path(__file__).parents[1]/'config/board_sim.yaml').read_text())
    canvas=BoardCanvas(profile);h=SimulationHarness(args.output);renderer=None
    generation=h.execution.stop.generation
    h.motion_guard=lambda:(h.execution.stop.generation!=generation or h.execution.stop.status.get('state') in ('stop_requested','stopped','blocked'))
    report={'scenario':'bounded canvas, grid/smooth curves, measured virtual ink and Reset','simulation_only':True,
            'geometry':profile,'grid_nodes':[canvas.nx+1,canvas.ny+1]}
    report['motion_settings']={key:h.node.get_parameter(key).value for key in ('velocity_scaling','acceleration_scaling','cartesian_speed')}
    frame={'msg':None}
    subscription=h.client.create_subscription(Image,'/camera1/image_raw',lambda msg:frame.update(msg=msg),qos_profile_sensor_data)
    bridge=CvBridge()
    def screenshot(name):
        frame['msg']=None;h.until(lambda:frame['msg'] is not None,10)
        cv2.imwrite(str(Path(args.output)/(name+'.png')),bridge.imgmsg_to_cv2(frame['msg'],'bgr8'))
    try:
        report['controllers']=h.preflight();report['live_scene']=verify_scene(profile)
        renderer=SimulatedBoard(h.client,profile,Path(args.output)/'ink',h.result)
        h.until(lambda:renderer.spawn.service_is_ready() and renderer.delete.service_is_ready())
        listing=h.client.create_client(GetModelList,'/get_model_list');h.until(listing.service_is_ready)
        report['zero_start']=h.named('zero')
        _,target=h.named_target('clear');target=copy.deepcopy(target);target.position.z=profile['hover_link6_z_m']
        report['orientation_setup']=h.pose(target)
        screenshot('before')
        painted=[];original_path=h.path
        def paint_path(poses):
            result=original_path(poses)
            item=renderer.paint(h.results[-1]['samples']);painted.append(item)
            print('INK '+item['model'],flush=True)
            return result
        h.path=paint_path
        shapes=[('cross',[[ (.30,.4),(.44,.50)],[ (.30,.50),(.44,.4)]],True),
                ('grid_circle',[circle(canvas,(.65,.4))],True),
                ('smooth_circle',[circle(canvas,(.65,.58))],False)]
        report['shapes']={}
        for name,strokes,snap in shapes:
            drawing=CanvasDrawing(canvas,strokes,snap=snap)
            offset=len(h.results)
            stages=drawing.run(h,cancelled=h.motion_guard,on_stage=lambda stage:print('STAGE '+name+' '+stage,flush=True))
            item={'stages':stages,'waypoints':[len(path) for path in drawing.paths]}
            if 'circle' in name:
                center_uv=(.65,.4 if snap else .58)
                center=(canvas.x0+center_uv[0]*(canvas.x1-canvas.x0),canvas.y1-center_uv[1]*(canvas.y1-canvas.y0))
                item['planned_max_radial_error_m']=radial_error(drawing.paths[0],center)
                draw_result=h.results[offset+2]
                item['actual_max_radial_error_m']=max(abs(math.dist(s['xyz'][:2],center)-.01) for s in draw_result['samples'])
                assert item['actual_max_radial_error_m'] < (.0006 if snap else .0003),item
            item['draw_duration_s']=sum(execution['planned_duration_s'] for stage,execution in zip(stages,h.results[offset:]) if stage['stage'].endswith('_draw'))
            report['shapes'][name]=item
        report['painted']=painted
        models=h.result(listing.call_async(GetModelList.Request())).model_names
        assert len(renderer.models)==4 and set(renderer.models).issubset(models)
        # Allow the camera renderer to load the spawned meshes before taking evidence.
        deadline=time.monotonic()+2;h.until(lambda:time.monotonic()>=deadline,4)
        screenshot('written')
        reset=copy.deepcopy(target);reset.position.x,reset.position.y=profile['reset_center'][:2]
        report['reset_hover']=h.pose(reset)
        lower=copy.deepcopy(reset.position);lower.z=profile['drawing_link6_z_m']
        report['reset_down']=h.linear(lower)
        assert renderer.press_reset(h.results[-1]['samples'])
        report['reset_clear']=True
        report['reset_up']=h.linear(reset.position)
        models=h.result(listing.call_async(GetModelList.Request())).model_names
        assert not any(item['model'] in models for item in painted)
        deadline=time.monotonic()+1;h.until(lambda:time.monotonic()>=deadline,3);screenshot('cleared')
        report['zero_finish']=h.named('zero')
        if args.test_stop:
            # An independent operator-like test, not automatic continuation after a cancelled drawing.
            h.motion_guard=None
            start=copy.deepcopy(target);start.position.x=.22;start.position.y=-.02
            h.pose(start)
            actual=h.current_pose()
            assert h.node.cartesian_planner.request_xy(.03,0.)
            h.until(lambda:not h.node.is_planning);h.guard()
            h.call('execute_planned_trajectory')
            h.until(lambda:h.execution.execution_goal_handle is not None)
            h.until(lambda:abs(h.current_pose().position.x-actual.position.x)>.0005,5)
            stamp=time.monotonic();h.call('stop_motion')
            h.until(lambda:h.execution.stop.status.get('state') in ('stopped','stop_blocked'),10)
            assert h.execution.stop.status['state']=='stopped',h.execution.stop.status
            assert not h.execution.is_executing and h.node.planned_trajectory is None
            rejected=h.call('execute_planned_trajectory',success=False)
            report['stop_test']={'confirmed':True,'confirmation_wall_s':time.monotonic()-stamp,'old_plan_rejected':not rejected.success,'status':copy.deepcopy(h.execution.stop.status)}
            report['zero_after_stop']=h.named('zero')
        report['passed']=True
    except BaseException as error:
        report.update(passed=False,error=repr(error));print('FAIL',repr(error),flush=True)
    finally:
        if renderer:
            try:renderer.close()
            except Exception as error:report.update(passed=False,cleanup_error=repr(error))
        h.client.destroy_subscription(subscription)
        report['executions']=h.results;h.close()
        write_report(Path(args.output)/'board_canvas.json',report)
        print('REPORT',report.get('passed'),args.output,flush=True)
    if not report.get('passed'):sys.exit(1)


if __name__=='__main__':main()
