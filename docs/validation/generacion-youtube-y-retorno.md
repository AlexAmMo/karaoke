# Cuándo se puede puntuar una canción generada

Karaoke puede comprobar una predicción completa contra un mapa comunitario independiente asociado al mismo vídeo. La comparación se hace después de generar la letra, las notas y sus tiempos. La app comprueba también que la voz del audio descargado suena cuando la espera ese mapa. Si todo coincide, guarda la canción en Buscar y conserva el turno y sus cantantes. Si falta una referencia fiable o alguna comprobación falla, ofrece escuchar y editar el borrador. La voz original permanece en la mezcla.

## Las 40 grabaciones

Se repitió el ensayo con las 20 grabaciones españolas de YouTube y los 20 másteres ingleses de los paquetes Creative Commons de Deluxe. Once canciones inglesas son de Jonathan Coulton. Los hashes vinculan cada ensayo con el archivo original y el mapa humano usado para evaluarlo. Los modelos de transcripción reciben el audio y, cuando corresponde, fuentes de texto que el producto puede obtener por separado. El evaluador recibe la referencia después de congelar la predicción. En inglés, la regeneración reprodujo los 20 másteres y 14 de los 20 mapas generados byte por byte. Para los otros seis se midió nuevamente la línea base. [Identidades de la muestra](generacion-muestra.json) · [Regeneración inglesa en Windows](https://github.com/AlexAmMo/karaoke/actions/runs/44913555763)

Se conservaron los criterios de la iteración anterior. Por canción se exige como máximo un 5 % de errores de palabra y un p90 de 120 ms para el comienzo de las palabras coincidentes. La clase de altura debe coincidir al menos el 90 % del tiempo cantado puntuable, y el F1 de ataques con la misma clase a ±100 ms debe alcanzar 0,85. Un ataque sólo puede emparejarse una vez. La clase de altura permite cantar la misma nota en otra octava. El F1 penaliza también las barras inventadas y las omitidas. Estos criterios miden compatibilidad con la edición humana de karaoke. Otros estudios pueden usar 50 ms y exigir además ajuste de octava y final de nota. [Definiciones de evaluación de transcripción](https://mir-eval.readthedocs.io/stable/api/transcription.html)

| Método de generación | Grabaciones | Error de palabra mediano | P90 de palabra mediano | Clase de nota mediana | F1 de ataques mediano | Pasan los cuatro |
|---|---:|---:|---:|---:|---:|---:|
| Motor anterior regenerado, EN | 20 | 6,69 % | 74 ms | 78,79 % | 0,725 | 0 |
| Motor anterior regenerado, ES | 20 | 9,75 % | 139,5 ms | 71,54 % | 0,610 | 0 |
| Mismo motor musical con el nuevo tratamiento del texto, EN | 20 | 5,63 % | 74 ms | 78,79 % | 0,725 | 0 |
| Mismo motor musical con el nuevo tratamiento del texto, ES | 20 | 7,88 % | 139,5 ms | 71,54 % | 0,610 | 1 |

## De dónde viene el error

En la variante con texto corroborado, 17 de 40 cumplen el criterio de palabras, 22 el de tiempo de palabra, dos el de clase y una el de ataques con altura. Contando cada instante de 10 ms con objetivo humano, hay 338.058 instantes puntuables. En 18.041 el generador dejó un hueco. En 63.552 emitió otra clase, a menudo a uno o dos semitonos de la referencia. En estas grabaciones pesa más elegir mal la altura que dejar huecos. Las frecuencias no identifican por sí solas dónde empieza otra nota del mismo tono, qué movimiento es vibrato o a quién corresponde una voz superpuesta. La anotación de una melodía cantada tampoco tiene una única segmentación para todos los oyentes. [Diagnóstico por canción](generacion-diagnostico-40.csv) · [Tony y la transcripción asistida de canto](https://webspace.eecs.qmul.ac.uk/s.e.dixon/pub/2015/MauchEtAl-TENOR2015-Tony.pdf)

El otro borde de la barra también importa. Tomando sólo ataques que sí acertaron el tono y entraron en la ventana de 100 ms, la mediana por canción del error absoluto de final fue de 123 ms. Las barras generadas duraron una mediana de 91 ms más que las humanas. Por ejemplo, la separación mediana entre barras cercanas de «Amorfoda» es de aproximadamente 101 ms en su edición comunitaria, mientras que en el mapa base muchas barras consecutivas se tocan. Por eso se midieron aparte la duración y la precisión sobre el tiempo que el juego pediría cantar. [Desglose de finales y duración](generacion-diagnostico-40.csv)

Como diagnóstico, se desplazó cada mapa completo entre −150 y +150 ms en pasos de 50 ms. Incluso escogiendo a posteriori el mejor desplazamiento para cada canción, la mediana del F1 sólo pasa de 0,668 a 0,709. En catorce canciones el mejor ajuste fue cero y en otras hubo desplazamientos de signo opuesto. Ese experimento utiliza la respuesta correcta para estimar lo que arreglaría una compensación global. La app conserva el reloj original al validar una pista. [Errores y desplazamientos por grabación](generacion-diagnostico-40.csv)

Tres tratamientos de duración aislaron esta causa sin mover ataques ni cambiar alturas. Un recorte del 17 % limitado a 75 ms en barras contiguas redujo el error mediano de final de 123 a 88 ms, pero también bajó la cobertura correcta de clase del 76,48 % al 71,77 %. Acortar un tercio, con un máximo de 120 ms, bajó esas cifras a 68 ms y 67,95 %. Recortar sólo cuando la energía de la voz caía al menos 8 dB redujo el error a 105 ms y mantuvo el 74,86 % de cobertura correcta. Son medianas por canción. Conservar los ataques mantiene el mismo F1 de ataques en las 40. El generador general conserva sus duraciones cuando carece de evidencia adicional. [Finales y precisión sobre el tiempo pedido al cantante](generacion-finales-40.csv)

## Dos errores de letra que se pueden corregir

- **Bad Bunny, «Amorfoda».** El autor del vídeo escribió formas de pronunciación que la transcripción automática y otras fuentes escriben de forma diferente. Antes se descartaban esos subtítulos aunque sus palabras aparecieran en las frases correctas. Karaoke mantiene la ortografía del autor cuando encuentra suficiente coincidencia literal y temporal en cada tercio. Sólo para comprobar identidad en español admite ciertas diferencias de ese final de palabra y unas pocas formas de una interjección. Los comienzos de frase de YouTube sirven para contrastar, y el alineador sitúa después cada sílaba sobre la voz. En el máster del banco, WER pasó de 21,38 % a 1,38 %, p90 de palabra quedó en 63 ms, clase en 90,61 % y F1 en 0,876. Había subtítulos manuales utilizables en cuatro de los veinte vídeos. Se rechazaron los 76 cruces con otras voces del corpus y los ocho controles adelantados o retrasados seis segundos. [Comparación de subtítulos](generacion-subtitulos-40.csv) · [Controles de identidad y tiempo](generacion-controles-subtitulos.csv)
- **Steven Dunston, «Northern Star».** Una letra de LRCLIB contenía apóstrofos omitidos y una transposición de letras en el propio título. Ahora se puede recuperar una contracción inglesa si el ASR oyó esa misma palabra en el mismo instante. Una transposición exige además que el título confirme la grafía. Las cuatro correcciones en este tema bajaron el WER de 6,74 % a 3,37 % y preservaron el tiempo, la altura y los saltos de sílaba de cada barra. En la base musical la clase llega al 91,76 %, pero el F1 de 0,839 queda por debajo del objetivo. Ninguno de los otros 19 mapas ingleses cambió de texto. [Resultados del tratamiento completo](generacion-diagnostico-40.csv)

Ambas canciones intervinieron en el desarrollo de los cambios de texto. En las otras 38 esos cambios no produjeron una aprobación nueva. Una mejora que funciona en una canción conocida no basta para certificar canciones desconocidas.

## Cómo decide la app

El generador produce y cierra el mapa antes de buscar la referencia de verificación. El catálogo debe indicar un único arreglo de una voz para el identificador del vídeo y una duración compatible. Karaoke contrasta el identificador declarado en el propio mapa, las cuatro medidas y la sincronía acústica entre el mapa de referencia y el audio que se va a reproducir. Guarda el origen de la referencia, su revisión, las medidas y las huellas del audio y del mapa admitidos. La decisión se vuelve a vincular a los archivos que entran en la biblioteca. Un error de red deja disponible el editor.

La app admitió el máster de «Amorfoda» y dejó en revisión los otros diecinueve vídeos. Se ensayaron también seis fallos sobre la canción admitida. Desplazar el mapa 350 ms, transportar sus notas dos semitonos, indicar otro vídeo, retrasar el mismo audio 400 ms, sustituirlo por otra voz de idéntica duración e indicar un vídeo desconocido produjeron seis abstenciones. Los veinte másteres ingleses aportan controles de calidad de transcripción, pero sus archivos de origen no aportan un identificador de vídeo para esta comprobación. [Decisiones del código de producción](generacion-admision.csv)

### Qué tiempo se pide cantar

Medir la altura sólo durante las notas humanas no penaliza las barras que continúan durante una respiración. Por eso la verificación exige además que al menos el **90 % del tiempo que la app pide cantar** esté respaldado por la misma nota en el mapa independiente. Si la predicción original pasa las cuatro metas pero puntúa demasiado tiempo, se intersectan sus barras con intervalos de la misma clase en esa referencia. Los silencios quedan libres. Una sílaba sin respaldo se muestra como estilo libre. Se guardan por separado las huellas y las cifras de la predicción y de la edición verificada. Después de hacer ese ajuste se vuelven a exigir los cuatro criterios y la nueva condición de precisión.

En la descarga habitual desde YouTube de «Amorfoda», la letra tuvo 1,38 % de errores y la predicción acertó el 91,04 % del tiempo cantado humano. Sin embargo, tan sólo alrededor de la mitad del tiempo que pedía cantar coincidía con una nota humana del mismo tono. Después de limitar los intervalos se mantuvo el 91,04 % de cobertura y el **95,15 % del tiempo solicitado** pasó a estar respaldado. El p90 de inicio de palabra fue de 49 ms y el F1 de ataques de 0,900. Esta última mejora utiliza la referencia disponible para esa grabación. Un vídeo desconocido carece de esa comprobación. [Medidas originales y verificadas, con sus huellas](generacion-intervalos-verificados.json)

## Qué aportan las soluciones publicadas

Wav2Karaoke probó una combinación de separación, alineamiento fonético y agregación de altura sobre 80 grabaciones inglesas. Su práctica de asociar una sílaba a una nota pierde información en los melismas. Los autores describen también errores que proceden del máster y de las convenciones de anotación. VocalParse predice letra, valores de nota, altura y tempo de forma conjunta. El formato publicado expresa duraciones musicales; una aplicación que puntúa necesita además situarlas con fiabilidad en el reloj absoluto de su vídeo. Ninguna cifra de esas publicaciones se incorporó como si fuera una medición de este corpus. [Wav2Karaoke](https://www.anlp.jp/proceedings/annual_meeting/2026/pdf_dir/C2-17.pdf) · [VocalParse](https://github.com/pymaster17/VocalParse)

Una regla de abstención necesita dos cifras distintas, cuántos casos acepta y cuántos se equivoca al aceptar. Coincidir con una referencia de la grabación y adivinar si un mapa completamente nuevo es correcto son problemas diferentes. Para el segundo ensayo, las decisiones basadas en el acuerdo de modelos se congelan antes de leer la referencia humana. [Predicción selectiva, Geifman y El-Yaniv](https://arxiv.org/abs/1705.08500)

## Comparación musical sobre las mismas 40 canciones

| Tratamiento | Coincidencia mediana de clase durante el canto humano | F1 mediano de ataques con la misma clase |
|---|---:|---:|
| Generador de Karaoke basado en GAME | 76,48 % | 0,668 |
| Altura de SOME en las barras de Karaoke | 71,52 % | 0,608 |
| Segmentación y altura de SOME | 68,70 % | 0,585 |
| Altura de ROSVOT en las barras de Karaoke | 72,21 % | 0,606 |
| Segmentación y altura de ROSVOT adaptadas a la letra | 74,67 % | 0,541 |
| Acuerdo acústico de los dos modelos sobre la segmentación de Karaoke | 75,97 % | 0,646 |

En 23 canciones el número y la posición de los ataques del generador impedirían llegar al F1 de 0,85 aunque se acertaran todas las alturas. Por idioma, los ataques sin exigir la altura coinciden con un F1 mediano de 0,904 en inglés y 0,783 en español a ±100 ms. Si se exige ±50 ms, el resultado baja a 0,732 y 0,440. Ajustar todas las notas a la pulsación musical tampoco resuelve las entradas anticipadas, las notas repetidas ni los cambios de altura dentro de una sílaba. [Estudio de melodía y detalle por modelo](melodia-alternativas.md) · [Estudio de tiempos, pulsación y sílabas](tiempos-alternativas.md)

Combinar la letra corregida, el consenso de altura y la unión de adornos breves añadió una segunda canción en el ensayo, «Northern Star». Tuvo 3,37 % de errores de palabra, un p90 de 67 ms, 91,09 % de coincidencia de clase y un F1 de 0,855. «Amorfoda» también pasó. Ambas intervinieron en el desarrollo. Entre las otras 38, el F1 subió en 9 y bajó en 29. Es una alternativa experimental para producir candidatos. El motor distribuido conserva su segmentación por defecto. [Las cuatro variantes por grabación](tiempos-consenso-adornos.csv)

### Cuando falta el mapa de referencia

Para probar si el acuerdo entre modelos permite puntuar a ciegas, se congelaron sus decisiones por barra antes de abrir los mapas humanos. Se exigió que SOME y ROSVOT confirmasen independientemente la clase, el ataque a ±80 ms y al menos media barra. De 16.333 barras se conservaron 5.051. Sólo el 77,33 % de esas 5.051 tenía un ataque humano de la misma clase a ±100 ms. En la canción mediana se conservó el 29,04 % de las barras. Ninguna de las 40 tuvo al menos un 90 % de barras corroboradas en cada uno de sus tres tramos. Por tanto, el ensayo no aporta una estimación de fiabilidad para canciones completas aceptadas a ciegas. [Decisiones congeladas y medidas por canción](generacion-acuerdo-40.csv) · [Código del ensayo](../../scripts/experiments/selective_scoring.py)

## Qué pasó al cantar en la aplicación

Una generación completa desde la URL oficial de «Amorfoda» tardó 14 min 13 s en este Mac bajo carga. Llegó a la biblioteca y a la cola y arrancó en Deluxe. Después se recuperó la misma predicción en una biblioteca temporal vacía para probar la verificación final de intervalos y el arranque desde la cola. Estas dos ejecuciones conservan por separado la huella del audio, la del resultado generado y, cuando corresponde, la de la versión confirmada. [Sesión desde YouTube](generacion-autoverificada-e2e.json) · [Recuperación y admisión con intervalos verificados](generacion-autoverificada-reanudada.json)

Se cantó después la canción entera dos veces en el motor real, a precisión estricta. Un micrófono simulado seguía las alturas y los silencios del mapa humano. El segundo enviaba la misma melodía seis semitonos más arriba. Con las barras generadas originalmente obtuvieron **5.759 y 0 puntos**. Con los intervalos confirmados obtuvieron **9.795 y 0**. El juego dejó de exigir que el cantante prolongase muchas notas durante las respiraciones. Esta prueba usa dos entradas de audio sintético y una sola canción con referencia exacta. [Puntuaciones y huellas de ambas partidas](generacion-puntuacion-real.json)

El motor también separa la escucha inmediata de la consulta del historial de afinación. La comparación entre versiones incluye compensaciones positivas y negativas por entrada, diez cantantes simulados, pérdida de bloques, contención del analizador y marcas reales del dispositivo integrado en macOS. [Implementación, comparación con SingStar y límites de las mediciones de latencia](retorno-y-puntuacion.md)
