# /polysquare_setuptools_lint/__init__.py
#
# Provides a setuptools command for running pychecker, prospector and
# flake8 with maximum settings on all distributed files and tests.
#
# See /LICENCE.md for Copyright information
"""Provide a setuptools command for linters."""

import multiprocessing

import os
import os.path

import re

import sys  # suppress(I100)
from sys import exit as sys_exit  # suppress(I100,PYC70)

from collections import namedtuple  # suppress(I100)

from contextlib import contextmanager

from distutils.errors import DistutilsArgError

import setuptools


class CapturedOutput(object):  # suppress(too-few-public-methods)

    """Represents the captured contents of stdout and stderr."""

    def __init__(self):
        """Initialize the class."""
        super(CapturedOutput, self).__init__()
        self.stdout = ""
        self.stderr = ""

        self._stdout_handle = None
        self._stderr_handle = None

    def __enter__(self):
        """Start capturing output."""
        from six import StringIO

        self._stdout_handle = sys.stdout
        self._stderr_handle = sys.stderr

        sys.stdout = StringIO()
        sys.stderr = StringIO()

        return self

    def __exit__(self, exc_type, value, traceback):
        """Finish capturing output."""
        del exc_type
        del value
        del traceback

        sys.stdout.seek(0)
        self.stdout = sys.stdout.read()

        sys.stderr.seek(0)
        self.stderr = sys.stderr.read()

        sys.stdout = self._stdout_handle
        self._stdout_handle = None

        sys.stderr = self._stderr_handle
        self._stderr_handle = None


@contextmanager
def _custom_argv(argv):
    """Overwrite argv[1:] with argv, restore on exit."""
    backup_argv = sys.argv
    sys.argv = backup_argv[:1] + argv
    try:
        yield
    finally:
        sys.argv = backup_argv


@contextmanager
def _patched_pep257():
    """Monkey-patch pep257 after imports to avoid info logging."""
    import pep257

    if getattr(pep257, "log", None):
        def dummy(*args, **kwargs):
            """A dummy logging function."""
            del args
            del kwargs

        old_log_info = pep257.log.info
        pep257.log.info = dummy  # suppress(unused-attribute)
    try:
        yield
    finally:
        if getattr(pep257, "log", None):
            pep257.log.info = old_log_info


class _Key(namedtuple("_Key", "file line code")):

    """A sortable class representing a key to store messages in a dict."""

    def __lt__(self, other):
        """Check if self should sort less than other."""
        if self.file == other.file:
            if self.line == other.line:
                return self.code < other.code

            return self.line < other.line

        return self.file < other.file


def _run_flake8(filename):
    """Run flake8."""
    from flake8.engine import get_style_guide
    from pep8 import BaseReport
    from prospector.message import Message, Location

    return_dict = dict()

    cwd = os.getcwd()

    class Flake8MergeReporter(BaseReport):

        """An implementation of pep8.BaseReport merging results.

        This implementation merges results from the flake8 report
        into the prospector report created earlier.
        """

        def __init__(self, options):
            """Initialize this Flake8MergeReporter."""
            super(Flake8MergeReporter, self).__init__(options)
            self._current_file = ""

        def init_file(self, filename, lines, expected, line_offset):
            """Start processing filename."""
            self._current_file = os.path.realpath(os.path.join(cwd,
                                                               filename))

            super(Flake8MergeReporter, self).init_file(filename,
                                                       lines,
                                                       expected,
                                                       line_offset)

        def error(self, line, offset, text, check):
            """Record error and store in return_dict."""
            code = super(Flake8MergeReporter, self).error(line,
                                                          offset,
                                                          text,
                                                          check)

            key = _Key(self._current_file, line, code)
            return_dict[key] = Message(code,
                                       code,
                                       Location(self._current_file,
                                                None,
                                                None,
                                                line,
                                                offset),
                                       text[5:])

    get_style_guide(reporter=Flake8MergeReporter,
                    jobs="1").check_files(paths=[filename])

    return return_dict


def can_run_pylint():
    """Return true if we can run pylint.

    Pylint fails on pypy3 as pypy3 doesn't implement certain attributes
    on functions.
    """
    from platform import python_implementation
    from sys import version_info  # suppress(PYC70)
    return not (python_implementation() == "PyPy" and version_info.major == 3)


def _run_prospector_on(filenames, tools, ignore_codes=None):
    """Run prospector on filename, using the specified tools.

    This function enables us to run different tools on different
    classes of files, which is necessary in the case of tests.
    """
    from prospector.run import Prospector, ProspectorConfig

    assert len(tools) > 0

    return_dict = dict()
    ignore_codes = ignore_codes or list()

    # pylint doesn't like absolute paths, so convert to relative.
    all_argv = (["-F", "-D", "-M", "--no-autodetect", "-s", "veryhigh"] +
                ("-t " + " -t ".join(tools)).split(" ") +
                [os.path.relpath(f) for f in filenames])
    with _custom_argv(all_argv):
        prospector = Prospector(ProspectorConfig())
        prospector.execute()
        messages = prospector.get_messages() or list()
        for message in messages:
            message.to_absolute_path(os.getcwd())
            loc = message.location
            code = message.code

            if code in ignore_codes:
                continue

            key = _Key(loc.path, loc.line, code)
            return_dict[key] = message

    return return_dict


def _file_is_test(filename):
    """Return true if file is a test."""
    is_test = re.compile(r"^.*test[^{0}]*.py$".format(os.path.sep))
    return bool(is_test.match(filename))


def _run_prospector(filename):
    """Run prospector."""
    linter_tools = [
        "dodgy",
        "pep257",
        "pep8",
        "pyflakes"
    ]

    if can_run_pylint():
        linter_tools.append("pylint")

    # Run prospector on tests. There are some errors we don't care about:
    # - invalid-name: This is often triggered because test method names can
    #                 be quite long. Descriptive test method names are good,
    #                 so disable this warning.
    # - super-on-old-class: unittest.TestCase is a new style class, but
    #                       pylint detects an old style class.
    # - too-many-public-methods: TestCase subclasses by definition have
    #                            lots of methods.
    test_ignore_codes = [
        "invalid-name",
        "super-on-old-class",
        "too-many-public-methods"
    ]

    if _file_is_test(filename):
        return _run_prospector_on([filename],
                                  linter_tools,
                                  ignore_codes=test_ignore_codes)
    else:
        return _run_prospector_on([filename],
                                  linter_tools + ["frosted"])


def can_run_pychecker():
    """Return true if we can use pychecker."""
    from platform import python_implementation
    from sys import version_info  # suppress(PYC70)
    return version_info.major == 2 and python_implementation() == "CPython"


def _run_pychecker(filename):
    """Run pychecker.

    This tool will not run if we're not on the right python version.
    """
    if not can_run_pychecker():
        return dict()

    from prospector.message import Message, Location

    return_dict = dict()

    def get_pychecker_warnings(filename):
        """Get all pychecker warnings."""
        os.environ["PYCHECKER_DISABLED"] = "True"

        from pychecker import checker
        from pychecker import pcmodules as pcm
        from pychecker import warn
        from pychecker import Config

        setup_py_file = os.path.realpath(os.path.join(os.getcwd(), "setup.py"))
        if os.path.realpath(filename) == setup_py_file:
            return list()

        args = ["--only",
                "--limit",
                "1000",
                "-Q",
                "-8",
                "-2",
                "-1",
                "-a",
                "--changetypes",
                "--no-unreachable",
                "-v",
                filename]
        config, files, supps = Config.setupFromArgs(args)

        with _custom_argv([]):
            with CapturedOutput():
                checker.processFiles(files, config, supps)
                check_modules = [m for m in pcm.getPCModules() if m.check]
                return warn.find(check_modules, config, supps) or list()

    for warning in get_pychecker_warnings(filename):
        code = "PYC" + str(warning.level)
        path = warning.file
        line = warning.line
        key = _Key(path, line, code)
        return_dict[key] = Message(code,
                                   code,
                                   Location(path,
                                            None,
                                            None,
                                            line,
                                            0),
                                   str(warning.err))

    return return_dict


def _run_pyroma():
    """Run pyroma."""
    from pyroma import projectdata, ratings
    from prospector.message import Message, Location

    return_dict = dict()

    data = projectdata.get_data(os.getcwd())
    all_tests = ratings.ALL_TESTS
    for test in [mod() for mod in [t.__class__ for t in all_tests]]:
        if test.test(data) is False:
            class_name = test.__class__.__name__
            key = _Key("setup.py", 0, class_name)
            loc = Location("setup.py", None, None, 0, 0)
            msg = test.message()
            return_dict[key] = Message("pyroma",
                                       class_name,
                                       loc,
                                       msg)

    return return_dict


def _parse_suppressions(suppressions):
    """Parse a suppressions field and return suppressed codes."""
    return suppressions[len("suppress("):-1].split(",")


class PolysquareLintCommand(setuptools.Command):  # suppress(unused-function)

    """Provide a lint command."""

    def __init__(self, *args, **kwargs):
        """Initialize this class' instance variables."""
        setuptools.Command.__init__(self, *args, **kwargs)
        self._file_lines_cache = None
        self.suppress_codes = None
        self.exclusions = None
        self.initialize_options()

    def _file_lines(self, filename):
        """Get lines for filename, caching opened files."""
        try:
            return self._file_lines_cache[filename]
        except KeyError:
            with open(filename) as python_file:
                self._file_lines_cache[filename] = python_file.readlines()
            return self._file_lines_cache[filename]

    def _suppressed(self, filename, line, code):
        """Return true if linter error code is suppressed inline.

        The suppression format is suppress(CODE1,CODE2,CODE3) etc.
        """
        if code in self.suppress_codes:
            return True

        lines = self._file_lines(filename)

        # File is zero length, cannot be suppressed
        if len(lines) == 0:
            return False

        relevant_line = lines[line - 1]

        try:
            suppressions_function = relevant_line.split("#")[1].strip()
            if suppressions_function.startswith("suppress("):
                return code in _parse_suppressions(suppressions_function)
        except IndexError:
            above_line = lines[max(0, line - 2)]
            suppressions_function = above_line.strip()[1:].strip()
            if suppressions_function.startswith("suppress("):
                return code in _parse_suppressions(suppressions_function)
        finally:
            pass

    def _get_files_to_lint(self, external_directories):
        """Get files to lint."""
        from fnmatch import filter as fnfilter
        from fnmatch import fnmatch

        def is_excluded(filename, exclusions):
            """True if filename matches any of exclusions."""
            for exclusion in exclusions:
                if fnmatch(filename, exclusion):
                    return True

            return False

        def all_python_files_recursively(directory):
            """Get all python files in this directory and subdirectories."""
            py_files = []
            for root, _, files in os.walk(directory):
                py_files += fnfilter([os.path.join(root, f) for f in files],
                                     "*.py")

            return py_files

        all_f = []

        for external_dir in external_directories:
            all_f.extend(all_python_files_recursively(external_dir))

        packages = self.distribution.packages or list()
        for package in packages:
            all_f.extend(all_python_files_recursively(package))

        py_modules = self.distribution.py_modules or list()
        for filename in py_modules:
            all_f.append(os.path.realpath(filename + ".py"))

        all_f.append(os.path.join(os.getcwd(), "setup.py"))

        exclusions = [
            "*.egg/*",
            "*.eggs/*"
        ] + self.exclusions
        return [f for f in all_f if not is_excluded(f, exclusions)]

    def run(self):  # suppress(unused-function)
        """Run linters."""
        import parmap
        from prospector.formatters.pylint import PylintFormatter

        cwd = os.getcwd()
        files = self._get_files_to_lint([os.path.join(cwd, "test")])

        if len(files) == 0:
            sys_exit(0)
            return

        if len(files) > multiprocessing.cpu_count():
            mapper = parmap.map
        else:
            # suppress(E731)
            mapper = lambda f, i, *a: [f(*((x, ) + a)) for x in i]

        with _patched_pep257():
            keyed_messages = dict()

            # Certain checks, such as vulture and pyroma cannot be
            # meaningfully run in parallel (vulture requires all
            # files to be passed to the linter, pyroma can only be run
            # on /setup.py, etc).
            non_test_files = [f for f in files if not _file_is_test(f)]
            mapped = (mapper(_run_prospector, files) +
                      mapper(_run_flake8, files) +
                      mapper(_run_pychecker, files) +
                      [_run_prospector_on(non_test_files, ["vulture"])] +
                      [_run_pyroma()])

            # This will ensure that we don't repeat messages, because
            # new keys overwrite old ones.
            for keyed_messages_subset in mapped:
                keyed_messages.update(keyed_messages_subset)

        messages = []
        for _, message in keyed_messages.items():
            if not self._suppressed(message.location.path,
                                    message.location.line,
                                    message.code):
                message.to_relative_path(cwd)
                messages.append(message)

        sys.stdout.write(PylintFormatter(dict(),
                                         messages,
                                         None).render(messages=True,
                                                      summary=False,
                                                      profile=False) + "\n")

        if len(messages):
            sys_exit(1)

    def initialize_options(self):  # suppress(unused-function)
        """Set all options to their initial values."""
        self._file_lines_cache = dict()
        self.suppress_codes = list()
        self.exclusions = list()

    def finalize_options(self):  # suppress(unused-function)
        """Finalize all options."""
        for option in ["suppress-codes", "exclusions"]:
            attribute = option.replace("-", "_")
            if isinstance(getattr(self, attribute), str):
                setattr(self, attribute, getattr(self, attribute).split(","))

            if not isinstance(getattr(self, attribute), list):
                raise DistutilsArgError("--{0} must be a list".format(option))

    user_options = [  # suppress(unused-variable)
        ("suppress-codes=", None, "Error codes to suppress"),
        ("exclusions=", None, "Glob expressions of files to exclude")
    ]
    # suppress(unused-variable)
    description = ("""run linter checks using prospector, """
                   """flake8 and pychecker""")
