# Por qué acertar el tono no basta para obtener un mapa puntuable

Este diagnóstico abre las referencias humanas de las mismas cuarenta grabaciones **sólo para explicar errores de predicciones ya congeladas**. No genera mapas, ajusta umbrales ni modifica el evaluador. Amplía el [diagnóstico anterior](generacion-youtube-y-retorno.md) descomponiendo todo el tiempo que el mapa automático solicita puntuar y comprobando el reloj con métodos independientes.

## Dos denominadores distintos

`correct_class_all` divide el tiempo de coincidencia de clase entre el tiempo puntuable de la referencia humana. `scored_frame_precision` divide esa misma coincidencia entre el tiempo puntuable que solicita el mapa generado. La cobertura sólo pregunta si hay una barra generada durante la barra humana, sin exigir la misma clase.

En el total de las cuarenta canciones hay 338.058 instantes humanos puntuables de 10 ms y 513.137 instantes puntuables generados: el generador pide **1,518 veces** el tiempo de la referencia. En 256.465 instantes coincide la clase. Por eso el mismo resultado da **75,86 %** de coincidencia sobre el tiempo humano y **49,98 %** de precisión sobre el tiempo solicitado. Las medianas por canción son respectivamente **76,48 %** y **50,26 %**; no se deben multiplicar medianas para comprobar la identidad de los cocientes.

| Situación en el tiempo que pide puntuar la predicción | Instantes de 10 ms | Fracción del total predicho |
|---|---:|---:|
| Misma clase, mismo número de altura | 73.457 | 14,32 % |
| Misma clase, otra octava | 183.008 | 35,66 % |
| Otra clase mientras la referencia pide cantar | 63.552 | 12,38 % |
| La referencia indica estilo libre (`F`) | 3.628 | 0,71 % |
| La referencia indica rap (`R`/`G`) | 0 | 0,00 % |
| Antes de la primera fila de la referencia | 555 | 0,11 % |
| En huecos entre filas de la referencia | 180.348 | 35,15 % |
| Después de la última fila de la referencia | 8.589 | 1,67 % |

Las diferencias de octava de las dos primeras filas **ya se aceptan** en la métrica de clase. No son la causa del 50 % restante. Las filas sin nota humana tampoco demuestran silencio acústico: pueden reflejar respiraciones, convenciones del mapa, adornos, voces que el autor decidió no puntuar u otros contenidos. Sin nuevas anotaciones o pistas aisladas no se puede atribuir cada hueco a coros, rap o versos omitidos. Que aquí no haya filas `R`/`G` tampoco demuestra ausencia de rap en el audio.

El JSON conserva también los encabezados `START` y `END`. La referencia de «Tu canción» declara `START:3,5` y `END:183012`; sus notas terminan en 176,409 s y las predichas en 190,233 s dentro de una grabación de 197,103 s. El diagnóstico sigue comparando la grabación completa y no recorta la predicción para favorecerla. Esta cola sin anotación es una limitación para atribuir todo el error matemático a una nota acústicamente inexistente.

## El límite de corregir solamente alturas

Manteniendo exactamente los intervalos puntuables actuales, un oráculo que acertase la clase de cada instante todavía estaría limitado al cociente **tiempo de solapamiento / tiempo predicho**. Ese techo es **62,36 % agregado**, **60,98 % en la canción mediana** y como máximo **78,80 %** en ABBA, «Estoy soñando». **Ninguna de las cuarenta canciones podría alcanzar el control del 90 % cambiando sólo alturas.** El oráculo es un límite matemático retrospectivo; no es un método disponible ni un resultado de generación.

De los 256.672 instantes predichos incorrectos, el **70,26 %** está en huecos internos de la referencia. El **78,62 %** de ese grupo pertenece a huecos de hasta 500 ms. Además, 116.442 instantes incorrectos aparecen después del final humano de una nota cuyo ataque sí pudo emparejarse con la misma clase a ±100 ms. Este último recuento es un subconjunto de errores, no otra fila que deba sumarse a la tabla. El diagnóstico respalda tratar los finales y la separación entre notas como un requisito propio; no justifica recortar todas las notas indiscriminadamente. Las variantes de recorte y finales fonéticos anteriores ya mostraron que se puede ganar precisión a costa de perder canto correcto.

| Grabación | Coincidencia de clase sobre referencia | Precisión sobre predicción | Tiempo predicho / humano |
|---|---:|---:|---:|
| «Amorfoda», predicción automática sin corrección de intervalos | 90,61 % | 49,83 % | 1,818 |
| «Northern Star» | 91,76 % | 57,15 % | 1,606 |
| «La señora interesante» | 62,79 % | 37,04 % | 1,695 |
| «Estoy soñando» | 87,97 % | 71,32 % | 1,233 |

Como ejemplo temporal, una barra de «Northern Star» entre 44,200 y 48,283 s tiene un ataque emparejado con una barra humana de 44,242 a 45,533 s, de la misma clase. Durante 275 instantes posteriores al final humano solicita una clase sin respaldo. Se conserva el detalle por índices y tiempos, sin texto de la canción, en `build/generation-next/error-diagnosis/examples.json`.

## Comprobación del reloj y del muestreo

Se volvieron a verificar las huellas de los cuarenta másteres, referencias y predicciones frente al manifiesto congelado. Todos los mapas analizados usan tiempos absolutos, un solo tempo y una voz; sus intervalos tienen duración positiva, están ordenados, no se solapan y quedan dentro de la grabación. No hay instantes predichos fuera del audio.

El script reproduce los resultados del evaluador de producción y del JSON congelado en las cuarenta canciones. Además:

- Un parser independiente con fracciones racionales para `BPM`, `GAP` y ticks difiere del reloj flotante como máximo **5,68 × 10⁻¹⁴ s**.
- Integrar la unión de intervalos de forma continua, sin muestreo de 10 ms, cambia la precisión como máximo **0,545 puntos porcentuales** por canción.
- Calcular la rejilla con límites racionales cambia esa precisión como máximo **0,430 puntos**; mover el origen de muestreo 5 ms la cambia como máximo **0,468 puntos**.
- Dos pruebas matemáticas comprueban intervalos semiabiertos sin doble recuento y un caso de cobertura/clase del 100 % con precisión del 50 % por prolongación de una nota. Se comprueba también que la octava equivalente se acepta.

Estas diferencias pequeñas no explican la pérdida de aproximadamente la mitad del tiempo puntuable. No se detectó en este corpus un error de conversión de ticks o de denominador que invalidara la conclusión. Tampoco se afirma que un único mapa humano sea la única transcripción musical posible.

## Reproducción y alcance

```sh
uv run python scripts/experiments/diagnose_generation_errors.py
```

El [script](../../scripts/experiments/diagnose_generation_errors.py) utiliza por defecto `build/generation-next/swift/common-evaluation/baseline/frozen.json`, la misma base de los ensayos de esta iteración. Produce `diagnosis.json`, `frames.csv` y `examples.json` en `build/generation-next/error-diagnosis/`; rechaza mapas de voz múltiple, tempo variable, tiempos relativos o intervalos fuera del alcance comprobado. El [CSV público de cuarenta filas](generacion-desglose-intervalos-2026-11-21.csv) contiene sólo identificadores y medidas. El JSON registra las huellas del script y de sus entradas para distinguir una medición nueva de una anterior.

Este trabajo usa CPU en el Mac, no abre audio ni ejecuta modelos. No prueba micrófonos, Windows o la exactitud perceptiva de una referencia frente a la grabación. No modifica los mapas publicados ni las reglas de admisión.
