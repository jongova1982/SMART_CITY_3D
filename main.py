"""Launch the monitoring dashboard and procedural 3D city."""
from __future__ import annotations

import argparse
import multiprocessing as mp
import sys
import traceback
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path


def _city_process(stop_event, command_queue=None, selection_queue=None):
    """Run Panda3D in an isolated process and preserve startup diagnostics."""
    log_path = Path(__file__).resolve().parent / "data" / "city3d.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with log_path.open("a", encoding="utf-8") as log, redirect_stdout(log), redirect_stderr(log):
            from city3d.app import SmartCityApp

            app = SmartCityApp(command_queue=command_queue, selection_queue=selection_queue)

            def watch_parent(task):
                if stop_event.is_set():
                    app.userExit()
                    return task.done
                return task.cont

            app.taskMgr.add(watch_parent, "supervisor-stop")
            try:
                app.run()
            except SystemExit:
                # Panda3D exits this way for a normal window close.
                pass
    except SystemExit:
        return
    except BaseException:
        with log_path.open("a", encoding="utf-8") as log:
            traceback.print_exc(file=log)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-3d", action="store_true", help="Run only the monitoring dashboard")
    parser.add_argument("--city-only", action="store_true", help="Run only the 3D city for diagnosis")
    parser.add_argument("--seed", action="store_true", help="Rebuild the deterministic logical inventory")
    args = parser.parse_args()

    if args.city_only:
        _city_process(mp.Event())
        return 0

    # Keep these imports inside main: Windows spawn re-imports this file in the
    # Panda3D child, which must not load the ML stack or the dashboard.
    from config.settings import load_settings
    from database.connection import connect, initialize_schema
    from scripts.seed_city import seed_city
    from simulation.service import CitySimulation
    from communications.broker import EventBroker
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from dashboard.app import MonitoringDashboard

    settings = load_settings()
    if args.seed or not settings.database_path.exists():
        seed_city(settings)
    conn = connect(settings.database_path)
    initialize_schema(conn)
    sim = CitySimulation(conn, settings.random_seed)
    broker = EventBroker()
    try:
        broker.start()
        sim.attach_broker(broker)
        print(f"Bus JSON local activo en {broker.endpoint}")
    except Exception as exc:
        broker.close()
        broker = None
        print(f"Bus ZeroMQ no disponible: {exc}")

    app = QApplication(sys.argv)
    city = None
    stop_city = None
    city_commands = None
    city_selections = None
    try:
        ctx = mp.get_context("spawn")
        city_commands = ctx.Queue(maxsize=128)
        city_selections = ctx.Queue(maxsize=128)
        window = MonitoringDashboard(sim, city_commands=city_commands, city_selections=city_selections)
        window.set_city_status("Ciudad 3D: iniciando…" if not args.no_3d else "Ciudad 3D: desactivada (--no-3d)")
        window.show()
        app.processEvents()

        if not args.no_3d:
            stop_city = ctx.Event()
            city = ctx.Process(target=_city_process, args=(stop_city, city_commands, city_selections), name="JONGOX-City3D", daemon=True)
            try:
                city.start()
                window.set_city_status("Ciudad 3D: iniciada. Usa Alt+Tab para cambiar de ventana.")
            except Exception as exc:
                window.set_city_status(f"Ciudad 3D: no inició ({exc})")

        monitor = QTimer(window)
        monitor.setInterval(1000)

        def check_city():
            if city is not None and not city.is_alive() and city.exitcode not in (None, 0):
                window.set_city_status(f"Ciudad 3D: error (código {city.exitcode}). Revisa data/city3d.log")

        monitor.timeout.connect(check_city)
        monitor.start()
        return app.exec()
    finally:
        if city and city.is_alive():
            stop_city.set()
            city.join(timeout=8)
            if city.is_alive():
                city.terminate()
                city.join(timeout=3)
        if broker:
            broker.close()
        for channel in (city_commands, city_selections):
            if channel is not None:
                channel.close()
                channel.join_thread()
        conn.close()


if __name__ == "__main__":
    main()
