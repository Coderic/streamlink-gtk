pkgdatadir = get_option('prefix') / get_option('datadir') / meson.project_name()
moduledir = pkgdatadir / 'streamlink_gtk'
gnome = import('gnome')

gnome.compile_resources('streamlinkgtk',
  'streamlinkgtk.gresource.xml',
  gresource_bundle: true,
  install: true,
  install_dir: pkgdatadir,
)

python_mod = import('python')
python_install = python_mod.find_installation(get_option('python'))

conf = configuration_data()
conf.set('PYTHON', python_install.full_path())
conf.set('VERSION', meson.project_version())
conf.set('localedir', get_option('prefix') / get_option('localedir'))
conf.set('pkgdatadir', pkgdatadir)

configure_file(
  input: 'streamlink-gtk.in',
  output: 'streamlink-gtk',
  configuration: conf,
  install: true,
  install_dir: get_option('bindir'),
  install_mode: 'rwxr-xr-x'
)

streamlink_gtk_sources = [
  'streamlink_gtk/__init__.py',
  'streamlink_gtk/job_item.py',
  'streamlink_gtk/main.py',
  'streamlink_gtk/player.py',
  'streamlink_gtk/recording.py',
  'streamlink_gtk/streamlink_backend.py',
  'streamlink_gtk/window.py',
]

install_data(streamlink_gtk_sources, install_dir: moduledir)
