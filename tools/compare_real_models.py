"""Audit frozen X/O detectors on reviewed real originals, without training or robot use."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import time

import cv2
import numpy as np
import torch

from tictactoe_gui.real_board_perception import RealBoardPerception

COHORTS = {
    'early_real': 'xo_real_review_v2_20261119',
    'capture48': 'xo_real_capture48_labeled_20261120',
    'nine_native': 'xo_real_nine_20261121/prepared_v1',
    'nine_edges': 'xo_real_nine_edges_20261122/prepared_v1',
    'nine_zero': 'xo_real_nine_zero_20261122/prepared_v1',
}
MODELS = ['xo_real.pt', 'xo_real_nine.pt', 'xo_real_nine_zero_candidate.pt']


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inventory(repo):
    rows=[]
    for cohort, folder in COHORTS.items():
        root=repo/'data/datasets'/folder
        if cohort.startswith('nine_'):
            for a in json.loads((root/'annotations.json').read_text()):
                rows.append(dict(cohort=cohort, group=cohort+'/'+a['group'], split=a['split'],
                    image=a['image'], size=9, boxes=[dict(mark=('X','O')[b['category']],xyxy=b['xyxy']) for b in a['boxes']],
                    marks=a['marks'], ignored=a.get('ignored_cells', [])))
        else:
            metadata={}
            if cohort=='early_real':
                metadata={Path(x['image']).name:x for x in json.loads((root/'split_manifest.json').read_text())['rows']}
            for image in sorted((root/'images').rglob('*.png')):
                split=image.parent.name
                name=image.stem
                group=(metadata[image.name]['group'] if metadata else
                       re.match(r'(capture48-\d+)', name).group(1))
                raw=cv2.imread(str(image));h,w=raw.shape[:2]
                label=root/'labels'/split/(name+'.txt')
                boxes=[]
                for line in label.read_text().splitlines():
                    c,x,y,bw,bh=map(float,line.split())
                    boxes.append(dict(mark=('X','O')[int(c)],xyxy=[(x-bw/2)*w,(y-bh/2)*h,(x+bw/2)*w,(y+bh/2)*h]))
                rows.append(dict(cohort=cohort,group=cohort+'/'+group,split=split,image=str(image),
                    size=3,boxes=boxes,marks=[],ignored=[]))
    unique=[];seen={};duplicates=[]
    for row in rows:
        raw=cv2.imread(row['image'])
        if raw is None:raise ValueError('Unreadable image '+row['image'])
        row['sha256']=sha(row['image']);row['shape']=list(raw.shape)
        row['pixel_sha256']=hashlib.sha256(raw.tobytes()).hexdigest()
        if row['pixel_sha256'] in seen:
            duplicates.append(dict(image=row['image'],kept=seen[row['pixel_sha256']]))
            continue
        row['id']=f"{row['cohort']}__{Path(row['image']).stem}"
        seen[row['pixel_sha256']]=row['image'];unique.append(row)
    return unique,duplicates


def add_exposure(rows,repo):
    # Include known initialization lineage, not merely the last fine-tuning run.
    base=repo/'data/datasets'
    train_files=[base/COHORTS['capture48']/'train.txt',
                 base/COHORTS['nine_native']/'train.txt',base/COHORTS['nine_zero']/'train.txt']
    train_paths=[[Path(line.strip()) for line in f.read_text().splitlines() if line.strip()]
                 for f in train_files]
    hash_cache={}
    train_hashes=[]
    for paths in train_paths:
        values=set()
        for path in paths:
            if path not in hash_cache:hash_cache[path]=sha(path)
            values.add(hash_cache[path])
        train_hashes.append(values)
    for row in rows:
        row['exposure']={}
        for i,model in enumerate(MODELS):
            trained=row['sha256'] in train_hashes[i]
            if row['size']==9:
                # A trained native crop exposes its physical capture group even
                # when the original full JPEG itself is absent from train.txt.
                cohort_root=base/COHORTS[row['cohort']]
                group=row['group'].split('/')[-1]
                trained=trained or any(cohort_root in path.parents and
                    path.name.startswith(group+'-layout-') for path in train_paths[i])
            validation=(row['split']=='val' and (row['cohort']=='capture48' or
                (i>=1 and row['cohort']=='nine_native') or (i>=2 and row['cohort']=='nine_zero')))
            row['exposure'][model]='training_source' if trained else 'validation_source' if validation else 'historical_not_trained'
        row['common_untrained']=all(v!='training_source' for v in row['exposure'].values())
        row['common_nonselection']=all(v=='historical_not_trained' for v in row['exposure'].values())


def iou(a,b):
    x0,y0=max(a[0],b[0]),max(a[1],b[1]);x1,y1=min(a[2],b[2]),min(a[3],b[3])
    intersection=max(0,x1-x0)*max(0,y1-y0)
    area=lambda q:max(0,q[2]-q[0])*max(0,q[3]-q[1])
    return intersection/max(1e-12,area(a)+area(b)-intersection)


def match_boxes(truth,prediction):
    candidates=sorted(((iou(t['xyxy'],p['xyxy']),i,j)
        for i,t in enumerate(truth) for j,p in enumerate(prediction)
        if t['mark']==p['mark']),reverse=True)
    used_t,used_p=set(),set()
    for overlap,i,j in candidates:
        if overlap>=.5 and i not in used_t and j not in used_p:
            used_t.add(i);used_p.add(j)
    fn=[i for i in range(len(truth)) if i not in used_t]
    fp=[i for i in range(len(prediction)) if i not in used_p]
    duplicates=sum(any(p['mark']==t['mark'] and iou(p['xyxy'],t['xyxy'])>=.5 for t in truth)
                   for j,p in enumerate(prediction) if j in fp)
    return dict(tp=len(used_t),fn=len(fn),fp=len(fp),fn_indices=fn,fp_indices=fp,
                duplicate_fp=duplicates,exact=not fn and not fp)


class RecordingModel:
    def __init__(self,model):self.model=model;self.results=None;self.shapes=None
    def predict(self,images,**options):
        self.shapes=[list(x.shape) for x in images]
        self.results=self.model.predict(images,**options)
        return self.results


def expected_cells(entry,transform):
    if entry['size']==9:
        return {(m['row'],m['col']):{m['mark']} for m in entry['marks']},True
    cells={};eligible=True
    for b in entry['boxes']:
        x0,y0,x1,y1=b['xyxy'];point=np.float32([[[(x0+x1)/2,(y0+y1)/2]]])
        x,y=cv2.perspectiveTransform(point,transform)[0,0]
        cell=(int(np.floor(y*3/567)),int(np.floor(x*3/420)))
        if not (0<=cell[0]<3 and 0<=cell[1]<3) or cell in cells:eligible=False
        cells.setdefault(cell,set()).add(b['mark'])
    return cells,eligible


def compare_cells(truth,actual,ignored):
    ignore={tuple(c) for c in ignored}
    t={(r,c,m) for (r,c),marks in truth.items() if (r,c) not in ignore for m in marks}
    a={(r,c,m) for (r,c),marks in actual.items() if (r,c) not in ignore for m in marks}
    return dict(tp=len(t&a),fn=len(t-a),fp=len(a-t),exact=t==a,
                fn_marks=sorted(t-a),fp_marks=sorted(a-t),conflicts=sum(len(v)>1 for c,v in actual.items() if c not in ignore))


def totals(rows,key):
    values=[r[key] for r in rows if r.get(key) is not None]
    tp=sum(v['tp'] for v in values);fn=sum(v['fn'] for v in values);fp=sum(v['fp'] for v in values)
    precision=tp/max(1,tp+fp);recall=tp/max(1,tp+fn)
    return dict(frames=len(values),groups=len({r['group'] for r in rows if r.get(key) is not None}),
        tp=tp,fn=fn,fp=fp,precision=precision,recall=recall,f1=2*precision*recall/max(1e-12,precision+recall),
        exact=sum(v['exact'] for v in values),exact_rate=sum(v['exact'] for v in values)/max(1,len(values)),
        duplicates=sum(v.get('duplicate_fp',0) for v in values),conflicts=sum(v.get('conflicts',0) for v in values))


def run(repo,output,device):
    from ultralytics import YOLO
    output.mkdir(parents=True,exist_ok=False)
    entries,duplicates=inventory(repo);add_exposure(entries,repo)
    (output/'manifest.json').write_text(json.dumps(dict(images=entries,duplicate_files=duplicates),indent=2))
    print('INVENTORY',len(entries),'unique originals;',len(duplicates),'pixel-identical duplicates excluded',flush=True)
    points=json.loads((repo/'tictactoe_gui/config/grid_points_real.json').read_text())
    torch.set_num_threads(2)
    all_results={}
    for name in MODELS:
        weights=repo/'tictactoe_gui/models'/name
        recorder=RecordingModel(YOLO(str(weights)))
        detector=RealBoardPerception(str(weights),points,device=device);detector.model=recorder
        rows=[];started=time.monotonic()
        for number,entry in enumerate(entries,1):
            image_bytes=Path(entry['image']).read_bytes()
            start=time.monotonic();actual=detector.detect_cells(image_bytes,entry['size']);elapsed=time.monotonic()-start
            _,transform=detector._camera_frame(image_bytes)
            truth,eligible=expected_cells(entry,transform)
            cell_score=compare_cells(truth,actual,entry['ignored']) if eligible else None
            predictions=[];box_score=None
            if entry['size']==3:
                result=recorder.results[0]
                predictions=[dict(xyxy=b[:4],confidence=b[4],mark=result.names[int(b[5])].upper()) for b in result.boxes.data.cpu().tolist()]
                box_score=match_boxes(entry['boxes'],predictions)
            ignored={tuple(c) for c in entry['ignored']}
            region={}
            for label,test in [('top',lambda r,c:r==0),('right',lambda r,c:c==entry['size']-1),
                               ('top_right',lambda r,c:r==0 and c==entry['size']-1),('interior',lambda r,c:0<r<entry['size']-1 and 0<c<entry['size']-1)]:
                expected={(r,c,m) for (r,c),marks in truth.items() if test(r,c) and (r,c) not in ignored for m in marks}
                detected={(r,c,m) for (r,c),marks in actual.items() if test(r,c) and (r,c) not in ignored for m in marks}
                region[label]=dict(tp=len(expected&detected),fn=len(expected-detected),fp=len(detected-expected))
            rows.append(dict(id=entry['id'],cohort=entry['cohort'],group=entry['group'],split=entry['split'],
                exposure=entry['exposure'][name],common_untrained=entry['common_untrained'],common_nonselection=entry['common_nonselection'],
                image=entry['image'],size=entry['size'],elapsed_s=elapsed,box=box_score,cells=cell_score,
                cell_mapping_eligible=eligible,ignored=entry['ignored'],predictions=predictions,regions=region,
                detected=[dict(row=r,col=c,marks=sorted(m)) for (r,c),m in actual.items()]))
            if number%40==0 or number==len(entries):print(name,number,'/',len(entries),'elapsed',round(time.monotonic()-started,1),flush=True)
        groups={}
        for cohort in COHORTS:
            subset=[r for r in rows if r['cohort']==cohort]
            groups[cohort]={key:totals(subset,key) for key in ['box','cells']}
        for subset_name,test in [('all',lambda r:True),('common_untrained',lambda r:r['common_untrained']),
                                ('common_nonselection',lambda r:r['common_nonselection'])]:
            subset=[r for r in rows if test(r)]
            groups[subset_name]={key:totals(subset,key) for key in ['box','cells']}
        report=dict(model=name,sha256=sha(weights),groups=groups,rows=rows,elapsed_s=time.monotonic()-started)
        (output/(name+'.json')).write_text(json.dumps(report,indent=2));all_results[name]=report
        print('MODEL_SUMMARY',name,json.dumps(groups['common_untrained']),flush=True)
        del detector,recorder;torch.cuda.empty_cache()
    (output/'summary.json').write_text(json.dumps({name:{'sha256':d['sha256'],'groups':d['groups'],'elapsed_s':d['elapsed_s']} for name,d in all_results.items()},indent=2))
    return all_results


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--repo',type=Path,default=Path(__file__).resolve().parents[1]);p.add_argument('--output',type=Path,required=True);p.add_argument('--device',default='0')
    args=p.parse_args();run(args.repo,args.output,args.device)
