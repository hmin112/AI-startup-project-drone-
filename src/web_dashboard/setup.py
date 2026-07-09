import os
from glob import glob

from setuptools import find_packages, setup

package_name = 'web_dashboard'

setup(
    name=package_name,
    version='0.0.1',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'static'),
            glob(os.path.join(package_name, 'static', '*'))),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='yuna',
    maintainer_email='yuna@ryukolab.top',
    description='분석 결과 및 3D 디지털 트윈 실시간 웹 시각화 패키지',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'web_dashboard_node = web_dashboard.web_dashboard_node:main',
        ],
    },
)
