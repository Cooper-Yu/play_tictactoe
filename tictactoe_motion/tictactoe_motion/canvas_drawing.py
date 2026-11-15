"""Execute normalized canvas polylines with explicit virtual pen-up/down motion."""
import copy
from geometry_msgs.msg import Pose
from tictactoe_motion.stroke_drawing import StrokeDrawing


class CanvasDrawing(StrokeDrawing):
    """! @brief Validate all canvas strokes before approaching their first start."""
    def __init__(self, canvas, strokes, upper_z=.22, depth=.01, snap=True):
        super().__init__('cross',depth=depth)
        if not 1<=len(strokes)<=32:raise ValueError('Require 1..32 separate strokes')
        self.paths=[canvas.stroke(points,snap=snap) for points in strokes]
        self.upper_z=upper_z
        if not .20<=upper_z-depth<upper_z<=.30:
            raise ValueError('Simulation hover height outside validated range')

    def run(self, driver, cancelled=lambda:False, on_stage=lambda name:None):
        self.results=[]
        if cancelled():raise RuntimeError('Drawing cancelled')
        upper=driver.current_pose()
        upper.position.x,upper.position.y,_=self.paths[0][0]
        upper.position.z=self.upper_z
        on_stage('approach')
        result=driver.pose(upper)
        if not isinstance(result,dict) or result.get('passed') is not True:raise RuntimeError('Canvas approach failed')
        self.results.append({'stage':'approach','result':copy.deepcopy(result)})
        strokes=[]
        for path in self.paths:
            poses=[]
            for x,y,_ in path:
                pose=Pose();pose.position.x=x;pose.position.y=y;pose.position.z=self.upper_z-self.depth
                pose.orientation=copy.deepcopy(upper.orientation);poses.append(pose)
            strokes.append(poses)
        return self.run_strokes(driver,strokes,upper,cancelled,on_stage)
