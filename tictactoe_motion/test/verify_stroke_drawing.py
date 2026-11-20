"""Gazebo-only X/O with Z lowering, lifting and an elevated inter-stroke transfer."""
import argparse
import copy
import math
from pathlib import Path
import sys
from rclpy.utilities import remove_ros_args
from simulation_support import SimulationHarness, write_report
from tictactoe_motion.actions.stroke_drawing import StrokeDrawing
from tictactoe_motion.trajectory_motion.cartesian_planner import polyline_error


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',required=True)
    args=p.parse_args(remove_ros_args(sys.argv)[1:])
    h=SimulationHarness(args.output)
    generation=h.execution.stop.generation
    h.motion_guard=lambda:(h.execution.stop.generation!=generation or
                          h.execution.stop.status.get('state') in ('stop_requested','stopped','blocked'))
    report={'scenario':'X/O with lower-draw-lift and raised X transfer','simulation_only':True,'depth_m':.01}
    try:
        report['controllers']=h.preflight()
        _,target=h.named_target('clear');target=copy.deepcopy(target);target.position.z+=.03
        report['zero_start']=h.named('zero')
        for shape in ('cross','circle'):
            report[shape]={'target':h.pose(target)}
            drawing=StrokeDrawing(shape)
            offset=len(h.results)
            stages=drawing.run(h,cancelled=h.motion_guard,on_stage=lambda stage:print('STAGE '+shape+' '+stage,flush=True))
            metrics=[]
            for stage,execution in zip(stages,h.results[offset:]):
                samples=execution['samples'];assert len(samples)>=3
                name=stage['stage']; metric={'stage':name,'samples':len(samples)}
                if name.endswith('_draw'):
                    index=int(name.split('_')[0])-1
                    stroke=drawing.strokes[index]
                    metric['max_path_error_m']=max(polyline_error(s['xyz'],stroke) for s in samples)
                    assert metric['max_path_error_m']<.0003,metric
                    if shape=='circle':
                        center=(stroke[0].position.x+.01,stroke[0].position.y)
                        angles=sorted(math.atan2(s['xyz'][1]-center[1],s['xyz'][0]-center[0]) for s in samples)
                        gaps=[b-a for a,b in zip(angles,angles[1:])]+[angles[0]+2*math.pi-angles[-1]]
                        metric['max_angular_gap_rad']=max(gaps);assert max(gaps)<.25,metric
                elif name.endswith('_transfer'):
                    metric['max_height_error_m']=max(abs(s['xyz'][2]-target.position.z) for s in samples)
                    assert metric['max_height_error_m']<.0003,metric
                else:
                    origin=samples[0]['xyz']
                    metric['max_xy_drift_m']=max(math.hypot(s['xyz'][0]-origin[0],s['xyz'][1]-origin[1]) for s in samples)
                    assert metric['max_xy_drift_m']<.0003,metric
                metrics.append(metric)
            report[shape].update(stages=stages,metrics=metrics)
            print('PASS '+shape,flush=True)
        report['zero_finish']=h.named('zero')
        report['passed']=True
    except BaseException as error:
        report.update(passed=False,error=repr(error));print('FAIL',repr(error),flush=True)
    finally:
        report['executions']=h.results
        h.close();write_report(Path(args.output)/'stroke_drawing.json',report)
        print('REPORT',report.get('passed'),args.output,flush=True)
    if not report.get('passed'):sys.exit(1)


if __name__=='__main__':main()
