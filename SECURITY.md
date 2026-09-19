# Security

This is a local command-line tool: it reads public web pages, downloads media
with your own credentials, and plays it through mpv. It runs no server and
collects nothing.

## Reporting

Report a vulnerability privately through GitHub's
[security advisories](https://github.com/Aegeaner/subcast/security/advisories/new)
rather than in a public issue.

Please include what you ran, what happened, and what you expected.

## In scope

- Command injection or path traversal from page contents, media URLs or file
  names (`sanitize_filename`, the cache stem, the mpv argument list).
- Escaping terminal output from programmatically obtained text (segment
  titles, captions) — text is not currently sanitised for control characters.
- Anything that silently exfiltrates data.

## Not in scope

- The security of mpv, Playwright, Chromium, faster-whisper or the media
  hosts; report those upstream.
- Downloading content you do not have the right to download.
