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

from distutils.errors import DistutilsArgError  # suppress(I100,import-error)

from iocapture import capture

from mock import Mock

from nose_parameterized import param, parameterized

import polysquare_setuptools_lint
from polysquare_setuptools_lint import (PolysquareLintCommand,
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
        if error.errno != errno.EEXIST:
            raise error

    with open(os.path.join(os.path.dirname(path), "__init__.py"), "w"):
        pass

    return open(path, mode)


def disable_mod(*disable_list):
    """Disable the specified linters for this test run."""
    def modifier(command):
        """Modifier for the command."""
        command.disable_linters = list(disable_list)

    return modifier


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
        os.environ["JOBSTAMPS_DISABLED"] = "1"
        self._previous_directory = os.getcwd()

        project_directory = mkdtemp(prefix=os.path.join(os.getcwd(),
                                                        "test_project_dir"))
        os.chdir(project_directory)

        def cleanup_func():
            """Change into the previous dir and remove the project dir."""
            os.chdir(self._previous_directory)
            shutil.rmtree(project_directory)

        self.addCleanup(cleanup_func)
        self.patch(polysquare_setuptools_lint, "sys_exit", Mock())

        with self._open_test_file():
            pass

        with self._open_module_file():
            pass

        with self._open_setup_file() as f:
            # Write a very basic /setup.py file so that pyroma doesn't trip
            # and throw an exception.
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
        with capture() as captured:
            cmd = PolysquareLintCommand(self._distribution)
            set_options_func(cmd)
            cmd.ensure_finalized()
            cmd.run()

            return captured.stdout

    PEP8_BUGS = [param("N801", "class wrong_name(object):\n    pass\n")]
    PEP257_BUGS = [param("D100", "def my_method():\n    pass\n")]

    FLAKE8_BUGS = [
        param("I100", "import sys\n\nimport os\n"),
        param("Q000", "call('single quotes')\n")
    ] + PEP8_BUGS + PEP257_BUGS

    PYLINT_BUGS = [param("unused-argument",
                         "def my_method(extras):\n    return 1\n")]
    PYFLAKES_BUGS = [param("F821", "bar"), param("F821", "bar")]
    DODGY_BUGS = [param("password", "FACEBOOK_PASSWORD = '123456'\n")]
    VULTURE_BUGS = [param("unused-function", "def my_method():\n    pass\n")]

    PROSPECTOR_TEST_ONLY_BUGS = PYFLAKES_BUGS
    PROSPECTOR_MODULE_ONLY_BUGS = PYFLAKES_BUGS + DODGY_BUGS + VULTURE_BUGS

    if can_run_pylint():
        PROSPECTOR_MODULE_ONLY_BUGS += PYLINT_BUGS

    PROSPECTOR_NO_TESTS_BUGS = [
        param("invalid-name",
              "def super_excessive_really_long_method_name_which_is_long():\n"
              "    pass\n")
    ] + VULTURE_BUGS + DODGY_BUGS

    PROSPECTOR_ALL_BUGS = (PROSPECTOR_MODULE_ONLY_BUGS +
                           PROSPECTOR_TEST_ONLY_BUGS)

    PYROMA_BUGS = [
        param("LongDescription",
              "from setuptools import setup\nsetup(name=\"foo\")")
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
    def test_disable_flake8(self, bug_type, script):
        """Don't find flake8 bugs when flake8 is disabled."""
        with self._open_module_file() as f:
            f.write(script)

        self.assertThat(self._get_command_output(disable_mod("flake8")),
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

    @parameterized.expand(PYLINT_BUGS)
    def test_disable_pylint(self, bug_type, script):
        """Don't find pylint bugs when pylint is disabled."""
        with self._open_module_file() as f:
            f.write(script)

        self.assertThat(self._get_command_output(disable_mod("pylint")),
                        Not(DocTestMatches("...{0}...".format(bug_type),
                                           doctest.ELLIPSIS)))

    @parameterized.expand(DODGY_BUGS)
    def test_disable_dodgy(self, bug_type, script):
        """Don't find dodgy bugs when dodgy is disabled."""
        with self._open_module_file() as f:
            f.write(script)

        self.assertThat(self._get_command_output(disable_mod("dodgy")),
                        Not(DocTestMatches("...{0}...".format(bug_type),
                                           doctest.ELLIPSIS)))

    @parameterized.expand(VULTURE_BUGS)
    def test_disable_vulture(self, bug_type, script):
        """Don't find vulture bugs when vulture is disabled."""
        with self._open_module_file() as f:
            f.write(script)

        self.assertThat(self._get_command_output(disable_mod("vulture")),
                        Not(DocTestMatches("...{0}...".format(bug_type),
                                           doctest.ELLIPSIS)))

    @parameterized.expand(PYROMA_BUGS)
    def test_find_bugs_with_pyroma(self, bug_type, script):
        """Find certain bugs with pyroma on /setup.py."""
        with self._open_setup_file() as setup_file:
            setup_file.write(script)

        self.assertThat(self._get_command_output(),
                        DocTestMatches("...{0}...".format(bug_type),
                                       doctest.ELLIPSIS))

    @parameterized.expand(PYROMA_BUGS)
    def test_disable_pyroma(self, bug_type, script):
        """Don't find pyroma bugs when vulture is disabled."""
        with self._open_setup_file() as setup_file:
            setup_file.write(script)

        self.assertThat(self._get_command_output(disable_mod("pyroma")),
                        Not(DocTestMatches("...{0}...".format(bug_type),
                                           doctest.ELLIPSIS)))

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
            module_file.write("# suppress(F401)\nimport sys\n")

        self.assertThat(self._get_command_output(),
                        MatchesAll(Not(DocTestMatches("...F401...",
                                                      doctest.ELLIPSIS))))

    def test_inline_suppression_aside(self):
        """Inline suppressions aside offending line."""
        with self._open_module_file() as module_file:
            module_file.write("import sys  # suppress(F401)\n")

        self.assertThat(self._get_command_output(),
                        MatchesAll(Not(DocTestMatches("...F401...",
                                                      doctest.ELLIPSIS))))

    @parameterized.expand([
        param("suppress_codes"),
        param("exclusions"),
        param("cache_directory")
    ])
    def test_passing_non_list_non_string_in_opts_raises(self, attrib):
        """Passing a non-list or non string as an option raises an error."""
        with ExpectedException(DistutilsArgError):
            self._get_command_output(lambda c: setattr(c, attrib, True))
