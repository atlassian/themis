#!/usr/bin/env python

# from __future__ import unicode_literals
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

with open('requirements.txt') as f:
    requirements = f.read()

for line in re.split('\n', requirements):
    if line and line[0] == '#' and '#egg=' in line:
        line = re.search(r'#\s*(.*)', line).group(1)
    if line and line[0] != '#':
        if '://' in line:
            if '#egg=' in line and 'http://' in line and 'github.com' in line:
                dependency_links.append(line)
                package = re.search(r'http://github.com/[^/]*/([^/]*)/.*', line).group(1)
                version = re.search(r'.*#egg=.*-([^\-]*)$', line).group(1)
                install_requires.append('%s==%s' % (package, version))
        else:
            install_requires.append(line)

package_data = {
    'web': ['*.html', '*.css', '*.js', '*.gif', '*.png']
}

if __name__ == '__main__':

    setup(
        name='themis-autoscaler',
        version='0.1.0',
        description='Themis is an autoscaler for Elastic Map Reduce (EMR) clusters on Amazon Web Services.',
        author='Atlassian and others',
        maintainer='Waldemar Hummer',
        author_email='waldemar.hummer@gmail.com',
        url='http://github.com/atlassian/themis',
        scripts=['bin/themis'],
        packages=find_packages(exclude=("test", "test.*")),
        package_data=package_data,
        install_requires=install_requires,
        dependency_links=dependency_links,
        test_suite="test",
        license="Apache License 2.0",
        zip_safe=False,
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
