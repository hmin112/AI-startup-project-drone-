import os
from glob import glob

from setuptools import find_packages, setup

package_name = 'drone_core'

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
    description='MAVROS 통신, FC 제어 및 비행 상태 모니터링을 담당하는 패키지',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'drone_core_node = drone_core.drone_core_node:main',
        ],
    },
)
