"""Three-in-a-row compatibility wrapper for the shared verified game state."""
from tictactoe_motion.grid_game import GridGame


class TicTacToe(GridGame):
    """! @brief Keep the existing three-by-three command and rule interface."""
    def __init__(self,actions,center=(.5,.5),width=.06,height=.06):
        super().__init__(actions,center,width,height,rows=3,columns=3,win_length=3)
