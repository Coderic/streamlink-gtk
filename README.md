# StreamlinkGTK

Aplicación GTK 4 (**streamlink-gtk**) que actúa como gestor de colas para **Streamlink**: añade URLs, resuelve calidades con la API de Streamlink y lanza un reproductor externo (por defecto `mpv`). No reproduce vídeo embebido.

## Dependencias en desarrollo

- GTK 4, GObject Introspection (`python3-gobject`), herramientas de compilación y Meson.
- **Streamlink** para el mismo intérprete que ejecutará la aplicación.
- **FFmpeg** en el `PATH` para remux/captura cuando Streamlink usa `--ffmpeg-fout` (grabación a archivo). En Fedora: `dnf install ffmpeg`. El Flatpak incluye FFmpeg como módulo de compilación del manifiesto (véase abajo).

### Intérprete y Streamlink

El proyecto usa el Python del sistema con PyGObject (p. ej. `/usr/bin/python3` en Fedora). Meson está configurado para preferir ese intérprete para el lanzador `streamlink-gtk`.

Instala Streamlink para ese intérprete, por ejemplo:

```bash
python3 -m pip install --user -r requirements.txt
```

También puedes usar un entorno virtual con **`--system-site-packages`** para seguir viendo `gi`:

```bash
python3 -m venv --system-site-packages .venv
. .venv/bin/activate
pip install -r requirements.txt
```

Fijamos `streamlink==8.3.0` en [requirements.txt](requirements.txt).

## Compilar y ejecutar sin instalar en el prefijo del sistema

Tras `meson setup build` y `meson compile -C build`:

```bash
DESTDIR=/tmp/sbx meson install -C build
glib-compile-schemas /tmp/sbx/usr/local/share/glib-2.0/schemas
```

Para desarrollo rápido, con el `DESTDIR` anterior y los esquemas compilados, puedes usar:

```bash
export DESTDIR=/tmp/sbx   # ejemplo
export STREAMLINK_GTK_PKGDATADIR="$DESTDIR/usr/local/share/streamlink-gtk"
export PYTHONPATH="$STREAMLINK_GTK_PKGDATADIR"
export GSETTINGS_SCHEMA_DIR="$DESTDIR/usr/local/share/glib-2.0/schemas"
```

Luego ejecuta el script `streamlink-gtk` generado en `build/src` o el instalado bajo `DESTDIR/usr/local/bin/streamlink-gtk`.

La variable **`STREAMLINK_GTK_PKGDATADIR`** (opcional) sobreescribe la ruta de datos empaquetados (`streamlinkgtk.gresource` y el paquete Python `streamlink_gtk`) definida en tiempo de compilación.

## Preferencias

GSettings (`org.coderic.streamlinkgtk`):

- **player-command**: orden que lanza el reproductor; incluye `%u` donde debe ir la URL del stream, o deja que la app añada la URL al final.
- **default-stream-quality**: clave preferida (p. ej. `best`, `720p`) cuando exista.

En Flatpak, el reproductor se lanza en el **host** mediante `flatpak-spawn --host` (requiere `mpv` u otro binario en el host).

## Flatpak

El manifiesto [org.coderic.streamlinkgtk.json](org.coderic.streamlinkgtk.json) compila e instala **FFmpeg** en `/app/bin` (Streamlink lo invoca para muxing al grabar con `--ffmpeg-fout`). Después incluye el módulo **`python3-streamlink-wheels`**, que instala [requirements.txt](requirements.txt) con **`pip install --no-index`** y las ruedas bajo [`flatpak/pypi-wheels/`](flatpak/pypi-wheels/), **sin contactar PyPI** durante `flatpak-builder` (adecuado cuando GNOME Builder no resuelve DNS).

### Generar las ruedas (obligatorio antes de construir sin interné en el build)

Con red, en la raíz del repositorio:

```bash
./tools/fetch-pypi-wheels.sh
```

Eso ejecuta `pip download` y rellena `flatpak/pypi-wheels/*.whl` (están en [`.gitignore`](flatpak/pypi-wheels/.gitignore) y no se versionan por defecto). Sin ese paso, el módulo pip fallará al no encontrar paquetes.

En `flatpak-builder`, un source `type: dir` copia **el contenido** de esa carpeta en la raíz del módulo de build (no crea `flatpak/pypi-wheels/` en un subdirectorio extra). El manifiesto usa `--find-links=file://${PWD}` para que `pip` vea las ruedas junto a `requirements.txt`.

**ABI:** las ruedas deben corresponder al **CPython del Sdk** (p. ej. 3.13), no al `python3` del host si es distinto. El script [`tools/fetch-pypi-wheels.sh`](tools/fetch-pypi-wheels.sh) usa por defecto `--python-version "${PIP_DOWNLOAD_PYTHON_VERSION:-3.13}" --only-binary=:all:`; si tienes **org.gnome.Sdk** instalado, intenta descargar con `flatpak run … python3` de ese Sdk. Si pip se queja de `charset_normalizer` u otra dependencia, regenera las ruedas tras instalar/actualizar el Sdk o ajusta `PIP_DOWNLOAD_PYTHON_VERSION`.

Desarrollo sin Flatpak sigue siendo `pip install -r requirements.txt` en el host (sección anterior).

Permisos relevantes en el manifiesto: `--talk-name=org.freedesktop.Flatpak` y bus de sesión para lanzar el reproductor en el **host**.

## Documentación Streamlink

- [https://streamlink.github.io/](https://streamlink.github.io/)
- Repositorio: [https://github.com/streamlink/streamlink](https://github.com/streamlink/streamlink)
