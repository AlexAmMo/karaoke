# Buscar, preparar y cantar en una sola sesión

El 21 de noviembre de 2026 se probó la ventana SDL/Deluxe real en un Mac Apple Silicon y el mando de la misma aplicación con tres clientes independientes en Chromium y WebKit. El vídeo y el audio comercial se obtuvieron durante la prueba de catálogo. Los repositorios de pruebas conservan únicamente código, resultados y capturas de la interfaz.

| Recorrido | Resultado observado |
|---|---|
| Buscar «Alex Ubago Sigo Aqui», pulsar `+`, pausar y reanudar | Una fila y un turno. Se preparó `allkaraoke:alex-ubago-sigo-aqui`, con voz, mapa verificado y carátula. La canción terminó con 1.844 puntos de señal sintética. |
| Seguir gestionando durante el canto | Se plegó el panel, se buscó, se importó una segunda canción, se reordenó la cola y se retiró una repetición. El primer turno siguió reproduciéndose. El segundo pudo empezar tras la puntuación. Al reabrir la aplicación se conservaron las canciones. Duración total de este recorrido, 295 segundos. |
| Buscar con tres mandos | Tres sesiones de navegador separadas buscaron y reservaron turnos. Las respuestas tardías de red y una retransmisión mantuvieron abierto el menú que otro usuario estaba editando. Se comprobó la reconexión después de perder wifi y el fin de la consulta periódica tras cerrar la sala. |
| Pantalla y teclado | La ventana nativa de 1280×800 puntos se capturó en su resolución Retina de 2560×1600. En los mandos se comprobó el archivo de Instrument Sans servido por el host, el filtro y la ausencia de desbordamiento a 320 y 390 px. La confirmación de añadir preserva la fila y ofrece «Deshacer». |
| Reutilizar una preparación | En pruebas de servicio, «Solo descargar» creó un trabajo y cero turnos. Dos invitados añadieron el mismo tema obteniendo dos turnos y un trabajo. Retirar un turno preservó el otro y la descarga. |
| El archivo desaparece | Si se borra el mapa o el audio después de encolar, los clientes muestran «Copia incompleta». Desaparece el inicio de ese turno. Se comprobó la consulta «Solo descargadas» sin red. |
| Consultar una grabación generada | Una prueba con base de datos y archivos locales confirmó que una grabación aprobada se recupera por su ID de YouTube, incluso si una fuente usa otro título para el mismo vídeo. La consulta de otro ID no devuelve la grabación. |

La [captura de escritorio](sesion-nativa-2026-11-21.webp) muestra el catálogo antes de descargar. La [captura móvil](sesion-mando-2026-11-21.webp) muestra el filtro activo en una sala de prueba. Las entradas de micrófono de estas sesiones son sintéticas. Impeccable indicó diferencias de tamaño y color en elementos secundarios y una advertencia general sobre fuentes. Se comprobó la fuente realmente cargada en ambos motores de navegador y se unificaron los radios de los controles principales.

Para reproducir el recorrido en línea se usa `scripts/test_host_journey.py --launcher RUTA --output informe.json`. Para repetir las interacciones del mando, `uv run --locked --with playwright python scripts/test_remote_browser.py --channel chrome --capture build/mando` o `--browser webkit` en un entorno con ese navegador instalado. Las pruebas de regresión de descarga, filtrado y grabación exacta están en `tests/test_unified_search.py`.
