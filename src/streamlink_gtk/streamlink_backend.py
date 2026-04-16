# streamlink_backend.py
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

from typing import Any


def resolve_streams(url: str) -> tuple[dict[str, Any] | None, str | None]:
    """Resolve a URL to Streamlink stream objects.

    Runs in a worker thread; return values are passed to the GTK thread only.
    Streamlink is imported lazily so the UI can start when the module is only
    installed in the host environment (pip/venv) and not inside a Flatpak.
    """
    try:
        from streamlink import Streamlink
    except ImportError:
        return None, (
            'Streamlink is not available in this Python environment. '
            'Install it with pip (see README) or run the app from the host '
            'where `python3 -m pip install -r requirements.txt` was executed.'
        )
    try:
        session = Streamlink()
        streams = session.streams(url)
    except OSError as exc:
        return None, str(exc)
    except Exception as exc:  # streamlink raises various plugin errors
        return None, str(exc)

    if not streams:
        return None, "No streams found for this URL."

    return streams, None
