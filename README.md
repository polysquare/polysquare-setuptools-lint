# polysquare-setuptools-lint #

This module provides a lint command to run several well-known
python static analysis tools, including prospector, flake8,
pyroma and pylint.

Pass --exclude=PAT1,PAT2 to exclude glob-expression patterns PAT1
and PAT2 from the list of files to be linted.

Pass --suppress=CODE1,CODE2 to suppress reported codes globally.

All linter errors can be suppressed inline by using
suppress(CODE1,CODE2) as either a comment at the end of the line
producing the error or the line directly above it.
