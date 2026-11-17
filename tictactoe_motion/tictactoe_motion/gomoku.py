"""Freestyle five-in-a-row with X/O placed in cells of a configurable grid."""
from tictactoe_motion.grid_game import GridGame


class Gomoku(GridGame):
    """! @brief Alternate explicit moves; five or more uninterrupted marks win.

    This cell-centered X/O variant has no forbidden-move/renju rules.
    A 9x9 cell grid is the default and supports Rapfi suggestions.
    """
    def __init__(self,actions,center=(.5,.5),width=.09,height=.09,size=9):
        super().__init__(actions,center,width,height,rows=size,columns=size,win_length=5)
