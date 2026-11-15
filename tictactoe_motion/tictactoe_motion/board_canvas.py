"""Map a bounded rectangular drawing canvas to an implicit metric grid."""
import math


class BoardCanvas:
    """! @brief Snap normalized canvas points, reject outside input, preserve pen strokes.

    Grid nodes are computed on demand; finer spacing does not imply finer robot
    accuracy. This first version requires an axis-aligned horizontal rectangle.
    """
    def __init__(self, profile):
        if profile.get('environment')!='sim' or profile.get('frame_id')!='base_link':
            raise ValueError('A simulation base_link geometry profile is required')
        corners=profile['safe_corners']
        if len(corners)!=4 or any(len(c)!=3 or not all(math.isfinite(v) for v in c) for c in corners):
            raise ValueError('Four finite 3D corners required')
        self.x0,self.y1,self.z=corners[0];self.x1,self.y0,_=corners[2]
        expected=[[self.x0,self.y1,self.z],[self.x1,self.y1,self.z],[self.x1,self.y0,self.z],[self.x0,self.y0,self.z]]
        if any(math.dist(a,b)>1e-9 for a,b in zip(corners,expected)) or self.x1<=self.x0 or self.y1<=self.y0:
            raise ValueError('Expected an ordered horizontal rectangular region')
        spacing=profile['grid_spacing_m']
        if not math.isfinite(spacing) or not .0001<=spacing<=.01:
            raise ValueError('Grid spacing must be in [0.0001, 0.01] meters')
        self.nx=math.ceil(round((self.x1-self.x0)/spacing,10))
        self.ny=math.ceil(round((self.y1-self.y0)/spacing,10))
        self.step_x=(self.x1-self.x0)/self.nx;self.step_y=(self.y1-self.y0)/self.ny

    def index(self,u,v):
        if not all(math.isfinite(a) and 0<=a<=1 for a in (u,v)):
            raise ValueError('Canvas coordinates must be finite and inside [0, 1]')
        return round(u*self.nx),round(v*self.ny)

    def point(self,i,j):
        if not isinstance(i,int) or not isinstance(j,int) or not 0<=i<=self.nx or not 0<=j<=self.ny:
            raise ValueError('Grid index outside usable board')
        return (self.x0+i*self.step_x,self.y1-j*self.step_y,self.z)

    def stroke(self,points,snap=True):
        """! @brief Quantize and connect one stroke; reject oversized paths before motion."""
        if not 2<=len(points)<=500:raise ValueError('Stroke requires 2..500 input points')
        indices=[self.index(*p) for p in points]
        if not snap:
            output=[(self.x0+u*(self.x1-self.x0),self.y1-v*(self.y1-self.y0),self.z) for u,v in points]
            if any(math.dist(a,b)==0 for a,b in zip(output,output[1:])):
                raise ValueError('Duplicate adjacent path points')
            if sum(math.dist(a,b) for a,b in zip(output,output[1:]))>.3:
                raise ValueError('Stroke exceeds 0.3 m')
            return output
        result=[indices[0]]
        for a,b in zip(indices,indices[1:]):
            count=max(abs(b[0]-a[0]),abs(b[1]-a[1]))
            for k in range(1,count+1):
                node=(round(a[0]+(b[0]-a[0])*k/count),round(a[1]+(b[1]-a[1])*k/count))
                if node!=result[-1]:result.append(node)
                if len(result)>500:raise ValueError('Quantized stroke exceeds 500 waypoints; split at pen-up boundaries')
        if len(result)<2:raise ValueError('Stroke collapses to a single grid node')
        output=[self.point(*node) for node in result]
        if sum(math.dist(a,b) for a,b in zip(output,output[1:]))>.3:
            raise ValueError('Stroke exceeds 0.3 m; split at pen-up boundaries')
        return output
