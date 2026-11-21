"""Draw and photograph two frozen-model 9x9 edge tests on the real board."""
import argparse
import json
from pathlib import Path
import time

import requests
import torch

from tictactoe_game.grid_game import GridGame
from tictactoe_gui.real_board_perception import RealBoardPerception
from tictactoe_gui.workstation_client import RemoteDrawing, Workstation


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--deadline-epoch',type=float,required=True)
    parser.add_argument('--guard-file',type=Path,required=True)
    parser.add_argument('--model',type=Path,required=True)
    parser.add_argument('--points',type=Path,required=True)
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    stop=lambda: time.time()>=args.deadline_epoch or args.guard_file.exists() or (args.output/'STOP').exists()
    client=Workstation('http://127.0.0.1:8765/',args.output/'motion'/str(time.time_ns()),cancelled=stop)
    game_status=requests.get('http://127.0.0.1:8775/api/status',timeout=3).json()
    if game_status['game'] is not None or game_status['busy']:
        raise RuntimeError('End the active game before an independent drawing test')
    actions=RemoteDrawing(client)
    grid=GridGame(actions,width=actions.width-.004,height=actions.height-.004,rows=9,columns=9,win_length=4)
    torch.set_num_threads(2)
    detector=RealBoardPerception(args.model,json.loads(args.points.read_text()))
    cells=[(0,0),(0,4),(0,8),(4,8),(8,8),(8,4),(8,0),(4,0)]
    for layout in range(2):
        folder=args.output/f'layout-{layout}'
        folder.mkdir(exist_ok=True)
        if (folder/'COMPLETE').exists():
            continue
        folder=folder/str(time.time_ns());folder.mkdir()
        expected={};marks=[]
        def capture(stage):
            sequence=client.get('status')['camera']['sequence']
            until=time.monotonic()+12
            while True:
                if stop():raise RuntimeError('Capture cancelled')
                state=client.get('status');camera=state['camera']
                if camera['fresh'] and camera['age_s']<1 and camera['sequence']>=sequence+3:break
                if time.monotonic()>until:raise RuntimeError('No new camera frame')
                time.sleep(.1)
            b=client.http.get(client.url+'api/frame',timeout=5);b.raise_for_status()
            (folder/f'stage-{stage}.jpg').write_bytes(b.content)
            detected=detector.detect_cells(b.content,9)
            truth={(r,c,m) for (r,c),m in expected.items()}
            actual={(r,c,m) for (r,c),ms in detected.items() for m in ms}
            record=dict(time=time.time(),layout=layout,stage=stage,expected=marks.copy(),
                        detected={f'{r+1},{c+1}':sorted(ms) for (r,c),ms in detected.items()},
                        exact=truth==actual,fn=sorted(truth-actual),fp=sorted(actual-truth),camera=camera,
                        model=str(args.model),annotation_status='Expected executed geometry; verify actual pen marks')
            (folder/f'stage-{stage}.json').write_text(json.dumps(record,indent=2))
            raw,transform=detector._camera_frame(b.content)
            import cv2
            cv2.imwrite(str(folder/f'annotated-{stage}.jpg'),cv2.resize(detector.camera_overlay(raw,transform,9),(848,480)))
            print('EDGE_CAPTURE',layout,stage,'marks',len(expected),'exact',record['exact'],'FN',record['fn'],'FP',record['fp'],flush=True)
        try:
            print('EDGE_LAYOUT_BEGIN',layout,flush=True)
            client.command(kind='reset',speed=.05);client.park('clear')
            client.command(kind='canvas',strokes=actions.grid_strokes((.5,.5),grid.width,grid.height,rows=9,columns=9),speed=.45)
            client.park('clear');capture(0)
            for pair in range(4):
                strokes=[];pending=[]
                for i in range(pair*2,pair*2+2):
                    row,col=cells[i];mark='X' if (i+layout)%2==0 else 'O';center=grid.cell_center(row,col)
                    geometry=(actions.x_strokes(center,grid.cell_size*.55) if mark=='X'
                              else actions.o_strokes(center,grid.cell_size*.25))
                    strokes.extend(geometry);pending.append((row,col,mark,geometry))
                client.command(kind='canvas',strokes=strokes,speed=.45);client.park('clear')
                for row,col,mark,geometry in pending:
                    expected[(row,col)]=mark;marks.append(dict(row=row,col=col,mark=mark,strokes=geometry))
                capture(pair+1)
            (folder.parent/'COMPLETE').write_text(folder.name)
            print('EDGE_LAYOUT_COMPLETE',layout,flush=True)
        except Exception as error:
            (folder/'FAILED.json').write_text(json.dumps(dict(error=repr(error),state=client.get('status')),indent=2))
            if client.get('status')['busy']:client.stop()
            raise
    client.park('zero')
    (args.output/'COMPLETE').write_text('Both layouts captured; robot returned to zero\n')
    print('EDGE_VALIDATION_COMPLETE',flush=True)


if __name__=='__main__':
    main()