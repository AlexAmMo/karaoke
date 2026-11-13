# Fuentes conservadas para compilaciones reproducibles

`lua-5.5.1.tar.gz` es el archivo original de Lua, sin modificar, obtenido del [área oficial de descarga](https://www.lua.org/ftp/). Se conserva porque el servidor devolvió una respuesta distinta del archivo en una compilación de Windows y conexiones TLS interrumpidas en pruebas posteriores.

SHA-256 publicado por Lua y comprobado antes de incorporar este archivo:

```text
1c4b4068d67061f2a2231ad2b5422e77acea1487ea9890f6320af614f4373dce
```

La licencia MIT y los avisos originales están incluidos dentro del archivo fuente. `scripts/prepare_engine.py` comprueba el hash y copia este archivo a la caché de fuentes del constructor; la receta de Deluxe vuelve a verificar el mismo hash. No se cambia la versión de Lua ni se omite la comprobación de integridad.
