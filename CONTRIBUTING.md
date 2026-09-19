# Contributing

Thanks for taking the time to help. This project is small on purpose, so the
process is short.

## Setting up

```
git clone https://github.com/Aegeaner/subcast
cd subcast
python -m venv .venv && . .venv/bin/activate
pip install -e ".[subs,dev]"
playwright install chromium
```

System packages: `mpv` for playback, `ffmpeg`/`ffprobe` for duration probing.

## Checks before a pull request

```
uvx ruff==0.16.8 check src tests
pytest
```

Both must pass. The lint command is pinned on purpose: ruff adds rules to its
default set between releases, so the `ruff` on `PATH` can pass while CI fails.
The test suite is offline and must stay that way: no network access, no
sleeping, and no dependence on a show being published today.

## Where documentation goes

Documentation follows the four types it is written in: the README
installs and orients, `docs/how-to.md` holds task recipes,
`docs/reference.md` holds options, paths and statuses, and
`docs/explanation.md` holds the design and its reasons. Put a change in the
page whose type it belongs to, and keep each page to its own type: a recipe
does not explain, and a reference entry does not instruct.

## What a good change looks like

- **Behaviour over implementation.** Tests should fail if the behaviour
  breaks, not if the code is reorganised. Asserting a helper was called, or
  that a field was copied, is not a test.
- **No new dependencies** without a good reason in the pull request.
- **Keep the pipeline honest**: `sources → media → transcript → segments →
  artifacts → player`. Anything RTÉ-specific belongs in `sources/rte.py`;
  anything usable elsewhere belongs in `segments.py`, `srt.py`, `chapters.py`
  or `captionbar.py`.
- **Report what you actually ran.** "Verified with `subcast --subs` on
  episode X" beats "should work".

## Legal

Do not add code or fixtures that redistribute copyrighted material (media,
scraped pages) or that circumvents access controls. Test fixtures are
synthetic: `tests/fixtures/episode_page.html` reproduces the *structure* of
an episode page with invented content.
