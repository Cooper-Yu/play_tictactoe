"""Execute normalized canvas polylines with explicit virtual pen-up/down motion."""
import copy
import math
from geometry_msgs.msg import Pose
from tictactoe_motion.stroke_drawing import StrokeDrawing


class CanvasDrawing(StrokeDrawing):
    """! @brief Validate all canvas strokes before approaching their first start."""
    def __init__(self, canvas, strokes, upper_z=.22, depth=.01, snap=True):
        super().__init__('cross',depth=depth)
        self.canvas = canvas
        if canvas.environment == 'real' and (
                abs(upper_z-canvas.profile['hover_link6_z_m']) > 1e-9
                or abs(upper_z-depth-canvas.z) > 1e-9):
            raise ValueError('Real drawing heights must match the calibrated board profile')
        if not 1<=len(strokes)<=32:raise ValueError('Require 1..32 separate strokes')
        self.paths=[canvas.stroke(points,snap=snap) for points in strokes]
        self.upper_z=upper_z
        if not .20<=upper_z-depth<upper_z<=.30:
            raise ValueError('Simulation hover height outside validated range')

    def run(self, driver, cancelled=lambda:False, on_stage=lambda name:None):
        self.results=[]
        if cancelled():raise RuntimeError('Drawing cancelled')
        upper=driver.current_pose()
        if self.canvas.environment == 'real':
            if getattr(getattr(driver, 'recording', None), 'environment', None) != 'real':
                raise ValueError('Real canvas requires a real motion driver')
            q = upper.orientation
            actual = [q.x, q.y, q.z, q.w]
            expected = self.canvas.profile['required_orientation_xyzw']
            norm = math.sqrt(sum(v*v for v in actual))
            if not math.isfinite(norm) or abs(norm-1) > .001:
                raise ValueError('Invalid current drawing orientation')
            error = 2*math.acos(min(1., abs(sum(a*b for a,b in zip(actual,expected))/norm)))
            if error > self.canvas.profile['orientation_tolerance_rad']:
                raise ValueError('Move to clear drawing orientation before drawing')
            if upper.position.z < self.upper_z-0.0001:
                on_stage('raise_before_transfer')
                lift = copy.deepcopy(upper.position); lift.z = self.upper_z
                result = driver.linear(lift)
                if not isinstance(result, dict) or result.get('passed') is not True:
                    raise RuntimeError('Canvas initial lift failed')
                self.results.append({'stage':'raise_before_transfer','result':copy.deepcopy(result)})
                if cancelled():raise RuntimeError('Drawing cancelled')
        upper.position.x,upper.position.y,_=self.paths[0][0]
        transfer_z = max(upper.position.z, self.upper_z) if self.canvas.environment == 'real' else self.upper_z
        upper.position.z=transfer_z
        on_stage('approach')
        actual = driver.current_pose().position
        distance = math.dist((actual.x,actual.y,actual.z),
                             (upper.position.x,upper.position.y,upper.position.z))
        if self.canvas.environment == 'real' and distance <= 0.00001:
            # A <=10 micrometer approach is already satisfied; do not execute a zero-length plan.
            result = dict(passed=True, skipped=True, reason='already_at_approach',
                          position_error_m=distance, orientation_error_rad=0.)
        else:
            result=driver.linear(upper.position) if self.canvas.environment == 'real' else driver.pose(upper)
        if not isinstance(result,dict) or result.get('passed') is not True:raise RuntimeError('Canvas approach failed')
        self.results.append({'stage':'approach','result':copy.deepcopy(result)})
        if self.canvas.environment == 'real' and transfer_z > self.upper_z+0.0001:
            if cancelled():raise RuntimeError('Drawing cancelled')
            upper.position.z = self.upper_z
            on_stage('approach_hover')
            result = driver.linear(upper.position)
            if not isinstance(result, dict) or result.get('passed') is not True:
                raise RuntimeError('Canvas hover approach failed')
            self.results.append({'stage':'approach_hover','result':copy.deepcopy(result)})
        upper.position.z = self.upper_z
        strokes=[]
        for path in self.paths:
            poses=[]
            for x,y,_ in path:
                pose=Pose();pose.position.x=x;pose.position.y=y;pose.position.z=self.upper_z-self.depth
                pose.orientation=copy.deepcopy(upper.orientation);poses.append(pose)
            strokes.append(poses)
        return self.run_strokes(driver,strokes,upper,cancelled,on_stage)
