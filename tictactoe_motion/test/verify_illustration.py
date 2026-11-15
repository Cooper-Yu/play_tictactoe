"""Gazebo-only parameterized grid and a complete explicit-turn Gomoku game."""
import argparse
import hashlib
from importlib.resources import files
import copy
from pathlib import Path
import sys
import time
import signal
import yaml
import cv2
from cv_bridge import CvBridge
from sensor_msgs.msg import Image
from rclpy.qos import qos_profile_sensor_data
from rclpy.utilities import remove_ros_args
from gazebo_msgs.srv import GetModelList
from simulation_support import SimulationHarness,write_report
from board_scene_support import verify_scene
from tictactoe_motion.board_canvas import BoardCanvas
from tictactoe_motion.drawing_actions import DrawingActions
from tictactoe_motion.illustration_drawing import IllustrationDrawing
from tictactoe_motion.simulated_board import SimulatedBoard


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True);p.add_argument('--shape',choices=['chair','docker','smile'],required=True);p.add_argument('--width',type=float,default=.06)
    args=p.parse_args(remove_ros_args(sys.argv)[1:]);profile=yaml.safe_load((Path(__file__).parents[1]/'config/board_sim.yaml').read_text())
    h=SimulationHarness(args.output);renderer=None;report={'simulation_only':True,'scenario':'illustration -> virtual Reset -> zero', 'shape':args.shape}
    # Keep the ROS context alive long enough to cancel and archive on timeout.
    def interrupt(signum, frame):raise KeyboardInterrupt()
    signal.signal(signal.SIGINT,interrupt)
    signal.signal(signal.SIGTERM,interrupt)
    generation=h.execution.stop.generation
    h.motion_guard=lambda:(h.execution.stop.generation!=generation or h.execution.stop.status.get('state') in ('stop_requested','stopped','blocked'))
    frame={'msg':None};sub=h.client.create_subscription(Image,'/camera1/image_raw',lambda msg:frame.update(msg=msg),qos_profile_sensor_data)
    def screenshot(name):
        deadline=time.monotonic()+1;h.until(lambda:time.monotonic()>=deadline,3)
        frame['msg']=None;h.until(lambda:frame['msg'] is not None,10)
        cv2.imwrite(str(Path(args.output)/(name+'.png')),CvBridge().imgmsg_to_cv2(frame['msg'],'bgr8'))
    try:
        report['controllers']=h.preflight();report['live_scene']=verify_scene(profile)
        renderer=SimulatedBoard(h.client,profile,Path(args.output)/'ink',h.result)
        h.until(lambda:renderer.spawn.service_is_ready() and renderer.delete.service_is_ready())
        listing=h.client.create_client(GetModelList,'/get_model_list');h.until(listing.service_is_ready)
        a=DrawingActions(BoardCanvas(profile),h,upper_z=profile['hover_link6_z_m'],depth=profile['hover_link6_z_m']-profile['drawing_link6_z_m'])
        illustration=IllustrationDrawing(a)
        paths=illustration.strokes(args.shape,width=args.width,rotation=180)
        report['asset_sha256']=hashlib.sha256(files('tictactoe_motion').joinpath('illustrations',args.shape+'.json').read_bytes()).hexdigest()
        report['geometry']={'rotation_degrees':180,'width_m':args.width,'strokes':len(paths),'points':sum(map(len,paths))}
        illustration.export_svg(args.shape,Path(args.output)/(args.shape+'.svg'))
        h.named('zero');_,target=h.named_target('clear');target=copy.deepcopy(target);target.position.z=profile['hover_link6_z_m'];h.pose(target)
        screenshot('before');painted=[];original=h.path
        def draw_path(poses):
            result=original(poses,excursion_limit=.75);painted.append(renderer.paint(h.results[-1]['samples']));return result
        h.path=draw_path
        options={'cancelled':h.motion_guard,'on_stage':lambda stage:print('STAGE '+stage,flush=True)}
        report['drawing']=illustration.draw(args.shape,width=args.width,rotation=180,**options)
        report['painted']=painted
        models=h.result(listing.call_async(GetModelList.Request())).model_names
        assert len(renderer.models)==len(paths) and set(renderer.models).issubset(models)
        screenshot('written')
        reset=copy.deepcopy(target);reset.position.x,reset.position.y=profile['reset_center'][:2]
        h.pose(reset);lower=copy.deepcopy(reset.position);lower.z=profile['drawing_link6_z_m'];h.linear(lower)
        assert renderer.press_reset(h.results[-1]['samples']);h.linear(reset.position)
        models=h.result(listing.call_async(GetModelList.Request())).model_names
        assert not any(item['model'] in models for item in painted)
        screenshot('cleared');report['reset_clear']=True;report['zero_finish']=h.named('zero');report['passed']=True
    except BaseException as error:
        report.update(passed=False,error=repr(error));print('FAIL',repr(error),flush=True)
        if not isinstance(error,KeyboardInterrupt) and not h.execution.is_executing and not h.motion_guard():
            try:report['recovery_zero']=h.named('zero')
            except Exception as recovery:report['recovery_error']=repr(recovery)
    finally:
        if renderer:
            try:renderer.close()
            except Exception as error:report.update(passed=False,cleanup_error=repr(error))
        h.client.destroy_subscription(sub);report['executions']=h.results
        try:h.close()
        except Exception as error:report.update(passed=False,close_error=repr(error))
        write_report(Path(args.output)/'illustration.json',report);print('REPORT',report.get('passed'),args.output,flush=True)
    if not report.get('passed'):sys.exit(1)


if __name__=='__main__':main()
