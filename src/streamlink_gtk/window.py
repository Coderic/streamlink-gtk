# window.py
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

import gettext
import os
import re
import signal
import threading
import time
import uuid
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import subprocess
from typing import Any

_LOG_MAX_LINES = 800

# Streamlink progress lines, e.g. "[download] Written 30.51 MiB to ... (2m15s @ 100 KiB/s)"
_DOWNLOAD_LINE = re.compile(r'^\[download\]', re.IGNORECASE)

import gi

gi.require_version('Gtk', '4.0')

from gi.repository import Gio, GLib, GObject, Gtk, Pango

from . import player as player_mod
from . import recording
from .job_item import JobItem
from .streamlink_backend import resolve_streams


def _tr(message: str) -> str:
    builtins_mod = __import__('builtins')
    trans = getattr(builtins_mod, '_', None)
    if callable(trans):
        return trans(message)
    return gettext.dgettext('streamlink-gtk', message)


def _status_label(code: str) -> str:
    labels = {
        'pending': _tr('Pending'),
        'resolving': _tr('Resolving…'),
        'ready': _tr('Ready'),
        'recording': _tr('Recording'),
        'paused': _tr('Paused'),
        'watching': _tr('Watching'),
        'error': _tr('Error'),
        'stopped': _tr('Stopped'),
    }
    return labels.get(code, code)


def _sort_stream_keys(keys: set[str]) -> list[str]:
    ordered: list[str] = []
    for special in ('best', 'worst'):
        if special in keys:
            ordered.append(special)
    mid = sorted(k for k in keys if k not in ('best', 'worst'))
    ordered.extend(sorted(mid, key=lambda x: x.lower()))
    return ordered


def _pick_quality(stream_keys: list[str], preferred: str) -> str:
    if preferred in stream_keys:
        return preferred
    if 'best' in stream_keys:
        return 'best'
    return stream_keys[0]


def _normalize_record_container_key(raw: str) -> str:
    k = raw.strip().lower()
    if k in recording.RECORD_CONTAINER:
        return k
    return 'mkv'


def _safe_record_basename(
    template: str, short_id: str, timestr: str, file_ext: str,
) -> str:
    """*file_ext* is without a leading dot (e.g. ``mkv``, ``ts``)."""
    name = template.replace('{job}', short_id).replace('{time}', timestr).replace(
        '{ext}', file_ext,
    )
    name = os.path.basename(name.replace(os.sep, '_').replace('/', '_'))
    if not name:
        name = f'streamlink-gtk-{short_id}-{timestr}.{file_ext}'
    return name


@Gtk.Template(resource_path='/org/coderic/streamlinkgtk/window.ui')
class StreamlinkGtkWindow(Gtk.ApplicationWindow):
    __gtype_name__ = 'StreamlinkGtkWindow'

    url_entry = Gtk.Template.Child()
    default_quality_entry = Gtk.Template.Child()
    status_message = Gtk.Template.Child()
    jobs_viewport = Gtk.Template.Child()
    recording_log_view = Gtk.Template.Child()

    def __init__(self, **kwargs: Any):
        super().__init__(**kwargs)
        self._settings = Gio.Settings.new('org.coderic.streamlinkgtk')
        self._store = Gio.ListStore(item_type=JobItem)
        self._streams: dict[str, dict[str, Any]] = {}
        self._processes: dict[str, subprocess.Popen] = {}
        self._job_log_deques: dict[str, deque[str]] = {}
        self._record_stderr_gen: dict[str, int] = {}
        self._recording_status_base: dict[str, str] = {}
        self._job_download_progress: dict[str, str] = {}
        self._job_selection: Gtk.SingleSelection | None = None
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix='streamlink')
        self._build_column_view()
        self.default_quality_entry.set_text(
            self._settings.get_string('default-stream-quality'))
        self.url_entry.connect('activate', lambda *_: self._enqueue_url())
        self.connect('destroy', lambda *_w: self.shutdown_executor())
        assert isinstance(self.recording_log_view, Gtk.TextView)
        self.recording_log_view.add_css_class('monospace')
        self._sync_log_view_to_selection()

    def _build_column_view(self) -> None:
        selection = Gtk.SingleSelection(model=self._store)
        self._job_selection = selection
        selection.connect('notify::selected-item', self._on_job_selection_changed)
        column_view = Gtk.ColumnView(model=selection)
        column_view.add_css_class('data-table')

        url_factory = Gtk.SignalListItemFactory()
        url_factory.connect('setup', self._on_url_setup)
        url_factory.connect('bind', self._on_url_bind)
        column_view.append_column(Gtk.ColumnViewColumn(title=_tr('URL'), factory=url_factory))

        status_factory = Gtk.SignalListItemFactory()
        status_factory.connect('setup', self._on_status_setup)
        status_factory.connect('bind', self._on_status_bind)
        status_factory.connect('unbind', self._on_status_unbind)
        column_view.append_column(Gtk.ColumnViewColumn(title=_tr('Status'), factory=status_factory))

        quality_factory = Gtk.SignalListItemFactory()
        quality_factory.connect('setup', self._on_quality_setup)
        quality_factory.connect('bind', self._on_quality_bind)
        quality_factory.connect('unbind', self._on_quality_unbind)
        column_view.append_column(Gtk.ColumnViewColumn(title=_tr('Quality'), factory=quality_factory))

        output_factory = Gtk.SignalListItemFactory()
        output_factory.connect('setup', self._on_output_setup)
        output_factory.connect('bind', self._on_output_bind)
        output_factory.connect('unbind', self._on_output_unbind)
        column_view.append_column(Gtk.ColumnViewColumn(title=_tr('Output'), factory=output_factory))

        actions_factory = Gtk.SignalListItemFactory()
        actions_factory.connect('setup', self._on_actions_setup)
        actions_factory.connect('bind', self._on_actions_bind)
        actions_factory.connect('unbind', self._on_actions_unbind)
        column_view.append_column(Gtk.ColumnViewColumn(title=_tr('Actions'), factory=actions_factory))

        self.jobs_viewport.set_child(column_view)

    def _on_job_selection_changed(
        self,
        _selection: Gtk.SingleSelection,
        _pspec: GObject.ParamSpec,
    ) -> None:
        self._sync_log_view_to_selection()
        self._sync_status_to_selection()

    def _compose_recording_status_message(self, job_id: str) -> str:
        base = self._recording_status_base.get(job_id, '').strip()
        if not base:
            return ''
        prog = self._job_download_progress.get(job_id, '').strip()
        if prog:
            return base + '\n' + prog
        return base

    def _set_recording_status_base(self, job_id: str, base: str) -> None:
        self._recording_status_base[job_id] = base
        self._refresh_live_recording_status(job_id)

    def _refresh_live_recording_status(self, job_id: str) -> None:
        sel = self._job_selection.get_selected_item() if self._job_selection else None
        if not isinstance(sel, JobItem) or sel.props.job_id != job_id:
            return
        if sel.props.status not in ('recording', 'paused'):
            return
        text = self._compose_recording_status_message(job_id)
        if text:
            self._set_status(text)

    def _sync_status_to_selection(self) -> None:
        sel = self._job_selection.get_selected_item() if self._job_selection else None
        if not isinstance(sel, JobItem):
            return
        jid = sel.props.job_id
        if sel.props.status in ('recording', 'paused') and jid in self._recording_status_base:
            self._set_status(self._compose_recording_status_message(jid))

    def _clear_recording_status_caches(self, job_id: str) -> None:
        self._recording_status_base.pop(job_id, None)
        self._job_download_progress.pop(job_id, None)

    def _sync_log_view_to_selection(self) -> None:
        assert isinstance(self.recording_log_view, Gtk.TextView)
        buf = self.recording_log_view.get_buffer()
        sel = self._job_selection.get_selected_item() if self._job_selection else None
        if not isinstance(sel, JobItem):
            buf.set_text(_tr(
                'Select a job in the list to see Streamlink output for that queue entry.',
            ))
            return
        jid = sel.props.job_id
        lines = self._job_log_deques.get(jid)
        if lines:
            buf.set_text('\n'.join(lines))
            end = buf.get_end_iter()
            self.recording_log_view.scroll_to_iter(end, 0.0, False, 0.0, 0.0)
        else:
            buf.set_text('')

    def _select_job_row_for_log(self, job_id: str) -> None:
        """Ensure the ColumnView selection matches *job_id* so the activity log updates for that row."""
        sel = self._job_selection
        if sel is None:
            return
        idx = self._find_index(job_id)
        if idx >= 0:
            sel.set_selected(idx)

    def _trim_text_buffer_lines(self, buf: Gtk.TextBuffer, max_lines: int) -> None:
        while buf.get_line_count() > max_lines:
            start = buf.get_start_iter()
            end = start.copy()
            if not end.forward_line():
                break
            buf.delete(start, end)

    def _append_streamlink_log_line(self, job_id: str, text: str, session_gen: int) -> bool:
        """GLib idle handler: append one stderr line; keeps deque and visible buffer aligned."""
        if self._record_stderr_gen.get(job_id) != session_gen:
            return False
        dq = self._job_log_deques.setdefault(job_id, deque())
        while len(dq) >= _LOG_MAX_LINES:
            dq.popleft()
        dq.append(text)
        if _DOWNLOAD_LINE.search(text):
            self._job_download_progress[job_id] = text.strip()
            self._refresh_live_recording_status(job_id)
        sel = self._job_selection.get_selected_item() if self._job_selection else None
        if isinstance(sel, JobItem) and sel.props.job_id == job_id:
            buf = self.recording_log_view.get_buffer()
            end = buf.get_end_iter()
            buf.insert(end, text + '\n')
            self._trim_text_buffer_lines(buf, _LOG_MAX_LINES)
            end = buf.get_end_iter()
            self.recording_log_view.scroll_to_iter(end, 0.0, False, 0.0, 0.0)
        return False

    def _begin_record_stderr_reader(
        self, job_id: str, proc: subprocess.Popen, session_gen: int,
    ) -> None:
        err = proc.stderr
        if err is None:
            return

        def _emit(text: str) -> None:
            if not text or not text.strip():
                return
            GLib.idle_add(
                self._append_streamlink_log_line,
                job_id,
                text.strip(),
                session_gen,
                priority=GLib.PRIORITY_LOW,
            )

        def _run() -> None:
            # Chunked read: Streamlink logs progress with \r (no \n) and Python may block-buffer
            # stderr when piped; readline() would then stay empty for a long time.
            pending = ''
            try:
                while True:
                    chunk = err.read(4096)
                    if not chunk:
                        break
                    pending += chunk.replace('\r', '\n')
                    while '\n' in pending:
                        line, pending = pending.split('\n', 1)
                        _emit(line)
                tail = pending.strip()
                if tail:
                    _emit(tail)
            finally:
                try:
                    err.close()
                except OSError:
                    pass

        threading.Thread(
            target=_run,
            name=f'streamlink-gtk-rec-{job_id[:8]}',
            daemon=True,
        ).start()

    def _on_output_setup(self, _f: Gtk.ListItemFactory, list_item: Gtk.ListItem) -> None:
        label = Gtk.Label(xalign=0.0, max_width_chars=28)
        label.set_ellipsize(Pango.EllipsizeMode.END)
        list_item.set_child(label)

    def _on_output_bind(self, _f: Gtk.ListItemFactory, list_item: Gtk.ListItem) -> None:
        item = list_item.get_item()
        assert isinstance(item, JobItem)
        label = list_item.get_child()
        assert isinstance(label, Gtk.Label)

        def _apply_path() -> None:
            rp = item.props.record_path.strip()
            if rp:
                label.set_label(os.path.basename(rp))
                label.set_tooltip_text(rp)
            else:
                label.set_label(_tr('—'))
                label.set_tooltip_text(None)

        _apply_path()
        hid = item.connect('notify::record-path', lambda *_a: _apply_path())
        setattr(label, '_slgtk_output_notify_id', hid)

    def _on_output_unbind(self, _f: Gtk.ListItemFactory, list_item: Gtk.ListItem) -> None:
        label = list_item.get_child()
        if not isinstance(label, Gtk.Label):
            return
        item = list_item.get_item()
        hid = getattr(label, '_slgtk_output_notify_id', None)
        if isinstance(item, JobItem) and hid is not None:
            item.disconnect(hid)
        if hasattr(label, '_slgtk_output_notify_id'):
            delattr(label, '_slgtk_output_notify_id')

    def _on_url_setup(self, _f: Gtk.ListItemFactory, list_item: Gtk.ListItem) -> None:
        label = Gtk.Label(xalign=0.0, max_width_chars=40)
        label.set_ellipsize(Pango.EllipsizeMode.END)
        list_item.set_child(label)

    def _on_url_bind(self, _f: Gtk.ListItemFactory, list_item: Gtk.ListItem) -> None:
        item = list_item.get_item()
        assert isinstance(item, JobItem)
        label = list_item.get_child()
        assert isinstance(label, Gtk.Label)
        url = item.props.url
        label.set_label(url)
        label.set_tooltip_text(url)

    def _on_status_setup(self, _f: Gtk.ListItemFactory, list_item: Gtk.ListItem) -> None:
        label = Gtk.Label(xalign=0.0)
        list_item.set_child(label)

    def _on_status_bind(self, _f: Gtk.ListItemFactory, list_item: Gtk.ListItem) -> None:
        item = list_item.get_item()
        assert isinstance(item, JobItem)
        label = list_item.get_child()
        assert isinstance(label, Gtk.Label)
        raw = item.props.status
        label.set_label(_status_label(raw))
        hid = item.connect(
            'notify::status',
            self._on_job_item_status_notify,
            label,
        )
        setattr(label, '_slgtk_status_notify_id', hid)

    def _on_job_item_status_notify(
        self,
        item: JobItem,
        _pspec: GObject.ParamSpec,
        label: Gtk.Label,
    ) -> None:
        label.set_label(_status_label(item.props.status))

    def _on_status_unbind(self, _f: Gtk.ListItemFactory, list_item: Gtk.ListItem) -> None:
        label = list_item.get_child()
        if not isinstance(label, Gtk.Label):
            return
        item = list_item.get_item()
        hid = getattr(label, '_slgtk_status_notify_id', None)
        if isinstance(item, JobItem) and hid is not None:
            item.disconnect(hid)
        if hasattr(label, '_slgtk_status_notify_id'):
            delattr(label, '_slgtk_status_notify_id')

    def _on_quality_setup(self, _f: Gtk.ListItemFactory, list_item: Gtk.ListItem) -> None:
        dropdown = Gtk.DropDown()
        list_item.set_child(dropdown)

    def _sync_quality_dropdown(self, item: JobItem, dropdown: Gtk.DropDown) -> None:
        """Rebuild DropDown model from JobItem when bind runs or quality_options changes."""
        keys = [k for k in item.props.quality_options.split('|') if k]
        slist = Gtk.StringList.new(keys)
        dropdown.set_model(slist)
        sel = item.props.selected_quality
        if sel in keys:
            dropdown.set_selected(keys.index(sel))
        elif keys:
            dropdown.set_selected(0)

    def _on_job_item_quality_options_notify(
        self,
        item: JobItem,
        _pspec: GObject.ParamSpec,
        dropdown: Gtk.DropDown,
    ) -> None:
        """ColumnView does not re-bind when model row properties change; refresh here."""
        self._sync_quality_dropdown(item, dropdown)

    def _on_quality_bind(self, _f: Gtk.ListItemFactory, list_item: Gtk.ListItem) -> None:
        item = list_item.get_item()
        assert isinstance(item, JobItem)
        dropdown = list_item.get_child()
        assert isinstance(dropdown, Gtk.DropDown)
        self._sync_quality_dropdown(item, dropdown)
        hid_sel = dropdown.connect('notify::selected-item', self._on_quality_selected, item)
        setattr(dropdown, '_slgtk_quality_notify_id', hid_sel)
        hid_opt = item.connect(
            'notify::quality-options',
            self._on_job_item_quality_options_notify,
            dropdown,
        )
        setattr(dropdown, '_slgtk_quality_item_notify_id', hid_opt)

    def _on_quality_unbind(self, _f: Gtk.ListItemFactory, list_item: Gtk.ListItem) -> None:
        dropdown = list_item.get_child()
        if not isinstance(dropdown, Gtk.DropDown):
            return
        item = list_item.get_item()
        hid_opt = getattr(dropdown, '_slgtk_quality_item_notify_id', None)
        if isinstance(item, JobItem) and hid_opt is not None:
            item.disconnect(hid_opt)
        if hasattr(dropdown, '_slgtk_quality_item_notify_id'):
            delattr(dropdown, '_slgtk_quality_item_notify_id')
        hid = getattr(dropdown, '_slgtk_quality_notify_id', None)
        if hid is not None:
            dropdown.disconnect(hid)
        if hasattr(dropdown, '_slgtk_quality_notify_id'):
            delattr(dropdown, '_slgtk_quality_notify_id')

    def _on_quality_selected(
        self, dropdown: Gtk.DropDown, _pspec: GObject.ParamSpec, item: JobItem,
    ) -> None:
        pos = dropdown.get_selected()
        model = dropdown.get_model()
        if pos == Gtk.INVALID_LIST_POSITION or model is None:
            return
        strobj = model.get_item(pos)
        if strobj is None:
            return
        item.props.selected_quality = strobj.get_string()

    def _action_icon_button(self, icon_name: str, tooltip: str) -> Gtk.Button:
        """Symbolic icon button with tooltip (labels via tooltips for a compact actions row)."""
        btn = Gtk.Button.new_from_icon_name(icon_name)
        btn.set_tooltip_text(tooltip)
        return btn

    def _on_actions_setup(self, _f: Gtk.ListItemFactory, list_item: Gtk.ListItem) -> None:
        box = Gtk.Box(spacing=4, orientation=Gtk.Orientation.HORIZONTAL)
        btn_record = self._action_icon_button(
            'media-record-symbolic',
            _tr('Record stream to file with Streamlink'),
        )
        btn_pause = self._action_icon_button(
            'media-playback-pause-symbolic',
            _tr('Pause capture (SIGSTOP on recorder process)'),
        )
        btn_resume = self._action_icon_button(
            'media-playback-start-symbolic',
            _tr('Resume capture (SIGCONT)'),
        )
        btn_stop = self._action_icon_button(
            'media-playback-stop-symbolic',
            _tr('Stop recording or playback'),
        )
        btn_watch = self._action_icon_button(
            'video-display-symbolic',
            _tr('Open stream in external player'),
        )
        btn_remove = self._action_icon_button(
            'list-remove-symbolic',
            _tr('Remove'),
        )
        for b in (btn_record, btn_pause, btn_resume, btn_stop, btn_watch, btn_remove):
            box.append(b)
        setattr(box, '_btn_record', btn_record)
        setattr(box, '_btn_pause', btn_pause)
        setattr(box, '_btn_resume', btn_resume)
        setattr(box, '_btn_stop', btn_stop)
        setattr(box, '_btn_watch', btn_watch)
        setattr(box, '_btn_remove', btn_remove)
        list_item.set_child(box)

    def _sync_action_buttons(self, item: JobItem, box: Gtk.Box) -> None:
        record = getattr(box, '_btn_record', None)
        pause = getattr(box, '_btn_pause', None)
        resume = getattr(box, '_btn_resume', None)
        stop = getattr(box, '_btn_stop', None)
        watch = getattr(box, '_btn_watch', None)
        remove = getattr(box, '_btn_remove', None)
        if not all(isinstance(x, Gtk.Button) for x in (
            record, pause, resume, stop, watch, remove,
        )):
            return
        assert isinstance(record, Gtk.Button)
        assert isinstance(pause, Gtk.Button)
        assert isinstance(resume, Gtk.Button)
        assert isinstance(stop, Gtk.Button)
        assert isinstance(watch, Gtk.Button)
        assert isinstance(remove, Gtk.Button)

        st = item.props.status
        has_streams = self._job_has_streams(item)

        record.set_sensitive(has_streams and st in ('ready', 'stopped'))
        watch.set_sensitive(has_streams and st in ('ready', 'stopped'))
        pause.set_sensitive(st == 'recording')
        resume.set_sensitive(st == 'paused')
        stop.set_sensitive(st in ('recording', 'paused', 'watching'))
        remove.set_sensitive(True)

    def _job_has_streams(self, item: JobItem) -> bool:
        jid = item.props.job_id
        return jid in self._streams and bool(self._streams[jid])

    def _on_actions_bind(self, _f: Gtk.ListItemFactory, list_item: Gtk.ListItem) -> None:
        item = list_item.get_item()
        assert isinstance(item, JobItem)
        box = list_item.get_child()
        assert isinstance(box, Gtk.Box)
        self._sync_action_buttons(item, box)

        def _on_status_changed(_it: JobItem, _pspec: GObject.ParamSpec) -> None:
            self._sync_action_buttons(item, box)

        hid_st = item.connect('notify::status', _on_status_changed)
        setattr(box, '_slgtk_actions_status_hid', hid_st)

        btn_record = getattr(box, '_btn_record')
        btn_pause = getattr(box, '_btn_pause')
        btn_resume = getattr(box, '_btn_resume')
        btn_stop = getattr(box, '_btn_stop')
        btn_watch = getattr(box, '_btn_watch')
        btn_remove = getattr(box, '_btn_remove')
        assert isinstance(btn_record, Gtk.Button)
        p1 = btn_record.connect('clicked', lambda *_b: self._start_recording(item))
        p2 = btn_pause.connect('clicked', lambda *_b: self._pause_recording(item))
        p3 = btn_resume.connect('clicked', lambda *_b: self._resume_recording(item))
        p4 = btn_stop.connect('clicked', lambda *_b: self._stop_job(item))
        p5 = btn_watch.connect('clicked', lambda *_b: self._watch_job(item))
        p6 = btn_remove.connect('clicked', lambda *_b: self._remove_job(item))
        setattr(box, '_slgtk_action_handler_ids', (p1, p2, p3, p4, p5, p6))

    def _on_actions_unbind(self, _f: Gtk.ListItemFactory, list_item: Gtk.ListItem) -> None:
        box = list_item.get_child()
        if not isinstance(box, Gtk.Box):
            return
        item = list_item.get_item()
        hid_st = getattr(box, '_slgtk_actions_status_hid', None)
        if isinstance(item, JobItem) and hid_st is not None:
            item.disconnect(hid_st)
        if hasattr(box, '_slgtk_actions_status_hid'):
            delattr(box, '_slgtk_actions_status_hid')
        t = getattr(box, '_slgtk_action_handler_ids', None)
        if not t:
            return
        btn_record = getattr(box, '_btn_record', None)
        btn_pause = getattr(box, '_btn_pause', None)
        btn_resume = getattr(box, '_btn_resume', None)
        btn_stop = getattr(box, '_btn_stop', None)
        btn_watch = getattr(box, '_btn_watch', None)
        btn_remove = getattr(box, '_btn_remove', None)
        buttons = (btn_record, btn_pause, btn_resume, btn_stop, btn_watch, btn_remove)
        for btn, hid in zip(buttons, t):
            if isinstance(btn, Gtk.Button):
                btn.disconnect(hid)
        delattr(box, '_slgtk_action_handler_ids')

    @Gtk.Template.Callback()
    def on_add_clicked(self, *_args: Any) -> None:
        self._enqueue_url()

    @Gtk.Template.Callback()
    def on_stop_all_clicked(self, *_args: Any) -> None:
        for i in range(self._store.get_n_items()):
            it = self._store.get_item(i)
            if isinstance(it, JobItem):
                self._stop_job(it, quiet=True)

    def shutdown_executor(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=False)

    def _enqueue_url(self) -> None:
        url = self.url_entry.get_text().strip()
        if not url:
            self._set_status(_tr('Enter a stream URL.'))
            return
        job_id = str(uuid.uuid4())
        preferred = self.default_quality_entry.get_text().strip() or \
            self._settings.get_string('default-stream-quality')
        row = JobItem(
            job_id=job_id,
            url=url,
            status='pending',
            quality_options='',
            selected_quality=preferred,
        )
        self._store.append(row)
        self._set_status(_tr('Queued.'))
        self.url_entry.set_text('')
        fut = self._executor.submit(resolve_streams, url)

        def _done(future: Any) -> None:
            try:
                streams, err = future.result()
            except Exception as exc:  # noqa: BLE001 — show any worker failure
                GLib.idle_add(self._apply_resolved, job_id, None, str(exc))
                return
            GLib.idle_add(self._apply_resolved, job_id, streams, err)

        fut.add_done_callback(lambda f: _done(f))

        row.props.status = 'resolving'

    def _apply_resolved(
        self, job_id: str, streams: dict[str, Any] | None, err: str | None,
    ) -> None:
        item = self._find_job(job_id)
        if item is None:
            return
        if err or streams is None:
            item.props.status = 'error'
            self._set_status(err or _tr('Unknown error'))
            return
        keys = _sort_stream_keys(set(streams.keys()))
        pref = self._settings.get_string('default-stream-quality')
        chosen = _pick_quality(keys, item.props.selected_quality or pref)
        item.props.quality_options = '|'.join(keys)
        item.props.selected_quality = chosen
        self._streams[job_id] = streams
        item.props.status = 'ready'
        self._set_status(_tr('Streams resolved.'))

    def _find_job(self, job_id: str) -> JobItem | None:
        for i in range(self._store.get_n_items()):
            it = self._store.get_item(i)
            if isinstance(it, JobItem) and it.props.job_id == job_id:
                return it
        return None

    def _find_index(self, job_id: str) -> int:
        for i in range(self._store.get_n_items()):
            it = self._store.get_item(i)
            if isinstance(it, JobItem) and it.props.job_id == job_id:
                return i
        return -1

    def _recording_output_path(self, job_id: str) -> str | None:
        template = self._settings.get_string('record-filename-template').strip() or \
            'streamlink-gtk-{job}-{time}.{ext}'
        container_key = _normalize_record_container_key(
            self._settings.get_string('record-container'),
        )
        file_ext = recording.record_container_file_extension(container_key)
        out_dir = self._settings.get_string('record-output-dir').strip()
        if not out_dir:
            base = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_VIDEOS)
            out_dir = base or os.path.expanduser('~/Videos')
        try:
            os.makedirs(out_dir, exist_ok=True)
        except OSError as exc:
            self._set_status(str(exc))
            return None
        short = job_id[:8]
        timestr = time.strftime('%Y%m%d-%H%M%S')
        name = _safe_record_basename(template, short, timestr, file_ext)
        return os.path.join(out_dir, name)

    def _start_recording(self, item: JobItem) -> None:
        job_id = item.props.job_id
        if item.props.status not in ('ready', 'stopped'):
            return
        if not self._job_has_streams(item):
            self._set_status(_tr('Resolve streams before recording.'))
            return
        page_url = item.props.url.strip()
        if not page_url:
            self._set_status(_tr('No URL.'))
            return
        key = item.props.selected_quality
        if not key:
            self._set_status(_tr('Select a quality.'))
            return
        out_path = self._recording_output_path(job_id)
        if out_path is None:
            return
        container_key = _normalize_record_container_key(
            self._settings.get_string('record-container'),
        )
        ffmpeg_fout = recording.record_container_ffmpeg_fout(container_key)
        argv = recording.build_streamlink_record_argv(
            page_url,
            key,
            out_path,
            ffmpeg_fout=ffmpeg_fout,
        )
        self._record_stderr_gen[job_id] = self._record_stderr_gen.get(job_id, 0) + 1
        session_gen = self._record_stderr_gen[job_id]
        self._job_log_deques[job_id] = deque()
        self._job_download_progress.pop(job_id, None)
        old = self._processes.get(job_id)
        if old is not None:
            try:
                old.terminate()
            except ProcessLookupError:
                pass
            self._processes.pop(job_id, None)
        try:
            proc = recording.launch_record_process(argv)
        except OSError as exc:
            self._set_status(str(exc))
            item.props.status = 'error'
            return
        self._processes[job_id] = proc
        item.props.record_path = out_path
        item.props.status = 'recording'
        self._select_job_row_for_log(job_id)
        self._begin_record_stderr_reader(job_id, proc, session_gen)
        GLib.child_watch_add(GLib.PRIORITY_DEFAULT, proc.pid, self._on_job_process_exit, job_id)
        self._set_recording_status_base(
            job_id,
            _tr('Recording to file:') + '\n' + out_path,
        )

    def _pause_recording(self, item: JobItem) -> None:
        if item.props.status != 'recording':
            return
        job_id = item.props.job_id
        proc = self._processes.get(job_id)
        if proc is None:
            item.props.status = 'stopped'
            item.props.record_path = ''
            return
        try:
            os.kill(proc.pid, signal.SIGSTOP)
        except OSError as exc:
            self._set_status(str(exc))
            return
        item.props.status = 'paused'
        rp = item.props.record_path.strip()
        if rp:
            self._set_recording_status_base(
                job_id,
                _tr('Recording paused.') + '\n' + rp,
            )
        else:
            self._set_recording_status_base(job_id, _tr('Recording paused.'))

    def _resume_recording(self, item: JobItem) -> None:
        if item.props.status != 'paused':
            return
        job_id = item.props.job_id
        proc = self._processes.get(job_id)
        if proc is None:
            item.props.status = 'stopped'
            item.props.record_path = ''
            return
        try:
            os.kill(proc.pid, signal.SIGCONT)
        except OSError as exc:
            self._set_status(str(exc))
            return
        item.props.status = 'recording'
        rp = item.props.record_path.strip()
        if rp:
            self._set_recording_status_base(
                job_id,
                _tr('Recording resumed.') + '\n' + rp,
            )
        else:
            self._set_recording_status_base(job_id, _tr('Recording resumed.'))

    def _watch_job(self, item: JobItem) -> None:
        job_id = item.props.job_id
        streams = self._streams.get(job_id)
        if not streams:
            self._set_status(_tr('Resolve streams before watching.'))
            return
        key = item.props.selected_quality
        stream = streams.get(key)
        if stream is None:
            self._set_status(_tr('Selected quality is not available.'))
            return
        url = getattr(stream, 'url', None) or ''
        if not url and callable(getattr(stream, 'to_url', None)):
            url = stream.to_url()
        if not url:
            self._set_status(_tr('Stream has no playable URL.'))
            return
        cmd = self._settings.get_string('player-command')
        argv = player_mod.build_player_argv(cmd, url)
        old = self._processes.get(job_id)
        if old is not None:
            try:
                old.terminate()
            except ProcessLookupError:
                pass
            self._processes.pop(job_id, None)
        try:
            proc = player_mod.launch_player(argv)
        except OSError as exc:
            self._set_status(str(exc))
            item.props.status = 'error'
            return
        self._processes[job_id] = proc
        item.props.record_path = ''
        item.props.status = 'watching'
        GLib.child_watch_add(GLib.PRIORITY_DEFAULT, proc.pid, self._on_job_process_exit, job_id)
        self._set_status(_tr('Playing in external player…'))

    def _on_job_process_exit(
        self, pid: int, wait_status: int, job_id: str,
    ) -> None:
        proc = self._processes.get(job_id)
        if proc is None or proc.pid != pid:
            return GLib.SOURCE_REMOVE
        self._processes.pop(job_id, None)
        item = self._find_job(job_id)
        if item is None:
            return GLib.SOURCE_REMOVE
        st = item.props.status
        if st in ('recording', 'paused', 'watching'):
            item.props.record_path = ''
            item.props.status = 'stopped'
            if st in ('recording', 'paused'):
                self._clear_recording_status_caches(job_id)
                sel = self._job_selection.get_selected_item() if self._job_selection else None
                if isinstance(sel, JobItem) and sel.props.job_id == job_id:
                    self._set_status(_tr('Recording ended.'))
        return GLib.SOURCE_REMOVE

    def _stop_job(self, item: JobItem, quiet: bool = False) -> None:
        job_id = item.props.job_id
        proc = self._processes.pop(job_id, None)
        if proc is not None:
            try:
                proc.terminate()
            except ProcessLookupError:
                pass
        st = item.props.status
        if st in ('recording', 'paused', 'watching'):
            item.props.record_path = ''
            item.props.status = 'stopped'
            if st in ('recording', 'paused'):
                self._clear_recording_status_caches(job_id)
        if not quiet:
            self._set_status(_tr('Stopped.'))

    def _remove_job(self, item: JobItem) -> None:
        self._stop_job(item, quiet=True)
        job_id = item.props.job_id
        self._job_log_deques.pop(job_id, None)
        self._record_stderr_gen.pop(job_id, None)
        self._clear_recording_status_caches(job_id)
        self._streams.pop(job_id, None)
        idx = self._find_index(job_id)
        if idx >= 0:
            self._store.remove(idx)
        self._set_status(_tr('Job removed.'))

    def _set_status(self, message: str) -> None:
        self.status_message.set_label(message)
        self.status_message.set_tooltip_text(message or None)
