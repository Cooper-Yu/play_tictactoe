"""Render actual airborne stroke feedback onto the simulation board's surface."""
import math
from pathlib import Path
import uuid
from gazebo_msgs.srv import SpawnEntity, DeleteEntity


def sampled_xy(samples, spacing=.0003):
    """! @brief Keep observed points at bounded spatial intervals and preserve endpoints."""
    result=[samples[0]['xyz'][:2]]
    for sample in samples[1:-1]:
        point=sample['xyz'][:2]
        if math.dist(point,result[-1])>=spacing:result.append(point)
    result.append(samples[-1]['xyz'][:2])
    return result


def write_ribbon(path, points, z, width=.001, round_joins=False):
    """! @brief Build a flat pen footprint with optional round joins; no collision/contact model."""
    vertices=[]
    for a,b in zip(points,points[1:]):
        dx,dy=b[0]-a[0],b[1]-a[1];length=math.hypot(dx,dy)
        if length<1e-10:continue
        ox,oy=-dy/length*width/2,dx/length*width/2
        v=[(a[0]+ox,a[1]+oy,z),(a[0]-ox,a[1]-oy,z),(b[0]+ox,b[1]+oy,z),(b[0]-ox,b[1]-oy,z)]
        vertices.extend([v[0],v[1],v[2],v[2],v[1],v[3]])
    if not vertices:raise ValueError('No drawable movement')
    if round_joins:
        # Sweep a fixed circular pen footprint through each observed point.
        # Separate rectangles alone leave holes outside a turning join.
        for x,y in points:
            for i in range(16):
                a,b=2*math.pi*i/16,2*math.pi*(i+1)/16
                vertices.extend([(x,y,z),(x+width/2*math.cos(a),y+width/2*math.sin(a),z),
                                 (x+width/2*math.cos(b),y+width/2*math.sin(b),z)])
    positions=' '.join(str(value) for point in vertices for value in point)
    indices=' '.join(str(i) for i in range(len(vertices)))
    text=f'''<?xml version="1.0"?><COLLADA xmlns="http://www.collada.org/2005/11/COLLADASchema" version="1.4.1">
<asset><unit name="meter" meter="1"/><up_axis>Z_UP</up_axis></asset><library_geometries><geometry id="ink"><mesh>
<source id="positions"><float_array id="array" count="{len(vertices)*3}">{positions}</float_array><technique_common><accessor source="#array" count="{len(vertices)}" stride="3"><param name="X" type="float"/><param name="Y" type="float"/><param name="Z" type="float"/></accessor></technique_common></source>
<vertices id="vertices"><input semantic="POSITION" source="#positions"/></vertices><triangles count="{len(vertices)//3}"><input semantic="VERTEX" source="#vertices" offset="0"/><p>{indices}</p></triangles>
</mesh></geometry></library_geometries><library_visual_scenes><visual_scene id="scene"><node id="stroke"><instance_geometry url="#ink"/></node></visual_scene></library_visual_scenes><scene><instance_visual_scene url="#scene"/></scene></COLLADA>'''
    Path(path).write_text(text,encoding='utf-8')
    return len(vertices)//3


def reset_gesture(samples,center,upper_z=.25,lower_z=.24,radius=.012):
    """! @brief Recognize elevated arrival followed by a downward virtual press over Reset."""
    armed=False
    for sample in samples:
        x,y,z=sample['xyz']
        if not all(math.isfinite(v) for v in (x,y,z)):
            armed=False
            continue
        if math.hypot(x-center[0],y-center[1])>radius:
            armed=False
            continue
        if z>=upper_z-.001:armed=True
        if armed and z<=lower_z+.0003:return True
    return False


class SimulatedBoard:
    """! @brief Paint completed measured strokes; clear only this renderer's owned models.

    This first renderer updates after each verified stroke, not every camera frame.
    Robot motion stays airborne. The mesh uses the observed link6 XY projection;
    physical pen TCP/contact calibration is explicitly outside this simulator.
    """
    def __init__(self,node,profile,directory,wait,grouped=False):
        self.profile=profile;self.directory=Path(directory);self.directory.mkdir(exist_ok=True)
        self.wait=wait;self.models=[];self.files=[];self.token=uuid.uuid4().hex[:10]
        self.grouped=grouped;self.active_files=[]
        self.spawn=node.create_client(SpawnEntity,'/spawn_entity')
        self.delete=node.create_client(DeleteEntity,'/delete_entity')

    def paint(self,samples):
        if len(samples)<3:raise ValueError('Insufficient observed trajectory')
        corners=self.profile['safe_corners'];x0,y1,z=corners[0];x1,y0,_=corners[2]
        # Keep the full ribbon, not just its center, inside the safe rectangle.
        for sample in samples:
            x,y,height=sample['xyz']
            if not (x0+.0005<=x<=x1-.0005 and y0+.0005<=y<=y1-.0005 and abs(height-self.profile['drawing_link6_z_m'])<.0003):
                raise ValueError('Observed stroke outside virtual drawing region/height')
        name='ptt_ink_'+self.token+'_'+str(len(self.files))
        path=self.directory/(name+'.dae')
        points=sampled_xy(samples);triangles=write_ribbon(path,points,z+.0004,round_joins=True)
        self.files.append(path)
        self._spawn_paths(name, [path])
        return {'model':name,'points':len(points),'triangles':triangles,'source':'actual link6 XY feedback'}

    def set_grid(self, lines):
        """Render the known grid as static simulation geometry."""
        self.clear()
        paths = []
        for points in lines:
            path = self.directory / f'ptt_ink_{self.token}_{len(self.files)}.dae'
            write_ribbon(path, points, self.profile['safe_corners'][0][2]+.0004)
            self.files.append(path)
            paths.append(path)
        self._spawn_paths(f'ptt_grid_{self.token}_{len(self.files)}', paths)

    def _spawn_paths(self, name, added_paths):
        paths = self.active_files + added_paths if self.grouped else added_paths
        visuals=''.join(f'''<visual name="trace{i}"><cast_shadows>false</cast_shadows><geometry><mesh><uri>{mesh.as_uri()}</uri></mesh></geometry><material><lighting>false</lighting><ambient>1 1 1 1</ambient><diffuse>1 1 1 1</diffuse></material></visual>''' for i,mesh in enumerate(paths))
        sdf=f'''<sdf version="1.6"><model name="{name}"><static>true</static><link name="ink">{visuals}</link></model></sdf>'''
        response=self.wait(self.spawn.call_async(SpawnEntity.Request(name=name,xml=sdf,reference_frame='world')))
        if not response.success:raise RuntimeError(response.status_message)
        previous=list(self.models);self.models.append(name)
        if self.grouped:
            self.active_files=paths
            for old in previous:
                deleted=self.wait(self.delete.call_async(DeleteEntity.Request(name=old)))
                if not deleted.success:raise RuntimeError(deleted.status_message)
                self.models.remove(old)

    def clear(self):
        for name in list(self.models):
            response=self.wait(self.delete.call_async(DeleteEntity.Request(name=name)))
            if not response.success:raise RuntimeError(response.status_message)
            self.models.remove(name)
        self.active_files=[]

    def press_reset(self,samples):
        if not reset_gesture(samples,self.profile['reset_center'],self.profile['hover_link6_z_m'],self.profile['drawing_link6_z_m']):return False
        self.clear();return True

    def close(self):
        self.clear()
        for path in self.files:path.unlink(missing_ok=True)
