"""A small turn-based game state committed only after verified robot drawing."""



class TicTacToe:
    """! @brief Keep grid geometry and legal turns; require Reset after partial failures.

    This layer uses explicit row/column inputs, not visual recognition or an AI
    opponent. Board state changes only after successful action completion.
    """
    def __init__(self,actions,center=(.5,.5),width=.06,height=.06):
        self.actions=actions;self.center=tuple(center);self.width=width;self.height=height
        actions.grid_strokes(center,width,height)
        self.board=['']*9;self.turn='X';self.phase='new';self.outcome=None
        # Validate future cell symbols before any grid execution.
        for row in range(3):
            for col in range(3):
                position=self.cell_center(row,col)
                actions.x_strokes(position,min(width,height)/3*.55)
                actions.o_strokes(position,min(width,height)/3*.25)

    def cell_center(self,row,col):
        if any(not isinstance(v,int) or isinstance(v,bool) or not 0<=v<3 for v in (row,col)):
            raise ValueError('Cell row/column must be integers in 0..2')
        return (self.center[0]+(col-1)*self.width/(3*self.actions.width),
                self.center[1]+(row-1)*self.height/(3*self.actions.height))

    def _perform(self,operation):
        try:
            result=operation()
            if not isinstance(result,dict) or result.get('passed') is not True:
                raise RuntimeError('Drawing not verified; Reset before starting a new game')
            return result
        except Exception:
            self.phase='blocked'
            raise

    def start(self,**options):
        if self.phase!='new':raise ValueError('Game is already started or blocked')
        self.phase='drawing_grid'
        result=self._perform(lambda:self.actions.draw_grid(self.center,self.width,self.height,**options))
        self.phase='playing';return result

    def play(self,symbol,row,col,**options):
        if self.phase!='playing':raise ValueError('Game is not accepting moves')
        center=self.cell_center(row,col);index=row*3+col
        if symbol!=self.turn:raise ValueError('Wrong player turn')
        if self.board[index]:raise ValueError('Cell already occupied')
        self.phase='drawing_move'
        if symbol=='X':result=self._perform(lambda:self.actions.draw_x(center,min(self.width,self.height)/3*.55,**options))
        else:result=self._perform(lambda:self.actions.draw_o(center,min(self.width,self.height)/3*.25,**options))
        self.board[index]=symbol
        lines=[(0,1,2),(3,4,5),(6,7,8),(0,3,6),(1,4,7),(2,5,8),(0,4,8),(2,4,6)]
        if any(all(self.board[i]==symbol for i in line) for line in lines):self.outcome=symbol
        elif all(self.board):self.outcome='draw'
        self.phase='finished' if self.outcome else 'playing'
        self.turn='O' if symbol=='X' else 'X'
        return result
