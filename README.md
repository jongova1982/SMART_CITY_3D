# JONGOX SMART CITY 3D

Gemelo digital urbano académico con inventario GPON reproducible, simulación eléctrica simplificada, telemetría sintética, agentes de diagnóstico y visualización 3D. Los controles y fallas son simulados; el programa no se conecta ni controla infraestructura real.

## Requisitos y ejecución

La guía fija Windows y Python 3.11. El desarrollo de esta entrega se verificó en Python 3.14.6; instala las dependencias en el intérprete que vayas a usar:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m scripts.seed_city
python main.py
```

El NOC indica el estado de arranque de la ciudad 3D; cambia entre ventanas con `Alt+Tab`. Si Panda3D falla, revisa `data/city3d.log`. Para diagnosticar la ciudad sin el dashboard: `python main.py --city-only`. Para abrir solo el NOC: `python main.py --no-3d`.

`main.py` conserva el inventario si ya existe. `python main.py --seed` lo vuelve a generar con la semilla configurada. Para abrir solo el NOC usa `python main.py --no-3d`. La base por defecto está en `data/jongox_city.sqlite3`; `JONGOX_DATA_DIR` y `JONGOX_RANDOM_SEED` permiten cambiar ruta y semilla.

En el visor usa las flechas/WASD para navegar, Q/E para girar, rueda para zoom y `R` para restablecer c?mara. `1`/`2` alternan las capas el?ctricas/GPON. El centro de operaciones permite pausar/reanudar y reiniciar el modelo, ajustar velocidad, iluminaci?n, zona y capas; tambi?n enfoca en 3D los activos seleccionados en sus tablas. Las dos ventanas se ejecutan en procesos separados y se coordinan mediante colas locales.

## Estado de las etapas

- **1 — Base:** settings, SQLite WAL e inventario de 5.000 ONT, 80 puertos, cuatro zonas y asignaciones reproducibles; máximo nominal 64 ONT/PON.
- **2 — Ciudad 3D:** geometría procedural de bajo detalle para PC básico, cuatro barrios diferenciados, edificios por lotes, fachadas y ventanas agrupadas, calles con marcas, aceras, árboles y activos. La capa eléctrica se muestra azul y GPON rojo; hay leyenda, cámara orbital y resaltado de selección.
- **3 — Simulación:** reloj fijo, perfil eléctrico sintético, kW/kWh, tensión/corriente/factor de potencia, carga de transformador, pérdidas ópticas calculadas, tráfico sintético, autos animados en las calles, semáforos en ciclo rojo/verde/ámbar, luminarias cálidas encendidas y fallas de transformador/fibra/saturación/activos urbanos. La falla de transformador apaga ONT asociadas al circuito de la zona.
- **4 ? Eventos/persistencia:** contrato JSON version 1 validado con Pydantic, ZeroMQ PUB en `tcp://127.0.0.1:5557` y telemetria SQLite con retencion de 100.000 filas. Las colas locales llevan comandos y seleccion entre los dos procesos; ZeroMQ permanece disponible para suscriptores externos.
- **5 — Agentes:** seis clases independientes (energía, pronóstico de carga, GPON, pronóstico PON, urbano y correlación topológica). El pronóstico de bosque aleatorio se evalúa con una separación temporal 80/20 y MAE/RMSE; métricas de detección con etiquetas y persistencia/versionado de modelos quedan pendientes.
- **6 ? NOC:** centro PySide6 con diez secciones; KPI obtenidos de modelos en memoria, vista electrica con filtros, GPON paginado a 100 ONT por pagina, agentes, control urbano, alarmas persistidas y exportacion CSV. Incluye pausa, reinicio, velocidad, iluminacion, zona y capas.
- **7 ? Integracion:** `main.py` prepara el inventario e inicia Panda3D separado del dashboard/simulacion. Colas locales transportan mandos y selecciones. Para ONT sin representacion individual se enfoca el equipo visible de su zona. Cerrar el dashboard detiene el proceso Panda3D.
- **8 — Entrega:** benchmark de ciclo implementado. FPS gráfico y memoria no medidos; revise limitaciones abajo.

## Pruebas y benchmark

```powershell
python -m pytest -q
python -m scripts.benchmark --iterations 15
```

Verificado en este entorno: `5 passed`. Benchmark preliminar (5 ciclos, Python 3.14.6, equipo de ejecución actual): mediana 40.8 ms/ciclo, p95 43.0 ms/ciclo, 5.000 ONT en memoria lógica y 440 filas generadas. El benchmark usa una base temporal para no reemplazar el inventario de trabajo. No se midieron FPS Panda3D ni RAM; esa medición debe hacerse en el PC objetivo Windows 3.11.

## Modelo y límites

La carga eléctrica por zona es sintética y agregada, aunque energía se acumula por medidor con `kWh += kW × segundos / 3600`. La óptica GPON aplica pérdidas parametrizadas simplificadas. El pronóstico usa historial sintético determinista; las salidas de IA son demostrativas, no validan desempeño de campo. La implementación aún no satisface toda la integración distribuida, la selección 3D, los modelos evaluados/versionados ni las métricas de recursos exigidas por la guía.
