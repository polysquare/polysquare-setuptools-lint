# /test/test_polysquare_lint.py
#
# Tests for polysquare-setuptools-lint.
#
#
# See /LICENCE.md for Copyright information
"""Tests for polysquare-setuptools-lint."""

import doctest

import errno

import os

import shutil

from tempfile import mkdtemp

from distutils.errors import DistutilsArgError  # suppress(I100)

from mock import Mock

from nose_parameterized import param, parameterized

import polysquare_setuptools_lint  # suppress(PYC70)
from polysquare_setuptools_lint import (CapturedOutput,  # suppress(PYC70)
                                        PolysquareLintCommand,
                                        can_run_pychecker,
                                        can_run_pylint)

from setuptools import Distribution
from setuptools import find_packages as fp

from testtools import ExpectedException, TestCase
from testtools.matchers import (DocTestMatches, MatchesAll, Not)


def _open_file_force_create(path, mode="w"):
    """Force creation of file at path and open it."""
    try:
        os.makedirs(os.path.dirname(path))
    except OSError as error:
        if error.errno != errno.EEXIST:  # suppress(PYC90)
            raise error

    with open(os.path.join(os.path.dirname(path), "__init__.py"), "w"):
        pass

    return open(path, mode)


class TestPolysquareLintCommand(TestCase):

    """Tests for the PolysquareLintCommand class."""

    def __init__(self, *args, **kwargs):
        """Initialize this test case."""
        super(TestPolysquareLintCommand, self).__init__(*args, **kwargs)
        self._previous_directory = None
        self._package_name = "package"
        self._distribution = None

    def setUp(self):  # suppress(N802)
        """Create a temporary directory and put some files in it."""
        super(TestPolysquareLintCommand, self).setUp()
        self._previous_directory = os.getcwd()

        project_directory = mkdtemp(prefix=os.path.join(os.getcwd(),
                                                        "test_project_dir"))
        os.chdir(project_directory)
        self.addCleanup(lambda: os.chdir(self._previous_directory))
        self.addCleanup(lambda: shutil.rmtree(project_directory))

        self.patch(polysquare_setuptools_lint, "sys_exit", Mock())

        with self._open_test_file():
            pass

        with self._open_module_file():
            pass

        with self._open_setup_file() as f:
            # Write a very basic /setup.py file so that pyroma doesn't trip
            # throw an exception.
            f.write("from setuptools import setup\n"
                    "setup()\n")

        self._distribution = Distribution(dict(name="my-package",
                                               version="0.0.1",
                                               packages=fp(exclude=["test"])))

    def _open_module_file(self):
        """Open test file and return it as a file object."""
        return _open_file_force_create(os.path.join(os.getcwd(),
                                                    self._package_name,
                                                    "module.py"),
                                       "w")

    # no-self-use is suppressed here to keep consistency
    # with _open_module_file.
    #
    # suppress(no-self-use)
    def _open_test_file(self):
        """Open test file and return it as a file object."""
        return _open_file_force_create(os.path.join(os.getcwd(),
                                                    "test",
                                                    "test.py"),
                                       "w")

    # no-self-use is suppressed here to keep consistency
    # with _open_module_file.
    #
    # suppress(no-self-use)
    def _open_setup_file(self):
        """Open setup file and return it as a file object."""
        return _open_file_force_create(os.path.join(os.getcwd(),
                                                    "setup.py"),
                                       "w")

    def _get_command_output(self, set_options_func=lambda d: None):
        """Get output of running lint command with command line arguments."""
        with CapturedOutput() as captured:
            cmd = PolysquareLintCommand(self._distribution)
            set_options_func(cmd)
            cmd.ensure_finalized()
            cmd.run()

        return captured.stdout

    FLAKE8_BUGS = [
        param("F401", "import sys\n"),
        param("N801", "class wrong_name(object):\n    pass\n"),
        param("D100", "def my_method():\n    pass\n"),
        param("I100", "import sys\n\nimport os\n"),
        param("Q000", "call('single quotes')\n")
    ]

    @parameterized.expand(FLAKE8_BUGS)
    def test_find_bugs_with_flake8(self, bug_type, script):
        """Find bugs with flake8."""
        with self._open_module_file() as f:
            f.write(script)

        self.assertThat(self._get_command_output(),
                        DocTestMatches("...{0}...".format(bug_type),
                                       doctest.ELLIPSIS))

    @parameterized.expand(FLAKE8_BUGS)
    def test_find_bugs_with_flake8_tests(self, bug_type, script):
        """Find bugs with flake8 on tests."""
        with self._open_test_file() as f:
            f.write(script)

        self.assertThat(self._get_command_output(),
                        DocTestMatches("...{0}...".format(bug_type),
                                       doctest.ELLIPSIS))

    if can_run_pylint():
        PROSPECTOR_TEST_ONLY_BUGS = [
            param("unused-argument",
                  "def my_method(extras):\n    return 1\n"),
        ]
    else:
        PROSPECTOR_TEST_ONLY_BUGS = []

    PROSPECTOR_MODULE_ONLY_BUGS = [
        param("unused-function", "def my_method():\n    pass\n"),
    ]

    PROSPECTOR_NO_TESTS_BUGS = [
        param("invalid-name",
              "def super_excessive_really_long_method_name_which_is_long():\n"
              "    pass\n")
    ] + PROSPECTOR_MODULE_ONLY_BUGS

    PROSPECTOR_ALL_BUGS = (PROSPECTOR_MODULE_ONLY_BUGS +
                           PROSPECTOR_TEST_ONLY_BUGS)

    @parameterized.expand(PROSPECTOR_ALL_BUGS)
    def test_find_bugs_with_prospector(self, bug_type, script):
        """Find bugs with prospector on package files."""
        with self._open_module_file() as f:
            f.write(script)

        self.assertThat(self._get_command_output(),
                        DocTestMatches("...{0}...".format(bug_type),
                                       doctest.ELLIPSIS))

    @parameterized.expand(PROSPECTOR_TEST_ONLY_BUGS)
    def test_find_bugs_with_prospector_tests(self, bug_type, script):
        """Find certain bugs with prospector on test files."""
        with self._open_test_file() as f:
            f.write(script)

        self.assertThat(self._get_command_output(),
                        DocTestMatches("...{0}...".format(bug_type),
                                       doctest.ELLIPSIS))

    @parameterized.expand(PROSPECTOR_NO_TESTS_BUGS)
    def test_dont_find_certain_bugs_on_tests(self, bug_type, script):
        """Do not find certain bugs on tests."""
        with self._open_test_file() as f:
            f.write(script)

        self.assertThat(self._get_command_output(),
                        Not(DocTestMatches("...{0}...".format(bug_type),
                            doctest.ELLIPSIS)))

    PYCHECKER_BUGS = [
        param("PYC70", "from sys import exit\n")
    ]

    @parameterized.expand(PYCHECKER_BUGS)
    def test_find_bugs_with_pychecker(self, bug_type, script):
        """Find bugs with pychecker on package files."""
        if not can_run_pychecker():
            self.skipTest("""Pychecker is not available on this python""")

        with self._open_module_file() as f:
            f.write(script)

        self.assertThat(self._get_command_output(),
                        DocTestMatches("...{0}...".format(bug_type),
                                       doctest.ELLIPSIS))

    @parameterized.expand(PYCHECKER_BUGS)
    def test_find_bugs_with_pychecker_tests(self, bug_type, script):
        """Find certain bugs with pychecker on test files."""
        if not can_run_pychecker():
            self.skipTest("""Pychecker is not available on this python""")

        with self._open_test_file() as f:
            f.write(script)

        self.assertThat(self._get_command_output(),
                        DocTestMatches("...{0}...".format(bug_type),
                                       doctest.ELLIPSIS))

    PYROMA_BUGS = [
        param("LongDescription",
              "from setuptools import setup\nsetup(name=\"foo\")")
    ]

    @parameterized.expand(PYROMA_BUGS)
    def test_find_bugs_with_pyroma(self, bug_type, script):
        """Find certain bugs with pyroma on /setup.py."""
        with self._open_setup_file() as setup_file:
            setup_file.write(script)

        self.assertThat(self._get_command_output(),
                        DocTestMatches("...{0}...".format(bug_type),
                                       doctest.ELLIPSIS))

    def test_suppress_pyroma_warnings(self):
        """Suppress pyroma warnings by command line option."""
        script = "from setuptools import setup\nsetup(name=\"foo\")"

        def options_modifier(command):
            """Set the suppress-codes option."""
            command.suppress_codes = ["LongDescription", "PythonVersion"]

        with self._open_setup_file() as setup_file:
            setup_file.write(script)

        self.assertThat(self._get_command_output(options_modifier),
                        MatchesAll(Not(DocTestMatches("...LongDescription...",
                                                      doctest.ELLIPSIS)),
                                   Not(DocTestMatches("...PythonVersion...",
                                                      doctest.ELLIPSIS))))

    def test_exclude_certain_files(self):
        """Exclude files from the lint checks."""
        script = "from setuptools import setup\nsetup(name=\"foo\")"

        def options_modifier(command):
            """Set the suppress-codes option to exclude everything."""
            command.exclusions = "*.py"

        with self._open_setup_file() as setup_file:
            setup_file.write(script)

        self.assertThat(self._get_command_output(options_modifier),
                        MatchesAll(Not(DocTestMatches("...LongDescription...",
                                                      doctest.ELLIPSIS)),
                                   Not(DocTestMatches("...PythonVersion...",
                                                      doctest.ELLIPSIS))))

    def test_inline_suppression_above(self):
        """Inline suppressions above offending line."""
        with self._open_module_file() as module_file:
            module_file.write("# suppress(F401,PYC70)\nimport sys\n")

        self.assertThat(self._get_command_output(),
                        MatchesAll(Not(DocTestMatches("...F401...",
                                                      doctest.ELLIPSIS)),
                                   Not(DocTestMatches("...PYC70...",
                                                      doctest.ELLIPSIS))))

    def test_inline_suppression_aside(self):
        """Inline suppressions aside offending line."""
        with self._open_module_file() as module_file:
            module_file.write("import sys  # suppress(F401,PYC70)\n")

        self.assertThat(self._get_command_output(),
                        MatchesAll(Not(DocTestMatches("...F401...",
                                                      doctest.ELLIPSIS)),
                                   Not(DocTestMatches("...PYC70...",
                                                      doctest.ELLIPSIS))))

    @parameterized.expand([
        param("suppress_codes"),
        param("exclusions")
    ])
    def test_passing_non_list_non_string_in_opts_raises(self, attrib):
        """Passing a non-list or non string as an option raises an error."""
        with ExpectedException(DistutilsArgError):
            self._get_command_output(lambda c: setattr(c, attrib, True))
