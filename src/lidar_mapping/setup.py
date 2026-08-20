import os
from glob import glob

from setuptools import find_packages, setup

package_name = 'lidar_mapping'

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
    description='LiDAR SLAM, 센서 퓨전, 3D 포인트클라우드 맵 생성 패키지',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'lidar_mapping_node = lidar_mapping.lidar_mapping_node:main',
            'crack_fusion_node = lidar_mapping.crack_fusion_node:main',
            'coverage_grid_node = lidar_mapping.coverage_grid_node:main',
            'crack_collector_node = lidar_mapping.crack_collector_node:main',
        ],
    },
)
