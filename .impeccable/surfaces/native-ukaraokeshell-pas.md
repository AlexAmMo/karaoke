---
version: 1
slug: "native-ukaraokeshell-pas"
primary_target: "native/UKaraokeShell.pas"
related_targets:
  - "src/karaoke/service.py"
---

# Biblioteca, catálogo y sesión de canto

Mode: Operate en búsqueda, ajustes y cola. Experience en biblioteca y canto. Implementación nativa SDL/OpenGL para macOS y Windows.

THESIS: La canción elegida ocupa el escenario con su portada, título, artista y acción de encolar. Las miniaturas de la tira inferior permiten explorar la biblioteca. El panel derecho reúne las acciones de la sesión.

OWN-WORLD: Grafito, texto claro, metadatos suaves y acción principal frambuesa. La imagen validada de la grabación identifica a la canción en biblioteca, búsqueda y cola. Cuando falta imagen se dibujan iniciales sobre un color estable por artista, con el título como alternativa.

STORY: Buscar una canción, comprobar su edición y añadirla a la cola. En una fila musical, Tab y Mayús+Tab permiten recorrer detalle y botón de añadir. Comenzar el turno desde la cola y plegar con Cmd/Ctrl+B. La flecha del sistema permanece visible durante el canto. El panel conserva alimentación de audio, cola y edición al plegar.

FIRST VIEWPORT: Cabecera «Mi repertorio» y recuento. Portada grande a la izquierda, información y botón a la derecha, hasta cinco miniaturas debajo. La biblioteca vacía ofrece «Buscar canciones». En el lateral, miniaturas de 48 unidades, título y metadatos en la misma fila. Panel abierto de 340–440 puntos y acceso «Mostrar panel» al plegarlo. Canto y letra conservan el lienzo 4:3 de Deluxe.

FORM: seed: none (pinned). La solicitud «Implementa el plan» se refiere a docs/research/PLAN-CATALOGO-E-INTERFAZ.md. La ventana única y la selección por flechas conservan la continuidad del producto; el sistema de grafito con arte real define el aspecto actual.

FINISH: Revisar el escenario mínimo de 1000×640, la ventana 1280×800, Retina y Windows. Probar canto y panel con la cola activa, títulos largos, imágenes ausentes o tardías, puntero y teclado. [Medidas y controles](../../DESIGN.md) · [Evidencia con SDL y señal sintética](../../docs/validation/catalog-ui-native-macos.json)
