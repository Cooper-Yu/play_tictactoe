from setuptools import find_packages, setup


package_name = 'tictactoe_coordinator'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='cooper',
    maintainer_email='liuzi9240@gmail.com',
    description='Game turn coordination and drawing dispatch for Play TicTacToe',
    license='Apache-2.0',
)
