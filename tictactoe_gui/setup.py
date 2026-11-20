from setuptools import find_packages, setup
setup(
    name='tictactoe_gui', version='0.1.0', packages=find_packages(exclude=['test']),
    package_data={'tictactoe_gui':['web/*']},
    data_files=[('share/ament_index/resource_index/packages',['resource/tictactoe_gui']),
                ('share/tictactoe_gui',['package.xml']),
                ('share/tictactoe_gui/launch',['launch/canvas_sim.launch.py', 'launch/localization_sim.launch.py', 'launch/localization_real.launch.py', 'launch/robot_games_real.launch.py']),
                ('share/tictactoe_gui/models',['models/xo_real.pt']),
                ('share/tictactoe_gui/config',['config/grid_points_real.json'])],
    install_requires=['setuptools'], zip_safe=True,
    maintainer='cooper', maintainer_email='liuzi9240@gmail.com',
    description='Local tablet canvas with ordered simulation drawing', license='Apache-2.0',
    entry_points={'console_scripts':['canvas_gui = tictactoe_gui.server:main',
                                     'localization_gui = tictactoe_gui.workbench:main',
                                     'real_game_gui = tictactoe_gui.real_game:main']})
