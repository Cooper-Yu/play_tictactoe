"""Prepare reviewed real 9x9 crops without changing physical-board split membership."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

import cv2
import numpy as np
import yaml

WIDTH, HEIGHT = 420, 567


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check_review(path, review):
    entry = review.get(str(path.name))
    if not entry or entry.get('approved') is not True or entry.get('sha256') != digest(path):
        raise ValueError(f'Image not reviewed or changed: {path.name}')


def crop_regions(shape, transform):
    height, width = shape[:2]
    inverse = np.linalg.inv(transform)
    regions = []
    for r0, r1 in ((0, 5), (5, 9)):
        for c0, c1 in ((0, 5), (5, 9)):
            x0, x1 = (c0-1)*WIDTH/9, (c1+1)*WIDTH/9
            y0, y1 = (r0-1)*HEIGHT/9, (r1+1)*HEIGHT/9
            corners = np.float32([[[x0,y0],[x1,y0],[x1,y1],[x0,y1]]])
            pixels = cv2.perspectiveTransform(corners, inverse)[0]
            left, top = np.maximum(np.floor(pixels.min(axis=0)).astype(int), 0)
            right, bottom = np.minimum(np.ceil(pixels.max(axis=0)).astype(int), [width,height])
            regions.append((int(left),int(top),int(right),int(bottom)))
    return regions


def mark_box(mark, inverse, canvas_size):
    points = np.asarray([p for stroke in mark['strokes'] for p in stroke], dtype=np.float32)
    if points.ndim != 2 or points.shape[1] != 2 or not np.isfinite(points).all():
        raise ValueError('Invalid planned stroke coordinates')
    mx, my = .002/canvas_size[0], .002/canvas_size[1]
    points[:,0] = (points[:,0]-mx)/(1-2*mx)*WIDTH
    points[:,1] = (points[:,1]-my)/(1-2*my)*HEIGHT
    pixels = cv2.perspectiveTransform(points[None], inverse)[0]
    return np.r_[pixels.min(axis=0)-1., pixels.max(axis=0)+1.].astype(float)


def crop_labels(boxes, region):
    left, top, right, bottom = region
    labels = []
    for category, box in boxes:
        x0,y0,x1,y1 = box
        clipped = np.array([max(x0,left),max(y0,top),min(x1,right),min(y1,bottom)])
        area = max(0.,clipped[2]-clipped[0])*max(0.,clipped[3]-clipped[1])
        if not area:
            continue
        # Do not teach an ambiguous clipped neighbor as background or a full mark.
        if area/((x1-x0)*(y1-y0)) < .995:
            return None
        x0,y0,x1,y1 = clipped - [left,top,left,top]
        labels.append((category,(x0+x1)/2/(right-left),(y0+y1)/2/(bottom-top),
                       (x1-x0)/(right-left),(y1-y0)/(bottom-top)))
    return labels


def prepare(raw, review_file, output, points_file, board_file, old_train, *, expected_counts=(8,2,2)):
    raw, output = Path(raw).resolve(), Path(output).resolve()
    if output.exists():
        raise FileExistsError(output)
    if len(expected_counts) != 3 or any(not isinstance(n,int) or n < 1 for n in expected_counts):
        raise ValueError('Require positive train, validation and test group counts')
    manifest = json.loads((raw/'manifest.json').read_text())
    complete = [x for x in manifest if x['complete']]
    required = sum(expected_counts)
    if len(complete) != required or len({x['group'] for x in complete}) != required:
        number = 'twelve' if required == 12 else str(required)
        raise ValueError(f'Require all {number} complete, independent capture groups')
    reviews = json.loads(Path(review_file).read_text())
    points = np.float32(json.loads(Path(points_file).read_text()))
    transform = cv2.getPerspectiveTransform(points,np.float32([[140,189],[280,189],[280,378],[140,378]]))
    inverse = np.linalg.inv(transform)
    corners = np.array(yaml.safe_load(Path(board_file).read_text())['safe_corners'])
    canvas_size = (np.linalg.norm(corners[1,:2]-corners[0,:2]),np.linalg.norm(corners[3,:2]-corners[0,:2]))
    split_lists = {s:[] for s in ('train','val','test')}
    groups = {s:set() for s in split_lists}
    annotations, excluded, hashes = [], [], {}
    for group in complete:
        attempt = raw/group['group']/group['attempt']
        review = reviews.get(group['group'],{})
        for stage in range(5):
            image_path = attempt/f'layout-{stage:02d}.jpg'
            check_review(image_path, review)
            meta = json.loads(image_path.with_suffix('.json').read_text())
            unreadable = review[image_path.name].get('unreadable_marks', [])
            if (not isinstance(unreadable,list) or any(type(i) is not int or i < 0 or i >= len(meta['marks']) for i in unreadable)
                    or (unreadable and not review[image_path.name].get('reason'))):
                raise ValueError('Unreadable mark exclusions require valid indexes and a reason')
            split = meta['split']
            if split not in split_lists or meta['group'] != group['group'] or len(meta['marks']) != 2*stage:
                raise ValueError('Inconsistent source metadata')
            if len({(m['row'],m['col']) for m in meta['marks']}) != len(meta['marks']):
                raise ValueError('Repeated source cell')
            groups[split].add(group['group'])
            image = cv2.imread(str(image_path))
            if image is None or image.shape != (240,424,3):
                raise ValueError('Unexpected source image resolution')
            boxes = [(('X','O').index(m['mark']),mark_box(m,inverse,canvas_size)) for m in meta['marks']]
            name = group['group']+f'-layout-{stage:02d}'
            original = output/'originals'/split/(name+'.jpg')
            original.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(image_path,original)
            annotations.append(dict(group=group['group'],split=split,image=str(original),
                                    source_sha256=digest(image_path),marks=meta['marks'],
                                    ignored_cells=[[meta['marks'][i]['row'],meta['marks'][i]['col']] for i in unreadable],
                                    boxes=[dict(category=c,xyxy=b.tolist()) for c,b in boxes]))
            for i,region in enumerate(crop_regions(image.shape,transform)):
                if any(crop_labels([boxes[i]],region) != [] for i in unreadable):
                    excluded.append(dict(image=name,zone=i,reason='visually unreadable intended mark; do not teach as symbol or background'))
                    continue
                labels = crop_labels(boxes,region)
                if labels is None:
                    excluded.append(dict(image=name,zone=i,reason='partially visible padding neighbor'))
                    continue
                left,top,right,bottom = region
                file = output/'images'/split/(name+f'-q{i}.png')
                file.parent.mkdir(parents=True,exist_ok=True)
                if not cv2.imwrite(str(file),image[top:bottom,left:right]):
                    raise RuntimeError('Could not save lossless crop')
                label = output/'labels'/split/(file.stem+'.txt')
                label.parent.mkdir(parents=True,exist_ok=True)
                label.write_text(''.join(f'{c} {x:.8f} {y:.8f} {w:.8f} {h:.8f}\n' for c,x,y,w,h in labels))
                value = digest(file)
                if value in hashes and hashes[value] != split:
                    raise ValueError('Identical crop crosses split boundary')
                hashes[value] = split
                split_lists[split].append(str(file))
    if {s:len(g) for s,g in groups.items()} != dict(zip(('train','val','test'),expected_counts)):
        raise ValueError('Source split membership changed')
    if any(groups[a]&groups[b] for a,b in (('train','val'),('train','test'),('val','test'))):
        raise ValueError('Physical capture group leakage')
    old = [x.strip() for x in Path(old_train).read_text().splitlines() if x.strip()]
    if not all(Path(x).is_file() for x in old):
        raise FileNotFoundError('Prior training image missing')
    # Repetition changes training weight, not the number of independent samples.
    training = old + split_lists['train']*2
    for s,paths in dict(train=training,val=split_lists['val'],test=split_lists['test']).items():
        (output/(s+'.txt')).write_text('\n'.join(paths)+'\n')
    (output/'data.yaml').write_text(yaml.safe_dump(dict(path=str(output),train='train.txt',val='val.txt',test='test.txt',names={0:'X',1:'O'}),sort_keys=False))
    (output/'annotations.json').write_text(json.dumps(annotations,indent=2))
    audit=dict(source_groups={s:sorted(g) for s,g in groups.items()},crop_images={s:len(p) for s,p in split_lists.items()},
               old_training_entries=len(old),new_training_repeat=2,training_entries=len(training),
               excluded_crops=excluded,original_frames=len(annotations),cross_split_crop_hash_overlap=0,
               review_sha256=digest(review_file),recipe='native perspective four-zone crops; no image enhancement')
    (output/'audit.json').write_text(json.dumps(audit,indent=2))
    print(json.dumps(audit,indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ('raw','review','output','points','board','old-train'):
        parser.add_argument('--'+option,required=True,type=Path)
    parser.add_argument('--split-groups',nargs=3,type=int,default=(8,2,2),metavar=('TRAIN','VAL','TEST'))
    args = parser.parse_args()
    prepare(args.raw,args.review,args.output,args.points,args.board,args.old_train,expected_counts=tuple(args.split_groups))