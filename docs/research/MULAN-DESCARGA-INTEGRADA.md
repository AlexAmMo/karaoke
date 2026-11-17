# Descarga de la edición castellana de Mulán

Comprobación del 18 de noviembre de 2026 para «Todo un hombre haré de ti».

| Fuente | Resultado |
|---|---|
| UltraStar España | La ficha de Jaxerl identifica una edición en español de 1998 y un paquete de 44,33 MB. El sitio ofrece el TXT y el torrent por separado. [Ficha del catálogo](https://ultrastar-es.org/es/canciones?artista=Mulan) |
| Índice histórico de Hehoe | La fila exacta tiene un único enlace atribuido a UltraStar España. Se solicitó tanto ese TXT como la búsqueda del proveedor con HTTP ordinario. Ambos devolvieron 403 con una pantalla de verificación de navegador. [Índice](https://usdb.hehoe.de/) |
| AllKaraoke | La revisión fijada en Karaoke devuelve cuatro mapas al buscar «mulan». Son ediciones inglesas y francesas. «todo un hombre» devuelve cero. [Índice de grabaciones](https://github.com/Asvarox/allkaraoke/blob/978f076b8b8b6641057ba16a66693155aedc2cf2/public/songs/index.json) |
| Paquetes públicos adicionales | Revisamos los nombres de los archivos en los árboles completos de UltraStar Deluxe Songs, Songs Stream y la colección de razzertronic. Ninguno contenía Mulán o ese título. [Songs](https://github.com/UltraStar-Deluxe/songs) · [Songs Stream](https://github.com/UltraStar-Deluxe/songs-stream) · [Colección adicional](https://github.com/razzertronic/usdx-songs) |

Una prueba del selector de Karaoke con QtWebEngine y un perfil temporal sin cuenta abrió la búsqueda real dentro de la app. El catálogo mostró la fila exacta y el control «Descargar torrent». Los enlaces de torrent y TXT compartían el mismo identificador de edición. Al activar el torrent, la misma ventana llegó a la pantalla «Identificarse» del proveedor, con sus campos de usuario y contraseña. Se cerró la ventana en ese punto y el selector devolvió «cancelled». No se envió ninguna credencial ni se inició transferencia. [Resultado de la prueba](../validation/in-app-spanish-login.json) · [Página de la canción](https://ultrastar-es.org/es/canciones?artista=Mul%C3%A1n&cancion=Todo+un+hombre+har%C3%A9+de+ti)

Para esta edición, el recorrido que documenta UltraStar España requiere elegir «Descargar torrent» en su sitio y obtener los archivos del paquete mediante BitTorrent. El RSS propio de la cuenta distribuye las selecciones hechas por ese usuario. Sin una sesión de esa cuenta y sin seleccionar la edición resulta imposible demostrar una transferencia completa desde este equipo. La investigación tampoco verificó un API público de selección del tema en el RSS. [Descargas con torrent](https://ultrastar-es.org/es/ayuda/18/tutorial/8090) · [RSS de cada usuario](https://ultrastar-es.org/es/ayuda/18/tutorial/8462)

La presencia de la ficha acredita el descubrimiento. La descarga completa requiere el torrent de la edición, al menos un par que aporte los datos y la validación del paquete recibido. Para acreditar que Mulán se puede cantar desde Karaoke, la prueba de aceptación debe llegar a la cola con su mapa español y el audio del mismo paquete.
