# ¿El ensamblado prolonga las notas de GAME?

En los **dos casos de desarrollo disponibles**, «Amorfoda» y «Northern Star», el error temporal está mayoritariamente presente en los eventos GAME guardados antes de ensamblarlos con las sílabas. Se reprodujeron **ocho pares de entrada/salida** —dos canciones por cuatro modos— y sus **dieciséis TXT congelados**, exactamente, sin ejecutar modelos ni GPU. Este resultado no se extrapola a las cuarenta canciones: sus trazas originales de GAME y CTC no están guardadas.

## Qué se compara

Los modos existentes son `free`, `syllables`, `spans` y `words`, bajo `build/generation-next/conditioned/`. No se repite su inferencia. Para cada modo se leen los eventos y el borrador predicho de partida. Se reproduce `melody_compare.transform`, capturando la salida real de `generation_worker.join_syllables_and_notes` antes de serializarla. Se comprueba que las variantes `pitch` y `events` coinciden con los SHA-256 de los TXT ya congelados. Sólo después se abre la referencia humana para descomponer el error.

Se distinguen tres estados: eventos guardados, notas ensambladas antes de cuantizar y TXT final. La contabilidad integra intervalos continuos usando todos sus extremos; no sustituye las métricas de admisión ni su rejilla de 10 ms. El tiempo erróneo comprende tanto una clase equivocada durante una nota humana como cualquier objetivo puntuable sin nota humana puntuable. Un hueco de la referencia no demuestra silencio acústico.

La documentación de GAME define `durations` en segundos y `presence` como una salida booleana. El adaptador fijado de Creator acumula esas duraciones y convierte esa marca a booleano, igual que el adaptador local de Tune Studio. No se encontró una confusión entre final absoluto y duración, ni entre probabilidad y marca de presencia. [Contrato ONNX original de GAME](https://github.com/openvpi/GAME/blob/main/ONNX.md).

## Resultado de los ocho pares

En los ocho casos, el ensamblado añade **0 s** a la unión de tiempo puntuable, cambia **0 s** de clase cromática y rellena **cero huecos** de la misma altura. Puede unir eventos contiguos en una barra más larga, pero eso no añade tiempo puntuable que antes estuviera vacío. El ensamblado elimina entre 0 y 2,003 s de los eventos guardados.

| Grabación | Modo | Tiempo puntuable en eventos guardados (s) | Tiempo retirado por ensamblado (s) | Error del TXT final (s) | Error ya presente con la misma clase antes de ensamblar |
|---|---|---:|---:|---:|---:|
| Amorfoda | `free` | 104,540 | 0,897 | 51,836 | 98,15 % |
| Amorfoda | `syllables` | 104,380 | 0,423 | 51,722 | 98,71 % |
| Amorfoda | `spans` | 104,470 | 0,443 | 51,733 | 98,71 % |
| Amorfoda | `words` | 103,760 | 0,447 | 51,627 | 98,58 % |
| Northern Star | `free` | 120,530 | 2,000 | 55,233 | 99,23 % |
| Northern Star | `syllables` | 120,730 | 2,003 | 56,175 | 99,41 % |
| Northern Star | `spans` | 108,890 | 0,000 | 45,808 | 99,39 % |
| Northern Star | `words` | 120,930 | 2,003 | 56,442 | 99,40 % |

En `free`, la partición del error final de «Amorfoda» es 50,878 s ya presentes con la misma clase, 0,097 s sin evento GAME anterior y 0,862 s con otra clase en ese instante anterior. En «Northern Star» son 54,807 s, 0,087 s y 0,340 s. Las dos últimas categorías aparecen después de cuantizar y resolver el orden de barras; no proceden de una ampliación de la unión temporal por `join`.

Así, el ensamblado no explica la mayor parte del error de duración de estos casos. La hipótesis de que sus fusiones rellenan muchos silencios queda descartada para estas ocho ejecuciones. El resultado orienta a comprobar cómo se decide el final y la presencia vocal antes de ese ensamblado.

## Límites de la atribución

- Los eventos guardados **ya pasaron** la selección de ventanas de doce segundos y la resolución de solapamientos. No se puede separar aquí el efecto del modelo del efecto de ese paso. Un ensayo posterior necesita guardar los eventos de cada ventana antes de combinarlos.
- `transform` reconstruye las sílabas desde un borrador que ya pasó por GAME. Sus finales pueden estar prolongados. No equivale a reproducir los tiempos CTC originales. Ambos lados de una comparación futura deben conservar esta misma interfaz o declarar el cambio de entrada.
- Este transformador pasa un contorno de frecuencia vacío a `join`. Los fragmentos sin evento GAME quedan libres; no se reproduce el recurso a FCPE que sí puede asignarles altura en producción. Por tanto, el resultado no descarta un problema en esa otra vía.
- La marca de origen de una parte melismática y el recurso al detector de frecuencia no se pueden reconstruir con certeza a partir de un TXT. Este diagnóstico no trata sus aproximaciones como trazas originales de `part`, `parts` o `fallback`.
- El JSON de eventos no tiene un hash propio dentro de la congelación original. Se conserva ahora su huella y se comprueba que produce exactamente los TXT originalmente congelados; no se presenta esta huella posterior como una declaración previa al ensayo.
- No se demuestra un defecto de código que justifique cambiar producción. Tampoco se demuestra que todas las prolongaciones sean silencio físico o que una única anotación humana agote las interpretaciones válidas.

## Hipótesis siguiente con datos ya disponibles

Se deja predeclarada, **sin generar ni evaluar candidatos todavía**, una alternativa distinta de los recortes por porcentaje, energía final y grafemas ya probados: acortar un final únicamente cuando dos transcriptores independientes coincidan en él. Puede usar los eventos SOME y ROSVOT ya guardados para las cuarenta grabaciones; no requiere otra inferencia.

El único candidato conservaría letra, altura y ataque de cada barra. Para cada modelo, emparejaría cronológicamente un evento de la misma clase con ataque a ±80 ms; escogería el ataque más próximo, resolvería empates por índice y no reutilizaría un evento. Sólo propondría un final cuando ambos finales difieran como máximo 40 ms, estén antes del final existente y el posterior de los dos deje al menos 80 ms desde el ataque de la barra. Se conservaría ese final posterior, redondeado a la rejilla actual; cualquier ambigüedad conservaría la barra original. No se modificarían barras libres ni se usarían referencias para elegir eventos, parámetros o canciones.

Antes de producir candidatos habría que congelar los hashes de los cuarenta borradores y ambos conjuntos de eventos, comprobar la identidad de sus voces y fijar la implementación. La evaluación posterior conservaría todas las métricas y puertas vigentes, mostraría las cuarenta parejas y separaría tiempo incorrecto retirado de canto correcto perdido. La hipótesis quedaría refutada si no reduce el error de finales o si elimina al menos tanto canto correcto como tiempo incorrecto. Una mejora parcial no demostraría fiabilidad casi perfecta ni autorizaría admisión automática. Estas cuarenta grabaciones siguen siendo desarrollo, no una reserva independiente.

## Reproducción

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 uv run python scripts/experiments/diagnose_game_join.py
```

[diagnose_game_join.py](../../scripts/experiments/diagnose_game_join.py) no escribe letras ni mapas. Guarda exclusivamente hashes, conteos y tiempos en `build/generation-next/error-diagnosis/game-join-diagnosis.json` y rechaza sobrescribirlo. Para repetir el diagnóstico se debe indicar otra ruta con `--output`.

Huellas de esta ejecución: script `d029e7bb70ed1783a7fac6baef42019405fde6a9932a682f21844c322a7c43e7`, ensamblador `42914898eb0180da3fe2d59d121295a629632e18fc000aecc4d37f4a09623333` y transformador `450f60fc82122d986d703a66926577f5175f2bd8447a7087c924e18da4631ead`. Los hashes de las entradas y los ocho resultados detallados quedan en el JSON. La reproducción exacta y las identidades de partición se comprobaron en menos de un segundo; Ruff y la comprobación de espacios pasan.
