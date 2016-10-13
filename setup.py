#!/usr/bin/env python

import os
import sys
import re
import subprocess
import setuptools
from setuptools import find_packages, setup
from setuptools.command.install_lib import install_lib

install_requires = []
dependency_links = []
package_data = {}
packages = find_packages(exclude=("test", "test.*"))

with open('requirements.txt') as f:
    requirements = f.read()

for line in re.split('\n', requirements):
    if line and line[0] == '#' and '#egg=' in line:
        line = re.search(r'#\s*(.*)', line).group(1)
    if line and line[0] != '#':
        install_requires.append(line)


class InstallLibCommand(install_lib):

    def run(self):
        install_lib.run(self)
        # prepare filesystem
        main_dir_name = 'themis'
        target_dir = '%s/%s' % (self.install_dir, main_dir_name)
        # delete existing directory
        subprocess.check_output('rm -r %s' % (main_dir_name), shell=True)
        # create symlink
        subprocess.check_output('ln -s %s %s' % (target_dir, main_dir_name), shell=True)
        # install npm modules
        subprocess.check_output('make npm', shell=True)

package_data = {
    '': ['requirements.txt', 'Makefile'],
    'themis': [
        'web/*.*',
        'web/css/*.*',
        'web/css/lib/*.*',
        'web/css/lib/fonts/*.*',
        'web/img/*.*',
        'web/js/*.*',
        'web/js/lib/*.*',
        'web/views/*.*']
}

if __name__ == '__main__':

    setup(
        name='themis-autoscaler',
        version='0.2.1',
        description='Themis is an autoscaler for Elastic Map Reduce (EMR) clusters on Amazon Web Services.',
        author='Atlassian and others',
        maintainer='Waldemar Hummer',
        author_email='waldemar.hummer@gmail.com',
        url='http://github.com/atlassian/themis',
        scripts=['bin/themis'],
        packages=packages,
        package_data=package_data,
        install_requires=install_requires,
        dependency_links=dependency_links,
        test_suite="test",
        license="Apache License 2.0",
        zip_safe=False,
        cmdclass={
            'install_lib': InstallLibCommand
        },
        classifiers=[
            "Programming Language :: Python :: 2",
            "Programming Language :: Python :: 2.6",
            "Programming Language :: Python :: 2.7",
            "Programming Language :: Python :: 3",
            "Programming Language :: Python :: 3.3",
            "License :: OSI Approved :: Apache Software License",
            "Topic :: Software Development :: Testing",
        ]
    )
