# /polysquare_setuptools_lint/__init__.py
#
# Provides a setuptools command for running pyroma, prospector and
# flake8 with maximum settings on all distributed files and tests.
#
# See /LICENCE.md for Copyright information
"""Provide a setuptools command for linters."""

import errno

import multiprocessing

import os
import os.path

import platform

import re

import subprocess

import traceback

import sys  # suppress(I100)
from sys import exit as sys_exit  # suppress(I100)

from collections import namedtuple  # suppress(I100)

from contextlib import contextmanager

from distutils.errors import DistutilsArgError  # suppress(import-error)

from fnmatch import filter as fnfilter
from fnmatch import fnmatch

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


def _debug_linter_status(linter, filename, show_lint_files):
    """Indicate that we are running this linter if required."""
    if show_lint_files:
        print("{linter}: {filename}".format(linter=linter, filename=filename))


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


def _run_flake8(filename, stamp_file_name, show_lint_files):
    """Run flake8, cached by stamp_file_name."""
    _debug_linter_status("flake8", filename, show_lint_files)
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


def _run_prospector_on(filenames,
                       tools,
                       disabled_linters,
                       show_lint_files,
                       ignore_codes=None):
    """Run prospector on filename, using the specified tools.

    This function enables us to run different tools on different
    classes of files, which is necessary in the case of tests.
    """
    from prospector.run import Prospector, ProspectorConfig

    assert len(tools) > 0

    tools = list(set(tools) - set(disabled_linters))
    return_dict = dict()
    ignore_codes = ignore_codes or list()

    # Early return if all tools were filtered out
    if not len(tools):
        return return_dict

    # pylint doesn't like absolute paths, so convert to relative.
    all_argv = (["-F", "-D", "-M", "--no-autodetect", "-s", "veryhigh"] +
                ("-t " + " -t ".join(tools)).split(" "))

    for filename in filenames:
        _debug_linter_status("prospector", filename, show_lint_files)

    with _custom_argv(all_argv + [os.path.relpath(f) for f in filenames]):
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


def _run_prospector(filename,
                    stamp_file_name,
                    disabled_linters,
                    show_lint_files):
    """Run prospector."""
    linter_tools = [
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
                         disabled_linters,
                         show_lint_files,
                         **kwargs)


def _run_pyroma(setup_file, show_lint_files):
    """Run pyroma."""
    from pyroma import projectdata, ratings
    from prospector.message import Message, Location

    _debug_linter_status("pyroma", setup_file, show_lint_files)

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


_BLOCK_REGEXPS = [
    r"\bpylint:disable=[^\s]*\b",
    r"\bNOLINT:[^\s]*\b",
    r"\bNOQA[^\s]*\b",
    r"\bsuppress\([^\s]*\)"
]


def _run_polysquare_style_linter(matched_filenames,
                                 cache_dir,
                                 show_lint_files):
    """Run polysquare-generic-file-linter on matched_filenames."""
    from polysquarelinter import linter as lint
    from prospector.message import Message, Location

    return_dict = dict()

    def _custom_reporter(error, file_path):
        """Reporter for polysquare-generic-file-linter."""
        key = _Key(file_path, error[1].line, error[0])
        loc = Location(file_path, None, None, error[1].line, 0)
        return_dict[key] = Message("polysquare-generic-file-linter",
                                   error[0],
                                   loc,
                                   error[1].description)

    for filename in matched_filenames:
        _debug_linter_status("style-linter", filename, show_lint_files)

    # suppress(protected-access,unused-attribute)
    lint._report_lint_error = _custom_reporter
    lint.main([
        "--spellcheck-cache=" + os.path.join(cache_dir, "spelling"),
        "--stamp-file-path=" + os.path.join(cache_dir,
                                            "jobstamps",
                                            "polysquarelinter"),
        "--log-technical-terms-to=" + os.path.join(cache_dir,
                                                   "technical-terms"),
    ] + matched_filenames + [
        "--block-regexps"
    ] + _BLOCK_REGEXPS)

    return return_dict


def _run_spellcheck_linter(matched_filenames, cache_dir, show_lint_files):
    """Run spellcheck-linter on matched_filenames."""
    from polysquarelinter import lint_spelling_only as lint
    from prospector.message import Message, Location

    for filename in matched_filenames:
        _debug_linter_status("spellcheck-linter", filename, show_lint_files)

    return_dict = dict()

    def _custom_reporter(error, file_path):
        """Reporter for polysquare-generic-file-linter."""
        line = error.line_offset + 1
        key = _Key(file_path, line, "file/spelling_error")
        loc = Location(file_path, None, None, line, 0)
        # suppress(protected-access)
        desc = lint._SPELLCHECK_MESSAGES[error.error_type].format(error.word)
        return_dict[key] = Message("spellcheck-linter",
                                   "file/spelling_error",
                                   loc,
                                   desc)

    # suppress(protected-access,unused-attribute)
    lint._report_spelling_error = _custom_reporter
    lint.main([
        "--spellcheck-cache=" + os.path.join(cache_dir, "spelling"),
        "--stamp-file-path=" + os.path.join(cache_dir,
                                            "jobstamps",
                                            "polysquarelinter"),
        "--technical-terms=" + os.path.join(cache_dir, "technical-terms"),
    ] + matched_filenames)

    return return_dict


def _run_markdownlint(matched_filenames, show_lint_files):
    """Run markdownlint on matched_filenames."""
    from prospector.message import Message, Location

    for filename in matched_filenames:
        _debug_linter_status("mdl", filename, show_lint_files)

    try:
        proc = subprocess.Popen(["mdl"] + matched_filenames,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
        lines = proc.communicate()[0].decode().splitlines()
    except OSError as error:
        if error.errno == errno.ENOENT:
            return []

    lines = [
        re.match(r"([\w\-.\/\\ ]+)\:([0-9]+)\: (\w+) (.+)", l).groups(1)
        for l in lines
    ]
    return_dict = dict()
    for filename, lineno, code, msg in lines:
        key = _Key(filename, int(lineno), code)
        loc = Location(filename, None, None, int(lineno), 0)
        return_dict[key] = Message("markdownlint", code, loc, msg)

    return return_dict


def _parse_suppressions(suppressions):
    """Parse a suppressions field and return suppressed codes."""
    return suppressions[len("suppress("):-1].split(",")


def _get_cache_dir(candidate):
    """Get the current cache directory."""
    if candidate and len(candidate):
        return candidate

    import distutils.dist  # suppress(import-error)
    import distutils.command.build  # suppress(import-error)
    build_cmd = distutils.command.build.build(distutils.dist.Distribution())
    build_cmd.finalize_options()
    cache_dir = os.path.abspath(build_cmd.build_temp)

    # Make sure that it is created before anyone tries to use it
    try:
        os.makedirs(cache_dir)
    except OSError as error:
        if error.errno != errno.EEXIST:
            raise error

    return cache_dir


def _all_files_matching_ext(start, ext):
    """Get all files matching :ext: from :start: directory."""
    md_files = []
    for root, _, files in os.walk(start):
        md_files += fnfilter([os.path.join(root, f) for f in files],
                             "*." + ext)

    return md_files


def _is_excluded(filename, exclusions):
    """True if filename matches any of exclusions."""
    for exclusion in exclusions:
        if fnmatch(filename, exclusion):
            return True

    return False


class PolysquareLintCommand(setuptools.Command):  # suppress(unused-function)
    """Provide a lint command."""

    def __init__(self, *args, **kwargs):
        """Initialize this class' instance variables."""
        setuptools.Command.__init__(self, *args, **kwargs)
        self._file_lines_cache = None
        self.cache_directory = None
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

    def _get_md_files(self):
        """Get all markdown files."""
        all_f = _all_files_matching_ext(os.getcwd(), "md")
        exclusions = [
            "*.egg/*",
            "*.eggs/*",
            "*build/*"
        ] + self.exclusions
        return sorted([f for f in all_f if not _is_excluded(f, exclusions)])

    def _get_files_to_lint(self, external_directories):
        """Get files to lint."""
        all_f = []

        for external_dir in external_directories:
            all_f.extend(_all_files_matching_ext(external_dir, "py"))

        packages = self.distribution.packages or list()
        for package in packages:
            all_f.extend(_all_files_matching_ext(package, "py"))

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
        return sorted([f for f in all_f if not _is_excluded(f, exclusions)])

    # suppress(too-many-arguments)
    def _map_over_linters(self,
                          py_files,
                          non_test_files,
                          md_files,
                          stamp_directory,
                          mapper):
        """Run mapper over passed in files, returning a list of results."""
        dispatch = [
            ("flake8", lambda: mapper(_run_flake8,
                                      py_files,
                                      stamp_directory,
                                      self.show_lint_files)),
            ("pyroma", lambda: [_stamped_deps(stamp_directory,
                                              _run_pyroma,
                                              "setup.py",
                                              self.show_lint_files)]),
            ("mdl", lambda: [_run_markdownlint(md_files,
                                               self.show_lint_files)]),
            ("polysquare-generic-file-linter", lambda: [
                _run_polysquare_style_linter(py_files,
                                             self.cache_directory,
                                             self.show_lint_files)
            ]),
            ("spellcheck-linter", lambda: [
                _run_spellcheck_linter(md_files,
                                       self.cache_directory,
                                       self.show_lint_files)
            ])
        ]

        # Prospector checks get handled on a case sub-linter by sub-linter
        # basis internally, so always run the mapper over prospector.
        #
        # vulture should be added again once issue 180 is fixed.
        prospector = (mapper(_run_prospector,
                             py_files,
                             stamp_directory,
                             self.disable_linters,
                             self.show_lint_files) +
                      [_stamped_deps(stamp_directory,
                                     _run_prospector_on,
                                     non_test_files,
                                     ["dodgy"],
                                     self.disable_linters,
                                     self.show_lint_files)])

        for ret in prospector:
            yield ret

        for linter, action in dispatch:
            if linter not in self.disable_linters:
                try:
                    for ret in action():
                        yield ret
                except Exception as error:
                    traceback.print_exc()
                    sys.stderr.write("""Encountered error '{}' whilst """
                                     """running {}""".format(str(error),
                                                             linter))
                    raise error

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
            if self.stamp_directory:
                stamp_directory = self.stamp_directory
            else:
                stamp_directory = os.path.join(self.cache_directory,
                                               "polysquare_setuptools_lint",
                                               "jobstamps")

            # This will ensure that we don't repeat messages, because
            # new keys overwrite old ones.
            for keyed_subset in self._map_over_linters(files,
                                                       non_test_files,
                                                       self._get_md_files(),
                                                       stamp_directory,
                                                       mapper):
                keyed_messages.update(keyed_subset)

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
        self.cache_directory = ""
        self.stamp_directory = ""
        self.disable_linters = list()
        self.show_lint_files = 0

    def finalize_options(self):  # suppress(unused-function)
        """Finalize all options."""
        for option in ["suppress-codes", "exclusions", "disable-linters"]:
            attribute = option.replace("-", "_")
            if isinstance(getattr(self, attribute), str):
                setattr(self, attribute, getattr(self, attribute).split(","))

            if not isinstance(getattr(self, attribute), list):
                raise DistutilsArgError("""--{0} must be """
                                        """a list""".format(option))

        if not isinstance(self.cache_directory, str):
            raise DistutilsArgError("""--cache-directory=CACHE """
                                    """must be a string""")

        if not isinstance(self.stamp_directory, str):
            raise DistutilsArgError("""--stamp-directory=STAMP """
                                    """must be a string""")

        if not isinstance(self.stamp_directory, str):
            raise DistutilsArgError("""--stamp-directory=STAMP """
                                    """must be a string""")

        if not isinstance(self.show_lint_files, int):
            raise DistutilsArgError("""--show-lint-files must be a int""")

        self.cache_directory = _get_cache_dir(self.cache_directory)

    user_options = [  # suppress(unused-variable)
        ("suppress-codes=", None, """Error codes to suppress"""),
        ("exclusions=", None, """Glob expressions of files to exclude"""),
        ("disable-linters=", None, """Linters to disable"""),
        ("cache-directory=", None, """Where to store caches"""),
        ("stamp-directory=",
         None,
         """Where to store stamps of completed jobs"""),
        ("show-lint-files", None, """Show files before running lint""")
    ]
    # suppress(unused-variable)
    description = ("""run linter checks using prospector, """
                   """flake8 and pyroma""")
