# Sistema visual de la próxima versión de Karaoke

Propuesta del 21 de noviembre de 2026 para el escenario nativo, el panel del ordenador y el mando móvil. La [maqueta navegable](sesion.html) permite probar búsqueda, descarga simulada, peticiones al anfitrión, cola y plegado. La letra del escenario es un ejemplo original. Los datos son ilustrativos. La implementación de la rama de desarrollo está descrita en [Diseño de Karaoke](../../DESIGN.md).

## La sala y la distancia de lectura

Durante una canción, alguien mira la letra desde el sofá y otra persona elige el próximo turno a medio metro del portátil. El escenario necesita una frase dominante y una referencia de tono que se pueda seguir con visión periférica. El panel necesita leer de un vistazo artista, título y disponibilidad sin tapar el canto. El móvil es el panel en la mano de un invitado. La pantalla compartida permanece en el PC. El vídeo y la voz originales son preferencias que se conservan.

La identidad parte de un escenario verde tinta, papel cálido para la letra y melocotón para el tiempo presente de la canción. La línea vertical, la posición de la nota y la palabra resaltada coinciden en un mismo instante. Las carátulas dan variedad a la lista. Cuando falten, las iniciales del artista sobre un color estable mantienen el mismo tamaño y la posición del título. La aplicación debe poder reconocer el paquete aunque no haya imagen ni red.

## Tokens de color y legibilidad

| Uso | Valor | Aplicación |
|---|---|---|
| Escenario | `#102321` | Lienzo y fondo opaco para el canto sin vídeo |
| Panel | `#172C29` | Superficie de gestión. Una línea delimita el escenario |
| Superficie elevada | `#243B37` | Sobrevuelo, botones secundarios, selección persistente con indicador |
| Separador | `#425953` | Guías tenues, divisores no interactivos |
| Tinta clara / secundaria | `#F7F4E9` / `#B7C8BF` | Títulos y letra / artista, estado y frase siguiente |
| Acción y sílaba activa | `#FFB18A` | Acción de inicio, avance de letra, trazo individual |
| Texto sobre acción | `#332019` | Texto en botón de acción relleno |
| Señal presente / preparada | `#ACF1CD` | Medidor y estado con texto o forma asociada |
| Guía de nota | `#81968C` | Barra de melodía, contorno de campo interactivo |
| Foco | `#FFE6A1` | Anillo de 2 unidades, separado otras 2 del control |
| Atención / error | `#F1CB87` / `#FFA9A1` | Acción requerida y problemas recuperables, siempre junto a su causa |

El semáforo de descarga siempre incluye texto. Para la afinación, la guía es una barra, la voz una línea y el acierto un relleno. Dibujar el contorno de la voz con contraste suficiente después de componer su transparencia. En vídeo, un fondo oscuro local bajo letra y notas garantiza contraste también en un fotograma blanco. Para una interfaz sobre pantallas de distinta calidad exigir ≥4,5:1 en texto común y ≥3:1 en letra grande, foco e indicadores necesarios. Probar también en monocromo y fondo de vídeo en movimiento. [Criterios de contraste](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html)

## Tipografía, escala y geometría

Instrument Sans para castellano e inglés, con cobertura de acentos, diéresis y signos de apertura. Para PC empaquetar los pesos que rasterice bien el motor y usar atlas a la escala real de salida. Para móvil y maqueta usar WOFF2 local. `system-ui` y Segoe UI son reservas de arranque. No descargar fuentes durante una sesión. La copia variable de la maqueta procede del commit `7fa22308` y conserva su licencia. [Instrument Sans](https://github.com/Instrument/instrument-sans) · [Licencia incluida](tipografia/OFL.txt)

| Preset | Tamaño lógico | Peso y uso |
|---|---|---|
| Letra actual / siguiente | 48–84 / 29–49 | 700 / 500, interlineado 1,03–1,18. Ajustar al ancho del escenario, permitir dos líneas y preservar la sílaba activa |
| Título de escenario | 27–32 | 650–700. Admite dos líneas y nombre completo en detalle |
| Cabecera del panel | 22–24 | 650. Solo donde el texto identifica el trabajo actual |
| Título de canción / acción | 16–18 | 600–650 / 550–650 |
| Artista, estado, posición | 14–16 | 450–500, cifras tabulares para tiempo y puntuación |
| Ayuda secundaria | 13–14 | 450. Información imprescindible también accesible a tamaño de cuerpo |

Espaciado base 4, 8, 12, 16, 24, 32 y 48 unidades. Filas de 64–76, carátulas de 44–48, acciones de al menos 44×44, redondeo de 6 en arte, 8 en controles y 12 en hojas. La densidad cómoda es la predeterminada. Solo en escritorio una lista compacta puede reducir el espacio entre filas conservando la zona de interacción. Iconos diseñados para una cuadrícula de 24, trazo de 1,75–2, etiqueta accesible y ayuda de puntero. Un solo `+` reservado a crear un turno. Las funciones de reproducir, pausar y terminar mantienen iconos y verbos distintos.

## Arquitectura de información

| Superficie | Qué tiene delante | Qué abre cuando lo necesita |
|---|---|---|
| Buscar | Campo, filtro «Solo descargadas», lista unificada. Sin texto aparecen repertorio local y descubrimiento claramente identificados. En móvil, estado de la canción en curso | Fila abre edición, «Solo descargar», variante instrumental existente, preescucha y créditos. Con enlace pegado, resolver el ID de esa grabación. Volver conserva texto, posición y foco |
| Cola | Orden, cantante(s) y preparación de cada turno. Una acción de transporte contextual. Los cambios llegan a todos los clientes | Detalle para cambiar participantes/entrada, mover, quitar, resolver incidencia. Ofrecer mover con botones además de arrastrar. «Terminar» con confirmación y vuelta inmediata al canto si se cancela |
| Sesión | Acceso secundario consistente desde cabecera. Cantantes y entradas, invitar por QR, audio y afinación | Avanzado agrupa carpeta, importación, vídeo, calidad, cuentas, procedencia y diagnóstico. En móvil se conserva gestión de reproducción y turnos. Credenciales, selector de archivos y permisos del sistema permanecen en el anfitrión |
| Escenario | Antes del canto, próximo turno y «Empezar». Durante el canto, letra, guía, trazo, tiempo y puntuación. Al terminar, resultados y próximo turno | Plegar el lateral conserva canto, consulta y cola. Volver al panel por la misma ubicación. Una sola orden explícita inicia el siguiente turno |

La navegación frecuente son dos destinos, **Buscar** y **Cola**. «Sesión» es una utilidad, accesible con texto descriptivo. Se retira el carrusel de la biblioteca como destino principal. «Solo descargar» vive en el detalle de la misma fila. Un usuario puede preparar una canción sin reservar turno. Las fuentes aparecen únicamente cuando aportan una decisión que el anfitrión necesita tomar.

## Componentes y estados

| Componente | Contrato |
|---|---|
| Campo de búsqueda | Los resultados locales aparecen al escribir y los remotos llegan en segundo plano. Mantener foco al refrescar, ignorar respuestas antiguas, preservar composición del teclado, búsqueda por título/artista/URL. Enter fuerza la consulta. Esc vacía el campo antes de abandonar la vista |
| Fila de canción | Portada de la edición, álbum o artista, en ese orden cuando se identifiquen. Usar iniciales al faltar imagen. Título y artista siempre visibles. Los identificadores de selección sobreviven al orden provisional. `+` encola desde cualquier versión directamente preparable. La fila abre el detalle también con teclado |
| Disponibilidad | «Descargada», «Para descargar», «Preparando…», «Requiere al anfitrión», «Sin edición compatible». Un fallo temporal de una fuente deja disponible el resto. Ofrecer «Reintentar» en contexto y causa breve. «Solo descargadas» funciona sin red |
| Trabajo de descarga | Compartido por canción/edición. Progreso real si el servidor informa tamaño. En otros casos mostrar la etapa. Publicar «Lista» solo tras validar y guardar. Un enlace «Preparaciones» en Cola da acceso también a descargas sin turno. Si varias personas encolan la misma canción, cada una conserva su turno |
| Turno | Orden y cantante estables mientras se descarga. «Añadida» se anuncia sin mover el botón ni abrir el detalle. Ofrecer deshacer de ese turno. Desactivar envíos repetidos de la misma pulsación. Un segundo turno deliberado sigue siendo posible |
| Entrada de voz | Nombre legible del dispositivo y canal, medidor y quién puede usarlo. El perfil tendrá una preferencia y cada turno podrá cambiarla. Indicar «Sin señal», «Señal débil» y «Con señal» combinando texto y forma. La ausencia de tono estable no equivale a desconexión |
| Afinación y retorno | Un nombre por ajuste: «Escuchar mi voz», «Precisión de las notas», «Calibrar esta entrada». Volumen musical separado. Distinguir monitor directo de interfaz y retorno por aplicación. Pausar/denegar un micro móvil conserva su mando |
| Más de dos voces | Objetivo de melodía común: una letra compartida y lista de participantes identificados por nombre, símbolo y posición. Con 3–10 voces, trazo propio destacado por página/grupo seleccionable, resúmenes individuales simultáneos y resultados para todos. A 1080p verificar que ninguna identificación o puntuación depende solo del color. Si se usa móvil, ofrecer vista personal de tono |

## Movimiento y respuesta

| Transición | Preset propuesto | Condición de aceptación |
|---|---|---|
| Pulsar, añadir, marcar | 80–120 ms, cambio de tinta o fondo | Botón y fila conservan tamaño, foco y posición. Confirmación de turno compartida con el lector de pantalla |
| Abrir detalle y volver | 140–180 ms, salida suave | Foco entra en el título o primera acción y vuelve al origen. Escape/cierre del sistema funcionan. Menú abierto permanece estable ante cambios remotos |
| Plegar panel | 160–200 ms, desplazamiento corto | Mantener el reloj del canto y redimensionar el escenario una vez por fotograma. Con movimiento reducido, cambio inmediato |
| Llegada de portada o resultado | 100–140 ms opcionales | Espacio reservado desde el principio. Mantener la fila enfocada y su posición visible. Descargar arte solo de las filas próximas |
| Tono y reloj | Tiempo musical del audio | Sin suavizado decorativo que retrase la voz. Al perder señal, el trazo caduca. El usuario puede seguir notas, aciertos y errores con animaciones reducidas |

## Auditoría y entregas

En la versión actual, el escenario de búsqueda puede seguir mostrando otra canción del antiguo carrusel mientras el panel muestra el resultado deseado. Biblioteca y Buscar repiten acciones con palabras distintas. El móvil calcula la disponibilidad con campos propios y el detalle asistido puede necesitar ir al ordenador. Ajustes reparte dispositivos, prueba de señal, retorno y corrección de sincronía en rutas distintas. El refactor fija propietario, acción y recuperación para cada una de estas situaciones.

La maqueta cubre solo el recorrido de selección, descarga simulada y cola. La integración posterior cubrirá transporte, permisos, sesiones concurrentes, portadas reales, modo completo de canto y personalización. La validación visual incluirá ventana de 1000×640, 1280×800, 1920×1080 y escala 2×, Windows 125–200 %, móvil a 320–430 de ancho y texto al 200 %. Usar títulos de dos líneas, cantantes con el mismo nombre, diez participantes, cero canciones, cien resultados, proveedor caído y permiso denegado.

La verificación de interfaz tendrá tres partes: recorrido de teclado, puntero y lector de pantalla, inspección del render en una pantalla real y detector de Impeccable con revisión manual de cada hallazgo. El panel SDL actual dibuja controles personalizados: validar VoiceOver y Narrador sobre la implementación real. Si no expone roles, foco y estado, probar un panel accesible integrado en la misma ventana antes de dar por completada la accesibilidad. En canto, controlar legibilidad sobre vídeo y percepción de la guía desde el sofá. [Plan de entregas](../PLAN-MACRO-REFACTOR.md)

En la maqueta, «On the run» usa la portada original sin modificar, © Joshua Morin, CC BY-SA 2.5. Las demás filas ejemplifican la reserva de espacio y el reconocimiento por iniciales. [Portada y créditos originales](https://github.com/UltraStar-Deluxe/songs/tree/c9246c799050acec96a03183df4b85493d283d51/Creative%20Commons/Joshua%20Morin%20-%20On%20the%20run) · [Licencia](https://creativecommons.org/licenses/by-sa/2.5/)

### Comprobaciones ejecutadas sobre la maqueta

El 21 de noviembre se ejecutó el mismo recorrido en Chromium a 1000×640, 1280×800, 1920×1080, 390×844 y 320×568, y en WebKit a los dos tamaños móviles. Se probó escribir sin tildes, filtrar descargadas, añadir desde el teclado sin perder foco, reservar posición durante una preparación simulada, descargar por separado, quitar un turno, pedir ayuda para Mulán, abrir un resultado sin edición, cerrar con Escape y plegar/restaurar el panel en PC. También se comprobó la carga de la portada y de la fuente desde disco. No hubo errores de JavaScript ni desbordamiento horizontal en esos tamaños. A 320 de ancho, duplicar el tamaño raíz del texto conservó la anchura y un control de añadir de 44×44. [Escritorio](escritorio.png) · [Móvil](movil.png)

El contraste calculado de tinta y texto secundario sobre el panel es de 13,35:1 y 8,42:1. El foco alcanza 11,96:1 sobre el panel y la guía de afinación, 5,20:1 sobre el escenario. Se revisaron las capturas y se pasó el detector de Impeccable: al compararlo con 0.2 señala los cambios deliberados de paleta, tamaños, radios y fuente. Al auditar la nueva dirección sin la paleta histórica queda un aviso tipográfico genérico. Se conserva Instrument Sans por legibilidad y se comprobó que el navegador carga el archivo local. Estas pruebas son de maqueta en navegadores de escritorio con vistas móviles simuladas. La revisión con lector de pantalla, móvil físico y pantalla a distancia corresponde al cliente de producción.
