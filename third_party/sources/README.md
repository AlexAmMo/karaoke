# Fuentes conservadas para compilaciones reproducibles

`lua-5.5.1.tar.gz` es el archivo original de Lua, sin modificar, obtenido del [área oficial de descarga](https://www.lua.org/ftp/). Se conserva porque el servidor devolvió una respuesta distinta del archivo en una compilación de Windows y conexiones TLS interrumpidas en pruebas posteriores.

SHA-256 publicado por Lua y comprobado antes de incorporar este archivo:

```text
1c4b4068d67061f2a2231ad2b5422e77acea1487ea9890f6320af614f4373dce
```

La licencia MIT y los avisos originales están incluidos dentro del archivo fuente. `scripts/prepare_engine.py` comprueba el hash y copia este archivo a la caché de fuentes del constructor; la receta de Deluxe vuelve a verificar el mismo hash. No se cambia la versión de Lua ni se omite la comprobación de integridad.

Los dos archivos `.patch` de OpenSSL son los parches originales que solicita la fórmula de Homebrew incluida en la entrega para macOS Intel. Ambos corrigen pruebas de la biblioteca. El recolector de fuentes los acepta únicamente si coinciden con el SHA-256 de la fórmula instalada. Esta copia evita que un 503 temporal de GitHub impida distribuir las fuentes correspondientes. [Primer parche de OpenSSL](https://github.com/openssl/openssl/commit/2e2438b494e7f661be5212e4732f7fab86bf6303) · [Segundo parche de OpenSSL](https://github.com/openssl/openssl/commit/cffb97915813aeeef58ee9a0d33c05d3d45e1fe6) · [Licencia de OpenSSL](OPENSSL-LICENSE.txt)
