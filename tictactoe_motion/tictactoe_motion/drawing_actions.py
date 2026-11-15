"""Parameterized grid/X/O commands shared by CLI, future GUI and motion drivers."""
import math
from tictactoe_motion.canvas_drawing import CanvasDrawing


class DrawingActions:
    """! @brief Convert board-local positions and metric dimensions into verified strokes.

    Centers use normalized board coordinates (u,v); lengths/radii are meters.
    Preview methods perform geometry validation without motion. A driver is
    required by draw methods and supplies the existing plan/execute/settle loop.
    No ROS node, robot state source or simulator renderer is created here.
    """
    def __init__(self,canvas,driver=None,upper_z=.22,depth=.01):
        self.canvas=canvas;self.driver=driver;self.upper_z=upper_z;self.depth=depth
        self.width=canvas.x1-canvas.x0;self.height=canvas.y1-canvas.y0

    def _center(self,center):
        if len(center)!=2:raise ValueError('Center must be normalized (u,v)')
        self.canvas.index(*center)
        return center

    def _length(self,value):
        if not math.isfinite(value) or value<=0:raise ValueError('Metric dimension must be finite and positive')
        return value

    def _prepare(self,strokes):
        return CanvasDrawing(self.canvas,strokes,upper_z=self.upper_z,depth=self.depth,snap=False)

    def grid_strokes(self,center=(.5,.5),width=.06,height=.06):
        """! @brief Preview two vertical and two horizontal grid lines inside the board."""
        u,v=self._center(center);du=self._length(width)/self.width;dv=self._length(height)/self.height
        strokes=[]
        for offset in (-1/6,1/6):
            strokes.append([(u+du*offset,v-dv/2),(u+du*offset,v+dv/2)])
            strokes.append([(u-du/2,v+dv*offset),(u+du/2,v+dv*offset)])
        self._prepare(strokes)
        return strokes

    def x_strokes(self,center=(.5,.5),size=.012):
        """! @brief Preview two independent diagonals; size is the bounding-square edge."""
        u,v=self._center(center);half=self._length(size)/2;du=half/self.width;dv=half/self.height
        strokes=[[(u-du,v-dv),(u+du,v+dv)],[(u-du,v+dv),(u+du,v-dv)]]
        self._prepare(strokes)
        return strokes

    def o_strokes(self,center=(.5,.5),radius=.005,samples=128):
        """! @brief Preview a closed unsnapped circular path with a metric radius."""
        u,v=self._center(center);r=self._length(radius)
        if not isinstance(samples,int) or isinstance(samples,bool) or not 16<=samples<=256:
            raise ValueError('Circle samples must be in 16..256')
        points=[(u+r/self.width*math.cos(2*math.pi*i/samples),v+r/self.height*math.sin(2*math.pi*i/samples)) for i in range(samples)]
        points.append(points[0]);strokes=[points];self._prepare(strokes)
        return strokes

    def _run(self,strokes,cancelled,on_stage):
        if self.driver is None:raise RuntimeError('Drawing requires an explicit motion driver')
        stages=self._prepare(strokes).run(self.driver,cancelled=cancelled,on_stage=on_stage)
        return {'passed':True,'stages':stages}

    def draw_grid(self,center=(.5,.5),width=.06,height=.06,*,cancelled=lambda:False,on_stage=lambda name:None):
        """! @brief Draw a parameterized grid using separate lifted strokes."""
        return self._run(self.grid_strokes(center,width,height),cancelled,on_stage)

    def draw_x(self,center=(.5,.5),size=.012,*,cancelled=lambda:False,on_stage=lambda name:None):
        """! @brief Draw two lifted diagonals at the requested board-local center."""
        return self._run(self.x_strokes(center,size),cancelled,on_stage)

    def draw_o(self,center=(.5,.5),radius=.005,samples=128,*,cancelled=lambda:False,on_stage=lambda name:None):
        """! @brief Draw a closed circle without forcing its samples onto grid nodes."""
        return self._run(self.o_strokes(center,radius,samples),cancelled,on_stage)
