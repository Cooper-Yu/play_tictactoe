"""Build a scene-grouped 1000-image X/O dataset without starting training."""
import argparse
from collections import Counter,defaultdict
import hashlib
import json
from pathlib import Path
import random
import shutil
import xml.etree.ElementTree as ET
import cv2
import numpy as np

SPLITS=('train','val','test')


def centerline_signature(files):
    """! @brief Ignore material/pen width, preserve all actual ink/grid centerlines."""
    strokes=[]
    for file in files:
        root=ET.parse(file).getroot();ns={'c':'http://www.collada.org/2005/11/COLLADASchema'}
        v=np.fromstring(root.find('.//c:float_array',ns).text,sep=' ').reshape(-1,3)
        points=[]
        for j in range(0,len(v)-5,6):
            a=v[j:j+6]
            # Ribbon rectangles precede round-join triangle fans.
            if not (np.allclose(a[2],a[3],atol=1e-12,rtol=0) and np.allclose(a[1],a[4],atol=1e-12,rtol=0)):break
            first=(a[0]+a[1])/2;last=(a[2]+a[5])/2
            if not points:points.append(first)
            points.append(last)
        assert points,file
        encoded=json.dumps(np.round(points,8).tolist(),separators=(',',':'))
        reverse=json.dumps(np.round(points[::-1],8).tolist(),separators=(',',':'))
        strokes.append(min(encoded,reverse))
    return hashlib.sha256(json.dumps(sorted(strokes),separators=(',',':')).encode()).hexdigest()


def subset(groups,target):
    """! @brief Select whole groups at an exact image count using bounded subset sum."""
    dp={0:[]}
    for group in groups:
        weight=len(group['records'])
        for total,chosen in list(dp.items())[::-1]:
            if total+weight<=target and total+weight not in dp:dp[total+weight]=chosen+[group['id']]
        if target in dp:return set(dp[target])
    raise ValueError(f'Cannot fill {target} images without splitting groups')


def record_tags(record):
    tags=['grid:'+str(bool(record.get('grid',False)))]
    if record['negative']:
        tags.append('background:'+record.get('background_type','unspecified'))
    else:
        tags.extend(o['kind']+':'+o['variant'] for o in record['objects'])
    return tags


def choose_split(groups,seed):
    best=None
    for trial in range(120):
        rng=random.Random(seed+trial);assigned={}
        for negative,target in [(False,120),(True,30)]:
            pool=[g for g in groups if g['negative']==negative];rng.shuffle(pool)
            val=subset(pool,target);remaining=[g for g in pool if g['id'] not in val]
            test=subset(remaining,target)
            for g in pool:assigned[g['id']]='val' if g['id'] in val else 'test' if g['id'] in test else 'train'
        total=Counter(tag for g in groups for r in g['records'] for tag in record_tags(r))
        counts={split:Counter(tag for g in groups if assigned[g['id']]==split for r in g['records'] for tag in record_tags(r)) for split in SPLITS}
        score=sum(abs(counts[sp][key]/max(number,1)-fraction) for sp,fraction in [('train',.7),('val',.15),('test',.15)] for key,number in total.items())
        if best is None or score<best[0]:best=(score,assigned,trial)
    return best


def copy_checked(src,dst):
    shutil.copy2(src,dst)
    assert hashlib.sha256(src.read_bytes()).digest()==hashlib.sha256(dst.read_bytes()).digest()


def main():
    p=argparse.ArgumentParser();p.add_argument('--pilot',type=Path,required=True);p.add_argument('--extra',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--seed',type=int,default=20261117);args=p.parse_args()
    out=args.output.resolve();assert not out.exists(),'Refuse overwrite'
    sources=[('pilot',args.pilot.resolve(),100),('extra',args.extra.resolve(),900)];all_records=[];source_hashes={};geometry_cache={}
    for source,root,expected in sources:
        audit=json.loads((root/'audit.json').read_text());assert audit['frames']==expected and audit['status']=='automated_audit_passed_human_review_pending'
        manifest=json.loads((root/'manifest.json').read_text());assert len(manifest['records'])==expected
        for r in manifest['records']:
            r=dict(r);r['source_batch']=source;r['source_root']=str(root)
            if r['negative']:
                layout_index=int(r['id'].rsplit('_',1)[1]) if source=='pilot' else int(r['scene_group'].rsplit('_',1)[1])
                r['background_type']=['blank','triangle','square','V','slash'][layout_index//5%5]
            if source=='extra':pattern=r['scene_group']+f"_view{r['view_index']}_*.dae"
            else:pattern=r['scene_group']+'_*.dae'
            files=sorted((root/'meshes').glob(pattern));signature=centerline_signature(files)
            key=(source,r['scene_group']);geometry_cache.setdefault(key,signature);assert geometry_cache[key]==signature,(key,'Views changed base geometry')
            r['geometry_sha256']=signature;r['origin_scene_group']=r['scene_group'];r['scene_group']='geometry_'+signature[:20]
            source_hashes[r['id']]={'image':hashlib.sha256((root/'images'/(r['id']+'.png')).read_bytes()).hexdigest(),'label':hashlib.sha256((root/'labels'/(r['id']+'.txt')).read_bytes()).hexdigest()}
            all_records.append(r)
        print(f'GROUP_AUDIT {source} records={expected}',flush=True)
    assert len({r['id'] for r in all_records})==1000
    assert len({r['sha256'] for r in all_records})==1000
    by_group=defaultdict(list)
    for r in all_records:by_group[r['scene_group']].append(r)
    groups=[dict(id=k,negative=rs[0]['negative'],records=rs) for k,rs in by_group.items()]
    assert all(len({r['negative'] for r in g['records']})==1 for g in groups)
    score,assignment,trial=choose_split(groups,args.seed)
    out.mkdir(parents=True)
    for split in SPLITS:
        for folder in ['images','labels','annotations']:(out/folder/split).mkdir(parents=True)
    (out/'previews').mkdir();(out/'review').mkdir()
    for r in all_records:
        split=assignment[r['scene_group']];r['split']=split;root=Path(r['source_root']);stem=r['id']
        for folder,ext in [('images','png'),('labels','txt')]:copy_checked(root/folder/(stem+'.'+ext),out/folder/split/(stem+'.'+ext))
        copy_checked(root/'previews'/(stem+'.jpg'),out/'previews'/(stem+'.jpg'))
        (out/'annotations'/split/(stem+'.json')).write_text(json.dumps(r,indent=2))
    stats={}
    for split in SPLITS:
        rs=[r for r in all_records if r['split']==split];stats[split]=dict(images=len(rs),positive=sum(not r['negative'] for r in rs),background=sum(r['negative'] for r in rs),groups=len({r['scene_group'] for r in rs}),class_instances=dict(Counter(o['kind'] for r in rs for o in r['objects'])),variants=dict(Counter(o['kind']+':'+o['variant'] for r in rs for o in r['objects'])),background_types=dict(Counter(r['background_type'] for r in rs if r['negative'])))
    assert [stats[s]['images'] for s in SPLITS]==[700,150,150]
    assert [stats[s]['background'] for s in SPLITS]==[140,30,30]
    leakage={g['id'] for g in groups if len({r['split'] for r in g['records']})!=1};assert not leakage
    assert all(len({assignment[r['scene_group']] for r in all_records if r['source_batch']==src and r['origin_scene_group']==original})==1 for src,original in geometry_cache)
    for r in all_records:
        actual_img=hashlib.sha256((out/'images'/r['split']/(r['id']+'.png')).read_bytes()).hexdigest();actual_label=hashlib.sha256((out/'labels'/r['split']/(r['id']+'.txt')).read_bytes()).hexdigest()
        assert actual_img==source_hashes[r['id']]['image'] and actual_label==source_hashes[r['id']]['label']
    (out/'data.yaml').write_text('path: '+str(out)+'\ntrain: images/train\nval: images/val\ntest: images/test\nnames:\n  0: X\n  1: O\n')
    manifest=dict(version='xo_sim_v1',rules='confirmed-v1-20261117',status='split_validated_not_trained',split_seed=args.seed,selection_trial=trial,selection_objective=score,split_uses_model_predictions=False,groups=len(groups),statistics=stats,records=all_records,source_file_hashes=source_hashes,limitations=['simulation only; no real-transfer validation','no hand/robot occlusion in this version','270-ish distinct base layouts, not 1000 independent layouts','five views per new layout, grouped across split','group membership also merges exact centerline geometry across source scene IDs','no post-capture augmentation or training run'])
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2))
    report=dict(status='passed',images=1000,unique_image_sha256=1000,groups=len(groups),geometry_cross_split_leaks=0,source_scene_cross_split_leaks=0,preserved_reviewed_images=100,preserved_reviewed_labels=100,all_image_and_label_bytes_preserved=True,statistics=stats,split_seed=args.seed,selection_trial=trial,training_started=False)
    (out/'split_audit.json').write_text(json.dumps(report,indent=2))
    # 20 images per HTTP page keeps long-page previews manageable.
    ordered=sorted(all_records,key=lambda r:r['id'])
    for page,start in enumerate(range(0,1000,20),1):
        cards=[]
        for r in ordered[start:start+20]:
            stem=r['id'];split=r['split'];cards.append(f'<article><h3>{stem} · {split} · {len(r["objects"])} objects</h3><a href="../images/{split}/{stem}.png"><img width="848" height="480" loading="eager" src="../previews/{stem}.jpg"></a><p>{", ".join(o["kind"]+":"+o["variant"] for o in r["objects"]) or "背景／干扰图"}</p><a href="../labels/{split}/{stem}.txt">标签</a> · <a href="../annotations/{split}/{stem}.json">元数据</a></article>')
        nav=' '.join(f'<a href="page_{i:02d}.html">{i}</a>' for i in range(1,51))
        content=f'<!doctype html><meta charset="utf-8"><title>X/O 1000审核 {page}/50</title><style>body{{font:16px sans-serif;margin:24px;background:#edf2f3}}nav{{line-height:2.2}}main{{display:grid;grid-template-columns:repeat(auto-fit,minmax(380px,1fr));gap:20px}}article{{background:white;padding:16px;border-radius:12px}}img{{width:100%;height:auto}}a{{color:#087c86}}</style><h1>X/O 1000：第 {page}/50 页</h1><p>700 train / 150 val / 150 test，按几何场景分组；未训练。黄色框仅在预览中。</p><nav>{nav}</nav><main>'+''.join(cards)+'</main>'
        (out/'review'/f'page_{page:02d}.html').write_text(content,encoding='utf-8')
    (out/'review'/'index.html').write_text('<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0;url=page_01.html"><a href="page_01.html">打开1000张审核页</a>',encoding='utf-8')
    # Overview every tenth base scene plus pilot samples; no model-derived outcomes.
    chosen=[ordered[i] for i in [0,24,49,74,99,100,150,250,350,450,550,650,750,850,950]]
    sheet=np.full((5*264,3*424,3),245,np.uint8)
    for i,r in enumerate(chosen):
        im=cv2.resize(cv2.imread(str(out/'previews'/(r['id']+'.jpg'))),(424,240));x=i%3*424;y=i//3*264;sheet[y:y+240,x:x+424]=im;cv2.putText(sheet,r['id']+' | '+r['split'],(x+8,y+257),cv2.FONT_HERSHEY_SIMPLEX,.48,(30,30,30),1)
    cv2.imwrite(str(out/'review'/'summary.jpg'),sheet)
    (out/'README.md').write_text('# X/O 仿真数据集 v1\n\n1000张：保留审核通过的100张，新增900张（180个布局，各5视图）。\n按实际笔迹/网格中心线几何指纹合并重复底图，并保留原scene_group约束。\n分组后固定随机种子，以类别/变体比例近似平衡，精确700/150/150。\n训练含560目标图+140背景；验证/测试各120目标图+30背景。\n原图和标签均逐文件SHA256一致；黄色框只在previews中。\n查看split_audit.json、manifest.json和data.yaml；review/为20图一页的HTTP审核入口。\n测试集现已冻结，不用于调参。没有启动训练或训练后增强。\n本版无机械臂/手遮挡，仍有仿真到真实的差异；不代表泛化或模型精度达标。\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
