"""Focused checks for grouped dataset allocation; no simulator or training needed."""
import copy
from prepare_xo_dataset import choose_split,subset


def make_groups():
    groups=[]
    # Positive: reviewed 80 singleton scenes + 144 new five-view scenes.
    for size,count,negative in [(1,80,False),(5,144,False),(1,16,True),(5,28,True),(33,1,True),(11,1,True)]:
        for _ in range(count):
            index=len(groups);objects=[] if negative else [dict(kind='X' if index%2 else 'O',variant='straight' if index%2 else 'circle')]
            groups.append(dict(id=str(index),negative=negative,records=[dict(objects=copy.deepcopy(objects),negative=negative,grid=index%3!=0,background_type='blank' if size>5 else ['triangle','square','V','slash'][index%4]) for _ in range(size)]))
    return groups


def main():
    groups=make_groups();first=choose_split(groups,20261117);again=choose_split(groups,20261117)
    assert first==again,'Fixed seed must reproduce allocation'
    assignment=first[1]
    for split,target,bg in [('train',700,140),('val',150,30),('test',150,30)]:
        selected=[g for g in groups if assignment[g['id']]==split]
        assert sum(len(g['records']) for g in selected)==target
        assert sum(len(g['records']) for g in selected if g['negative'])==bg
    assert len(assignment)==len(groups)
    try:subset([dict(id='a',records=[0]*5)],3)
    except ValueError:pass
    else:raise AssertionError('Must refuse a target that would split a scene')
    print('Passed: exact 700/150/150, stratified 140/30/30 backgrounds, fixed-seed repeatability, indivisible groups.')

if __name__=='__main__':main()
