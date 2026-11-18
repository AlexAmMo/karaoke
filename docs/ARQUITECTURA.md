# Arquitectura de V1

`app.py` controla el ciclo de vida del motor y del servicio, la exclusión de instancias y las rutas separadas de instalación/datos. `service.py` aplica los casos de uso y construye el modelo de pantalla. `store.py` es la frontera persistente SQLite (WAL, transacciones y recuperación). `songs.py` valida mapas/recursos y publica paquetes mediante staging y rename. `provider.py` aísla el API fijado de Syncer en un proceso hijo; recibe credenciales por stdin y devuelve JSON.

`native/UKaraokeShell.pas` amplía el mismo proceso/ventana SDL de Deluxe. Toda manipulación de canciones, pantalla, reproductor y entradas ocurre en el hilo del motor. La biblioteca se incorpora al iniciar un turno entre interpretaciones; las búsquedas y descargas no tocan la canción activa. La zona de juego conserva su relación de aspecto. El foco de los controles intercepta teclas para evitar pausar al escribir.

## Contrato de IPC

Cada arranque crea canales limpios bajo `ipc/`. El servicio escribe `view.json`; el motor escribe `engine.json` (estado, token de turno, puntos, niveles, dispositivos y errores). Peticiones y acciones son archivos JSON independientes en `commands/` y `events/`, publicados por rename. Los tokens de turno evitan atribuir a un nuevo turno el estado anterior. Este IPC permanece privado. Al activar «Conectar móviles», el servicio abre un puerto HTTP temporal en la interfaz de red elegida. La carpeta de datos tiene permisos 0700 en POSIX.

Los procesos pueden cerrarse entre cualquier par de escrituras. SQLite preserva solicitudes; al reabrir, un turno en canto vuelve a pendiente y una preparación interrumpida vuelve a espera. Nada se reproduce automáticamente. Un trabajo puede dar servicio a varios turnos. Una cancelación de turno no borra la biblioteca ni cancela por sorpresa otros turnos de esa canción.

## Audio

El análisis de tono recibe la señal original de la captura con su ajuste de sensibilidad. El retorno usa una copia independiente con ganancia 0–1 por jugador; cero silencia solo la escucha. El volumen de música es otro control. No hay generación/separación de audio ni guardado de tomas. Las señales sintéticas solo se activan mediante el modo de prueba explícito.

La latencia de retorno depende de dispositivo/backend y tamaño de búfer; no se deduce de la capacidad del búfer. La corrección de sincronía no elimina el retraso acústico. El retorno empieza silenciado y la prueba física queda pendiente hasta disponer de micrófonos.

## Fuentes y confianza

Un mapa necesita notas válidas, audio legible y recursos dentro de su carpeta. Se rechazan escapes de rutas, dúos de partes distintas, tiempos inválidos y audio que termine antes del mapa. El hash del contenido identifica el paquete. Cada instrumental se conserva como variante de su original. Para audio obtenido de catálogos o asociado a un mapa suelto, el proceso de preparación contrasta la grabación con el mapa en tres tramos. Una comparación dudosa o un desfase impiden publicar esa combinación. Los paquetes oficiales se comprueban contra el manifiesto de su edición y los paquetes locales completos conservan las referencias a sus propios medios.

La búsqueda por enlace obtiene metadatos para localizar candidatos. Elegir un candidato conserva los medios asociados por USDB; no reutiliza el enlace como si se hubiera demostrado compatibilidad. Se distinguen error de fuente, autenticación necesaria y búsqueda sin resultados.
