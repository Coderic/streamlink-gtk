# main.py
#
# Copyright 2026 Neftali Yagua
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# 	http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# SPDX-License-Identifier: Apache-2.0

import sys
import gi

gi.require_version('Gtk', '4.0')

from gi.repository import Gtk, Gio, GLib

from . import recording
from .window import StreamlinkGtkWindow


class StreamlinkGtkApplication(Gtk.Application):
    """The main application singleton class."""

    def __init__(self):
        super().__init__(application_id='org.coderic.streamlinkgtk',
                         flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
                         resource_base_path='/org/coderic/streamlinkgtk')
        self.create_action('quit', lambda *_: self.quit(), ['<control>q'])
        self.create_action('about', self.on_about_action)
        self.create_action('preferences', self.on_preferences_action)

    def do_activate(self):
        """Called when the application is activated.

        We raise the application's main window, creating it if
        necessary.
        """
        win = self.props.active_window
        if not win:
            win = StreamlinkGtkWindow(application=self)
        win.present()

    def on_about_action(self, *args):
        """Callback for the app.about action."""
        about = Gtk.AboutDialog(transient_for=self.props.active_window,
                                modal=True,
                                program_name='StreamlinkGTK',
                                logo_icon_name='org.coderic.streamlinkgtk',
                                version='0.1.0',
                                authors=['Neftali Yagua'],
                                copyright='© 2026 Neftali Yagua')
        # Translators: Replace "translator-credits" with your name/username, and optionally an email or URL.
        about.set_translator_credits(_('translator-credits'))
        about.present()

    def on_preferences_action(self, *_args):
        """Open preferences for player, default quality, and recording output."""
        parent = self.props.active_window
        settings = Gio.Settings.new('org.coderic.streamlinkgtk')
        dlg = Gtk.Dialog(
            transient_for=parent,
            modal=True,
            title=_('Preferences'),
        )
        dlg.add_button(_('_Cancel'), Gtk.ResponseType.CANCEL)
        dlg.add_button(_('_OK'), Gtk.ResponseType.OK)
        dlg.set_default_response(Gtk.ResponseType.OK)

        grid = Gtk.Grid(
            column_spacing=8,
            row_spacing=12,
            margin_top=12,
            margin_bottom=12,
            margin_start=12,
            margin_end=12,
        )
        player_lbl = Gtk.Label(label=_('Player command'), xalign=1.0)
        player_lbl.add_css_class('dim-label')
        player = Gtk.Entry()
        player.set_text(settings.get_string('player-command'))
        player.set_tooltip_text(
            _('Use %u for the stream URL, or leave it out to append the URL.'),
        )
        qual_lbl = Gtk.Label(label=_('Default quality'), xalign=1.0)
        qual_lbl.add_css_class('dim-label')
        quality = Gtk.Entry()
        quality.set_text(settings.get_string('default-stream-quality'))

        rec_dir_lbl = Gtk.Label(label=_('Recording folder'), xalign=1.0)
        rec_dir_lbl.add_css_class('dim-label')
        rec_dir = Gtk.Entry()
        rec_dir.set_text(settings.get_string('record-output-dir'))
        default_videos = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_VIDEOS) or ''
        rec_dir.set_placeholder_text(
            default_videos or _('(system Videos folder)'),
        )
        rec_dir.set_tooltip_text(
            _('Leave empty to use the XDG Videos directory.'),
        )
        rec_tpl_lbl = Gtk.Label(label=_('Recording filename template'), xalign=1.0)
        rec_tpl_lbl.add_css_class('dim-label')
        rec_tpl = Gtk.Entry()
        rec_tpl.set_text(settings.get_string('record-filename-template'))
        rec_tpl.set_tooltip_text(_('Basename only. Placeholders: {job}, {time}, {ext}'))

        cont_lbl = Gtk.Label(label=_('Recording container'), xalign=1.0)
        cont_lbl.add_css_class('dim-label')
        cont_keys = list(recording.RECORD_CONTAINER.keys())
        cont_labels = (
            _('Matroska (.mkv)'),
            _('MP4'),
            _('MPEG-TS (.ts)'),
        )
        cont_model = Gtk.StringList.new(list(cont_labels))
        rec_container_dd = Gtk.DropDown(model=cont_model)
        cur_cont = settings.get_string('record-container').strip().lower()
        if cur_cont in cont_keys:
            rec_container_dd.set_selected(cont_keys.index(cur_cont))
        else:
            rec_container_dd.set_selected(0)
        rec_container_dd.set_tooltip_text(
            _('FFmpeg muxer for Streamlink --ffmpeg-fout; must match file extension.'),
        )

        row = 0
        grid.attach(player_lbl, 0, row, 1, 1)
        grid.attach(player, 1, row, 1, 1)
        row += 1
        grid.attach(qual_lbl, 0, row, 1, 1)
        grid.attach(quality, 1, row, 1, 1)
        row += 1
        grid.attach(rec_dir_lbl, 0, row, 1, 1)
        grid.attach(rec_dir, 1, row, 1, 1)
        row += 1
        grid.attach(rec_tpl_lbl, 0, row, 1, 1)
        grid.attach(rec_tpl, 1, row, 1, 1)
        row += 1
        grid.attach(cont_lbl, 0, row, 1, 1)
        grid.attach(rec_container_dd, 1, row, 1, 1)

        area = dlg.get_content_area()
        area.append(grid)

        def on_response(_dialog: Gtk.Dialog, response: int) -> None:
            if response == Gtk.ResponseType.OK:
                pc = player.get_text().strip() or 'mpv'
                dq = quality.get_text().strip() or 'best'
                settings.set_string('player-command', pc)
                settings.set_string('default-stream-quality', dq)
                settings.set_string('record-output-dir', rec_dir.get_text().strip())
                tpl = rec_tpl.get_text().strip() or 'streamlink-gtk-{job}-{time}.{ext}'
                settings.set_string('record-filename-template', tpl)
                pos = rec_container_dd.get_selected()
                if pos != Gtk.INVALID_LIST_POSITION and pos < len(cont_keys):
                    settings.set_string('record-container', cont_keys[pos])
            _dialog.destroy()

        dlg.connect('response', on_response)
        dlg.present()

    def create_action(self, name, callback, shortcuts=None):
        """Add an application action.

        Args:
            name: the name of the action
            callback: the function to be called when the action is
              activated
            shortcuts: an optional list of accelerators
        """
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", callback)
        self.add_action(action)
        if shortcuts:
            self.set_accels_for_action(f"app.{name}", shortcuts)


def main(version):
    """The application's entry point."""
    app = StreamlinkGtkApplication()
    return app.run(sys.argv)
