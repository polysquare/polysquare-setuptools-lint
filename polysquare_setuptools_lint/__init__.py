# /polysquare_setuptools_lint/__init__.py
#
# Provides a setuptools command for running pyroma, prospector and
# flake8 with maximum settings on all distributed files and tests.
#
# See /LICENCE.md for Copyright information
"""Provide a setuptools command for linters."""

import hashlib

import multiprocessing

import os
import os.path

import platform

import re

import sys  # suppress(I100)
from sys import exit as sys_exit  # suppress(I100)

import tempfile  # suppress(I100)

from collections import namedtuple  # suppress(I100)

from contextlib import contextmanager

from distutils.errors import DistutilsArgError  # suppress(import-error)

from jobstamps import jobstamp

import setuptools


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


def _stamped_deps(stamp_directory, func, dependencies, *args, **kwargs):
    """Run func, assumed to have dependencies as its first argument."""
    if not isinstance(dependencies, list):
        jobstamps_dependencies = [dependencies]
    else:
        jobstamps_dependencies = dependencies

    kwargs.update({
        "jobstamps_cache_output_directory": stamp_directory,
        "jobstamps_dependencies": jobstamps_dependencies
    })
    return jobstamp.run(func, dependencies, *args, **kwargs)


class _Key(namedtuple("_Key", "file line code")):
    """A sortable class representing a key to store messages in a dict."""

    def __lt__(self, other):
        """Check if self should sort less than other."""
        if self.file == other.file:
            if self.line == other.line:
                return self.code < other.code

            return self.line < other.line

        return self.file < other.file


def _run_flake8_internal(filename):
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
            relative_path = os.path.join(cwd, filename)
            self._current_file = os.path.realpath(relative_path)

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

    flake8_check_paths = [filename]
    get_style_guide(reporter=Flake8MergeReporter,
                    jobs="1").check_files(paths=flake8_check_paths)

    return return_dict


def _run_flake8(filename, stamp_file_name):
    """Run flake8, cached by stamp_file_name."""
    return _stamped_deps(stamp_file_name,
                         _run_flake8_internal,
                         filename)


def can_run_pylint():
    """Return true if we can run pylint.

    Pylint fails on pypy3 as pypy3 doesn't implement certain attributes
    on functions.
    """
    return not (platform.python_implementation() == "PyPy" and
                sys.version_info.major == 3)


def can_run_frosted():
    """Return true if we can run frosted.

    Frosted fails on pypy3 as the installer depends on configparser. It
    also fails on Windows, because it reports file names incorrectly.
    """
    return (not (platform.python_implementation() == "PyPy" and
                 sys.version_info.major == 3) and
            platform.system() != "Windows")


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
    is_test = re.compile(r"^.*test[^{0}]*.py$".format(re.escape(os.path.sep)))
    return bool(is_test.match(filename))


def _run_prospector(filename, stamp_file_name):
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
    # - invalid-name: This is often triggered because test method names
    #                 can be quite long. Descriptive test method names are
    #                 good, so disable this warning.
    # - super-on-old-class: unittest.TestCase is a new style class, but
    #                       pylint detects an old style class.
    # - too-many-public-methods: TestCase subclasses by definition have
    #                            lots of methods.
    test_ignore_codes = [
        "invalid-name",
        "super-on-old-class",
        "too-many-public-methods"
    ]

    kwargs = dict()

    if _file_is_test(filename):
        kwargs["ignore_codes"] = test_ignore_codes
    else:
        if can_run_frosted():
            linter_tools += ["frosted"]

    return _stamped_deps(stamp_file_name,
                         _run_prospector_on,
                         [filename],
                         linter_tools,
                         **kwargs)


def _run_pyroma(setup_file):
    """Run pyroma."""
    from pyroma import projectdata, ratings
    from prospector.message import Message, Location

    return_dict = dict()

    data = projectdata.get_data(os.getcwd())
    all_tests = ratings.ALL_TESTS
    for test in [mod() for mod in [t.__class__ for t in all_tests]]:
        if test.test(data) is False:
            class_name = test.__class__.__name__
            key = _Key(setup_file, 0, class_name)
            loc = Location(setup_file, None, None, 0, 0)
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
        self.stamp_directory = None
        self.suppress_codes = None
        self.exclusions = None
        self.initialize_options()

    def _file_lines(self, filename):
        """Get lines for filename, caching opened files."""
        try:
            return self._file_lines_cache[filename]
        except KeyError:
            if os.path.isfile(filename):
                with open(filename) as python_file:
                    self._file_lines_cache[filename] = python_file.readlines()
            else:
                self._file_lines_cache[filename] = ""

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

        # Handle errors which appear after the end of the document.
        while line > len(lines):
            line = line - 1

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

        # Remove duplicates which may exist due to symlinks or repeated
        # packages found by /setup.py
        all_f = list(set([os.path.realpath(f) for f in all_f]))

        exclusions = [
            "*.egg/*",
            "*.eggs/*"
        ] + self.exclusions
        return sorted([f for f in all_f if not is_excluded(f, exclusions)])

    def run(self):  # suppress(unused-function)
        """Run linters."""
        import parmap
        from prospector.formatters.pylint import PylintFormatter

        cwd = os.getcwd()
        files = self._get_files_to_lint([os.path.join(cwd, "test")])

        if len(files) == 0:
            sys_exit(0)
            return

        use_multiprocessing = (not os.getenv("DISABLE_MULTIPROCESSING",
                                             None) and
                               multiprocessing.cpu_count() < len(files) and
                               multiprocessing.cpu_count() > 2)

        if use_multiprocessing:
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
            mapped = (mapper(_run_prospector, files, self.stamp_directory) +
                      mapper(_run_flake8, files, self.stamp_directory) +
                      [_stamped_deps(self.stamp_directory,
                                     _run_prospector_on,
                                     non_test_files,
                                     ["vulture"])] +
                      [_stamped_deps(self.stamp_directory,
                                     _run_pyroma,
                                     "setup.py")])

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
        self.stamp_directory = ""

    def finalize_options(self):  # suppress(unused-function)
        """Finalize all options."""
        for option in ["suppress-codes", "exclusions"]:
            attribute = option.replace("-", "_")
            if isinstance(getattr(self, attribute), str):
                setattr(self, attribute, getattr(self, attribute).split(","))

            if not isinstance(getattr(self, attribute), list):
                raise DistutilsArgError("""--{0} must be """
                                        """a list""".format(option))

        if not isinstance(self.stamp_directory, str):
            raise DistutilsArgError("""--stamp-directory=STAMP, STAMP """
                                    """must be a string""")

        if self.stamp_directory == "":
            dir_hash = hashlib.md5(os.getcwd().encode("utf-8")).hexdigest()
            self.stamp_directory = os.path.join(tempfile.gettempdir(),
                                                "jobstamps",
                                                "polysquare_setuptools_lint",
                                                dir_hash)

    user_options = [  # suppress(unused-variable)
        ("suppress-codes=", None, """Error codes to suppress"""),
        ("exclusions=", None, """Glob expressions of files to exclude"""),
        ("stamp-directory=", None,
         """Where to store stamps of completed jobs""")
    ]
    # suppress(unused-variable)
    description = ("""run linter checks using prospector, """
                   """flake8 and pyroma""")
