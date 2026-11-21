# YourMT3+: cuatro canciones completas frente a la base

YourMT3+ termina las cuatro grabaciones del piloto en CPU, con procesos acotados y sin otro reinicio. Su reconstrucción de eventos mejora el F1 que incluye finales en las cuatro, pero pierde acierto de clase y cobertura también en las cuatro. **Ninguna supera los cinco controles ni el objetivo casi perfecto.** No se sustituye el generador de la app ni se amplía esta configuración a cuarenta canciones por estos resultados.

## Qué se comparó

Se mantienen Amorfoda, 11 y 6, Mr. Fancy Pants y Northern Star completos, dos por idioma. Son desarrollo, no un conjunto reservado. [La investigación](research-finales-nota-2026-11-21.md) fija código, pesos, licencias, configuración y recursos. El modelo recibe las mezclas originales, preparadas como mono float32 a 16 kHz; no recibe letras, partituras ni tiempos humanos. La comparación con la base mide cadenas completas: la base utilizó otra arquitectura y voces separadas. No se atribuye toda diferencia únicamente al modelo de notas.

Los cuatro resultados del programa vocal `100` son monofónicos y válidos: 463, 292, 219 y 218 notas, respectivamente. Se conservaron también todos los instrumentos, tokens y reparaciones del decodificador. El brazo `100+101` tiene en estos casos las mismas notas vocales; sigue siendo diagnóstico y no se convierte a mapa. No hubo reducción de polifonía, corrección de octava, ajuste del reloj o recorte de notas inválidas.

Antes de la segunda tanda se fijaron dos conversiones mediante `melody_compare.transform`, sin cambios: `pitch` conserva ritmo y letra de la predicción base y cambia alturas cuando hay cobertura suficiente; `events`, el brazo **primario**, reconstruye eventos sobre esa misma letra predicha. Primero se congelaron los cuatro resultados acústicos; después los ocho mapas candidatos y los cuatro controles base; sólo entonces se interpretaron las referencias. Los bytes de las letras base se contrastaron con su congelación anterior, no sólo con un manifiesto de rutas.

Cada conjunto registra cuatro evaluadas, treinta y seis ausentes y cero mapas inválidos. Las ausentes permanecen en el denominador cuarenta. **0/4 del piloto no significa que se hayan probado y suspendido las otras 36.** Las métricas siguientes usan únicamente las cuatro grabaciones medidas, con el evaluador común sin modificar: clase cromática, ataques a ±100 ms y final a `max(50 ms, 20 % de duración humana)` para el F1 adicional de finales.

## Resultado por canción

Porcentajes salvo F1. En cada pareja se muestra base → `events`, sin escoger variante por canción.

| Grabación | Clase correcta | Precisión del tiempo puntuable | Cobertura humana | F1 ataque y clase | F1 con final |
|---|---:|---:|---:|---:|---:|
| Amorfoda | 90,61 → 88,83 | 49,83 → 50,19 | 99,07 → 96,07 | 0,8756 → 0,8806 | 0,1244 → 0,1757 |
| 11 y 6 | 72,07 → 66,19 | 62,11 → 60,75 | 84,37 → 76,81 | 0,5237 → 0,5314 | 0,2429 → 0,2770 |
| Mr. Fancy Pants | 79,04 → 75,24 | 51,05 → 50,73 | 97,04 → 93,36 | 0,7531 → 0,7078 | 0,0823 → 0,1358 |
| Northern Star | 91,76 → 86,61 | 57,15 → 61,25 | 98,85 → 92,84 | 0,8394 → 0,8470 | 0,0683 → 0,0922 |

La mejora de finales no compensa las pérdidas. La precisión del tiempo puntuable mejora en dos casos y retrocede en dos; todavía queda muy lejos del control de 90 %. Amorfoda deja de pasar el control de clase del 90 % al reconstruir eventos. La variante `pitch` mejora ligeramente la clase de tres canciones y empeora Mr. Fancy Pants; no resuelve los intervalos ni añade ninguna aprobación.

| Mediana de las cuatro grabaciones | Base | Sólo alturas | Eventos, primario |
|---|---:|---:|---:|
| WER | 5,005 % | 5,005 % | 5,005 % |
| p90 del inicio de palabras coincidentes | 65 ms | 65 ms | 72,5 ms |
| Clase correcta | 84,825 % | 83,540 % | 80,925 % |
| Precisión del tiempo puntuable | 54,100 % | 53,630 % | 55,740 % |
| Cobertura humana | 97,945 % | 97,945 % | 93,100 % |
| F1 de ataque y clase | 0,79625 | 0,78190 | 0,77740 |
| F1 que incluye final | 0,10335 | 0,10040 | 0,15575 |
| Cinco controles / objetivo casi perfecto | 0/4 / 0/4 | 0/4 / 0/4 | 0/4 / 0/4 |

Las letras proceden de la base; no se ha probado aquí un reconocedor de palabras nuevo. En Amorfoda, 11 y 6, Mr. Fancy Pants y Northern Star el WER sigue siendo 1,38 %, 6,79 %, 6,64 % y 3,37 %. Las diferencias temporales de `events` proceden de la nueva proyección sobre notas. No se reinterpretan como una mejora de ASR.

## Eventos crudos, antes de construir el mapa

La evaluación adicional conserva emparejamiento cronológico uno a uno, sin pintar una única altura sobre una predicción polifónica. No utiliza los mapas proyectados para ocultar errores de la salida acústica.

| Grabación | F1 ataque y clase crudo | F1 con final crudo | Error absoluto de final p50 / p90 | Sesgo mediano de duración |
|---|---:|---:|---:|---:|
| Amorfoda | 0,8680 | 0,1700 | 88,8 / 152,9 ms | +108,9 ms |
| 11 y 6 | 0,5087 | 0,2607 | 54,6 / 187,0 ms | +78,1 ms |
| Mr. Fancy Pants | 0,6911 | 0,1123 | 106,1 / 206,1 ms | +81,7 ms |
| Northern Star | 0,8728 | 0,0965 | 140,0 / 327,7 ms | +125,0 ms |

El sesgo de duración y los errores de final describen sólo ataques emparejados; no todos los eventos. No se restó ese sesgo ni se eligieron umbrales después de medirlo. Cuatro bloques llegaron al máximo de 256 tokens sin EOS —dos del canal 5 en 11 y 6 y dos del canal 3 en Mr. Fancy Pants—; se conserva el diagnóstico de posible truncamiento sin atribuirlo automáticamente a la voz.

## Ejecución, revisión y evidencia

La tanda v2 termina en **326,625 s** en el Mac M4 real, CPU con dos hilos y un proceso nuevo por canción. Los cuatro trabajadores salen con código cero y quedan recogidos. Máximos observados: **2.211,28 MiB RSS y 2.128,72 MiB de huella física**, bajo la cuota declarada de 2.560 MiB. La lectura cada 50 ms no garantiza capturar todos los picos. La tanda anterior, detenida a 2 GiB, permanece preservada; el informe de investigación explica la revisión de recursos antes de fijar la nueva cuota.

Los 87 archivos de tokens de Amorfoda y ambos conjuntos vocales son idénticos byte a byte a los de la tanda anterior; las notas, canales y reparaciones crudos también coinciden, descontando sólo el tiempo de ejecución. Se comprobaron los 384 archivos del freeze y 349 matrices de tokens de v2. Esto valida la reproducción observada de esa canción, no una superioridad musical. No se reprodujo audio y el Mac permaneció silenciado. No se ejecutó este modelo en Windows ni en una máquina virtual.

[yourmt3_evaluate.py](../../scripts/experiments/yourmt3_evaluate.py) separa congelación y evaluación. Una revisión independiente y controles sintéticos verifican elegibilidad, conservación de casos inválidos como ausentes, emparejamiento polifónico uno a uno y rechazo de cambios en letras o mapas antes de interpretar referencias. El CSV contiene **120 filas**: tres conjuntos de cuarenta, con los ausentes explícitos, sin audio ni letras. Otra revisión concilió sus filas, campos, medianas, puertas y hashes con los JSON congelados, sin repetir inferencia ni métricas musicales; `review-export-result.json` conserva ese control.

- [CSV completo](generacion-yourmt3-2026-11-21.csv), SHA-256 `9e2c6cb53c4f82f5bf9a4a557ae51a85a59436d915fbfd4d19cb9fa3b5391718`.
- Protocolo previo: `map-evaluation-plan-v1.json`, SHA-256 `13bf73193782abefd6bd77971e3445e097a7eaa869c5bded5f168081dada34c1`.
- Predicciones: `pilot-v2/frozen.json`, SHA-256 `317f58edad55a7b302655e0150e399e9a0e35c2a41d63ac167ce3005f9c05e9a`.
- Mapas: `maps-v2/frozen.json`, SHA-256 `8e7c4a2f203117db8e62613512596c9049daf99db2c22a66fabdcfc1871c65d6`.
- Evaluación primaria: `maps-v2/events/evaluation.json`, SHA-256 `477c52ce0185735d2b9f82f2c4ac6dfce32e11e0300130c09a4d75c39b0b4ee4`.

Los artefactos locales están bajo `build/generation-next/yourmt3/`. `maps-v2/export_summary.py` conserva la exportación posterior a CSV y resumen; no produce notas. Para otra ejecución se requieren carpetas nuevas, fuentes compatibles con el protocolo y predicciones completas congeladas.
