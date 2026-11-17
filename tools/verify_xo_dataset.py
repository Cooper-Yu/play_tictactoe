"""Independently verify a prepared dataset from saved files; never import a model."""
import argparse
from collections import Counter,defaultdict
import hashlib
import json
from pathlib import Path
import cv2
import numpy as np
import yaml


def verify(root,pilot):
    manifest=json.loads((root/'manifest.json').read_text());records=manifest['records'];config=yaml.safe_load((root/'data.yaml').read_text())
    assert config['names']=={0:'X',1:'O'} and Path(config['path'])==root.resolve()
    assert len(records)==1000 and manifest['status']=='split_validated_not_trained'
    by_id={r['id']:r for r in records};assert len(by_id)==1000
    hashes=set();geometry_splits=defaultdict(set);original_splits=defaultdict(set);statistics={};retained=0
    for split,target,background in [('train',700,140),('val',150,30),('test',150,30)]:
        files=sorted((root/config[split]).glob('*.png'));assert len(files)==target
        assert len(list((root/'labels'/split).glob('*.txt')))==target
        assert len(list((root/'annotations'/split).glob('*.json')))==target
        negatives=0;counts=Counter()
        for file in files:
            rec=json.loads((root/'annotations'/split/(file.stem+'.json')).read_text());assert rec==by_id[file.stem] and rec['split']==split
            image=cv2.imread(str(file));assert image is not None and image.shape==(480,848,3)
            sha=hashlib.sha256(file.read_bytes()).hexdigest();assert sha==rec['sha256'] and sha not in hashes;hashes.add(sha)
            label=root/'labels'/split/(file.stem+'.txt');lines=label.read_text().splitlines();assert len(lines)==len(rec['objects'])
            if not lines:negatives+=1
            for line,obj in zip(lines,rec['objects']):
                values=np.array(list(map(float,line.split())));assert values.shape==(5,) and np.isfinite(values).all()
                cls,cx,cy,w,h=values;assert cls in (0,1) and int(cls)==obj['class_id']
                assert 0<w<=1 and 0<h<=1 and 0<=cx-w/2<cx+w/2<=1 and 0<=cy-h/2<cy+h/2<=1
                counts['X' if cls==0 else 'O']+=1
            geometry_splits[rec['geometry_sha256']].add(split);original_splits[(rec['source_batch'],rec['origin_scene_group'])].add(split)
            if rec['source_batch']=='pilot':
                assert file.read_bytes()==(pilot/'images'/file.name).read_bytes()
                assert label.read_bytes()==(pilot/'labels'/label.name).read_bytes();retained+=1
        assert negatives==background
        statistics[split]=dict(images=target,background=negatives,class_instances=dict(counts))
    assert retained==100 and len(hashes)==1000
    assert all(len(v)==1 for v in geometry_splits.values())
    assert all(len(v)==1 for v in original_splits.values())
    report=dict(status='passed',files_read=1000,unique_images=1000,preserved_pilot_image_and_label_pairs=100,geometry_groups=len(geometry_splits),source_scene_groups=len(original_splits),geometry_leaks=0,source_scene_leaks=0,statistics=statistics,training_started=False)
    (root/'independent_verification.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root',type=Path);parser.add_argument('--pilot',type=Path,required=True);args=parser.parse_args();verify(args.root.resolve(),args.pilot.resolve())
