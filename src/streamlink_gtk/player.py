# player.py
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

from __future__ import annotations

import os
import shlex
import subprocess
from typing import Sequence


def build_player_argv(player_command: str, stream_url: str) -> list[str]:
    """Build argv for the external player.

    If ``player_command`` contains ``%u``, it is replaced with the stream URL.
    Otherwise the URL is appended as the last argument (after ``shlex.split``).
    """
    if '%u' in player_command:
        parts = shlex.split(player_command, posix=True)
        return [p.replace('%u', stream_url) for p in parts]
    parts = shlex.split(player_command, posix=True)
    return [*parts, stream_url]


def launch_detached(argv: Sequence[str]) -> subprocess.Popen:
    """Start a subprocess detached from the app session; host spawn when inside Flatpak."""
    flatpak_id = os.environ.get('FLATPAK_ID')
    if flatpak_id:
        run_on_host = ['flatpak-spawn', '--host', *argv]
        return subprocess.Popen(
            run_on_host,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    return subprocess.Popen(
        list(argv),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def launch_player(argv: Sequence[str]) -> subprocess.Popen:
    """Start the player process; detached from the app session when possible."""
    return launch_detached(argv)
