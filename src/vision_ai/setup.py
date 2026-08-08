import os
from glob import glob

from setuptools import find_packages, setup

package_name = 'vision_ai'

setup(
    name=package_name,
    version='0.0.1',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='yuna',
    maintainer_email='yuna@ryukolab.top',
    description='RealSense D455F 연동 및 YOLO 기반 실시간 균열 탐지 추론 패키지',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'vision_ai_node = vision_ai.vision_ai_node:main',
            'recorder_node = vision_ai.recorder_node:main',
        ],
    },
)
