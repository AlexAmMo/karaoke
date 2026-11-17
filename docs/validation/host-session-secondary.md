# Controles de la sesión y recuperación

Recorrido de la versión de desarrollo en macOS con una biblioteca temporal. Se enviaron las acciones de la vista al servicio local y se inspeccionaron las filas mostradas, las preferencias SQLite y los comandos dirigidos al motor. Para la asignación se simuló una entrada USB estéreo. El arranque nativo, el movimiento del puntero y el canto se comprueban en las pruebas de escritorio.

| Paso | Acción y resultado observado |
|---|---|
| 1 | Abrir con biblioteca y cola vacías. La primera vista es Buscar. |
| 2 | Entrar en Ajustes e introducir Ángela y José. Se guardan al confirmar cada campo y aparece el volumen de la segunda voz. |
| 3 | Abrir Micrófonos con dos participantes. Cada nombre abre su selección de entrada y aparecen las dos lecturas de nivel durante la prueba. |
| 4 | Elegir el segundo canal del dispositivo USB para José. El comando enviado indica segundo jugador, dispositivo elegido y segundo canal. |
| 5 | En Biblioteca y descargas, introducir otra carpeta y aplicar. Se crea la nueva ubicación para futuras canciones. |
| 6 | Abrir Cuenta USDB con sesión cerrada. Se muestra la opción de conectar. |
| 7 | Ir a Cola vacía. Se ofrece Buscar una canción. |
| 8 | Añadir una solicitud de preparación, simular un recurso inaccesible y añadir después una canción guardada. Empezar a cantar señala la canción disponible conservando el orden de ambos turnos. |
| 9 | Abrir el turno fallido. Se ve el motivo y la acción Reintentar. |
| 10 | Bajar ese turno. La canción preparada queda primera y el turno fallido pasa a segundo. |
| 11 | Quitar el turno fallido. La canción restante conserva su identificador. |
| 12 | Cerrar y volver a abrir. La biblioteca, la cola y los dos nombres se recuperan. El turno queda pendiente de inicio. |

Los doce pasos y las regresiones adicionales de arranque, número de cantantes, recuperación de la cola y acceso a fuentes secundarias se pueden repetir desde la raíz del repositorio con el siguiente comando.

```sh
uv run pytest -q tests/test_service.py -k 'host_secondary_workflow or first_run_search or queue_offers or open_catalogue or cancelling_turn'
```

El recorrido adicional del paquete nativo usa la canción de prueba local «Probe A». Busca desde el campo visible, añade con el control de la fila y empieza desde Cola. La prueba se ejecuta con los catálogos HTTP inaccesibles y comprueba el cursor durante el canto, al plegar y al volver a abrir el panel. [Prueba del paquete](../../scripts/smoke_desktop.py)
