"""Extract derived geometry only from the course's horizontal board model."""
import argparse
import hashlib
from pathlib import Path
import xml.etree.ElementTree as ET
import numpy as np
import yaml


def extract(share):
    """! @brief Reject unsupported scene transforms rather than guessing coordinates."""
    world=share/'worlds/tictactoe.world'
    sdf=share/'models/board/model.sdf'
    dae=share/'models/board/meshes/board.dae'
    root=ET.parse(world).getroot()
    includes=[e for e in root.findall('.//include') if e.findtext('uri')=='model://board']
    assert len(includes)==1
    pose=[float(v) for v in includes[0].findtext('pose').split()]
    assert len(pose)==6 and all(abs(v)<1e-12 for v in pose[3:]), 'Only this axis-aligned simulation model is supported'
    model=ET.parse(sdf).getroot().find('model')
    assert model.findtext('static') in ('1','true')
    assert not model.findall('.//pose'), 'Unexpected model/link/visual transform'
    scale=np.array([float(v) for v in model.findtext('.//mesh/scale').split()])
    assert model.findtext('.//mesh/uri')=='model://board/meshes/board.dae'
    root=ET.parse(dae).getroot();ns={'c':root.tag.split('}')[0][1:]}
    assert root.findtext('c:asset/c:up_axis',namespaces=ns)=='Z_UP'
    unit=float(root.find('c:asset/c:unit',ns).get('meter'))
    materials={}
    def walk(node,parent):
        matrix=parent.copy()
        for child in node:
            tag=child.tag.split('}')[-1]
            if tag=='matrix':matrix=matrix@np.fromstring(child.text,sep=' ').reshape(4,4)
            elif tag in ('translate','rotate','scale'):raise ValueError('Unsupported COLLADA transform')
        for inst in node.findall('c:instance_geometry',ns):
            geo=root.find("c:library_geometries/c:geometry[@id='%s']"%inst.get('url')[1:],ns)
            mesh=geo.find('c:mesh',ns)
            source=mesh.find('c:vertices/c:input',ns).get('source')[1:]
            positions=np.fromstring(mesh.find("c:source[@id='%s']/c:float_array"%source,ns).text,sep=' ').reshape(-1,3)
            transformed=(np.c_[positions,np.ones(len(positions))]@matrix.T)[:,:3]*unit*scale+np.array(pose[:3])
            bindings={b.get('symbol'):b.get('target')[1:] for b in inst.findall('.//c:instance_material',ns)}
            for tri in mesh.findall('c:triangles',ns):
                inputs=tri.findall('c:input',ns);stride=max(int(i.get('offset')) for i in inputs)+1
                offset=int(next(i for i in inputs if i.get('semantic')=='VERTEX').get('offset'))
                indices=np.fromstring(tri.find('c:p',ns).text,sep=' ',dtype=int).reshape(-1,stride)[:,offset]
                materials.setdefault(bindings[tri.get('material')],[]).extend(transformed[indices].tolist())
        for child in node.findall('c:node',ns):walk(child,matrix)
    scene_id=root.find('c:scene/c:instance_visual_scene',ns).get('url')[1:]
    for node in root.find("c:library_visual_scenes/c:visual_scene[@id='%s']"%scene_id,ns).findall('c:node',ns):walk(node,np.eye(4))
    screen=np.array(materials['screen-material']);button=np.array(materials['metal-material'])
    low,high=screen.min(0),screen.max(0)
    assert high[2]-low[2]<1e-8
    margin=.005;x0,y0=low[:2]+margin;x1,y1=high[:2]-margin
    # A convex screen contains the inset rectangle; verify every corner by hull halfspaces.
    polygon=np.unique(screen[:,:2],axis=0);center=polygon.mean(0)
    polygon=polygon[np.argsort(np.arctan2(polygon[:,1]-center[1],polygon[:,0]-center[0]))]
    for corner in [(x0,y0),(x1,y0),(x1,y1),(x0,y1)]:
        assert all(np.cross(b-a,np.array(corner)-a)>=-1e-10 for a,b in zip(polygon,np.roll(polygon,-1,axis=0)))
    return {'environment':'sim','frame_id':'base_link','base_world_pose_required':[0.,0.,0.,0.,0.,0.],
            'board_world_pose':pose,'screen_bounds':{'min':low.tolist(),'max':high.tolist()},
            'safe_corners':[[float(x0),float(y1),float(low[2])],[float(x1),float(y1),float(low[2])],
                            [float(x1),float(y0),float(low[2])],[float(x0),float(y0),float(low[2])]],
            'margin_m':margin,'grid_spacing_m':.0005,
            'reset_center':((button.min(0)+button.max(0))/2).tolist(),
            'reset_semantics':'white visual geometry; no button sensor/contact plugin in model',
            'motion_reference':'link6 XY projection; no physical pen TCP calibrated',
            'hover_link6_z_m':.22,'drawing_link6_z_m':.21,
            'source_sha256':{str(p.relative_to(share)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (world,sdf,dae)}}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--share',required=True,type=Path);p.add_argument('--output',required=True,type=Path)
    args=p.parse_args();result=extract(args.share)
    args.output.write_text(yaml.safe_dump(result,sort_keys=False),encoding='utf-8')
    print(yaml.safe_dump(result,sort_keys=False))
