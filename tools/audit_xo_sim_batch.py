"""Audit camera frames against projected labels and produce review contact sheets."""
import argparse
import base64
from collections import Counter
import hashlib
import html
import json
from pathlib import Path
import cv2
import numpy as np


def audit(root,expected=100,build_review=True):
    manifest=json.loads((root/'manifest.json').read_text());records=manifest['records']
    assert len(records)==expected
    assert len({r['sha256'] for r in records})==expected,'Duplicate frames'
    assert len(list((root/'images').glob('*.png')))==expected
    assert len(list((root/'labels').glob('*.txt')))==expected
    variants=Counter();counts=Counter();worst=10**9;rows=[]
    for record in records:
        image=cv2.imread(str(root/'images'/(record['id']+'.png')));assert image is not None and image.shape==(480,848,3)
        assert hashlib.sha256((root/'images'/(record['id']+'.png')).read_bytes()).hexdigest()==record['sha256']
        lines=(root/'labels'/(record['id']+'.txt')).read_text().splitlines();assert len(lines)==len(record['objects'])
        for line,obj in zip(lines,record['objects']):
            values=list(map(float,line.split()));assert len(values)==5 and int(values[0])==obj['class_id']
            _,cx,cy,w,h=values;assert 0<cx<1 and 0<cy<1 and 0<w<=1 and 0<h<=1
            xyxy=np.array([(cx-w/2)*848,(cy-h/2)*480,(cx+w/2)*848,(cy+h/2)*480]);assert np.max(np.abs(xyxy-obj['bbox_xyxy']))<1e-4
            x0,y0,x1,y1=obj['bbox_xyxy'];assert 0<=x0<x1<848 and 0<=y0<y1<480
            roi=image[y0:y1+1,x0:x1+1].astype(float)
            target=np.array(obj['color_rgb'][::-1])*255
            # Material colors must actually appear in the camera frame, not just SDF metadata.
            background=np.median(roi.reshape(-1,3),axis=0)
            direction=target-background
            alpha=np.sum((roi-background)*direction,axis=2)/np.dot(direction,direction)
            residual=np.linalg.norm(roi-background-alpha[:,:,None]*direction,axis=2)
            mask=(alpha>.12)&(alpha<1.2)&(residual<30)&(roi[:,:,1]-roi[:,:,2]>8)
            pixels=int(mask.sum());assert pixels>=8,(record['id'],obj['kind'],pixels,target)
            yy,xx=np.nonzero(mask);dist=[xx.min(),yy.min(),x1-x0-xx.max(),y1-y0-yy.max()]
            # Geometry-derived rectangles allow 1 px rasterization margin plus 1 px rounding.
            assert max(dist)<=6,(record['id'],obj['kind'],'loose/misaligned box',dist)
            worst=min(worst,pixels);counts[obj['kind']]+=1;variants[(obj['kind'],obj['variant'])]+=1
        assert bool(lines)!=record['negative']
        rows.append(dict(id=record['id'],objects=len(lines),negative=record['negative']))
    assert sum(r['negative'] for r in records)==expected//5
    # Keep scene groups intact; this pilot remains unsplit pending human review.
    assert all(r['split']=='review_unsplit' for r in records)
    cleanup=json.loads((root/'cleanup.json').read_text());assert cleanup['remaining_owned_pids']==[]
    report=dict(status='automated_audit_passed_human_review_pending',frames=expected,positive=sum(not r['negative'] for r in records),negative=sum(r['negative'] for r in records),class_counts=dict(counts),variants={k[0]+':'+k[1]:v for k,v in variants.items()},min_visible_ink_pixels_per_object=worst,unique_hashes=expected,checks=['matching image/label/metadata counts','valid YOLO normalized boxes','boxes match projected mesh geometry','visible target-color pixels inside every box','visible ink reaches each box edge within 6px','no duplicate images','no train/val/test split leakage introduced: pilot unsplit','owned simulator cleaned'],limitations=manifest['limitations'])
    (root/'audit.json').write_text(json.dumps(report,indent=2))
    if not build_review:
        print(json.dumps(report,ensure_ascii=False));return report
    review=root/'review';review.mkdir(exist_ok=True)
    for batch in range((expected+24)//25):
        sheet=np.full((5*264,5*424,3),245,np.uint8)
        for pos,i in enumerate(range(batch*25,min((batch+1)*25,expected))):
            record=records[i];im=cv2.imread(str(root/'previews'/(record['id']+'.jpg')));im=cv2.resize(im,(424,240));x=(pos%5)*424;y=(pos//5)*264
            sheet[y:y+240,x:x+424]=im;cv2.putText(sheet,f"{i:04d} | {len(record['objects'])} objects"+(' | background' if record['negative'] else ''),(x+10,y+257),cv2.FONT_HERSHEY_SIMPLEX,.45,(25,25,25),1)
        cv2.imwrite(str(review/f'contact_{batch+1}.jpg'),sheet)
    selected=[0,1,7,14,17,24,31,44,49,69,84,99];selected=[i for i in selected if i<expected]
    summary=np.full((4*264,3*424,3),245,np.uint8)
    for j,i in enumerate(selected):
        record=records[i];im=cv2.resize(cv2.imread(str(root/'previews'/(record['id']+'.jpg'))),(424,240));x=j%3*424;y=j//3*264;summary[y:y+240,x:x+424]=im;cv2.putText(summary,f"{i:04d} | {len(record['objects'])} objects",(x+10,y+257),cv2.FONT_HERSHEY_SIMPLEX,.5,(25,25,25),1)
    cv2.imwrite(str(review/'summary.jpg'),summary)
    def embedded_preview(record):
        image = root/'previews'/(record['id']+'.jpg')
        return 'data:image/jpeg;base64,' + base64.b64encode(image.read_bytes()).decode('ascii')

    cards=''.join(f'<article><h3>{r["id"]} — {len(r["objects"])} objects</h3><a href="../images/{r["id"]}.png"><img width="848" height="480" style="height:auto" src="{embedded_preview(r)}" loading="eager"></a><p>{html.escape(", ".join(o["kind"]+":"+o["variant"] for o in r["objects"])) or "Background / Distractor image: Empty labels"}</p><a href="../labels/{r["id"]}.txt">Labels</a> · <a href="../annotations/{r["id"]}.json">Metadata</a></article>' for r in records)
    (review/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>X/O Pilot batch 100 images reviewed</title><style>body{font:16px sans-serif;margin:30px;background:#edf2f3;color:#20363a}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(420px,1fr));gap:20px}article{background:white;padding:16px;border-radius:12px}img{width:100%}p{line-height:1.6}a{color:#007b84}</style><h1>X/O Simulation camera pilot review</h1><p>80 images with objects, 20 background images.Yellow boxes and classes appear only in previews; Click the image to view the original camera frame.Not trained, Dataset has not been split.</p><main>'+cards+'</main>',encoding='utf-8')
    (root/'README.md').write_text('''# X/O Pilot simulation camera review data

- 100 images: 80 including X/O, 20 Background; Rules confirmed-v1-20261117.
- Raw camera image `images/`; YOLO Labels `labels/`; Parameters, Intrinsics, Camera pose, Timestamp `annotations/`.
- Detection preview `previews/` and `review/index.html`; 4 full contact sheet and summary images at `review/`.
- Labels class 0=X, 1=O; Boxes are projected from rendered meshes and checked against camera images.Yellow boxes are not written to original images.
- Course board, Desktop, Camera plugin; Independent scenes/Domain 191/Port 11619; Camera 848×480, 12Hz, Small viewpoint changes.
- Render grid strokes directly, No arm, No motion, No physical contact.Grid and marks use validated distinct material colors.
- Cover straight strokes/curved/broken stroke/Length variation/retraced X; circle/ellipse/gap/hand-drawn/retraced O; Blank, Grid, triangle, square, V, single line.
- `audit.json` uses automated structure and pixel checks, requires human label review; Review boundary examples.
- Pilot batch uses no robot arm/hand occlusion, real lighting remains unverified, blur or real-camera transfer; Incomplete stroke/Ambiguous shapes are excluded from background labels.
- Current setting review_unsplit.After review, split by scene_group Split, Apply augmentation only to the training split; This batch is not an independent generalization test.
- `data.yaml` Register only the class, No train/val/test Entry point; Training was not started.
''',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('--expected',type=int,default=100);p.add_argument('--no-review',action='store_true');args=p.parse_args();audit(args.root,args.expected,not args.no_review)
