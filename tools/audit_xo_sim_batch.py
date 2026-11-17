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


def audit(root,expected=100):
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

    cards=''.join(f'<article><h3>{r["id"]} — {len(r["objects"])} objects</h3><a href="../images/{r["id"]}.png"><img width="848" height="480" style="height:auto" src="{embedded_preview(r)}" loading="eager"></a><p>{html.escape(", ".join(o["kind"]+":"+o["variant"] for o in r["objects"])) or "背景／干扰图：空标签"}</p><a href="../labels/{r["id"]}.txt">标签</a> · <a href="../annotations/{r["id"]}.json">元数据</a></article>' for r in records)
    (review/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>X/O 首批100张审核</title><style>body{font:16px sans-serif;margin:30px;background:#edf2f3;color:#20363a}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(420px,1fr));gap:20px}article{background:white;padding:16px;border-radius:12px}img{width:100%}p{line-height:1.6}a{color:#007b84}</style><h1>X/O 仿真相机首批审核</h1><p>80 张含目标，20 张背景。黄色框和类别仅在预览上；点击图像查看未画框的相机原图。尚未训练、尚未划分数据集。</p><main>'+cards+'</main>',encoding='utf-8')
    (root/'README.md').write_text('''# X/O 首批仿真相机审核数据

- 100 张：80 含 X/O，20 背景；规则 confirmed-v1-20261117。
- 原始相机图像 `images/`；YOLO 标签 `labels/`；参数、内参、相机位姿、时间戳 `annotations/`。
- 带框预览 `previews/` 与 `review/index.html`；4 张完整联系表与摘要图在 `review/`。
- 标签 class 0=X，1=O；框由实际渲染三角网格投影并按相机画面核查。黄色框不写入原图。
- 原课程黑板、桌面、相机插件；独立场景/域191/端口11619；相机848×480、12Hz，轻微改变视点。
- 直接渲染网格笔迹，无机械臂、无运动、无物理接触。网格与符号使用已验证的不同材质颜色。
- 覆盖直线/弯曲/断线/长短变化/重描 X；圆/椭圆/缺口/手绘/重描 O；空白、网格、三角形、方形、V、单线。
- `audit.json` 是自动结构与像素核对，不能替代人的标注审核；边界样例仍需查看。
- 首批没有机械臂/手遮挡，也不代表已验证真实光照、模糊或真实相机迁移；未完成笔画/待复核形状未混作背景。
- 当前保持 review_unsplit。审核后按 scene_group 划分，之后仅对训练部分增强；本批不是独立泛化测试。
- `data.yaml` 只登记类别，没有 train/val/test 入口；没有启动训练。
''',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('--expected',type=int,default=100);args=p.parse_args();audit(args.root,args.expected)
