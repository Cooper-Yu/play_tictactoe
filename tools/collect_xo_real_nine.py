"""Collect real 9x9 layouts through the existing serialized workstation.

Physical motion is explicit. Intended geometry remains pending visual label review.
A failed motion is logged and never replayed automatically.
"""
import argparse
import json
from pathlib import Path
import random
import time

from tictactoe_gui.workstation_client import Workstation, RemoteDrawing
from tictactoe_game.grid_game import GridGame

CUTOFF = 1795243979.0


def collect(output, groups=12):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    guard = output.parent / 'robustness_20261121' / 'closeout_requested'
    def cancelled():
        return time.time() >= CUTOFF or guard.exists() or (output/'STOP').exists()
    client = Workstation('http://127.0.0.1:8765/', output/'motion', cancelled=cancelled)
    actions = RemoteDrawing(client)
    game = GridGame(actions, width=actions.width-.004, height=actions.height-.004,
                    rows=9, columns=9, win_length=4)
    split_order = ['train']*8+['val']*2+['test']*2
    for index in range(groups):
        if cancelled():
            raise RuntimeError('Collection deadline/stop reached')
        folder = output/f'board-{index:02d}'
        folder.mkdir(exist_ok=True)
        if (folder/'COMPLETE').exists():
            continue
        attempt = folder / f'attempt-{time.time_ns()}'
        attempt.mkdir()
        marks = []
        def snapshot(stage):
            initial = client.get('status')['camera']['sequence']
            deadline = time.monotonic()+12
            while time.monotonic() < deadline:
                if cancelled():
                    raise RuntimeError('Cancelled before capture')
                state = client.get('status')
                camera = state['camera']
                if camera.get('fresh') and camera.get('age_s',99)<1 and camera['sequence']>=initial+3:
                    break
                time.sleep(.1)
            else:
                raise RuntimeError('No fresh camera frame after observation pose')
            image = client.http.get(client.url+'api/frame',timeout=8)
            image.raise_for_status()
            stem = f'layout-{stage:02d}'
            (attempt/(stem+'.jpg')).write_bytes(image.content)
            metadata = dict(group=f'board-{index:02d}',split=split_order[index],
                            stage=stage,marks=marks.copy(),camera=camera,
                            pose=state.get('pose'),time=time.time(),label_status='pending_visual_review')
            (attempt/(stem+'.json')).write_text(json.dumps(metadata,indent=2))
            print('COLLECTED',index,stage,'objects',len(marks),'sequence',camera['sequence'],flush=True)
        try:
            print('BOARD_BEGIN',index,split_order[index],flush=True)
            client.command(kind='reset',speed=.05)
            client.park('clear')
            client.command(kind='canvas',strokes=actions.grid_strokes(
                (.5,.5),game.width,game.height,rows=9,columns=9),speed=.45)
            client.park('clear')
            snapshot(0)
            rng = random.Random(2026112100+index)
            cells = [(r,c) for r in range(9) for c in range(9)]
            rng.shuffle(cells)
            # Cover every corner over the batch while retaining random independent layouts.
            cells = [((0,0),(0,8),(8,8),(8,0))[index%4]] + cells
            unique = list(dict.fromkeys(cells))[:8]
            for pair in range(4):
                strokes = []
                pending = []
                for j in range(2):
                    row,col = unique[pair*2+j]
                    mark = 'X' if (index+pair+j)%2==0 else 'O'
                    factor = [.55,.65,.75,.8][(index+pair+j)%4]
                    center = game.cell_center(row,col)
                    geometry = (actions.x_strokes(center,game.cell_size*factor) if mark=='X'
                                else actions.o_strokes(center,game.cell_size*factor/2))
                    strokes.extend(geometry)
                    pending.append(dict(row=row,col=col,mark=mark,size_factor=factor,strokes=geometry))
                client.command(kind='canvas',strokes=strokes,speed=.45)
                client.park('clear')
                marks.extend(pending)
                snapshot(pair+1)
            (attempt/'COMPLETE').write_text('All five layout captures complete\n')
            (folder/'COMPLETE').write_text(attempt.name)
            print('BOARD_COMPLETE',index,flush=True)
        except Exception as error:
            state = client.get('status')
            (attempt/'FAILED.json').write_text(json.dumps(dict(error=repr(error),state=state),indent=2))
            if state.get('busy'):
                client.stop()
            print('COLLECTION_FAILED',index,repr(error),flush=True)
            raise
    print('COLLECTION_COMPLETE',groups,flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True)
    parser.add_argument('--groups',type=int,default=12,choices=range(1,13))
    args = parser.parse_args()
    collect(args.output,args.groups)