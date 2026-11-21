"""Evaluate a frozen model through the deployed four-zone cell mapping, offline."""
import argparse
import hashlib
import json
from pathlib import Path
import time

import cv2
from tictactoe_gui.real_board_perception import RealBoardPerception


def compare_cells(expected, detected, ignore_cells=()):
    ignored = {tuple(c) for c in ignore_cells}
    truth = {(m['row'],m['col'],m['mark']) for m in expected if (m['row'],m['col']) not in ignored}
    actual = {(r,c,mark) for (r,c),marks in detected.items() if (r,c) not in ignored for mark in marks}
    return dict(tp=len(truth & actual),fn=sorted(truth-actual),fp=sorted(actual-truth),
                exact=truth==actual,conflicts=sum(len(x)>1 for c,x in detected.items() if c not in ignored),ignored_cells=sorted(ignored))


def evaluate(weights, dataset, split, points, output, device='0'):
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    output.mkdir(parents=True)
    perception = RealBoardPerception(weights,json.loads(Path(points).read_text()),device=device)
    annotations = json.loads((Path(dataset)/'annotations.json').read_text())
    rows=[]
    for entry in (x for x in annotations if x['split']==split):
        raw = Path(entry['image']).read_bytes()
        start=time.monotonic()
        detected = perception.detect_cells(raw,9)
        result=compare_cells(entry['marks'],detected,entry.get('ignored_cells',()))
        result.update(image=entry['image'],group=entry['group'],elapsed=time.monotonic()-start,
                      detected=[dict(row=r,col=c,marks=sorted(m)) for (r,c),m in detected.items()])
        rows.append(result)
        image,transform = perception._camera_frame(raw)
        overlay=perception.camera_overlay(image,transform,9)
        cv2.imwrite(str(output/(Path(entry['image']).stem+'.jpg')),cv2.resize(overlay,(848,480)))
    totals=dict(frames=len(rows),physical_groups=len({x['group'] for x in rows}),
                exact=sum(x['exact'] for x in rows),tp=sum(x['tp'] for x in rows),
                fn=sum(len(x['fn']) for x in rows),fp=sum(len(x['fp']) for x in rows),
                conflicts=sum(x['conflicts'] for x in rows),
                ignored_cell_observations=sum(len(x['ignored_cells']) for x in rows),
                exact_scope='reviewed cells only; unreadable cells excluded from all counts')
    totals['recall']=totals['tp']/max(1,totals['tp']+totals['fn'])
    totals['precision']=totals['tp']/max(1,totals['tp']+totals['fp'])
    report=dict(model=str(weights),sha256=hashlib.sha256(Path(weights).read_bytes()).hexdigest(),
                split=split,recipe='deployed native four-zone crops, conf=.25, iou=.7, end2end=False',
                totals=totals,frames=rows)
    (output/'report.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(dict(output=str(output),**totals)),flush=True)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('weights','dataset','points','output'):
        parser.add_argument('--'+key,required=True,type=Path)
    parser.add_argument('--split',choices=('train','val','test'),required=True)
    parser.add_argument('--device',default='0')
    args=parser.parse_args()
    evaluate(args.weights,args.dataset,args.split,args.points,args.output,args.device)