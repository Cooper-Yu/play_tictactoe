"""A small turn-based game state committed only after verified robot drawing."""

from tictactoe_motion.decision import choose_move



class GridGame:
    """! @brief Keep grid geometry and legal turns; require Reset after partial failures.

    This layer uses explicit row/column inputs and offers optional AI suggestions.
    Board state changes only after successful action completion.
    """
    def __init__(self,actions,center=(.5,.5),width=.06,height=.06,rows=3,columns=3,win_length=3,*,flip=False,swap_marks=False):
        self.actions=actions;self.center=tuple(center);self.width=width;self.height=height
        if any(not isinstance(n,int) or isinstance(n,bool) or not 2<=n<=15 for n in (rows,columns)):
            raise ValueError('Board rows/columns must be integers in 2..15')
        actions.grid_strokes(center,width,height,rows,columns)
        if not isinstance(win_length,int) or isinstance(win_length,bool) or not 2<=win_length<=min(rows,columns):
            raise ValueError('Win length must fit the board')
        self.rows=rows;self.columns=columns;self.win_length=win_length
        self.flip=flip
        self.swap_marks=swap_marks
        self.board=['']*(rows*columns);self.turn='X';self.phase='new';self.outcome=None
        self.cell_size=min(width/columns,height/rows)
        # Validate future cell symbols before any grid execution.
        for row in range(rows):
            for col in range(columns):
                position=self.cell_center(row,col)
                actions.x_strokes(position,self.cell_size*.55)
                actions.o_strokes(position,self.cell_size*.25)

    def cell_center(self,row,col):
        if any(not isinstance(v,int) or isinstance(v,bool) or not 0<=v<limit for v,limit in ((row,self.rows),(col,self.columns))):
            raise ValueError('Cell row/column outside the configured board')
        if self.flip:
            row, col = self.rows-1-row, self.columns-1-col
        return (self.center[0]+((col+.5)/self.columns-.5)*self.width/self.actions.width,
                self.center[1]+((row+.5)/self.rows-.5)*self.height/self.actions.height)

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
        result=self._perform(lambda:self.actions.draw_grid(self.center,self.width,self.height,rows=self.rows,columns=self.columns,**options))
        self.phase='playing';return result

    def _move_index(self, symbol, row, col):
        if self.phase != 'playing':
            raise ValueError('Game is not accepting moves')
        self.cell_center(row, col)
        index = row * self.columns + col
        if symbol != self.turn:
            raise ValueError('Wrong player turn')
        if self.board[index]:
            raise ValueError('Cell already occupied')
        return index

    def record_observed_move(self, symbol, row, col):
        '''Commit a confirmed mark that is already present on the board.'''
        index = self._move_index(symbol, row, col)
        self._commit_move(symbol, row, col, index)

    def play(self,symbol,row,col,**options):
        index = self._move_index(symbol, row, col)
        center = self.cell_center(row, col)
        self.phase='drawing_move'
        drawn = ('O' if symbol == 'X' else 'X') if self.swap_marks else symbol
        if drawn=='X':result=self._perform(lambda:self.actions.draw_x(center,self.cell_size*.55,**options))
        else:result=self._perform(lambda:self.actions.draw_o(center,self.cell_size*.25,**options))
        self._commit_move(symbol, row, col, index)
        return result

    def _commit_move(self, symbol, row, col, index):
        self.board[index] = symbol
        self.outcome = self.outcome_after_move(symbol, row, col)
        self.phase = 'finished' if self.outcome else 'playing'
        self.turn = 'O' if symbol == 'X' else 'X'

    def outcome_after_move(self, symbol, row, col):
        if self.has_line(symbol, row, col):
            return symbol
        return "draw" if all(self.board) else None

    def suggest_move(self, **engine_options):
        """! @brief Suggest a move for the current turn without changing the board."""
        if self.phase == "finished":
            return None
        if self.phase != "playing":
            raise ValueError("Game is not accepting moves")
        if (self.rows, self.columns, self.win_length) not in ((3, 3, 3), (9, 9, 4), (9, 9, 5)):
            raise ValueError("AI suggestions support 3x3 three-in-a-row or 9x9 four- and five-in-a-row")
        board = [self.board[index:index + self.columns]
                 for index in range(0, len(self.board), self.columns)]
        return choose_move(board, self.turn, win_length=self.win_length, **engine_options)

    def has_line(self,symbol,row,col):
        """! @brief Count uninterrupted runs in four axes through the latest move."""
        for dr,dc in ((0,1),(1,0),(1,1),(1,-1)):
            count=1
            for sign in (-1,1):
                r,c=row+sign*dr,col+sign*dc
                while 0<=r<self.rows and 0<=c<self.columns and self.board[r*self.columns+c]==symbol:
                    count+=1;r+=sign*dr;c+=sign*dc
            if count>=self.win_length:return True
        return False
