# Centro de Operaciones Inteligentes — estado de integración

## Ejecutar

Desde la raíz del proyecto:

```powershell
python main.py
```

El visor Panda3D y el centro PySide6 abren ventanas separadas. `Alt+Tab` cambia entre ellas. `python main.py --no-3d` permite usar el centro sin la ciudad.

## Arquitectura que quedó conectada

- `CitySimulation` sigue siendo el coordinador de energía, GPON y agentes. El panel consulta sus modelos en memoria, así que los KPI y las tablas se alimentan del mismo ciclo que persiste la telemetría.
- `main.py` ejecuta la ciudad en un proceso Panda3D y la interfaz en PySide6. Colas locales de multiprocessing transportan mandos/selecciones en ambas direcciones sin bloquear el render ni tocar Qt desde el proceso de Panda.
- El dashboard está organizado en diez vistas: resumen, electricidad, GPON, IA, control urbano, alarmas, zonas, activos, reportes y configuración.
- El inventario de 5.000 ONT permanece en el modelo. La tabla GPON muestra 100 filas por página. Electricidad filtra por zona y estado; activos filtran por zona.
- La vista eléctrica incluye una curva reciente de demanda por zona. El detalle de ONT consulta en inventario la OLT, puerto PON, splitter, medidor/circuito, RX/TX, tráfico, energía y eventos relacionados.
- El reconocimiento/estado de alarma se guarda en `alarm_acknowledgements`. El CSV conserva ID, tiempo, zona, activo, severidad, evento, evidencia y estado.
- Seleccionar una fila de equipo o una ONT enfoca en 3D el equipo visible o el activo de su zona. Seleccionar un equipo en 3D abre Equipos y activos en el dashboard.
- Pausa/reanudación, reinicio confirmado, velocidad, día/tarde/noche/automático, zona y capas se operan desde la barra superior. El visor mantiene sus controles locales.
- Dentro del visor hay una barra translúcida agrupada en Simulación, Iluminación y Sectores. Los botones visibles son PAUSAR/REANUDAR, REINICIAR, AUTOMÁTICO, DÍA, TARDE, NOCHE, A–D, BAJA/MEDIA, RED ELÉCTRICA, RED GPON y AYUDA. AYUDA abre una tarjeta con instrucciones de cámara, teclado, tráfico, luces, zonas y capas.

## Verificación ejecutada

- `python -m py_compile` sobre el launcher, dashboard, puente 3D, servicio y repositorio: correcto.
- `python -m pytest -q`: **7 passed**.
- Prueba PySide6 `offscreen`: KPI 5.000, paginación de 100, inyección de falla, reconocimiento guardado y mando de selección a cola: correcto.
- Prueba Panda3D `offscreen`: 16 peatones y 16 vehículos, recepción de pausa, iluminación, enfoque de zona/ONT y reinicio: correcto.
- Prueba Panda3D de selección: el picker seleccionó `TX-A-01` y lo envió por la cola al dashboard: correcto.
- Inspección de captura Qt offscreen: el entorno no registró familias tipográficas disponibles (`QFontDatabase` vacía), por eso no es válida para revisar legibilidad; en el escritorio se solicita Segoe UI. El render visual final debe confirmarse en Windows interactivo.
- Punto previo a cambios V3: `backups\JONGOX_SMART_CITY_3D_before_v3_20261020_215805.zip` (código, pruebas y base SQLite). Verificado con `PRAGMA integrity_check = ok` y 5.000 ONT.

## Límites pendientes

- Los datos de energía y GPON son sintéticos. El pronóstico de carga y las reglas de los agentes son demostrativos, no modelos validados para campo.
- ONT y puertos PON no tienen 5.000 representaciones 3D individuales; se enfoca el equipo visible de su zona.
- Todavía faltan gráficos históricos/por zona, ficha completa de ruta óptica y tráfico, refresco de latido real, detalle topológico ampliado y mecanismos de reconexión del bus. Las colas actuales conectan mandos y selección, mientras el bus ZeroMQ sigue publicando telemetría para suscriptores externos.
- No se midió FPS ni RAM comparables LOW/MEDIUM en esta integración; por tanto no se declara cumplido el objetivo de 20–30 FPS.
- Qt y Panda3D se probaron por separado en modo offscreen para validar sus controles. Al final se inició `python main.py` en Windows y se confirmó que quedaron ejecutándose la ventana de Operaciones y el proceso de Panda3D. La revisión de fuente y controles se verificó en el render offscreen.

## Restaurar el punto anterior

Extraer el archivo sin sobrescribir el árbol actual:

```powershell
Expand-Archive .\backups\JONGOX_SMART_CITY_3D_before_v3_20261020_215805.zip .\backups\restore_before_v3
```

El directorio `backups\restore_before_v3` contiene el estado anterior completo y su inventario.

## Ajuste geométrico y consola visual

- Las avenidas principales miden 8 m de calzada (dos carriles) y tienen aceras de 1,8 m; la retícula se separó a 40 m para que edificios y fachadas queden fuera de sus calzadas.
- Cada manzana conserva una calle local de 5 m y aceras de 1 m. Los lotes usan huellas de hasta 2,6 m, con una separación mínima comprobada de 73 cm respecto al borde exterior de las aceras.
- Se mantienen las cantidades de edificios configuradas y se ampliaron de forma coordinada cruces, semáforos, recorridos vehiculares y peatonales.
- La consola del visor separa encabezado y barra de mandos; presenta tarjetas para Simulación, Iluminación y Sectores, con botones cian redondeados, texto negro en negrita y contorno rojo fino. Calidad y ciclo tienen una fila independiente.
- Validación de esta corrección: `python -m py_compile city3d\app.py city3d\layout.py`; `python -m pytest -q` (**10 passed**). Render Panda3D `offscreen`: 16 vehículos, 16 peatones y 4 sectores; captura visual revisada.
