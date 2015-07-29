# Polysquare Setuptools Linter

This module provides a lint command to run several well-known
python static analysis tools, including prospector, flake8,
pyroma and pylint.

## Status

| Travis CI (Ubuntu) | AppVeyor (Windows) | Coverage | PyPI | Licence |
|--------------------|--------------------|----------|------|---------|
|[![Travis](https://img.shields.io/travis/polysquare/polysquare-setuptools-lint.svg)](http://travis-ci.org/polysquare/polysquare-setuptools-lint)|[![AppVeyor](https://img.shields.io/appveyor/ci/smspillaz/polysquare-setuptools-lint-7r9ws.svg)](https://ci.appveyor.com/project/smspillaz/polysquare-setuptools-lint-7r9ws)|[![Coveralls](https://img.shields.io/coveralls/polysquare/polysquare-setuptools-lint.svg)](http://coveralls.io/polysquare/polysquare-setuptools-lint)|[![PyPIVersion](https://img.shields.io/pypi/v/polysquare-setuptools-lint.svg)](https://pypi.python.org/pypi/polysquare-setuptools-lint)[![PyPIPythons](https://img.shields.io/pypi/pyversions/polysquare-setuptools-lint.svg)](https://pypi.python.org/pypi/polysquare-setuptools-lint)|[![License](https://img.shields.io/github/license/polysquare/polysquare-setuptools-lint.svg)](http://github.com/polysquare/polysquare-setuptools-lint)|

## Usage

    Options for 'PolysquareLintCommand' command:
      --suppress-codes   Error codes to suppress
      --exclusions       Glob expressions of files to exclude
      --stamp-directory  Where to store stamps of completed jobs

Pass `--exclude=PAT1,PAT2` to exclude glob-expression patterns PAT1
and PAT2 from the list of files to be linted.

Pass `--suppress-codes=CODE1,CODE2` to suppress reported codes globally.

All linter errors can be suppressed inline by using
`suppress(CODE1,CODE2)` as either a comment at the end of the line
producing the error or the line directly above it.
