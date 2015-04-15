# /setup.py
#
# Installation and setup script for polysquare-setuptools-lint
#
# See /LICENCE.md for Copyright information
"""Installation and setup script for polysquare-setuptools-lint."""

from polysquare_setuptools_lint import PolysquareLintCommand

from setuptools import find_packages
from setuptools import setup

setup(name="polysquare-setuptools-lint",
      version="0.0.1",
      description="""Provides a 'lint' command for setuptools""",
      long_description_markdown_filename="README.md",
      author="Sam Spilsbury",
      author_email="smspillaz@gmail.com",
      url="http://github.com/polysquare/polysquare-setuptools-lint",
      classifiers=["Development Status :: 3 - Alpha",
                   "Programming Language :: Python :: 2",
                   "Programming Language :: Python :: 2.7",
                   "Programming Language :: Python :: 3",
                   "Programming Language :: Python :: 3.1",
                   "Programming Language :: Python :: 3.2",
                   "Programming Language :: Python :: 3.3",
                   "Programming Language :: Python :: 3.4",
                   "Intended Audience :: Developers",
                   "Topic :: Software Development :: Build Tools",
                   "License :: OSI Approved :: MIT License"],
      license="MIT",
      keywords="development linters",
      packages=find_packages(exclude=["test"]),
      cmdclass={
          "lint": PolysquareLintCommand
      },
      install_requires=[
          "setuptools",
          "pep8",
          "pylint",
          "pylint-common",
          "dodgy",
          "frosted",
          "mccabe",
          "pep257",
          "pyflakes",
          "pyroma",
          "vulture",
          "prospector",
          "flake8==2.3.0",
          "flake8-blind-except",
          "flake8-docstrings",
          "flake8-double-quotes",
          "flake8-import-order",
          "flake8-todo",
          "pychecker",
          "six"
      ],
      dependency_links=[
          ("https://github.com/landscapeio/prospector/tarball/master"
           "#egg=prospector"),
          ("http://downloads.sourceforge.net/project/pychecker/pychecker/"
           "0.8.19/pychecker-0.8.19.tar.gz#egg=pychecker-0.8.19")
      ],
      extras_require={
          "test": ["testtools"]
      },
      entry_points={
          "distutils.commands": [
              "lint=polysquare_setuptools_lint:PolysquareLintCommand",
          ]
      },
      zip_safe=True,
      include_package_data=True)
