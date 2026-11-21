# Carrera de recepción UDP en la prueba de voz móvil

La compilación [44942748050](https://github.com/AlexAmMo/karaoke/actions/runs/44942748050), sobre `c7d1dcbf80b7fc68c3adf9e4ed6742135e51ca3d`, falló únicamente en macOS. La variante de sustitución de una captura estéreo esperaba las secuencias `[3, 4]` y recibió `[3]`; las otras 250 pruebas pasaron. Linux y Windows terminaron correctamente. Se conserva el fallo original, sin sustituirlo por una repetición.

La prueba leía un socket UDP no bloqueante hasta el primer `BlockingIOError`, inmediatamente después de finalizar el emisor. Eso suponía que terminar `sendto` hacía legibles todos los datagramas en el receptor. Se reprodujo exactamente el síntoma aplazando sólo el segundo envío mediante `call_soon` al salir del contexto del emisor, sin pausas temporizadas ni micrófono: el código de producción había emitido `[3, 4]`, pero la prueba antigua observaba `[3]`.

Ese caso mínimo descarta que el emisor omitiera el bloque final, que el remuestreador lo retuviera o que se calculara mal la secuencia: ambos datagramas correctos habían pasado por `sendto`. La entrega aplazada hace fallar repetidamente la prueba antigua y pasa con la corrección. La evidencia reproduce una carrera suficiente para explicar el fallo de CI; no se ha instrumentado retrospectivamente el kernel de aquel runner.

Sólo cambia `tests/test_mobile_voice.py`. La lectura espera mediante `sock_recv` la colección esperada bajo un plazo global de dos segundos. Después conserva el drenaje de paquetes adicionales y la igualdad exacta de secuencias. No se añade un `sleep`, se limita una aserción ni se modifica `src/karaoke/mobile_voice.py`. Una prueba de regresión conduce el mismo puente real de remuestreo y UDP, aplaza el datagrama final y confirma los dos índices emitidos.

Validación local en el Mac, con salida silenciada y audio sintético:

- La nueva regresión falló antes del cambio con `[3] != [3, 4]`.
- Las 16 pruebas de voz móvil pasan en 0,49 s.
- La suite completa pasa: **252 pruebas en 19,40 s**.
- Ruff y `git diff --check` pasan.
- Una revisión independiente estática confirmó que se conservan orden, aserción exacta y comprobación de paquetes adicionales; no repitió la suite.

No se cargaron modelos durante este diagnóstico. Después se lanzó la [ejecución 44943417527](https://github.com/AlexAmMo/karaoke/actions/runs/44943417527) sobre `e1208c2`, que incluye la corrección: **252 pruebas macOS en 74,10 s**, **251 más una omisión en Ubuntu en 31,49 s** y **249 más tres omisiones en Windows en 54,25 s**. Las omisiones corresponden a la API nativa Apple y, en Windows, a los dos temporizadores POSIX. La ejecución termina correctamente en los tres sistemas; su log está en `ci-e1208c2-green.log`.

La evidencia local está en `build/ci-mobile-voice-44942748050/`: log original de CI, regresión roja anterior al cambio, reproducción pequeña marcada como diagnóstico y resumen de la suite. `diagnosis.json` tiene SHA-256 `e52c81d71777b3b8da1be3da21e4f7b92cecae08f2cca9ce71737d1fbf25a4a9`; el log original tiene SHA-256 `52a343174543b935d02ca5b43bcc51f2e26513e925a6ffe9b252790b71ea56f5`.

```sh
uv run pytest -q tests/test_mobile_voice.py
uv run python build/ci-mobile-voice-44942748050/reproduce_delayed_udp.py
```
