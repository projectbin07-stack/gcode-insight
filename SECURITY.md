# Security policy

## Supported versions

Only the latest release receives fixes.

## Reporting a vulnerability

Please do not open a public issue for security problems. Use GitHub's private reporting instead:
<https://github.com/projectbin07-stack/gcode-insight/security/advisories/new>.

Include a description, a minimal input that triggers the problem and the version you used. Reports
are handled on a best-effort basis by a single maintainer.

## Scope

`gcode-insight` parses untrusted text files and `.3mf` zip archives. It never executes file content,
writes only to the path given to `--html`, and makes no network requests. Reports of interest
include crashes or excessive memory/CPU use on crafted input and HTML injection through file content
into the generated report.
