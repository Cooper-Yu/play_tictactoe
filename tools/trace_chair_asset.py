"""Offline chair centerline tracing. Usage: official-512.png output.json.

Removes gradient/background/frame, repairs observed source gaps and retraces
existing edges to reduce pen lifts. This approximate tracing is not original
vector artwork. No robot or ROS calls. Diagnostic images are written to /tmp.
"""
import cv2,numpy as np,math
from pathlib import Path

def thin(mask):
 a=np.pad(mask>0,1).astype(np.uint8)
 while True:
  changed=False
  for step in (0,1):
   p=[a[:-2,1:-1],a[:-2,2:],a[1:-1,2:],a[2:,2:],a[2:,1:-1],a[2:,:-2],a[1:-1,:-2],a[:-2,:-2]]
   n=sum(p);s=sum((p[i]==0)&(p[(i+1)%8]>0) for i in range(8));center=a[1:-1,1:-1]
   triple=(p[0]*p[2]*p[4]==0)&(p[2]*p[4]*p[6]==0) if step==0 else (p[0]*p[2]*p[6]==0)&(p[0]*p[4]*p[6]==0)
   erase=(center>0)&(n>=2)&(n<=6)&(s==1)&triple
   if erase.any():center[erase]=0;changed=True
  if not changed:return a[1:-1,1:-1]*255

def graph(mask):
 nodes={(int(x),int(y)) for y,x in zip(*np.where(mask>0))};adj={p:set() for p in nodes}
 for x,y in nodes:
  for dx,dy in ((0,1),(1,0),(1,1),(-1,1)):
   q=x+dx,y+dy
   if q not in nodes:continue
   if dx and dy and ((x+dx,y) in nodes or (x,y+dy) in nodes):continue
   adj[x,y].add(q);adj[q].add((x,y))
 return adj


import json,sys
im=cv2.imread(sys.argv[1],-1);hsv=cv2.cvtColor(im[:,:,:3],cv2.COLOR_BGR2HSV);background=cv2.medianBlur(im[:,:,:3],31);difference=(im[:,:,:3].astype(np.int16)-background.astype(np.int16)).min(axis=2);m=((difference>20)&(im[:,:,:3].min(axis=2)>150)&(im[:,:,3]>200)).astype(np.uint8)*255;roi=np.zeros(m.shape,np.uint8)
cv2.fillPoly(roi,[(np.array([[128,72],[272,72],[284,161],[305,165],[305,262],[290,306],[274,306],[270,270],[138,270],[135,306],[116,306],[104,259],[103,167],[132,160]])*512/400).astype(int)],255);m=cv2.bitwise_and(m,roi);cv2.circle(m,(357,128),3,255,-1);cv2.polylines(m,[np.array([[338,102],[357,128],[350,166]],np.int32)],False,255,1);cv2.line(m,(319,115),(357,128),255,1);cv2.polylines(m,[np.array([[142,222],[142,256],[143,292]],np.int32)],False,255,1);cv2.line(m,(172,323),(166,381),255,2);cv2.line(m,(186,323),(186,339),255,2);cv2.line(m,(201,323),(200,341),255,2);cv2.polylines(m,[np.array([[170,128],[177,167],[184,212]],np.int32)],False,255,1);cv2.polylines(m,[np.array([[142,256],[143,292],[145,323],[154,360],[156,381]],np.int32)],False,255,1);cv2.polylines(m,[np.array([[186,323],[201,323],[200,341],[186,339],[186,323]],np.int32)],False,255,1);cv2.imwrite('/tmp/chair_repaired_mask512.png',m);sk=thin(m)
for attempt in range(3):
 connections=[];a=graph(sk);ends=[p for p in a if len(a[p])==1]
 for i,p in enumerate(ends):
  for q in ends[:i]:
   distance=math.dist(p,q)
   if not 1<distance<=16:continue
   v=np.array(q)-p;pa=np.array(p)-next(iter(a[p]));qa=np.array(q)-next(iter(a[q]))
   if np.dot(pa,v)/(np.linalg.norm(pa)*distance)<.25 or np.dot(qa,-v)/(np.linalg.norm(qa)*distance)<.25:continue
   line=np.linspace(p,q,max(4,int(distance*2))).round().astype(int)
   if np.mean(im[line[:,1],line[:,0],:3].min(axis=1))<160:continue
   connections.append((distance,p,q))
 used=set()
 for distance,p,q in sorted(connections):
  if p in used or q in used:continue
  cv2.line(m,p,q,255,1);used.update((p,q))
 sk=thin(m)
cv2.imwrite('/tmp/chair_repaired_mask512.png',m)
import heapq
adj=graph(sk);left=set(adj);strokes=[];covered=0;retrace=0
while left:
 start=min(left);todo=[start];component={start};left.remove(start)
 while todo:
  for q in adj[todo.pop()]:
   if q in left:left.remove(q);component.add(q);todo.append(q)
 if len(component)<3:continue
 mult={v:[] for v in component};eid=0
 def add(a,b):
  global eid
  mult[a].append((b,eid));mult[b].append((a,eid));eid+=1
 for a in sorted(component):
  for b in sorted(adj[a]):
   if a<b:add(a,b)
 covered+=eid
 odds={a for a in component if len(adj[a])%2}
 while odds:
  a=min(odds);odds.remove(a);heap=[(0,a)];dist={a:0};parent={}
  while heap:
   d,v=heapq.heappop(heap)
   if d!=dist[v]:continue
   if v in odds:break
   for q in adj[v]:
    nd=d+math.dist(v,q)
    if nd<dist.get(q,float('inf')):dist[q]=nd;parent[q]=v;heapq.heappush(heap,(nd,q))
  odds.remove(v)
  while v!=a:
   p=parent[v];add(v,p);retrace+=1;v=p
 used=set();stack=[start];out=[]
 while stack:
  v=stack[-1]
  while mult[v] and mult[v][-1][1] in used:mult[v].pop()
  if mult[v]:q,k=mult[v].pop();used.add(k);stack.append(q)
  else:out.append(stack.pop())
 path=cv2.approxPolyDP(np.array(out[::-1],np.float32),1.0,False).reshape(-1,2).tolist();strokes.append(path)
xs=[p[0] for s in strokes for p in s];ys=[p[1] for s in strokes for p in s];x0,x1=min(xs),max(xs);y0,y1=min(ys),max(ys)
data={'source':'https://www.theconstruct.ai/wp-content/uploads/2020/09/Logo-The-Construct-512x512-1.png','description':'White line skeleton, background omitted, tiny disconnected raster speckles removed. Existing lines may be retraced to avoid excessive pen lifts. Approximate raster tracing, not original vector geometry.','source_bounds_px':[x0,y0,x1,y1],'aspect':(x1-x0)/(y1-y0),'extraction':{'skeleton_edges':covered,'retraced_edges':retrace,'simplification_pixels':1.0},'strokes':[[[(x-x0)/(x1-x0),(y-y0)/(y1-y0)] for x,y in s] for s in strokes]}
Path(sys.argv[2]).write_text(json.dumps(data,indent=2));preview=np.full((400,400,3),30,np.uint8)
for s in strokes:cv2.polylines(preview,[np.array(s).round().astype('int32')],False,(255,255,255),1,cv2.LINE_AA)
cv2.imwrite('/tmp/chair_full.png',preview);print(len(strokes),'components',sum(map(len,strokes)),'points',covered,'edges',retrace,'retraced')