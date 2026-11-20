"""Capture a bounded first-review batch from the course board in Gazebo Classic.

No robot controllers or hardware are started. Labels project the actual rendered
ribbon vertices through the received CameraInfo and the commanded camera pose.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import time
import xml.etree.ElementTree as ET

import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from cv_bridge import CvBridge
from sensor_msgs.msg import Image, CameraInfo
from gazebo_msgs.srv import SpawnEntity, DeleteEntity, SetEntityState

def apply_mesh_color(path, color):
    """! @brief Bind a COLLADA effect; Classic ignores SDF colors on bare meshes."""
    tree=ET.parse(path);root=tree.getroot();ns='http://www.collada.org/2005/11/COLLADASchema';ET.register_namespace('',ns)
    def add(parent,tag,**attrs):return ET.SubElement(parent,'{'+ns+'}'+tag,attrs)
    effects=add(root,'library_effects');effect=add(effects,'effect',id='ink_effect');profile=add(effect,'profile_COMMON');technique=add(profile,'technique',sid='common');constant=add(technique,'lambert');emission=add(constant,'emission');add(emission,'color').text=' '.join(map(str,[*color,1]));diffuse=add(constant,'diffuse');add(diffuse,'color').text=' '.join(map(str,[*color,1]))
    materials=add(root,'library_materials');material=add(materials,'material',id='ink_material',name='ink_material');add(material,'instance_effect',url='#ink_effect')
    root.find('.//{'+ns+'}triangles').set('material','ink_binding')
    instance=root.find('.//{'+ns+'}instance_geometry');binding=add(instance,'bind_material');common=add(binding,'technique_common');add(common,'instance_material',symbol='ink_binding',target='#ink_material')
    tree.write(path,encoding='unicode')

REPO = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(REPO/'tictactoe_motion'))
from tictactoe_motion.simulation.simulated_board import write_ribbon


def rotation(r, p, y):
    cr,sr,cp,sp,cy,sy=math.cos(r),math.sin(r),math.cos(p),math.sin(p),math.cos(y),math.sin(y)
    return np.array([[cy*cp,cy*sp*sr-sy*cr,cy*sp*cr+sy*sr],
                     [sy*cp,sy*sp*sr+cy*cr,sy*sp*cr-cy*sr],[-sp,cp*sr,cp*cr]])


def quaternion(r,p,y):
    cr,sr,cp,sp,cy,sy=math.cos(r/2),math.sin(r/2),math.cos(p/2),math.sin(p/2),math.cos(y/2),math.sin(y/2)
    return (sr*cp*cy-cr*sp*sy,cr*sp*cy+sr*cp*sy,cr*cp*sy-sr*sp*cy,cr*cp*cy+sr*sp*sy)


def symbol_paths(kind, variant, rng):
    t=np.linspace(0,1,81)
    if kind=='X':
        warp={'straight':0,'curved':float(rng.uniform(.10,.35)), 'gap':0,'unequal':0,'retrace':0}.get(variant,0)
        a=np.c_[-1+2*t,-1+2*t+warp*np.sin(2*np.pi*t)]
        b=np.c_[-1+2*t,1-2*t-warp*np.sin(2*np.pi*t)]
        if variant=='gap':
            gap=float(rng.choice([.06,.12,.20,.32]));return [a,b[t<.5-gap/2],b[t>.5+gap/2]]
        if variant=='unequal':b=b[10:-10]
        if variant=='offset':b[:,1]+=.28
        if variant=='jitter':
            a[:,1]+=.035*np.sin(12*np.pi*t);b[:,1]+=.035*np.sin(12*np.pi*t)
        return [a,b,b+np.array([.035,0])] if variant=='retrace' else [a,b]
    if variant=='multi_gap':
        gap=float(rng.choice([.08,.20]));return [np.c_[np.cos(t),np.sin(t)] for t in [np.linspace(gap,np.pi-gap,81),np.linspace(np.pi+gap,2*np.pi-gap,81)]]
    rx=float(rng.uniform(.55,1.0)) if variant=='ellipse' else 1.
    gap=math.radians(float(rng.choice([20,40,60,90]))) if variant=='gap' else 0
    t=np.linspace(gap/2,2*np.pi-gap/2,145)
    rad=1+.055*np.sin(5*t+.3) if variant=='handdrawn' else np.ones_like(t)
    a=np.c_[rx*rad*np.cos(t),rad*np.sin(t)]
    return [a,a+np.array([.035,0])] if variant=='retrace' else [a]


class Capture(Node):
    def __init__(self):
        super().__init__('xo_review_capture')
        self.image=None;self.info=None;self.seq=0;self.bridge=CvBridge()
        self.create_subscription(Image,'/xo_camera/xo_camera/image_raw',self.on_image,qos_profile_sensor_data)
        self.create_subscription(CameraInfo,'/xo_camera/xo_camera/camera_info',self.on_info,qos_profile_sensor_data)
        self.spawn=self.create_client(SpawnEntity,'/spawn_entity')
        self.delete=self.create_client(DeleteEntity,'/delete_entity')
        self.set_state=self.create_client(SetEntityState,'/set_entity_state')

    def on_image(self,msg):
        self.image=msg;self.seq+=1

    def on_info(self,msg):
        self.info=msg

    def wait(self,future,seconds=15):
        end=time.monotonic()+seconds
        while not future.done() and time.monotonic()<end:rclpy.spin_once(self,timeout_sec=.05)
        if not future.done():raise TimeoutError('Gazebo service timeout')
        result=future.result()
        if result is None or not result.success:raise RuntimeError(str(result))
        return result

    def settle_image(self,seconds=.4):
        before=self.seq;start=time.monotonic();deadline=start+12
        while time.monotonic()<deadline:
            rclpy.spin_once(self,timeout_sec=.05)
            if self.seq>=before+4 and time.monotonic()-start>=seconds:return self.image
        raise TimeoutError('No fresh stable camera frames')


def create_world(out,source):
    tree=ET.parse(source);w=tree.getroot().find('world');w.remove(w.find('gui'))
    # Keep the original course board, plane and lights, change only the capture camera.
    cam=w.find("model[@name='camera_model']/link/sensor")
    cam.find('update_rate').text='12';cam.find('visualize').text='false'
    cam.find('camera/image/width').text='848';cam.find('camera/image/height').text='480'
    plugin=cam.find('plugin');ros=plugin.find('ros');ros.clear()
    ET.SubElement(ros,'namespace').text='/xo_camera'
    ET.SubElement(plugin,'camera_name').text='xo_camera'
    ET.SubElement(plugin,'frame_name').text='xo_camera_optical_frame'
    ET.SubElement(w,'plugin',name='state',filename='libgazebo_ros_state.so')
    scene=ET.SubElement(w,'scene');ET.SubElement(scene,'shadows').text='false'
    tree.write(out,encoding='unicode')


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--count',type=int,default=100);p.add_argument('--seed',type=int,default=20261117);p.add_argument('--start-index',type=int,default=0);p.add_argument('--views-per-scene',type=int,default=1);p.add_argument('--expanded',action='store_true');args=p.parse_args()
    assert 1<=args.count<=1000
    assert args.views_per_scene in (1,5) and args.count%args.views_per_scene==0
    assert args.start_index>=0
    assert os.environ.get('ROS_DOMAIN_ID')=='191' and os.environ.get('ROS_LOCALHOST_ONLY')=='1'
    assert os.environ.get('GAZEBO_MASTER_URI')=='http://127.0.0.1:11619', 'Use isolated capture master'
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    for sub in ['images','labels','annotations','previews','meshes']: (out/sub).mkdir()
    share=Path('/home/cooper/final_project_1063805/install/piper_gazebo/share/piper_gazebo')
    create_world(out/'capture.world',share/'worlds/tictactoe.world')
    if args.expanded:
        tree=ET.parse(out/'capture.world');camera=tree.getroot().find(".//sensor/camera");noise=ET.SubElement(camera,'noise');ET.SubElement(noise,'type').text='gaussian';ET.SubElement(noise,'mean').text='0';ET.SubElement(noise,'stddev').text='0.002';tree.write(out/'capture.world',encoding='unicode')
    from simulation_session import simulator_processes,terminate_owned
    assert not simulator_processes(),'Existing simulator: refuse duplicate'
    tag='xo-review-'+str(os.getpid());env=dict(os.environ,PLAY_TICTACTOE_SESSION=tag)
    log=(out/'gazebo.log').open('w');server=subprocess.Popen(['gzserver',str(out/'capture.world'),'--verbose','-s','libgazebo_ros_init.so','-s','libgazebo_ros_factory.so'],env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    node=None;records=[]
    try:
        rclpy.init();node=Capture()
        for client in [node.spawn,node.delete,node.set_state]:
            if not client.wait_for_service(timeout_sec=45):raise RuntimeError('Service unavailable: '+client.srv_name)
        node.settle_image(1)
        rng=np.random.default_rng(args.seed);model=None
        for sample_index in range(args.count):
            i=sample_index+args.start_index
            scene_index=sample_index//args.views_per_scene;view_index=sample_index%args.views_per_scene
            if args.expanded:
                rng=np.random.default_rng(args.seed+scene_index)
            pose_rng=np.random.default_rng(args.seed+1000000+sample_index) if args.expanded else rng
            appearance_rng=np.random.default_rng(args.seed+2000000+sample_index) if args.expanded else rng
            if model:node.wait(node.delete.call_async(DeleteEntity.Request(name=model)))
            pose=[.198395+float(pose_rng.uniform(-.004,.004)),.199552+float(pose_rng.uniform(-.005,.005)),.203527+float(pose_rng.uniform(-.004,.004)),float(pose_rng.uniform(-.015,.015)) if args.expanded else 0.,.785379+float(pose_rng.uniform(-.035,.035)),-1.57+float(pose_rng.uniform(-.035,.035))]
            req=SetEntityState.Request();req.state.name='camera_model';req.state.reference_frame='world';req.state.pose.position.x,req.state.pose.position.y,req.state.pose.position.z=pose[:3]
            q=quaternion(*pose[3:]);req.state.pose.orientation.x,req.state.pose.orientation.y,req.state.pose.orientation.z,req.state.pose.orientation.w=q
            node.wait(node.set_state.call_async(req))
            visuals=[];objects=[];groupid=f'extra_scene_{scene_index:04d}' if args.expanded else f'scene_{i:03d}';negative=(scene_index if args.expanded else i)%5==4;layout_index=scene_index if args.expanded else i
            def mesh(paths,width,color,object_id):
                vertices=[]
                for k,points in enumerate(paths):
                    f=out/'meshes'/f'{groupid}_view{view_index}_{object_id}_{k}.dae';write_ribbon(f,points,.0275,width,True);apply_mesh_color(f,color)
                    root=ET.parse(f).getroot();ns={'c':'http://www.collada.org/2005/11/COLLADASchema'}
                    vertices.extend(np.fromstring(root.find('.//c:float_array',ns).text,sep=' ').reshape(-1,3).tolist())
                    c=' '.join(map(str,[*color,1]))
                    visuals.append(f'<visual name="v{len(visuals)}"><cast_shadows>false</cast_shadows><geometry><mesh><uri>{f.as_uri()}</uri></mesh></geometry><material><lighting>true</lighting><ambient>0 0 0 1</ambient><diffuse>0 0 0 1</diffuse><emissive>{c}</emissive></material></visual>')
                return np.asarray(vertices)
            grid=bool(layout_index%3!=0)
            if grid:
                paths=[np.array([[x,-.079],[x,.097]]) for x in [.176,.224]]+[np.array([[.136,y],[.264,y]]) for y in [-.023,.041]]
                mesh(paths,.0007,[.16,.35,.36],'grid')
            cells=rng.choice(9,size=int(rng.integers(1,10)) if not negative else int(rng.integers(1,5)),replace=False)
            for j,cell in enumerate(cells):
                col,row=int(cell%3),int(cell//3);center=np.array([.152+col*.048,-.055+row*.064])+rng.uniform(-.003,.003,2)
                scale=float(rng.uniform(.009,.0165) if args.expanded else rng.uniform(.010,.016));angle=float(rng.uniform(-.32,.32));rot=np.array([[math.cos(angle),-math.sin(angle)],[math.sin(angle),math.cos(angle)]])
                if negative:
                    variant=['blank','triangle','square','V','slash'][layout_index//5%5]
                    if variant=='blank':continue
                    base={'triangle':[[-1,-1],[1,-1],[0,1],[-1,-1]],'square':[[-1,-1],[1,-1],[1,1],[-1,1],[-1,-1]],'V':[[-1,1],[0,-1],[1,1]],'slash':[[-1,-1],[1,1]]}[variant];paths=[np.array(base)]
                    kind=None
                else:
                    kind='X' if (layout_index+j)%2==0 else 'O';variants=['straight','curved','gap','unequal','retrace'] if kind=='X' else ['circle','ellipse','gap','handdrawn','retrace']
                    if args.expanded:variants+=['offset','jitter'] if kind=='X' else ['multi_gap']
                    variant=variants[(layout_index+j//2)%len(variants)];paths=symbol_paths(kind,variant,rng)
                paths=[points@rot.T*scale+center for points in paths]
                color=[float(appearance_rng.uniform(.35,.65)),float(appearance_rng.uniform(.7,1)),float(appearance_rng.uniform(.7,1))];width=float(appearance_rng.uniform(.00065,.0014));v=mesh(paths,width,color,str(j))
                if kind:objects.append(dict(class_id=0 if kind=='X' else 1,kind=kind,variant=variant,boundary=variant=='gap',paths_board_xy=[a.tolist() for a in paths],center_xy=center.tolist(),scale_m=scale,rotation_rad=angle,color_rgb=color,vertices=v.tolist(),width_m=width))
            model=f'xo_capture_{i:03d}';sdf=f'<sdf version="1.6"><model name="{model}"><static>true</static><link name="ink">'+''.join(visuals)+'</link></model></sdf>'
            if not visuals:sdf=f'<sdf version="1.6"><model name="{model}"><static>true</static><link name="ink"/></model></sdf>'
            node.wait(node.spawn.call_async(SpawnEntity.Request(name=model,xml=sdf,reference_frame='world')))
            msg=node.settle_image(.55);image=node.bridge.imgmsg_to_cv2(msg,'bgr8');h,w=image.shape[:2];K=np.array(node.info.k).reshape(3,3)
            assert np.max(np.abs(node.info.d))<1e-8 if node.info.d else True
            labels=[];preview=image.copy();boxes=[]
            for obj in objects:
                v=(np.asarray(obj.pop('vertices'))-pose[:3])@rotation(*pose[3:]);opt=np.c_[-v[:,1],-v[:,2],v[:,0]];assert opt[:,2].min()>.02
                pix=opt@K.T;pix=pix[:,:2]/pix[:,2,None];lo=np.floor(pix.min(0)-1);hi=np.ceil(pix.max(0)+1)
                assert (lo>=0).all() and hi[0]<w and hi[1]<h,('Clipped object',i,lo,hi)
                x0,y0=lo.astype(int);x1,y1=hi.astype(int);box=[int(x0),int(y0),int(x1),int(y1)];obj['bbox_xyxy']=box;boxes.append(box)
                labels.append(f"{obj['class_id']} {(x0+x1)/2/w:.8f} {(y0+y1)/2/h:.8f} {(x1-x0)/w:.8f} {(y1-y0)/h:.8f}")
                cv2.rectangle(preview,(x0,y0),(x1,y1),(0,220,255),1);cv2.putText(preview,obj['kind'],(x0,max(10,y0-3)),cv2.FONT_HERSHEY_SIMPLEX,.4,(0,220,255),1)
            stem=f'xo_sim_{i:04d}';cv2.imwrite(str(out/'images'/f'{stem}.png'),image);cv2.imwrite(str(out/'previews'/f'{stem}.jpg'),preview)
            (out/'labels'/f'{stem}.txt').write_text('\n'.join(labels)+('\n' if labels else ''))
            rec=dict(id=stem,scene_group=groupid,split='review_unsplit',source='Gazebo Classic camera rendering; direct board ribbons; no robot motion',negative=negative,grid=grid,seed=args.seed+(scene_index if args.expanded else 0),view_index=view_index,camera_noise_stddev=.002 if args.expanded else 0.,camera_pose_world=pose,camera_info=dict(width=node.info.width,height=node.info.height,k=list(node.info.k),d=list(node.info.d)),image_header=dict(frame_id=msg.header.frame_id,sec=msg.header.stamp.sec,nanosec=msg.header.stamp.nanosec),objects=objects,sha256=hashlib.sha256((out/'images'/f'{stem}.png').read_bytes()).hexdigest())
            (out/'annotations'/f'{stem}.json').write_text(json.dumps(rec,indent=2));records.append(rec)
            (out/'manifest.json').write_text(json.dumps(dict(status='capturing',rules='confirmed-v1-20261117',records=records),indent=2))
            print(f'CAPTURE {sample_index+1}/{args.count} id={stem} group={groupid} objects={len(objects)}',flush=True)
        (out/'data.yaml').write_text(f'path: {out}\n# Review pool: split by scene before assigning train/val/test.\nnames:\n  0: X\n  1: O\n')
        manifest=dict(status='captured_awaiting_visual_audit',rules='confirmed-v1-20261117',count=len(records),negative=sum(r['negative'] for r in records),class_counts={c:sum(o['kind']==c for r in records for o in r['objects']) for c in ['X','O']},records=records,limitations=['no robot/hand occlusion in this first batch','synthetic illuminated pen ribbons are not physical contact simulation','camera resolution 848x480; course board/world reused; viewpoint perturbed','not yet an independently split training/validation/test dataset','real-image transfer unverified'])
        (out/'manifest.json').write_text(json.dumps(manifest,indent=2))
    finally:
        if node:node.destroy_node()
        if rclpy.ok():rclpy.shutdown()
        remaining=terminate_owned(tag)
        server.wait(timeout=5);log.close();(out/'cleanup.json').write_text(json.dumps(dict(remaining_owned_pids=remaining,server_returncode=server.returncode)))
        if remaining:raise RuntimeError('Owned Gazebo processes remain')

if __name__=='__main__':main()
