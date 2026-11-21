from setuptools import find_packages, setup
from glob import glob
from pathlib import Path

package_name = 'tictactoe_perception'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/launch', [path for path in glob('launch/*.launch.py') if Path(path).is_file()]),
        ('share/' + package_name + '/config', glob('config/*.yaml')),
        ('share/' + package_name + '/models', glob('models/*.pt') + ['models/README.md']),
        ('share/' + package_name + '/models/archive', glob('models/archive/*.pt')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='cooper',
    maintainer_email='liuzi9240@gmail.com',
    description='TODO: Package description',
    license='TODO: License declaration',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [
            'enhancement_demo = tictactoe_perception.enhancement_demo:main',
        ],
    },
)
