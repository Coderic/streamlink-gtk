# recording.py
#
# Copyright 2026 Neftali Yagua
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# SPDX-License-Identifier: Apache-2.0

"""Streamlink CLI recording (``streamlink --ffmpeg-fout … URL quality -o path``)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from typing import Any, Sequence

# Keys match GSettings ``record-container``; values are FFmpeg muxer names for ``--ffmpeg-fout``
# and the file extension substituted for ``{ext}`` in filename templates.
RECORD_CONTAINER: dict[str, tuple[str, str]] = {
    'mkv': ('matroska', 'mkv'),
    'mp4': ('mp4', 'mp4'),
    'mpegts': ('mpegts', 'ts'),
}


def record_container_ffmpeg_fout(container_key: str) -> str:
    """Return the ``--ffmpeg-fout`` muxer name (Streamlink/FFmpeg)."""
    return RECORD_CONTAINER.get(container_key, RECORD_CONTAINER['mkv'])[0]


def record_container_file_extension(container_key: str) -> str:
    """File extension (without dot) for ``{ext}`` in templates."""
    return RECORD_CONTAINER.get(container_key, RECORD_CONTAINER['mkv'])[1]


def streamlink_invocation() -> list[str]:
    """Argv prefix: ``streamlink`` executable or ``python -m streamlink``."""
    exe = shutil.which('streamlink')
    if exe:
        return [exe]
    return [sys.executable, '-m', 'streamlink']


def build_streamlink_record_argv(
    page_url: str,
    quality: str,
    output_path: str,
    *,
    ffmpeg_fout: str,
) -> list[str]:
    """Build argv to capture a stream to *output_path* using Streamlink ``-o``.

    *ffmpeg_fout* must be a valid FFmpeg muxer for ``--ffmpeg-fout`` (e.g. ``matroska``, ``mp4``,
    ``mpegts``) so the mux matches the file extension when Streamlink remuxes via FFmpeg.
    """
    return [
        *streamlink_invocation(),
        '--ffmpeg-fout',
        ffmpeg_fout,
        page_url,
        quality,
        '-o',
        output_path,
    ]


def launch_record_process(argv: Sequence[str]) -> subprocess.Popen:
    """Start Streamlink for recording.

    Inside Flatpak, avoid ``flatpak-spawn --host`` so the returned PID matches the
    Streamlink process (needed for ``SIGSTOP`` / ``SIGCONT`` on pause/resume).

    Standard error is a pipe (text mode). **The caller must consume**
    :attr:`~subprocess.Popen.stderr` continuously while the process runs; if the
    pipe buffer fills, Streamlink can block on writes and stall the recording.
    """
    argv_list = list(argv)
    popen_kw: dict[str, Any] = {
        'stdin': subprocess.DEVNULL,
        'stdout': subprocess.DEVNULL,
        'stderr': subprocess.PIPE,
        'text': True,
        'encoding': 'utf-8',
        'errors': 'replace',
        'bufsize': 1,
        'start_new_session': True,
    }
    return subprocess.Popen(argv_list, **popen_kw)
