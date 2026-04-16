Este directorio debe contener las ruedas PyPI generadas con:

```bash
./tools/fetch-pypi-wheels.sh
```

Se usa el módulo `python3-streamlink-wheels` del manifiesto Flatpak para instalar Streamlink **sin acceso a PyPI** durante el build (por ejemplo GNOME Builder sin DNS). En el build, `flatpak-builder` copia el **contenido** de este directorio en la raíz del módulo; `pip` usa `--find-links=file://$PWD`.

Los `*.whl` están en `.gitignore`; haz commit del script y de `requirements.txt`, y en CI o antes de empaquetar ejecuta el script con red.
