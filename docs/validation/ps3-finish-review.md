## verdict

1. **resolved — STORY / teclado.** `native/UKaraokeShell.pas:704` y `:834` mantienen `Focus=-12` al tomar el escenario y navegar con flechas. `.impeccable/review/ps3-focus-fixed-1000.jpg` muestra el foco en el control de plegado, sin contorno simultáneo en la portada; `docs/evidence/ps3-keyboard-focus.json` registra Right→Tab→panel y la conservación del recorrido tras plegar/reabrir. Se cierra la parada duplicada de Tab.
2. **resolved — Truth / estado final.** Las recapturas `.impeccable/review/ps3-results-1000.jpg` y `ps3-results-collapsed.jpg` muestran «Elige otra canción para seguir cantando» con la cola vacía. El código condiciona la frase del siguiente turno al estado de la cola. Se cierra el anuncio de una canción inexistente.

No se observan regresiones introducidas por este lote en las tres capturas revisadas. Evidencia del constructor: commit `6be1f3e`; motor empaquetado SHA-256 `5c24b3c387ca64081e9aacf8859f2beb9a3a2e3a25f381a12fdf8c83da87105d`.

## remaining

clear — los dos hallazgos de la revisión inicial están resueltos. Este ship cubre exclusivamente las correcciones puntuadas; no es una nueva revisión completa de la superficie. Conserva el alcance macOS Retina de la primera revisión, sin certificar Windows, micrófono físico, clic físico, accesibilidad AX ni animación temporal. No se ha operado el navegador ni modificado código de producto en esta pasada.

disposition: ship

---

## Registro de la revisión inicial

Revisión completa realizada antes del lote de correcciones, con disposición inicial `fix`. Contrato: `.impeccable/surfaces/native-ukaraokeshell-pas.md`; contexto: `PRODUCT.md`; referencias históricas: `docs/research/SINGSTAR-REFERENCIAS.md`; procedencia gráfica: `assets/theme/manifest.json`. Construcción code-led, `seed: none (pinned)`, sin comp aprobada ni tarjeta QUALITY BAR. No se ejecutó detector HTML/CSS por tratarse de SDL/Pascal nativo.

Se inspeccionaron visualmente diez capturas en `.impeccable/review/`: `ps3-library-1000.jpg`, `ps3-library-zoomed.jpg`, `ps3-collapsed-zoomed.jpg`, `ps3-settings-1000.jpg`, `ps3-singing-1000.jpg`, `ps3-singing-active-1000.jpg`, `ps3-packaged-playing-1000.jpg`, `ps3-results-1000.jpg`, `ps3-results-collapsed.jpg` y `ps3-installed-empty-1280.jpg`. Cubrían biblioteca con contenido y vacía, títulos largos, ajustes, canto activo y pausado, paquete ejecutándose, resultados y panel plegado, en escritorio macOS Retina con anchos de 1000, 1280 y 1512 puntos. La vista de resultados plegados tenía mayor altura y no se presentó como prueba del viewport 1512×831. Negro durante el canto: fixture sin vídeo y proporción conservada del motor, no captura incompleta.

### persistence

Pass: contexto, contrato y procedencia presentes. La sustitución del DESIGN verde estaba autorizada; su documentación correspondía al siguiente handoff. El camino code-led no exigía estado ni diff de comp.

### fidelity

Se revisaron THESIS, OWN-WORLD, STORY, FIRST VIEWPORT y FORM. Escenario burdeos/carmesí, selección fucsia, portada dominante, vecinos reflejados, pie claro, biblioteca vacía honesta y expansión al plegar cumplían el contrato. TYPE se aceptó como adaptación sans abierta empaquetada, sin atribuir una fuente exacta a Sony; MATERIAL y GROUND correspondían al mundo acordado. Canto 4:3 y resultados propios eran adaptaciones explícitamente admitidas. Las dos contradicciones fueron el Tab duplicado y el pie de cola vacía; ambas están resueltas en el verdict superior.

### ceiling

Sin comp ni QUALITY BAR no se certificó réplica histórica exacta. El mundo acordado estaba representado por el carrusel, escala del foco, reflejos, paleta y pie inferior. Vídeo en portada, desplazamiento animado y contador animado constaban como recursos históricos, sin convertirlos en obligaciones nuevas ni afirmar su validación temporal. No se identificaron otras infracciones visuales materiales del craft floor en las capturas examinadas.

### material_fixes

1. Resuelto: mantener el identificador de foco del escenario para eliminar la parada duplicada de Tab después de navegar con flechas o tomar foco desde el escenario.
2. Resuelto: ajustar el mensaje de resultados al estado real de la cola para no anunciar un siguiente turno inexistente.

### keep

La revisión pidió conservar portada protagonista, vecinos reflejados, paleta burdeos/fucsia, pie claro, estado vacío honesto, foco visible y expansión del escenario; las correcciones no debían alterar canto, audio ni cola. Este registro conserva la revisión inicial y no constituye una nueva inspección ni amplía el alcance del verdict final.
