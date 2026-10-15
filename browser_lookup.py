#!/usr/bin/env python3
"""Chrome/Chromium binary discovery, shared by the scraper and the setup tools.

Single source of truth for "which browser will the pipeline use?". The scraper
(which launches it via nodriver) and scripts/setup.py + scripts/check_setup.py
(which warn about a missing browser) used to carry separate candidate lists that
had already drifted apart, so a preflight check could pass while the scrape then
failed with "no Chrome binary found".

Deliberately dependency-free (no config import) so it can be imported by a
script running from scripts/ as well as by the root-level pipeline stages.
"""
import logging
import os
import shutil
import sys

logger = logging.getLogger(__name__)

# Chrome/Chromium binaries looked up on PATH, in order of preference. This is
# the authoritative list - the launched browser is exactly what is resolved
# here (nodriver has no chromedriver to version-match).
CHROME_BINARY_NAMES = [
    "google-chrome-stable",
    "google-chrome",
    "chromium-browser",
    "chromium",
]

_MACOS_APP_BUNDLES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
]

_WINDOWS_SUBPATHS = [
    os.path.join("Google", "Chrome", "Application", "chrome.exe"),
    os.path.join("Chromium", "Application", "chrome.exe"),
]


def platform_chrome_candidates():
    """
    Well-known Chrome/Chromium install paths for the current platform.

    macOS .app bundles and Windows Program Files installs are not on PATH, so
    ``shutil.which`` cannot find them. Returns deduplicated candidate paths
    (empty on Linux, where the PATH names above are the only option).
    """
    candidates = []
    if sys.platform == "darwin":
        candidates = list(_MACOS_APP_BUNDLES)
    elif os.name == "nt":
        bases = [
            os.environ.get("PROGRAMFILES"),
            os.environ.get("PROGRAMW6432"),
            os.environ.get("PROGRAMFILES(X86)"),
            os.environ.get("LOCALAPPDATA"),
        ]
        for base in bases:
            if not base:
                continue
            candidates.extend(os.path.join(base, sub) for sub in _WINDOWS_SUBPATHS)
    seen = set()
    return [c for c in candidates if not (c in seen or seen.add(c))]


def find_on_path():
    """Return the first Chrome/Chromium binary on PATH, or None."""
    for name in CHROME_BINARY_NAMES:
        path = shutil.which(name)
        if path:
            return path
    return None


def get_chrome_executable(env_override=None):
    """
    Resolve the exact Chrome binary to launch.

    Precedence: ``env_override`` (the CHROME_BINARY_PATH setting), then a
    deterministic PATH scan, then well-known per-platform install paths.

    Args:
        env_override (str | None): explicit binary path from configuration.

    Returns:
        str | None: absolute path to the binary, or None when none is found.
    """
    if env_override:
        if os.path.isfile(env_override):
            logger.info("Using Chrome binary from CHROME_BINARY_PATH: %s", env_override)
            return env_override
        logger.warning("CHROME_BINARY_PATH set but not found: %s", env_override)

    path = find_on_path()
    if path:
        return path

    for candidate in platform_chrome_candidates():
        if os.path.isfile(candidate):
            logger.info("Found Chrome binary at well-known path: %s", candidate)
            return candidate

    return None
