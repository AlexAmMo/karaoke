# Plan del karaoke casero con puntuación

**Estado: alcance de V1 cerrado; implementación y distribución en validación. Versión del plan: 1.1. Fecha: 13 de noviembre de 2026.**

Este documento es la referencia vigente del producto. Consolida las decisiones expresas del usuario y fija criterios de cierre para los detalles que seguían como propuestas. Las comprobaciones técnicas y los datos de publicación pendientes se enumeran al final; no son funciones opcionales ni pruebas ya superadas. La implementación de la V1 está en curso; el estado comprobado y los pendientes se registran en README.md y docs/VALIDACION.md.

Queremos una experiencia de karaoke casero parecida a SingStar: cantar con letras, barras de notas, indicación de afinación en directo y puntuación. Mientras una persona canta, otras deben poder buscar canciones y añadirlas a una lista; el sistema obtendrá automáticamente los archivos necesarios y permitirá cantarlas después, sin reiniciar el juego ni gestionar archivos a mano.

**La V1 se controla desde el PC en una única ventana: zona principal de canto y columna lateral para buscar canciones y gestionar la cola. Se canta con un micrófono convencional por cable y se escucha la voz original del cantante como referencia. La voz capturada del jugador también podrá reproducirse por los altavoces, con un control de volumen independiente.** El móvil como mando se reserva como posible ampliación; no es necesario para completar la primera versión. El móvil como micrófono queda fuera del alcance actual. **La V1 incluirá la búsqueda y elección de una pista instrumental ya existente y compatible**, manteniendo la voz original como opción por defecto y sin generar ni separar audio con IA.

La solución reunirá herramientas abiertas bajo una experiencia de uso común. **La generación de notas mediante IA queda fuera del alcance actual.** Se utilizarán mapas de notas existentes. **El despliegue elegido para la V1 es una aplicación completa instalada en el ordenador, con repositorio público en GitHub y objetivo de instalación mediante un solo comando.** El motor, la preparación de canciones y la biblioteca funcionarán localmente; **macOS y Windows están incluidos desde la V1**; quedan por concretar las versiones mínimas, las arquitecturas soportadas y el mecanismo de distribución de cada sistema.

Este documento sustituye a la propuesta inicial, que contemplaba una posible etapa de generación con IA. Las investigaciones anteriores se conservan como antecedentes locales; no son necesarias para construir la aplicación desde este repositorio.

## Estado de la validación técnica

La aplicación integrada y empaquetada supera 17 comprobaciones de sesión en macOS Apple Silicon con señales sintéticas: ventana única, canto y gestión simultáneos, incorporación de canciones entre interpretaciones, puntuaciones independientes, retorno separado, persistencia y recuperación. También se ha comprobado el selector nativo de carpetas y el arranque normal desde la aplicación instalada. El servicio tiene pruebas automatizadas en macOS, Windows y Linux. La evidencia exacta se mantiene en [Validación de la implementación](docs/VALIDACION.md).

**La fase de validación no se da por terminada.** El usuario todavía no dispone del micrófono por cable; faltan captura física, latencia de retorno, dos micrófonos, ejecución nativa en Windows, descargas autenticadas reales bajo carga y arranque/instalación en un equipo limpio. La instrucción posterior del usuario autoriza implementar la V1 completa mientras se mantienen pendientes las comprobaciones que requieren hardware o cuentas externas. Esa autorización no convierte esas pruebas en superadas.

## Alcance y criterios de cierre

| Estado | Definición |
|---|---|
| Confirmado | Decisión o necesidad expresada durante la conversación. |
| Criterio de cierre | Valor adoptado en esta revisión para concretar la V1; no se atribuye a una preferencia expresada previamente por el usuario. |
| Validación técnica | Comprobación necesaria durante el desarrollo antes de declarar una función o plataforma operativa. |
| Fuera del alcance | Función que no se desarrollará en esta etapa. |

**Confirmado:** uso doméstico; experiencia similar a SingStar; barras y puntuación real; interés en software abierto y gratuito; búsqueda amplia de canciones, incluyendo la relación con YouTube; descarga automática del material; selección de próximas canciones mientras se canta; continuidad de la sesión; una solución integrada; micrófono convencional por cable; audio con la voz original del cantante como opción base; móvil como micrófono e IA excluidos por ahora; aplicación instalada para macOS y Windows desde la V1, con biblioteca local; repositorio público en GitHub; instalación con un solo comando como objetivo de facilidad de uso.

**También confirmado para la V1:** una pantalla y una ventana con canto principal y columna lateral de búsqueda y cola; repertorio prioritario en inglés y español; reproducción de la voz del micrófono por los altavoces con volumen ajustable; buscar y elegir una pista instrumental existente y compatible, cuando esté disponible; usar Impeccable como metodología de diseño y revisión de la interfaz. La falta de instrumental para una canción no impide cantarla con voz original.

**Confirmado como experiencia:** control completo y cola desde el PC, biblioteca local persistente. **Base técnica propuesta:** UltraStar Deluxe como motor inicial; USDB como primera fuente de mapas; reutilización de USDB Syncer para obtener los recursos.

**Ampliación prevista para V2:** dos pantallas, con gestión de canciones y cola en el portátil y una vista exclusiva de canto en la TV. No es un requisito de entrega de la V1.

**Criterios de cierre adoptados para V1:**

- Uno o dos jugadores simultáneos cantan la misma melodía con entradas y puntuaciones independientes. Los dúos con partes distintas quedan fuera.
- Búsqueda por artista y título en biblioteca y catálogo; entrada adicional mediante enlace de YouTube para localizar un mapa compatible. El buscador general de vídeos de YouTube queda fuera de V1.
- USDB es el primer catálogo integrado. Se incluye importar carpetas UltraStar preparadas; otros catálogos quedan para una ampliación salvo que las pruebas demuestren que hace falta sustituir la fuente inicial para cumplir el repertorio previsto.
- Se respeta el orden de cola. Si un turno no está listo, el anfitrión decide esperar o iniciar otro preparado. El inicio tras los resultados siempre se confirma manualmente.
- Se incluye guardar canciones sin añadir un turno, recuperar la cola tras cerrar y conservar la biblioteca hasta un borrado explícito.
- Una instrumental ambigua requiere preescucha y validación explícita del anfitrión; la confirmación no sustituye las comprobaciones técnicas del paquete ni certifica automáticamente su calidad musical.
- La interfaz inicial estará en español; los títulos y letras conservarán su idioma original. Inglés y español son prioritarios para repertorio, no una obligación de traducir toda la interfaz a ambos idiomas en V1.

**Comprobaciones de implementación:** versión mínima y arquitectura soportadas, motor y composición de la ventana, recorrido de audio, compatibilidad de variantes y empaquetado. **Destino de publicación confirmado:** [AlexAmMo/karaoke](https://github.com/AlexAmMo/karaoke), aplicación «Karaoke». Los pendientes técnicos tienen responsables y momentos de resolución al final del documento; no reabren las decisiones de producto anteriores.

## La experiencia completa

### Preparar una sesión

El anfitrión abre la solución desde el PC y accede a su biblioteca, al buscador y a la sesión de karaoke. Conecta el micrófono por cable, comprueba que recibe señal, asigna el cantante y ajusta la sincronización si hace falta. Si participan dos jugadores, realiza esa comprobación por cada entrada. La zona principal de la ventana queda preparada para mostrar el juego, con la búsqueda y la cola en la columna lateral. El anfitrión prueba también la salida de su voz y ajusta su volumen sin modificar la sensibilidad usada para puntuar.

En la V1, las peticiones se introducen y gestionan desde el propio PC. No hace falta un teléfono, emparejar dispositivos ni crear cuentas de invitados. Las credenciales que pudiera exigir una fuente de canciones las gestiona el anfitrión una sola vez.

Como posible ampliación, los invitados podrían acceder al buscador y a la cola desde su teléfono mediante un enlace o código de sesión. Esta opción se conserva como idea, pero no se implementa ni se exige para validar la V1.

### Pedir y cantar canciones

| Momento | Pantalla de canto | Buscador y cola |
|---|---|---|
| Empieza la canción A | Muestra letra, notas, afinación y puntos. | Permite seguir buscando y haciendo peticiones. |
| Alguien pide B | A continúa sin interrupción. | B entra en la cola y comienza su preparación si hace falta. |
| Alguien pide C | A continúa. | C se prepara de forma independiente de su posición en la cola. |
| B termina de descargarse | A continúa con los mismos jugadores y puntuación. | B aparece como lista. |
| Termina A | Muestra los resultados. | El motor incorpora B en un momento seguro, sin reiniciarse. |
| Empieza el siguiente turno | Se inicia la canción lista que corresponda. | El resto de peticiones conserva su orden y estado. |

En la V1, todas las acciones del buscador y la cola de este ejemplo se realizan desde el PC, incluso mientras alguien canta. **Descargar no significa interrumpir ni reproducir inmediatamente.** El usuario pide un turno; la aplicación prepara sus recursos y respeta las reglas de la cola.

### Terminar y volver otro día

Las canciones descargadas correctamente permanecen en la biblioteca. Volver a pedirlas no provoca otra descarga. Se conservará también la cola pendiente para que el anfitrión pueda recuperarla o empezar una sesión nueva; una sesión interrumpida no comienza a reproducir por sí sola al abrir la aplicación.

## Canciones y mapas de notas

### Repertorio prioritario

La V1 prioriza canciones en **inglés y español**. Ambos idiomas deben estar representados en la muestra de validación, en las búsquedas y en las pruebas de letras y metadatos con acentos y otros caracteres. Esta prioridad orienta la cobertura de los catálogos; no excluye canciones de otros idiomas. La interfaz inicial estará en español. Se seleccionarán títulos concretos para las pruebas, incluyendo rap si forma parte del repertorio deseado.

### Qué necesita una canción

Una canción puntuable requiere un audio y un mapa compatible. El mapa indica las sílabas, las notas y sus tiempos. El vídeo y la carátula mejoran la presentación, pero no son imprescindibles para cantar si el audio y el mapa están completos.

La unidad de biblioteca será una **versión preparada de una canción**: artista, título, grabación concreta, mapa y recursos asociados. Un directo, una versión de estudio y una edición recortada pueden necesitar mapas diferentes. También puede haber mapas alternativos para la misma grabación.

La aplicación distinguirá entre encontrar una ficha, tener todos los archivos y haber comprobado que la canción funciona bien. Una descarga completa acredita que está preparada técnicamente; no demuestra por sí sola la calidad musical de todas sus notas.

### De dónde salen las canciones

| Fuente | Uso previsto | Alcance |
|---|---|---|
| Biblioteca ya preparada | Cantar sin volver a descargar. | Incluida. |
| USDB | Buscar mapas existentes y obtener sus recursos asociados mediante Syncer. | Primera integración de V1, sujeta a validación de acceso y cobertura. |
| YouTube | Identificar una grabación desde un enlace y obtener medios asociados a mapas o variantes compatibles. | Incluido en V1; sin buscador general de vídeos. |
| Carpeta preparada por el usuario | Importar un paquete compatible que ya contenga audio y mapa. | Incluida en V1. |
| Otros catálogos, como UltraStar España | Ampliar cobertura donde USDB no sea suficiente. | Integración posterior según demanda y posibilidades reales de acceso. |

No se presupone que un mapa encontrado en otra web pueda descargarse con Syncer: cada fuente requiere su propia integración o una importación de archivos preparada por el usuario.

### Catálogo y enlaces de YouTube

El objetivo es poder descubrir canciones sin conocer previamente el catálogo de UltraStar. Debemos conservar la diferencia entre **un resultado de YouTube** y **una canción disponible para cantar con puntuación**.

La V1 tendrá dos entradas al mismo buscador:

1. **Buscar por artista y título.** La aplicación consulta primero biblioteca y catálogos de mapas, ofrece las versiones preparables y obtiene los medios asociados a la elegida. Es el camino principal recomendado.
2. **Pegar un enlace de YouTube.** La aplicación intenta localizar un mapa compatible con esa grabación. Si la coincidencia no es suficientemente clara, muestra las versiones disponibles para que el usuario elija; no asocia silenciosamente cualquier TXT con el mismo título.

El buscador general de YouTube se aplaza. Esto no impide obtener medios de YouTube asociados a mapas ni consultar candidatos instrumentales relacionados con una canción: son operaciones de preparación, no una búsqueda general de vídeos.

Los resultados deben permitir reconocer cuatro situaciones: ya disponible, preparable con mapa, coincidencia pendiente de comprobar y sin mapa localizado. La disponibilidad en línea se vuelve a comprobar cuando se solicita la canción.

**Sin un mapa compatible, la aplicación no ofrece puntuación ni fabrica notas.** Mostrará que esa versión no está disponible y, cuando sea posible, ofrecerá otra versión de la misma canción con mapa. Esto no debe presentarse como prueba de que no exista ningún mapa en Internet: significa que no se ha localizado en las fuentes consultadas.

Un fallo de búsqueda, una fuente desconectada y una búsqueda completada sin coincidencias deben producir mensajes distintos. Un vídeo con letra tampoco se considera automáticamente un mapa de notas.

### Audio original y pista instrumental

**El modo base reproduce la canción con la voz original del cantante, para poder escucharla y usarla como referencia al cantar.** La búsqueda, selección y preparación deben priorizar versiones con esa voz y un mapa compatible. No se elimina ni se atenúa automáticamente la voz del cantante.

La V1 ofrecerá una acción para **buscar una pista instrumental existente** y una elección **Con voz original / Instrumental** antes de iniciar el turno cuando haya una alternativa compatible. La búsqueda y el selector forman parte del alcance obligatorio de la V1; la disponibilidad de una instrumental para cada canción no está garantizada. No se requiere cambiar entre ambas pistas durante la reproducción.

Las variantes deben distinguirse en la biblioteca y en la petición. Solo se ofrecerá una instrumental cuando se haya comprobado su correspondencia con el mapa, los tiempos y la estructura. No se sustituirá silenciosamente una versión con voz por una instrumental. Si una fuente solo ofrece instrumental, se indicará y el usuario podrá elegirla expresamente o buscar otra versión con voz.

La búsqueda empezará por variantes y enlaces asociados a la versión preparada y podrá consultar las fuentes de medios integradas. Un resultado con el mismo título o duración será solo un candidato: hay que comprobar que conserva la grabación de referencia, estructura, tempo, tonalidad y sincronización requeridos por el mapa. Una coincidencia ambigua se mostrará como pendiente de comprobar y permitirá una revisión con preescucha; no se ofrecerá como lista para cantar. Si la fuente no aporta suficiente información para resolverla automáticamente, la validación del anfitrión será explícita. El procedimiento concreto se validará con ejemplos reales durante el desarrollo.

La interfaz distinguirá entre búsqueda en curso, instrumental compatible disponible, candidato por revisar, ningún candidato localizado y error al consultar la fuente. Si no se encuentra una alternativa compatible, se mantiene la opción con voz original sin inventar ni sustituir pistas. La variante instrumental elegida se guardará para reutilizarla en otra sesión.

La separación de voz mediante IA queda fuera. La opción instrumental aprovechará material ya existente; no se generará a partir de la grabación original.

## Búsqueda y selección

El buscador debe funcionar por artista y título, tolerar diferencias habituales de mayúsculas y acentos y distinguir versiones. Se mostrarán primero las canciones ya preparadas, después las descargables con mapa y, finalmente, los resultados pendientes de correspondencia.

Cada resultado mostrará lo necesario para decidir: artista, título, versión, idioma si se conoce, duración si está disponible, estado de preparación y tipo de mapa. Los mapas exclusivamente de dúo con partes distintas se marcarán como no compatibles con el modo de V1. Identificará el audio como con voz original o instrumental cuando se haya comprobado; si no se conoce, no lo dará por confirmado. La selección por defecto priorizará la voz original. También debe avisar cuando el mapa tenga partes libres o limitaciones relevantes para la puntuación.

Se ofrecerá una acción principal, **Añadir a la cola**, que realizará la descarga necesaria sin un segundo proceso manual. La acción **Guardar en biblioteca** preparará repertorio sin reservar un turno de canto.

El resultado debe conservar su fuente y versión internamente, aunque el usuario no necesite ver identificadores técnicos. Los títulos parecidos no deben provocar descargas equivocadas.

## Descarga y preparación automática

### Estados visibles

| Estado | Qué significa para el usuario |
|---|---|
| Solicitada | La petición se ha registrado. |
| Comprobando recursos | Se verifica el mapa y se localizan sus medios. |
| Descargando | Se están obteniendo los archivos necesarios. |
| Preparando | Se realizan las conversiones o ajustes descritos por la fuente y se comprueba el paquete. No interviene IA. |
| Lista | Audio y mapa están completos y son compatibles con el motor. |
| Requiere atención | Hay una ambigüedad o un recurso que necesita intervención del anfitrión. |
| Error | La preparación ha fallado y se explica el motivo. |

El progreso de descarga y el estado del turno son distintos. Una canción puede estar lista en la biblioteca y tener varias peticiones de canto. Cancelar una petición no tiene por qué eliminar la canción descargada.

### Reglas de preparación

- Añadir varias peticiones inicia su preparación sin tener que esperar a que termine cada descarga para seleccionar otra.
- La misma versión de una canción se descarga una sola vez, aunque la pidan varias personas.
- El motor solo recibe paquetes completos. Los archivos parciales permanecen separados de la biblioteca utilizable.
- Audio y mapa son obligatorios. Si falla un vídeo opcional, se permite cantar con un fondo alternativo, dejando claro que falta el vídeo.
- Se prepara el audio con voz original por defecto. Cuando se elige una instrumental compatible, se descarga esa variante y se conserva cualquier versión con voz ya preparada. Un fallo de la instrumental no invalida la versión con voz; el usuario puede volver a elegirla, sin cambiar silenciosamente su petición.
- Si el vídeo era también la única fuente del audio y no se puede obtener, la canción no se considera lista.
- Los fallos ofrecen reintento o elección de otra versión; no se entra en un bucle ilimitado de descargas.
- La preparación debe limitar su consumo para proteger la reproducción y los micrófonos. La prioridad de descarga podrá favorecer los próximos turnos, sin alterar por ello su orden.
- Los archivos existentes que funcionan no se reemplazan a mitad de una canción. Una actualización se publica cuando puede aplicarse sin afectar a la sesión.

La persistencia permitirá recuperar trabajos tras una interrupción. Reanudar desde un punto parcial dependerá del descargador; si no es posible, se reiniciará únicamente la preparación afectada.

## Cola y turnos

### Qué contiene cada petición

Cada entrada tendrá canción y versión, cantante o cantantes si ya están asignados, posición y estado. El nombre de quien la pidió podrá anotarse desde el PC, sin cuentas personales. La petición también conservará la variante de audio elegida, con voz original por defecto. La descarga pertenece a la canción y su variante; el turno pertenece a la petición. Así se puede repetir una canción sin duplicar sus archivos.

### Reglas de V1

| Situación | Comportamiento |
|---|---|
| Se añade una canción | Entra al final de la cola, salvo que el anfitrión la mueva. |
| Cambia el orden de peticiones | Se actualiza la cola visible en el PC; no cambia la canción en curso. |
| Otra persona pide la misma versión | Se informa de que ya está pedida y se permite confirmar un turno adicional. |
| Se elimina una petición pendiente | Sale de la cola; la biblioteca no se borra. |
| La próxima canción no está lista | El anfitrión puede esperar o elegir continuar con otra lista. |
| Se decide continuar con otra | La petición pendiente permanece visible y pendiente; no se elimina ni pasa a completada. |
| Termina una canción | Se muestran resultados antes de iniciar el siguiente turno. |
| Se necesita detener la canción actual | El anfitrión usa un control explícito para detenerla o saltarla. |

Se respeta el orden solicitado. Si la siguiente no está lista, se espera a que el anfitrión elija continuar con otra o mantener la espera. El turno omitido conserva su posición relativa entre los pendientes; cuando se prepara, vuelve a ser elegible según ese orden. No se salta automáticamente ni interrumpe una canción ya iniciada.

El anfitrión confirma el inicio del siguiente turno después de los resultados, para dar tiempo a pasar los micrófonos. La V1 no incorpora avance automático ni cuenta atrás entre turnos.

## Canto y puntuación

La pantalla principal mostrará letras sincronizadas, notas objetivo en forma de barras, la afinación detectada de cada cantante y la puntuación durante la canción. El audio reproducirá por defecto la voz original como referencia, mientras la evaluación utilizará la entrada del micrófono del jugador. Al terminar, mostrará el resultado por jugador. La presentación debe poder leerse desde la distancia habitual del salón.

La puntuación reutilizará el comportamiento del motor elegido y comparará la entrada del micrófono con el mapa. No se presentará como una evaluación completa de dicción, expresividad o técnica vocal. Tampoco se prometerá reconocer que el cantante pronuncia correctamente todas las palabras.

Para rap y partes libres, el producto debe distinguir la presencia de letra de la existencia de notas puntuables. En algunos mapas de Eminem, por ejemplo, las partes rapeadas están marcadas como freestyle. El formato y el motor determinan qué se evalúa; no se inventará una puntuación de afinación donde el mapa no la proporciona.

### Jugadores y micrófonos

La V1 admite uno o dos cantantes simultáneos, cada uno con entrada, afinación y puntuación independientes. Ambos cantan la misma melodía del mapa. Los dúos con partes diferentes quedan fuera de V1. Se probará primero una voz y después dos, sin dar por completado el alcance con una sola.

Se utilizará un micrófono convencional por cable, sin exigir una marca específica. La configuración debe permitir seleccionar dispositivo y canal, ver el nivel de señal y asociarlo al jugador. El conector y cualquier adaptador o interfaz necesarios se concretarán con el equipo de despliegue. Dos voces mezcladas en una sola señal no se tratarán como dos jugadores independientes.

**El móvil como micrófono queda excluido de esta etapa.** El móvil como mando también se aplaza fuera de V1, aunque se conserva como posible ampliación independiente del audio.

### Escuchar la voz del jugador por los altavoces

La V1 incluirá reproducción local en directo del micrófono junto con la canción. El control **«Volumen de mi voz»** ajustará cuánto se escucha la voz del jugador; el volumen de la canción tendrá un control independiente. No permite separar ni ajustar únicamente la voz del artista dentro de una grabación mezclada.

- El slider actúa sobre la salida del micrófono, después de separar la señal destinada al detector de tono. No cambia la ganancia de captura, la calibración ni los parámetros de puntuación.
- Ponerlo a cero o utilizar **«Silenciar mi voz»** silencia únicamente esa reproducción: el jugador puede seguir cantando y puntuando. El cambio será continuo, sin reiniciar el audio ni la canción.
- En el modo de dos jugadores, cada micrófono tendrá su control independiente, identificado por el nombre del jugador.
- La primera configuración permite activar la escucha y subirla desde cero mientras se prueba el micrófono. Se conservará el nivel elegido; un cambio de dispositivo exigirá comprobar de nuevo la salida antes de recuperar ese nivel.
- La mezcla se dirige al dispositivo de salida seleccionado para la canción. La aplicación debe evitar saturación digital al sumar música y voces, mostrar el nivel de entrada y ofrecer un silencio inmediato. Estos controles no garantizan eliminar los acoples acústicos.
- La prueba real debe comprobar que los altavoces no provocan acoples ni que la voz del artista se puntúe de forma sistemática cuando el jugador permanece en silencio. La posición y volumen del micrófono y los altavoces forman parte de la configuración.
- El retorno solo está activo durante el canto o una prueba explícita de micrófono; no se mantiene al cerrar la sesión. No se graban actuaciones en archivos.

**Validación técnica pendiente:** medir el retardo entre micrófono y altavoces y comprobar que permite cantar cómodamente en macOS y Windows mientras se descargan canciones. Ajustar el desfase de las notas puede corregir la evaluación temporal, pero no elimina el retardo con el que se oye la voz. No se promete latencia cero ni el mismo resultado con cualquier dispositivo. Se usarán salidas cableadas como referencia de prueba; la monitorización directa de una interfaz externa puede ser alternativa, pero no sustituye por sí sola el slider solicitado dentro de la aplicación.

Deluxe expone una opción de reproducción del micrófono, pero eso no acredita la calidad ni el control requerido para nuestra integración. El código consultado de su backend PortAudio selecciona por defecto una latencia de entrada conservadora; existen antecedentes de problemas de retorno. Debemos comprobar la versión y backend usados, y adaptar el recorrido de audio o revisar el motor si no satisface la experiencia. [Opciones de Deluxe](https://github.com/UltraStar-Deluxe/USDX/blob/master/game/languages/English.ini), [backend PortAudio](https://github.com/UltraStar-Deluxe/USDX/blob/master/src/media/UAudioInput_Portaudio.pas). La documentación de UltraStar Play también distingue calibración y reproducción del micrófono y recomienda modos de baja latencia para esta última; sirve como referencia del problema, no como prueba de Deluxe. [Configuración de micrófonos](https://ultrastar-play.com/learn/microphones-and-speakers).

## Diseño visual y experiencia con Impeccable

**Impeccable será la metodología de diseño, implementación y revisión de la interfaz.** El objetivo es una aplicación agradable, coherente y fácil de manejar durante una sesión real de karaoke. El diseño debe facilitar las acciones y permitir detectar y corregir problemas; no se considerará suficiente una maqueta atractiva sin estados reales ni pruebas de interacción.

### Dirección y prioridades

El control de biblioteca, búsqueda, preparación y cola tendrá un enfoque de herramienta: jerarquía clara, acciones reconocibles, navegación estable y poco esfuerzo para entender qué está sonando y qué viene después. La pantalla de canto dará prioridad a letras, notas y afinación, con elementos legibles a distancia y un fondo que no compita con ellos.

La dirección estética se definirá antes de implementar las pantallas, utilizando el contexto de este plan. Colores, tipografías, iconos, espaciado y componentes formarán un sistema consistente. La elección visual respetará la ventana única de V1 y no introducirá funciones nuevas. La composición se revisará con Impeccable antes de implementar las pantallas.

### Aplicación de las capacidades de Impeccable

Se considerará el conjunto de capacidades de la habilidad y se aplicará cada una según su propósito y las necesidades de la pantalla. Las acciones de intensificar y suavizar el diseño son alternativas según el problema observado, no cambios obligatorios que deban ejecutarse sucesivamente.

| Capacidades | Aplicación en el karaoke |
|---|---|
| `init` y `shape` | Registrar el contexto de producto y concretar flujos, estados y composición antes de escribir la interfaz. Reutilizar las decisiones ya confirmadas. |
| Flujo de diseño nuevo y `document` | Definir y mantener la dirección visual; documentar el sistema que finalmente se implemente. |
| `layout`, `typeset` y `extract` | Jerarquía de información, tipografía legible y componentes reutilizables para canciones, turnos, progreso y controles. |
| `colorize` | Color coherente para acciones, jugadores y estados, acompañado de texto o formas cuando comunique información. |
| `clarify` y `distill` | Etiquetas claras y controles sencillos; distinguir canción, mapa, variante de audio, descarga y turno sin mostrar detalles técnicos innecesarios. |
| `onboard` | Primera sesión, selección del micrófono y biblioteca vacía con un siguiente paso comprensible. |
| `harden` | Estados de carga, ausencia de resultados, descargas fallidas, candidatos incompatibles, nombres largos y recuperación de acciones. |
| `adapt` | Tamaños de la ventana única, zoom y legibilidad simultánea del canto y la columna lateral. No convierte el móvil en requisito de V1. |
| `animate` y `delight` | Movimiento y respuesta visual que ayuden a entender acciones y resultados, sin distraer del canto ni perjudicar el audio. |
| `bolder`, `quieter` y `overdrive` | Ajustar expresividad solo cuando mejore la dirección elegida; evitar efectos que dificulten leer notas, letras o controles. |
| `critique` y `audit` | Revisar usabilidad, coherencia, accesibilidad, adaptación a pantalla y calidad técnica sobre la interfaz implementada. |
| `optimize` y `polish` | Corregir problemas de rendimiento y defectos finales de presentación e interacción. |
| `live` y `generate` | Comparar o generar alternativas de elementos concretos si se implementa una interfaz web y esa exploración ayuda a resolver una decisión de diseño. |

Las referencias y herramientas aplicables se cargarán al realizar cada tarea. Impeccable está actualizado a la versión 4.9.0; la documentación de la habilidad se encuentra en [Impeccable SKILL.md](/Users/ton/.agents/skills/impeccable/SKILL.md).

### Requisitos de interacción y legibilidad

- El estado de la canción actual y de la cola debe permanecer comprensible mientras se busca o prepara otra canción.
- Los controles de parar, saltar o borrar deben distinguirse de añadir y seleccionar, para evitar interrupciones accidentales.
- La interfaz debe poder operarse con teclado y ratón, mostrar el foco y ofrecer alternativas a arrastrar para reordenar turnos.
- Los estados no dependerán solo del color. Texto, iconos y contraste deben permitir entenderlos con facilidad.
- Los títulos largos, nombres con acentos y caracteres de otros idiomas no deben romper la composición ni ocultar las acciones principales.
- La selección de audio debe dejar claro qué se oirá: voz original por defecto o instrumental compatible elegido expresamente.
- Cada error debe explicar qué ha fallado y ofrecer una acción útil: reintentar, elegir otra versión o seguir con una canción lista.
- Las animaciones decorativas deben respetar la preferencia de movimiento reducido; el movimiento esencial de las notas seguirá siendo funcional y legible.

### Verificación visual y funcional

La revisión se realizará sobre pantallas ejecutables y contenido representativo, incluyendo carga, errores y casos extremos. Se hará una primera inspección agrupada de las superficies y tamaños soportados, una corrección conjunta de los defectos encontrados y una ronda de confirmación visual. Se repetirán comprobaciones cuando nuevos cambios o defectos sin resolver lo justifiquen. Las pruebas funcionales comprobarán también navegación, cola y selección de variantes de audio.

Se utilizarán los detectores de Impeccable cuando correspondan a la tecnología elegida. Una comprobación automática no sustituye la inspección visual ni la prueba de una sesión. La entrega deberá resolver los defectos conocidos que bloqueen las tareas principales y documentar las limitaciones restantes; no se prometerá una ausencia absoluta de errores sin verificación.

## Pantallas y control de la sesión

| Superficie | Funciones |
|---|---|
| Pantalla de canto | Canción actual, letras, barras, afinación, puntuación, resultados y próximo turno. |
| Buscador y biblioteca | Encontrar canciones, distinguir versiones, añadir peticiones y preparar repertorio. |
| Cola | Consultar posiciones y progreso; mover o eliminar peticiones desde el PC. |
| Panel del anfitrión | Gestionar jugadores y micrófonos; iniciar, pausar, reanudar o detener el canto; resolver descargas y controlar la sesión. |

### V1: una pantalla y una ventana

La zona principal ocupa la mayor parte de la ventana y muestra vídeo o fondo, letras, barras, afinación y puntuación. A su derecha, una columna reúne el buscador, los resultados y la cola. Las superficies de la tabla son regiones o vistas de esta misma aplicación, no ventanas independientes.

La búsqueda se sitúa en la parte superior del lateral; los resultados tienen su propio desplazamiento. La cola conserva una región visible con el próximo turno y el estado de las descargas. Se podrá ajustar el reparto vertical para consultar listas largas sin desplazar ni cubrir el canto. Los controles compactos de reproducción, volumen de canción y volumen de voz permanecen accesibles.

Buscar, escribir, añadir, reordenar y descargar no pausa la canción ni tapa las letras o las barras. Cuando el foco esté en el buscador, las teclas de escritura no dispararán atajos del juego. Los errores y progresos habituales se muestran en el lateral sin diálogos que interrumpan el canto.

La columna tendrá un ancho acotado y el canto conservará un tamaño mínimo legible. El ancho mínimo soportado de la ventana se fijará con un prototipo y los equipos objetivo; no se resolverá una ventana demasiado pequeña encogiendo indefinidamente las letras. Se permitirá plegar voluntariamente el lateral para dar más espacio al canto y reabrirlo conservando búsqueda y cola. El modo habitual mantiene ambas zonas visibles.

### V2: portátil y TV

La ampliación prevista separará la gestión en el portátil de la vista de canto en una TV. La TV mostrará la canción, las letras y las ayudas de canto —barras, afinación y puntuación—, sin buscador ni cola de gestión. El portátil permitirá preparar y ordenar los siguientes turnos. Esta vista no equivale a duplicar toda la ventana del portátil.

En V1 se separarán el estado de sesión y su presentación para facilitar esa ampliación, pero no se implementarán todavía una segunda ventana, selección de monitor ni transmisión inalámbrica. La conexión a la TV y el destino del audio se concretarán en V2.

El anfitrión es quien maneja el PC y controla reproducción, orden y configuración. Otras personas pueden pedirle canciones o utilizar ese mismo control; no se requiere una interfaz separada de invitados, cuentas personales ni un sistema de permisos para la V1.

El buscador, la cola y la pantalla de canto deben reflejar el mismo estado. La sincronización entre mandos de distintos dispositivos, su emparejamiento y los permisos de invitados solo se definirán si se incorpora el control móvil posteriormente.

## Biblioteca y continuidad

La biblioteca conservará en el equipo los archivos preparados y su relación con la versión y fuente, separada de los archivos de instalación para que actualizar la aplicación no elimine canciones. Se ofrecerá una carpeta predeterminada de datos de usuario y se permitirá elegir otra al configurar la biblioteca; las rutas concretas se fijarán al empaquetar. Los archivos permanecerán hasta que el usuario los borre expresamente. No habrá borrado automático para liberar espacio ni copias en la nube en V1. Si falta espacio, se detendrá la preparación afectada con una explicación, sin borrar canciones existentes.

Como valor inicial, el vídeo se descargará hasta 720p cuando la fuente lo permita, con opción de elegir otra calidad o preparar solo audio y mapa. No se aumentará artificialmente la resolución ni se volverán a descargar canciones existentes al cambiar esa preferencia. La calidad de audio se elegirá sin transcodificaciones innecesarias y sin alterar los tiempos del mapa.

Se permitirá consultar el estado de una canción, volver a comprobar recursos, importar paquetes preparados y retirar canciones que ya no se quieran conservar. El borrado de archivos será una acción distinta de quitar una petición de la cola y no podrá eliminar una canción que se esté utilizando en ese momento.

Las canciones completas deben poder cantarse sin acceso a Internet desde los archivos guardados en el equipo. La búsqueda remota, la obtención de nuevas canciones y las actualizaciones sí necesitan acceso a sus fuentes. No se requerirá un servidor propio remoto ni una sesión en una web alojada para utilizar el repertorio ya preparado.

Un problema con YouTube o un catálogo no debe inutilizar la biblioteca preparada. Si se cierra inesperadamente la aplicación, se conservarán biblioteca y peticiones; no se promete continuar una interpretación en el segundo exacto donde se interrumpió.

## Arquitectura propuesta

La integración tendrá una experiencia común aunque internamente utilice varios componentes. No se exige fusionar todos los proyectos en un único ejecutable. En la V1, la interfaz, el motor de canto, el gestor de preparación y la biblioteca se ejecutarán en el ordenador del usuario. La aplicación arrancará y cerrará sus componentes auxiliares sin exigir que el usuario abra cada herramienta por separado.

| Componente | Responsabilidad |
|---|---|
| Interfaz común | Ventana única con zona de canto y columna lateral de búsqueda, cola y preparación; controles de sesión y volúmenes. |
| Servicio de biblioteca y cola | Mantener versiones, peticiones, orden y estado persistente. |
| Adaptadores de fuentes | Consultar catálogos y relacionar mapas con recursos concretos. |
| Gestor de preparación | Ejecutar descargas, conversiones y validaciones fuera del proceso de canto. |
| Motor de canto y audio | Reproducir, capturar micrófonos, dibujar notas y calcular puntos; mezclar la voz del jugador con volumen independiente y baja latencia. |
| Puente de control | Comunicar al motor qué canciones completas puede incorporar y qué turno debe iniciar; recibir inicio, final y errores. |

**Base técnica propuesta:** UltraStar Deluxe para canto; USDB Syncer para la fuente USDB; yt-dlp y FFmpeg para las operaciones de medios que necesiten los proveedores. Se fijarán versiones reproducibles al comenzar la implementación.

La elección de Deluxe queda condicionada a tres pruebas: importar una canción nueva entre partidas sin reiniciar ni perder jugadores; integrar canto y lateral en una ventana; y reproducir el micrófono con volumen independiente y latencia adecuada. Se comprobarán en macOS y Windows, incluyendo el modo de dos jugadores. El servicio externo mantiene identificadores estables; no usa la posición de una canción en una lista del juego como identidad permanente.

Los nuevos paquetes se registran en un momento seguro entre canciones. El motor no reconstruye su biblioteca mientras la partida está usando sus datos. Los comandos se procesan de forma ordenada y los reintentos no pueden iniciar dos veces un turno ni registrar dos veces una canción.

La integración se apoyará en una comunicación explícita entre componentes. Simular pulsaciones de teclado no será la base del funcionamiento definitivo. Se buscará conservar el motor de canto existente. Además de importación, control y eventos de sesión, la ventana única y la mezcla del micrófono pueden exigir cambios en presentación y audio. No se presupone que integrar una ventana nativa de Deluxe dentro de otra interfaz sea sencillo o portable: se probará una composición real en macOS y Windows antes de elegir el contenedor de la aplicación. Dos ventanas colocadas una junto a otra no cumplen el requisito de V1.

Separar la interfaz de la lógica de biblioteca y cola permitirá valorar un mando móvil más adelante. Esta posibilidad no obliga a construir acceso remoto, emparejamiento ni interfaces de invitados en la V1. Cualquier comunicación auxiliar necesaria para esta primera versión quedará dentro del equipo.

Si la prueba muestra que Deluxe exige cambios desproporcionados, se revisará el motor antes de construir el resto de la experiencia. El comportamiento solicitado seguirá siendo el criterio de elección.

## Instalación y distribución

### Experiencia de instalación

El objetivo es ejecutar **un solo comando documentado para cada sistema: macOS y Windows**, obtener una versión publicada y dejar la aplicación lista para abrir desde su icono. El usuario no tendrá que clonar el repositorio, compilar código ni instalar y configurar por separado Deluxe, Syncer, Python, Node o FFmpeg para usarla.

La instalación incorporará o resolverá automáticamente las dependencias necesarias, identificará la arquitectura del equipo y comprobará que se han instalado los componentes de la misma versión. El mecanismo podrá ser un gestor de paquetes o un instalador automatizado, según la plataforma. Si depende de una herramienta previa, ese requisito se hará explícito y se ofrecerá un instalador directo como alternativa.

Los scripts de instalación por usuario y sus comandos están documentados en [Construcción y distribución](docs/PACKAGING.md). Descargan paquetes de GitHub Releases y verifican su SHA-256; solo funcionan para versiones cuyos archivos estén publicados. Un comando de instalación no elimina los permisos normales del sistema, como autorizar el micrófono al abrir la aplicación por primera vez. La firma del paquete y esos avisos se validarán por separado en macOS y Windows.

### Cobertura de macOS y Windows desde la V1

Ambos sistemas forman parte de la primera entrega, con las mismas funciones principales: micrófono por cable, barras y puntuación, búsqueda de mapas y variantes compatibles, preparación en segundo plano, cola y biblioteca local. No se considerará terminada la V1 si solo uno de ellos dispone de un paquete instalable y probado.

El comando y el formato del paquete podrán ser distintos en cada sistema. Quedan pendientes las versiones mínimas y la matriz de arquitecturas: se evaluarán macOS Apple Silicon e Intel y Windows x64; Windows ARM no se presupone incluido. La cobertura definitiva dependerá de la compatibilidad de todos los componentes y se documentará antes de cerrar la distribución.

Se prepararán procesos de construcción y paquetes por plataforma, junto con pruebas de instalación limpia, permisos y captura de micrófono, reproducción y sincronización, descarga durante el canto, rutas con espacios o caracteres especiales y actualización que conserve los datos. Las pruebas de construcción automática no sustituirán la validación de audio con un micrófono real en ambos sistemas.

### Primer arranque y uso habitual

1. Abrir la aplicación desde el icono instalado.
2. Autorizar y seleccionar el micrófono por cable, comprobar señal y calibración y ajustar la escucha de la propia voz por los altavoces.
3. Confirmar la carpeta de biblioteca y, si una fuente lo exige, configurar su acceso desde la aplicación.
4. Buscar una canción, elegir la variante con voz original o una instrumental compatible y añadirla a la cola.
5. Dejar que la aplicación reúna el mapa y los medios, los prepare y los conserve para próximos usos.

No se incluye una biblioteca masiva en el instalador. Se descargan las canciones solicitadas, y la V1 conserva la posibilidad de seguir cantando mientras se preparan las siguientes. La interfaz puede utilizar tecnologías web dentro de una ventana de escritorio, sin depender de streaming para reproducir los archivos ya descargados.

### Repositorio público y versiones

El repositorio público de GitHub contendrá el código propio, los cambios o referencias reproducibles de los componentes reutilizados, las instrucciones de desarrollo, los scripts de construcción e instalación y las pruebas. Se distribuirán versiones identificables con paquetes preparados para las plataformas soportadas, instrucciones de instalación y notas de cambios.

La biblioteca del usuario, las credenciales de las fuentes y los archivos temporales de descarga permanecen fuera del repositorio. Se conservarán las licencias y atribuciones de los componentes distribuidos. La publicación del código no significa incluir canciones comerciales en las releases.

El repositorio público [AlexAmMo/karaoke](https://github.com/AlexAmMo/karaoke) está creado y contiene la implementación. La primera release forma parte de la entrega; su disponibilidad y plataformas se comprueban en la sección Releases. Una compilación de desarrollo no implica que se hayan superado todas las validaciones de una V1 estable.

### Actualización y conservación de datos

Las actualizaciones de la aplicación y de sus descargadores deben conservar biblioteca, configuración y cola guardada. La V1 permitirá actualizar mediante el mismo mecanismo de instalación, sin pasos manuales para cada componente. No se aplicará una actualización mientras haya una sesión de canto activa. Un actualizador dentro de la interfaz podrá incorporarse después. Una instalación interrumpida debe permitir reintentar sin borrar datos ni dejar una combinación de componentes incompatible.

Desinstalar la aplicación y borrar la biblioteca serán operaciones separadas. Se documentará cómo conservar o retirar los datos. No se requiere contratar alojamiento para ejecutar el servicio: el trabajo ocurre en el PC, y GitHub sirve como repositorio y canal de distribución.

El paquete local de macOS Apple Silicon mide aproximadamente **192 MB descargados y 412 MB instalados, sin canciones**; sus bibliotecas requieren macOS 26. El inventario exacto está en [la evidencia de empaquetado](docs/validation/packaging-macos.json). Estas cifras no se extrapolan a Windows ni Mac Intel. La biblioteca se presupuestará aparte según número de canciones, duración y calidad de vídeo.

## Condiciones de calidad

- **Continuidad:** buscar, añadir o descargar no corta la canción ni reinicia el motor.
- **Coherencia:** la cola y los estados coinciden en todas las superficies de control.
- **Claridad:** no se anuncia como lista una canción que todavía no tiene audio o mapa utilizables.
- **Recuperación:** los errores de una petición no bloquean las demás ni borran la biblioteca.
- **Audio:** la carga de preparación no debe degradar captura, sincronización ni reproducción de la voz del jugador. El slider de retorno debe funcionar sin alterar la señal que se evalúa.
- **Composición:** canto, búsqueda y cola deben funcionar dentro de la misma ventana; letras y barras siguen visibles durante la gestión del lateral.
- **Referencia vocal:** las canciones con voz original son el caso principal de uso y prueba. Deben conservar esa voz durante la preparación; la ausencia de una instrumental no limita la experiencia base.
- **Uso sencillo:** durante una sesión normal no hace falta abrir Syncer por separado, copiar TXT, mover carpetas o usar una terminal.
- **Reutilización:** una canción preparada vuelve a estar disponible sin descargarla de nuevo.
- **Mantenimiento:** los proveedores de medios pueden actualizarse cuando cambien las fuentes externas sin rehacer la experiencia de canto.
- **Coste:** funcionamiento sin suscripción propia, servidor contratado ni APIs de pago obligatorias para el usuario. Los costes de hardware y almacenamiento son independientes. La firma y distribución de instaladores se evaluarán antes de publicar; no se presupone que todos los mecanismos de publicación carezcan de coste.

Los objetivos numéricos de latencia, duración de descargas y capacidad no se fijan antes de conocer el equipo, la red y las fuentes. La validación funcional sí exige comprobar la experiencia completa en condiciones simultáneas de canto y descargas.

## Qué queda fuera

| Función | Decisión actual |
|---|---|
| Generar mapas de notas con IA | Excluida. |
| Transcribir letras con IA | Excluida. |
| Separar automáticamente voz e instrumental con IA | Excluida. |
| Móvil como micrófono | Excluido de esta etapa; se utiliza micrófono por cable. |
| Dos pantallas con gestión en portátil y canto en TV | Ampliación prevista para V2; V1 utiliza una ventana con columna lateral. |
| Móvil como mando, acceso por enlace o código y control de invitados | Posible ampliación, aplazada fuera de V1. |
| Crear pistas instrumentales o garantizar que existan para todas las canciones | Excluido. Buscar y elegir una instrumental existente y compatible sí forma parte de la V1. |
| Crear un editor completo de mapas | Excluido; se podrán importar paquetes preparados externamente. |
| Reproducir cualquier vídeo sin mapa como karaoke sin puntuación | Fuera de V1; no sustituye la experiencia de SingStar solicitada. |
| Buscador general de vídeos de YouTube | Aplazado; V1 incluye búsqueda en catálogo y entrada por enlace. |
| Dúos con partes distintas, más de dos jugadores y avance automático entre turnos | Fuera de V1. |
| Garantizar cualquier canción de YouTube | No es un compromiso posible con mapas existentes y fuentes externas. |
| Descargar automáticamente todo un catálogo | No es necesario para el concepto; se prepara lo solicitado. |
| Reescribir el detector de tono o el sistema de puntuación | Excluido mientras el motor existente cumpla los requisitos. |
| Grabación de actuaciones, retransmisión, rankings en línea y cuentas sociales | Fuera del alcance actual. |
| Servicio alojado para cantar por streaming desde una URL | Fuera de la V1 elegida; se entrega una aplicación instalada con archivos locales. |

La IA no forma parte de las fases de trabajo que siguen. Se podría reconsiderar en otra revisión de alcance, si la experiencia real demuestra que faltan canciones importantes.

## Plan de trabajo

### Fase 1 Preparar el repertorio de validación

Tomar este alcance cerrado como referencia y preparar una lista de 30–50 canciones en inglés y español para comprobar cobertura, incluyendo rap y versiones de distinta estructura. Se partirá de una selección de trabajo que el usuario podrá ajustar con sus favoritas; no es necesario esperar a recibir todos los títulos para comenzar. El resultado no se tratará como una estadística universal.

Para cada canción, registrar mapa localizado, versión disponible con voz original, recursos accesibles y posibilidad de automatizar la preparación. Anotar instrumentales compatibles cuando existan, sin convertir su ausencia en un fallo de cobertura. La muestra debe cubrir expresamente canciones en inglés y español, ambos prioritarios, y rap si Eminem representa el repertorio esperado. Se registrará la cobertura por idioma para no ocultar carencias de uno con los resultados del otro.

**Resultado:** lista reproducible de canciones, cobertura por idioma y casos de error o ambigüedad. Si USDB no permite cumplir el recorrido previsto, investigar una fuente alternativa y documentar la decisión antes de ampliar la integración; la generación de notas permanece fuera del alcance.

### Fase 2 Concretar la compatibilidad y la distribución

Concretar las versiones mínimas y arquitecturas de macOS y Windows, el tamaño mínimo de la ventana única y su lateral, la conexión del micrófono, la salida de altavoces y la carpeta de biblioteca en cada sistema. Fijar propietario y nombre del repositorio público, formatos de release y mecanismo de instalación con un comando para cada sistema. El procesamiento y los datos de uso permanecen en el ordenador.

**Resultado:** matriz de compatibilidad, entornos de pruebas y estrategia de distribución para macOS y Windows. La comprobación del paquete se ejecutará junto con la prueba técnica siguiente; no se pospondrá todo el riesgo de instalación hasta el final. Los datos del repositorio remoto no bloquean estas pruebas locales.

### Fase 3 Validar integración, ventana única y audio en directo

Preparar una prueba mínima con Deluxe: cantar A, incorporar B mientras la sesión sigue abierta y cantar B a continuación. Comprobar importación entre canciones, conservación de jugadores, puntuación, biblioteca y ausencia de duplicados.

Repetir con un archivo inválido, varias incorporaciones y las entradas de micrófono previstas. La primera prueba puede usar paquetes ya preparados; después se conecta una descarga real para comprobar el recorrido completo.

La prueba incluirá una zona de canto y un lateral interactivo dentro de una misma ventana en ambos sistemas. Verificar foco de teclado, redimensionado y continuidad del canto al buscar o mover la cola. Esto resolverá si la interfaz debe integrarse dentro del motor o mediante otra composición técnicamente viable.

Probar también micrófono → puntuación y micrófono → mezcla de salida, con slider independiente y silencio del retorno. Medir latencia y estabilidad con descargas simultáneas, comprobar saturación, acoples y captación de la voz original por el micrófono. Registrar equipo, backend, ajustes y resultados. No dar por resuelto el retorno porque exista una opción similar en Deluxe.

**Resultado:** decisión fundamentada de conservar Deluxe, adaptar presentación/audio o cambiar de motor antes de invertir en la integración completa. Importación, ventana única y monitorización de voz deben superar la prueba.

### Fase 4 Construir el recorrido completo con mapas existentes

Integrar biblioteca, búsqueda USDB, peticiones, preparación automática, estados y control del siguiente turno. Diseñar e implementar con Impeccable la ventana única, el canto principal, la columna lateral y los controles independientes de volumen. Resolver persistencia, duplicados y cancelación. Priorizar y reproducir las versiones con voz original. Incluir la búsqueda, comprobación y selección de instrumentales existentes compatibles, manteniendo explícitos los casos de ausencia y coincidencia dudosa.

**Resultado:** una sesión utilizable en la que se buscan y descargan nuevas canciones mientras otras se cantan, con barras y puntuación, sin reiniciar ni gestionar archivos manualmente.

### Fase 5 Completar entrada por enlace y correspondencia con mapas

Implementar la entrada por enlace de YouTube y la búsqueda de su correspondencia con mapas existentes. Mostrar alternativas y ausencia de mapas sin confundirlas con disponibilidad para jugar. No incorporar el buscador general de vídeos ni nuevos catálogos como trabajo accesorio de esta fase.

**Resultado:** el usuario puede partir del descubrimiento de una canción, además del catálogo de mapas, con una respuesta clara sobre qué versión puede cantar.

### Fase 6 Validar una sesión real y completar la entrega

Probar el repertorio con voz original, los turnos y el micrófono por cable con el despliegue acordado. Incluir búsquedas y descargas simultáneas desde el lateral, cambios de foco entre controles y canto, redimensionado de la ventana, reproducción del micrófono y ajuste de su volumen, recuperación de la aplicación, pérdida de Internet y recursos no disponibles. Probar repertorio en inglés y español. Verificar la búsqueda y selección de instrumentales con candidatos compatibles, incompatibles y no disponibles, sin exigir que existan para todas las canciones. Realizar las revisiones de usabilidad, accesibilidad, rendimiento y acabado de Impeccable y completar las instrucciones mínimas de uso, diagnóstico y recuperación.

Construir y publicar los paquetes de macOS y Windows en el repositorio público definido en la fase 2. Probar el comando de cada sistema en un entorno sin herramientas de desarrollo, el arranque desde el icono, la actualización con canciones existentes y la recuperación de una instalación fallida. Medir tamaño real del paquete y de la aplicación instalada, documentar requisitos previos inevitables y conservar los avisos y condiciones de las licencias de los componentes distribuidos.

**Resultado:** solución completa según el alcance validado y los criterios de aceptación siguientes. El calendario se estimará tras medir el trabajo de integración y empaquetado en las pruebas iniciales.

## Criterios de aceptación

| Prueba | Resultado exigido |
|---|---|
| Cantar una canción preparada | Se ven letra, barras y afinación; la puntuación responde a la voz conforme al mapa. |
| Usar la V1 sin teléfono | Toda la sesión, incluida búsqueda, cola y reproducción, se controla desde el PC. |
| Buscar mientras se canta en una pantalla | Canto y lateral pertenecen a la misma ventana; las letras y barras siguen visibles y la cola conserva su estado. |
| Escribir en el buscador | El texto no activa atajos del juego, no pausa el canto ni cambia el turno. |
| Redimensionar la ventana | Dentro del tamaño mínimo soportado, canto y lateral siguen siendo legibles y utilizables. |
| Validar el repertorio prioritario | La muestra incluye inglés y español; se registran cobertura y fallos por idioma y se muestran correctamente letras y metadatos. |
| Escuchar la propia voz | La salida mezcla canción y micrófono con retardo y estabilidad validados para cantar en los equipos soportados de macOS y Windows. |
| Ajustar el volumen de mi voz | Solo cambia el retorno por los altavoces; no se modifica la ganancia ni la señal entregada al detector de tono. |
| Silenciar mi voz o bajar el slider a cero | Desaparece el retorno, pero la captura para puntuación sigue funcionando. |
| Dejar de cantar con voz original en reproducción | Se comprueba que la captación ambiental no genere puntuación sistemática; se documenta la configuración de micrófono y altavoces usada. |
| Cantar con el micrófono por cable | Se recibe y calibra la señal del jugador sin utilizar un móvil. |
| Elegir una canción en el flujo habitual | Se prioriza y reproduce la versión con voz original como referencia; no se elimina ni se sustituye silenciosamente por instrumental. |
| No disponer de pista instrumental | La canción con voz original sigue siendo plenamente utilizable. |
| Buscar una instrumental | La búsqueda ofrece candidatos existentes y distingue compatibilidad, revisión pendiente, ausencia y error de la fuente. |
| Elegir instrumental | La variante es explícita, compatible con el mapa y se elige antes del turno; no se genera con IA. |
| Encontrar una instrumental incompatible | No se presenta como lista para puntuar con el mapa elegido; se conserva la opción con voz original. |
| Pedir B mientras suena A | A no se interrumpe; B queda registrada con su estado. |
| Descargar B durante A | Se ve el progreso; la reproducción y los micrófonos mantienen un funcionamiento adecuado. |
| Cantar B después de A | B entra en el motor sin reinicio y los jugadores siguen configurados. |
| Añadir varias canciones | Todas se registran; su preparación y orden son distinguibles y controlables. |
| Guardar sin reservar turno | Se prepara y conserva la canción sin añadirla a la cola. |
| Importar una carpeta UltraStar | Se valida audio y mapa antes de incorporarla; un paquete incompleto no aparece listo. |
| Pegar un enlace de YouTube | Se busca un mapa compatible o se explica su ausencia; no se asigna uno solo por coincidir el título. |
| Pedir una canción ya descargada | Se reutilizan los archivos y no se repite la descarga. |
| Pedir dos veces la misma canción | Hay dos turnos si se confirma la repetición, pero una sola copia de los recursos. |
| Elegir un vídeo sin mapa localizado | Se informa de que no se puede ofrecer canto con puntuación; no se generan notas. |
| Elegir una versión distinta | No se asocia automáticamente un mapa incompatible solo por coincidir artista y título. |
| Fallar el vídeo opcional | Si audio y mapa están completos, se puede cantar con otro fondo. |
| Fallar audio o mapa | La canción no aparece lista; hay explicación y una acción de recuperación. |
| Tener una próxima petición aún pendiente | Se espera la decisión del anfitrión; saltar manualmente a otra preparada conserva el turno pendiente y su orden relativo. |
| Terminar una canción | Se muestran resultados y el siguiente turno no empieza hasta la confirmación del anfitrión. |
| Buscar y gestionar la cola desde el PC durante el canto | El cambio de foco no pausa la canción; todas las superficies muestran una cola coherente. |
| Perder Internet | El canto actual y las canciones completas siguen disponibles localmente, incluida la puntuación y la mezcla del micrófono. |
| Reabrir tras una interrupción | Biblioteca y cola guardada se recuperan; no arranca una canción inesperadamente. |
| Cantar con dos micrófonos | Ambos cantan la misma melodía; cada jugador recibe señal, puntuación y control de volumen de retorno independientes. |
| Cantar rap o freestyle | El producto refleja las posibilidades reales del mapa y no promete afinación evaluada en todas las partes. |
| Operar la interfaz con teclado | El foco es visible, las acciones principales son accesibles y reordenar no depende exclusivamente de arrastrar. |
| Mostrar títulos largos, carga y errores | El diseño conserva su jerarquía y los controles siguen visibles y utilizables. |
| Revisar la interfaz con Impeccable | Se completan las revisiones aplicables y se corrigen los defectos conocidos que impidan las tareas principales. |
| Instalar una release en macOS y en Windows | El comando documentado de cada sistema instala el paquete sin clonar ni compilar el proyecto; las dependencias de uso se resuelven automáticamente. Se verifica en ambos sistemas dentro de la matriz de compatibilidad declarada. |
| Cantar con micrófono real en macOS y Windows | Captura, calibración, sincronización, barras y puntuación se validan en ambos sistemas, además de comprobar la construcción de sus paquetes. |
| Abrir la aplicación instalada | Un icono inicia la experiencia completa sin abrir manualmente varias herramientas ni mantener una terminal. |
| Actualizar con canciones guardadas | La biblioteca, configuración y cola se conservan y la aplicación sigue funcionando. |
| Cantar sin conexión | Las canciones completas se reproducen desde el equipo y la puntuación funciona sin un servidor remoto. |
| Consultar el repositorio público | Código, instrucciones y paquetes de las versiones publicadas están disponibles; los datos personales y la biblioteca del usuario quedan fuera. |

## Cierre del plan y condiciones de entrega

El alcance funcional de V1 queda definido en este documento. Los criterios de cierre concretan los antiguos puntos opcionales: hasta dos jugadores sobre la misma melodía, catálogo y enlaces, avance manual, importación y preparación anticipada, biblioteca persistente y revisión explícita de instrumentales ambiguas. No quedan elecciones de producto que obliguen a detener el inicio de las pruebas técnicas.

La V1 solo se considerará completa al cumplir los criterios de aceptación en macOS y Windows, con instalación probada y una sesión real. El fallo de un componente reutilizado exige adaptarlo o cambiarlo; no convierte una función obligatoria en opcional. Si ninguna solución viable permite cumplirla, se documentará el bloqueo y se revisará explícitamente el alcance antes de declarar la entrega terminada.

### Trabajo técnico y datos de entrega aún necesarios

| Punto | Responsable y momento | Evidencia requerida |
|---|---|---|
| Motor, ventana única y retorno del micrófono | Implementación, fase 3, antes de desarrollar toda la interfaz. | Recorrido A → preparar B → cantar B, control lateral, uno y dos micrófonos y retorno estable en ambos sistemas. |
| Compatibilidad de sistemas y arquitecturas | Implementación, fases 2–3. | Matriz de versiones mínimas y arquitecturas comprobadas; evaluación de Apple Silicon, Mac Intel y Windows x64. Windows ARM no se incluye sin validación expresa. |
| Equipos y medidas de audio | Implementación, con acceso a hardware de prueba, fases 2–3 y 6. | Dispositivos, backend, configuración, latencia medida, estabilidad bajo carga y comprobación de captación ambiental. La falta de hardware limita la validación, no se reemplaza por una prueba simulada. |
| Catálogo, credenciales y variantes instrumentales | Implementación, fases 1, 3–5. | Repertorio en ambos idiomas, acceso real, preparación automática y ejemplos de coincidencia compatible, incompatible y ambigua. No se promete validar una instrumental solo por su título o duración. |
| Tecnologías de interfaz, comunicación y persistencia | Implementación, tras la prueba de integración. | Elección documentada compatible con ventana única, separación de audio y trabajos de descarga, y recuperación de biblioteca y cola. |
| Comando, instaladores y actualización | Implementación, prueba temprana en fases 2–3 y cierre en fase 6. | Instalación sin herramientas de desarrollo, dependencias resueltas, arranque por icono y actualización que conserve datos en ambos sistemas. |
| Licencias, firma y publicación | Implementación, antes de distribuir. | Licencias compatibles con la forma de integración y distribución, avisos incluidos y procedimiento de firma/publicación con sus requisitos y costes reales. |
| Propietario y nombre del repositorio | Resuelto por el usuario. | Repositorio público AlexAmMo/karaoke; nombre de aplicación Karaoke. |
| Tamaño y límites operativos | Implementación, a partir de mediciones. | macOS arm64: aproximadamente 192 MB de descarga y 412 MB instalado; ventana revisada desde 1000×640. Faltan las mediciones de las demás plataformas y la sesión física bajo carga. |

### Orden de ejecución

Preparar la muestra de repertorio y la matriz de equipos; después demostrar integración, ventana única, audio y empaquetado mínimo. Con esas pruebas superadas, construir el recorrido completo y aplicar el diseño con Impeccable. Finalmente, completar enlaces, pruebas de sesión, instaladores y publicación. La selección de títulos puede avanzar junto con la prueba del motor; el nombre del repositorio no bloquea el desarrollo local.

### Evolución posterior

V2 contempla separar gestión en portátil y canto en TV. El mando móvil, otros catálogos, dúos con partes distintas, búsqueda general en YouTube y automatizaciones adicionales se reconsiderarán según uso real. No se implementan preventivamente en V1. La IA y el móvil como micrófono continúan excluidos; no se incorporan automáticamente por pasar a V2.

## Fundamentos técnicos y antecedentes

Las funciones de este plan son requisitos de la integración, no prestaciones que ya ofrezca Deluxe por sí solo. La base técnica es provisional hasta superar las pruebas descritas. Estas fuentes justifican las piezas reutilizables y las limitaciones que afectan al plan:

- [UltraStar Deluxe](https://github.com/UltraStar-Deluxe/USDX): motor de canto, barras y puntuación.
- [Recarga de canciones en Deluxe](https://github.com/UltraStar-Deluxe/USDX/issues/549): diferencia entre modificar una canción conocida e incorporar otras sin reiniciar.
- [USDB Syncer](https://github.com/bohning/usdb_syncer) y su [servidor web](https://github.com/bohning/usdb_syncer/blob/main/src/usdb_syncer/webserver/webserver.py): descarga de recursos y base para catálogo accesible externamente.
- [Metadatos de Syncer](https://github.com/bohning/usdb_syncer/wiki/Meta-Tags): asociación de fuentes concretas de audio y vídeo con el mapa.
- [Formato UltraStar](https://github.com/UltraStar-Deluxe/format/blob/main/The%20UltraStar%20File%20Format%20%28v1%29.md): notas, tiempos, letras y tipos de nota.
- [Stan en USDB](https://usdb.animux.de/?link=detail&id=444): ejemplo de mapa con partes rapeadas marcadas como freestyle.
- [Inspección de la integración con Deluxe](/Users/ton/Desktop/Karaoke/research-integracion-deluxe.md) y [comprobación de cobertura](/Users/ton/Desktop/Karaoke/research-cobertura-catalogo.md): antecedentes específicos del proyecto.
