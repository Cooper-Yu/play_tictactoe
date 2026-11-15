"""Gazebo-only zero -> elevated coordinate -> -Z -> +Z -> zero acceptance."""
import argparse
import copy
import math
from pathlib import Path
import sys
from rclpy.utilities import remove_ros_args
from simulation_support import SimulationHarness, write_report
from tictactoe_motion.pose_cycle import PoseCycle


def vertical_metrics(samples, upper):
    assert len(samples)>=3
    return {'sample_count':len(samples),
            'max_xy_error_m':max(math.hypot(s['xyz'][0]-upper.position.x,s['xyz'][1]-upper.position.y) for s in samples),
            'min_z':min(s['xyz'][2] for s in samples),'max_z':max(s['xyz'][2] for s in samples)}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',required=True)
    p.add_argument('--clearance',type=float,default=.03)
    p.add_argument('--distance',type=float,default=.01)
    p.add_argument('--target',type=float,nargs=3,metavar=('X','Y','Z'))
    args=p.parse_args(remove_ros_args(sys.argv)[1:])
    if args.target is None and (not math.isfinite(args.clearance) or not args.distance < args.clearance <= .1):
        p.error('Demo clearance must exceed descent distance and be at most 0.1 m')
    h=SimulationHarness(args.output)
    stop_generation=h.execution.stop.generation
    h.motion_guard=lambda: (h.execution.stop.generation!=stop_generation or
                            h.execution.stop.status.get('state') in ('stop_requested','stopped','blocked'))
    report={'scenario':'zero -> target -> -Z -> +Z -> zero','simulation_only':True,'distance_m':args.distance}
    try:
        report['controllers']=h.preflight()
        _,target=h.named_target('clear')
        target=copy.deepcopy(target)
        if args.target:target.position.x,target.position.y,target.position.z=args.target
        else:target.position.z+=args.clearance
        cycle=PoseCycle(target,args.distance)
        report['target_xyz']=[target.position.x,target.position.y,target.position.z]
        report['stages']=cycle.run(h,cancelled=h.motion_guard,on_stage=lambda name:print('STAGE '+name,flush=True))
        report['upper_xyz']=[cycle.upper.position.x,cycle.upper.position.y,cycle.upper.position.z]
        report['lower_xyz']=[cycle.lower.position.x,cycle.lower.position.y,cycle.lower.position.z]
        report['descent']=vertical_metrics(h.results[2]['samples'],cycle.upper)
        report['retract']=vertical_metrics(h.results[3]['samples'],cycle.upper)
        for key in ('descent','retract'):
            assert report[key]['max_xy_error_m']<.0003,report[key]
        assert abs(report['descent']['min_z']-cycle.lower.position.z)<.0003
        assert abs(report['retract']['max_z']-cycle.upper.position.z)<.0003
        report['passed']=True
    except BaseException as error:
        report.update(passed=False,error=repr(error))
        print('FAIL',repr(error),flush=True)
    finally:
        report['executions']=h.results
        h.close()
        write_report(Path(args.output)/'pose_cycle.json',report)
        print('REPORT',report.get('passed'),args.output,flush=True)
    if not report.get('passed'):sys.exit(1)


if __name__=='__main__':main()
