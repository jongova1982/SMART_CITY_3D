"""Spanish operations center connected to the live academic city model."""
from __future__ import annotations

import csv
import queue
import sys
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton, QSpinBox,
    QStackedWidget, QStatusBar, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget,
)

from dashboard.data_provider import SimulationData
from dashboard.theme import STYLE
from dashboard.widgets.trend_chart import DemandTrend


PAGES = ["Resumen general", "Red eléctrica", "Telecomunicaciones GPON",
         "Inteligencia artificial", "Control urbano", "Alarmas y eventos",
         "Zonas de la ciudad", "Equipos y activos", "Reportes", "Configuración"]


class MonitoringDashboard(QMainWindow):
    def __init__(self, simulation, interval_ms=1200, city_commands=None, city_selections=None):
        super().__init__()
        self.simulation = simulation
        self.data = SimulationData(simulation)
        self.city_commands = city_commands
        self.city_selections = city_selections
        self._paused = False
        self._zone_filter = "Todas"
        self._status_filter = "Todos"
        self._gpon_page = 0
        self._selected_asset = None
        self.setWindowTitle("JONGOX | Centro de Operaciones Inteligentes")
        self.resize(1440, 900)
        self.setMinimumSize(1080, 680)
        self.setStyleSheet(STYLE)

        root = QWidget()
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.sidebar = QFrame(objectName="Sidebar")
        self.sidebar.setFixedWidth(240)
        side = QVBoxLayout(self.sidebar)
        brand = QLabel("JONGOX | SMART CITY 3D", objectName="Brand")
        brand.setWordWrap(True)
        side.addWidget(brand)
        side.addWidget(QLabel("CENTRO DE OPERACIONES\nINTELIGENTES", objectName="Subbrand"))
        side.addSpacing(16)
        self.nav_buttons = []
        for index, name in enumerate(PAGES):
            button = QPushButton(f"{index+1:02d}   {name}")
            button.setProperty("nav", "true")
            button.clicked.connect(lambda _checked=False, idx=index: self.show_page(idx))
            side.addWidget(button)
            self.nav_buttons.append(button)
        side.addStretch(1)
        side.addWidget(QLabel("Gemelo digital académico\nDatos sintéticos · sin control real", objectName="Subbrand"))
        outer.addWidget(self.sidebar)

        body = QVBoxLayout()
        body.setContentsMargins(22, 16, 22, 12)
        body.setSpacing(12)
        outer.addLayout(body, 1)
        header = QHBoxLayout()
        title_stack = QVBoxLayout()
        self.page_title = QLabel(PAGES[0], objectName="PageTitle")
        self.subhead = QLabel("Supervisión de ciudad, energía, conectividad y operación urbana", objectName="Subbrand")
        title_stack.addWidget(self.page_title)
        title_stack.addWidget(self.subhead)
        header.addLayout(title_stack, 1)
        self.connection = QLabel("●  SIMULACIÓN LOCAL ACTIVA", objectName="Status")
        header.addWidget(self.connection)
        body.addLayout(header)
        self.city_status = QLabel("Visor 3D: iniciando")
        self.city_status.setStyleSheet("color:#93c5fd")
        body.addWidget(self.city_status)

        controls = QHBoxLayout()
        self.pause_button = QPushButton("Pausar")
        self.pause_button.clicked.connect(self.toggle_pause)
        controls.addWidget(self.pause_button)
        restart = QPushButton("Reiniciar simulación")
        restart.clicked.connect(self.reset_simulation)
        controls.addWidget(restart)
        controls.addWidget(QLabel("Velocidad"))
        self.speed = QComboBox()
        self.speed.addItem("0,5×", .5)
        self.speed.addItem("1×", 1.0)
        self.speed.addItem("2×", 2.0)
        self.speed.addItem("5×", 5.0)
        self.speed.setCurrentIndex(1)
        self.speed.currentIndexChanged.connect(self.change_speed)
        controls.addWidget(self.speed)
        controls.addWidget(QLabel("Iluminación"))
        self.time_mode = QComboBox()
        self.time_mode.addItem("Ciclo automático", "AUTO")
        self.time_mode.addItem("Día", "DAY")
        self.time_mode.addItem("Tarde", "AFTERNOON")
        self.time_mode.addItem("Noche", "NIGHT")
        self.time_mode.currentIndexChanged.connect(self.change_time)
        controls.addWidget(self.time_mode)
        self.zone_control = QComboBox()
        self.zone_control.addItems(["Zona A", "Zona B", "Zona C", "Zona D"])
        self.zone_control.currentIndexChanged.connect(lambda i: self._send_city({"action": "zone", "zone": "ABCD"[i]}))
        controls.addWidget(self.zone_control)
        self.layer_control = QComboBox()
        self.layer_control.addItem("Capas: completas", "both")
        self.layer_control.addItem("Red eléctrica", "electrical")
        self.layer_control.addItem("Red GPON", "gpon")
        self.layer_control.addItem("Ocultar redes", "none")
        self.layer_control.currentIndexChanged.connect(self.change_layers)
        controls.addWidget(self.layer_control)
        body.addLayout(controls)

        self.stack = QStackedWidget()
        body.addWidget(self.stack, 1)
        self.pages = []
        self.tables = {}
        self._make_pages()
        self.setCentralWidget(root)
        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Listo · métricas obtenidas de los modelos activos")

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(interval_ms)
        self.refresh()
        self.show_page(0)

    def _make_pages(self):
        for name in PAGES:
            page = QWidget()
            layout = QVBoxLayout(page)
            layout.setContentsMargins(0, 4, 0, 4)
            if name == "Resumen general":
                self.kpi_grid = QGridLayout()
                self.kpi_labels = {}
                metrics = [("ont_total", "Abonados GPON"), ("ont_online", "ONT conectadas"),
                           ("ont_offline", "ONT desconectadas"), ("pon_ports", "Puertos PON"),
                           ("power_kw", "Potencia instantánea · kW"), ("energy_kwh", "Energía acumulada · kWh"),
                           ("transformers", "Transformadores en servicio"), ("signals", "Semáforos operativos"),
                           ("lighting", "Luminarias activas"), ("alarms", "Alarmas críticas activas"),
                           ("agents", "Agentes de IA disponibles"), ("simulation_time", "Tiempo simulado · s")]
                for idx, (key, label) in enumerate(metrics):
                    card = QFrame(objectName="Card")
                    card_layout = QVBoxLayout(card)
                    value = QLabel("—", objectName="Metric")
                    title = QLabel(label, objectName="MetricTitle")
                    card_layout.addWidget(value)
                    card_layout.addWidget(title)
                    self.kpi_labels[key] = value
                    self.kpi_grid.addWidget(card, idx // 4, idx % 4)
                layout.addLayout(self.kpi_grid)
                layout.addWidget(QLabel("Indicadores actualizados desde la simulación activa. Las cifras son sintéticas."))
                self.tables[name] = self._table(layout, ["Zona", "Potencia kW", "Energía kWh", "Tensión V", "Carga TX %", "ONT en línea", "Estado"])
            elif name == "Red eléctrica":
                self._filters(layout, electrical=True)
                self.demand_chart = DemandTrend()
                layout.addWidget(self.demand_chart)
                self.tables[name] = self._table(layout, ["Medidor", "Zona", "Potencia kW", "Energía kWh", "Tensión V", "Corriente A", "FP", "Estado"])
            elif name == "Telecomunicaciones GPON":
                search_row = QHBoxLayout()
                self.gpon_search = QLineEdit()
                self.gpon_search.setPlaceholderText("Buscar identificador ONT o puerto PON")
                self.gpon_search.textChanged.connect(self._reset_gpon_page)
                search_row.addWidget(self.gpon_search, 1)
                self.gpon_info = QLabel("5.000 abonados lógicos · vista paginada de 100 filas")
                search_row.addWidget(self.gpon_info)
                layout.addLayout(search_row)
                self.tables[name] = self._table(layout, ["ONT", "Zona", "Puerto PON", "RX dBm", "Tráfico Mbps", "Enlace", "Alimentación"])
                self.ont_detail = QLabel("Selecciona una ONT para consultar su ruta, señal óptica, tráfico, alimentación y alarmas asociadas.")
                self.ont_detail.setWordWrap(True)
                self.ont_detail.setStyleSheet("background:#111c2e;border:1px solid #24364d;border-radius:8px;padding:10px;color:#cbd5e1")
                layout.addWidget(self.ont_detail)
                pager = QHBoxLayout()
                prev = QPushButton("Página anterior")
                prev.clicked.connect(lambda: self._turn_gpon(-1))
                nxt = QPushButton("Página siguiente")
                nxt.clicked.connect(lambda: self._turn_gpon(1))
                self.gpon_page_label = QLabel("Página 1")
                pager.addWidget(prev); pager.addWidget(self.gpon_page_label); pager.addWidget(nxt); pager.addStretch(1)
                layout.addLayout(pager)
                self.tables[name].cellClicked.connect(self._select_table_asset)
                self.tables[name].cellClicked.connect(self._show_ont_detail)
            elif name == "Inteligencia artificial":
                layout.addWidget(QLabel("Estado de agentes existentes y actividad observada. Pronósticos sintéticos identificados como tales."))
                self.tables[name] = self._table(layout, ["Agente", "Estado", "Último pulso", "Eventos recibidos", "Predicción / actividad", "Método / nota"])
            elif name == "Control urbano":
                layout.addWidget(QLabel("Activos urbanos simulados. Las fallas se pueden inyectar/restaurar desde controles de escenario."))
                self.tables[name] = self._table(layout, ["Activo", "Zona", "Tipo", "Estado"])
                self.tables[name].cellClicked.connect(self._select_table_asset)
            elif name == "Alarmas y eventos":
                row = QHBoxLayout()
                row.addWidget(QLabel("Inyectar escenario simulado"))
                self.fault_kind = QComboBox()
                self.fault_kind.addItems(["transformer_outage", "fiber_cut", "pon_saturation", "street_light_failure", "traffic_light_failure"])
                row.addWidget(self.fault_kind)
                self.fault_asset = QComboBox()
                self._refresh_fault_assets()
                self.fault_kind.currentTextChanged.connect(self._refresh_fault_assets)
                row.addWidget(self.fault_asset)
                inject = QPushButton("Inyectar falla")
                inject.clicked.connect(self.inject_fault)
                row.addWidget(inject)
                restore = QPushButton("Restaurar activo")
                restore.clicked.connect(self.restore_fault)
                row.addWidget(restore)
                export = QPushButton("Exportar CSV")
                export.clicked.connect(self.export_alarms)
                row.addWidget(export)
                acknowledge = QPushButton("Reconocer seleccionada")
                acknowledge.clicked.connect(self.acknowledge_selected_alarm)
                row.addWidget(acknowledge)
                self.alarm_status_control = QComboBox()
                self.alarm_status_control.addItems(["Reconocida", "En investigación", "Resuelta"])
                row.addWidget(self.alarm_status_control)
                update_status = QPushButton("Actualizar estado")
                update_status.clicked.connect(self.acknowledge_selected_alarm)
                row.addWidget(update_status)
                layout.addLayout(row)
                self.tables[name] = self._table(layout, ["ID", "Fecha UTC", "Zona", "Equipo", "Severidad", "Evento", "Descripción / evidencia", "Estado"])
                self.tables[name].cellClicked.connect(self._select_table_asset)
            elif name == "Zonas de la ciudad":
                layout.addWidget(QLabel("Resumen operativo por zona, alimentado por medidores y ONT simuladas."))
                self.tables[name] = self._table(layout, ["Zona", "Potencia kW", "Energía kWh", "Tensión V", "Carga TX %", "ONT en línea", "Transformador"])
            elif name == "Equipos y activos":
                row = QHBoxLayout()
                row.addWidget(QLabel("Filtrar por zona"))
                self.asset_zone = QComboBox(); self.asset_zone.addItems(["Todas", "A", "B", "C", "D"])
                self.asset_zone.currentTextChanged.connect(lambda _v: self.refresh())
                row.addWidget(self.asset_zone)
                row.addWidget(QLabel("Selecciona una fila para enfocar el activo en el visor 3D."))
                layout.addLayout(row)
                self.tables[name] = self._table(layout, ["ID activo", "Zona", "Tipo", "Estado"])
                self.tables[name].cellClicked.connect(self._select_table_asset)
            elif name == "Reportes":
                layout.addWidget(QLabel("Exportación de eventos y métricas actuales de operación."))
                export = QPushButton("Exportar alarmas/eventos a CSV")
                export.clicked.connect(self.export_alarms)
                layout.addWidget(export, alignment=Qt.AlignmentFlag.AlignLeft)
                self.report_text = QLabel("Los reportes muestran registros generados por el simulador. No representan mediciones de campo.")
                layout.addWidget(self.report_text)
                layout.addStretch(1)
            else:
                layout.addWidget(QLabel("Preferencias de presentación y operación local"))
                layout.addWidget(QLabel("Tema: azul oscuro · idioma: español · actualización de KPI: 1,2 s"))
                layout.addWidget(QLabel("Los mandos día/tarde/noche, zonas, capas y pausa están disponibles en la barra superior."))
                layout.addWidget(QLabel("El sistema es un gemelo digital académico y no controla infraestructura real."))
                layout.addStretch(1)
            self.stack.addWidget(page)
            self.pages.append(page)

    def _table(self, layout, headers):
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(table, 1)
        return table

    def _filters(self, layout, electrical=False):
        row = QHBoxLayout()
        row.addWidget(QLabel("Zona"))
        self.electrical_zone = QComboBox(); self.electrical_zone.addItems(["Todas", "A", "B", "C", "D"])
        self.electrical_zone.currentTextChanged.connect(lambda value: setattr(self, "_zone_filter", value) or self.refresh())
        row.addWidget(self.electrical_zone)
        row.addWidget(QLabel("Estado"))
        self.electrical_status = QComboBox(); self.electrical_status.addItems(["Todos", "Normal", "Sin servicio"])
        self.electrical_status.currentTextChanged.connect(lambda value: setattr(self, "_status_filter", value) or self.refresh())
        row.addWidget(self.electrical_status)
        row.addStretch(1)
        layout.addLayout(row)

    def show_page(self, index):
        self.stack.setCurrentIndex(index)
        self.page_title.setText(PAGES[index])
        for i, button in enumerate(self.nav_buttons):
            button.setProperty("active", i == index)
            button.style().unpolish(button); button.style().polish(button)
        self.refresh()

    def _populate(self, table, rows):
        table.setUpdatesEnabled(False)
        table.setRowCount(len(rows))
        for r, values in enumerate(rows):
            for c, value in enumerate(values):
                table.setItem(r, c, QTableWidgetItem(str(value)))
        table.setUpdatesEnabled(True)

    def refresh(self):
        try:
            if not self._paused:
                result = self.simulation.step()
            else:
                result = self.simulation.last_result or self.data.summary()
            self.connection.setText("●  SIMULACIÓN PAUSADA" if self._paused else "●  SIMULACIÓN LOCAL ACTIVA")
            self.connection.setStyleSheet("color:#86efac; padding:5px 10px; border:1px solid #24564a; border-radius:8px")
            summary = self.data.summary()
            if hasattr(self, "demand_chart"):
                self.demand_chart.add_sample(summary["zones"])
            self.city_status.setText(f"Visor 3D: activo · tiempo simulado {summary['simulation_time']:.0f} s · selección: {self._selected_asset or 'ninguna'}")
            if hasattr(self, "kpi_labels"):
                for key, label in self.kpi_labels.items():
                    value = summary[key]
                    label.setText(f"{value:,.2f}" if isinstance(value, float) else f"{value:,}")
            self._populate(self.tables["Resumen general"], self._zone_rows(summary, False))
            self._populate(self.tables["Zonas de la ciudad"], self._zone_rows(summary, True))
            if self.stack.currentIndex() == 1:
                rows = self.data.electrical_rows(self._zone_filter, self._status_filter)
                self._populate(self.tables["Red eléctrica"], [tuple(f"{v:.2f}" if isinstance(v, float) else v for v in r) for r in rows])
            elif self.stack.currentIndex() == 2:
                rows = self.data.gpon_rows(self.gpon_search.text(), self._gpon_page*100, 100)
                self._populate(self.tables["Telecomunicaciones GPON"], [tuple(f"{v:.2f}" if isinstance(v, float) else v for v in r) for r in rows])
                self.gpon_page_label.setText(f"Página {self._gpon_page+1} · {len(rows)} filas")
            elif self.stack.currentIndex() == 3:
                self._populate(self.tables["Inteligencia artificial"], self.data.agent_rows())
            elif self.stack.currentIndex() == 4:
                self._populate(self.tables["Control urbano"], self.data.urban_rows())
            elif self.stack.currentIndex() == 5:
                self._populate(self.tables["Alarmas y eventos"], self.data.alarm_rows())
            elif self.stack.currentIndex() == 7:
                zone = self.asset_zone.currentText()
                assets = self._asset_rows()
                self._populate(self.tables["Equipos y activos"], [r for r in assets if zone == "Todas" or r[1] == zone])
            self._drain_city_selections()
        except Exception as exc:
            self.connection.setText("●  DATOS OBSOLETOS / ERROR")
            self.connection.setStyleSheet("color:#fca5a5; padding:5px 10px; border:1px solid #7f1d1d; border-radius:8px")
            self.statusBar().showMessage(f"Error de actualización: {type(exc).__name__}: {exc}")

    def _zone_rows(self, summary, include_transformer):
        rows = []
        for zone, values in summary["zones"].items():
            state = "FALLA" if values["outage"] else "Normal"
            row = (f"Zona {zone}", f"{values['power_kw']:.2f}", f"{values['energy_kwh']:.3f}",
                   f"{values['voltage_v']:.1f}", f"{values['loading_pct']:.1f}", f"{values['ont_online']:,}")
            rows.append(row + (f"TX-{zone}-01 · {state}",) if include_transformer else row + (state,))
        return rows

    def _asset_rows(self):
        sim = self.simulation
        rows = []
        for asset_id, t in sim.grid.transformers.items():
            rows.append((asset_id, t.zone_id, "Transformador", "Falla" if t.outage else "Operativo"))
        for asset_id, state in sim.grid.traffic_lights.items():
            rows.append((asset_id, asset_id.split("-")[1], "Semáforo", "Operativo" if state else "Falla"))
        for asset_id, state in sim.grid.street_lights.items():
            rows.append((asset_id, asset_id.split("-")[1], "Alumbrado", "Activo" if state else "Falla"))
        ports = {}
        for state in sim.gpon.ont_states.values():
            ports[state["pon_port_id"]] = state["zone_id"]
        for port, zone in ports.items():
            rows.append((port, zone, "Puerto PON", "En servicio"))
        return rows

    def _select_table_asset(self, row, _column):
        table = self.stack.currentWidget().findChild(QTableWidget)
        if table and table.item(row, 0):
            asset_column = 3 if self.stack.currentIndex() == 5 else 0
            self._selected_asset = table.item(row, asset_column).text() if table.item(row, asset_column) else table.item(row, 0).text()
            self._send_city({"action": "select_asset", "asset_id": self._selected_asset})

    def _show_ont_detail(self, row, _column):
        table = self.tables.get("Telecomunicaciones GPON")
        if not table or not table.item(row, 0):
            return
        details = self.data.ont_details(table.item(row, 0).text())
        if not details:
            self.ont_detail.setText("Sin detalle disponible para este abonado.")
            return
        status = "Conectada" if details["online"] else "Desconectada"
        power = "Con energía" if details["powered"] else "Sin energía"
        alarm_count = len(details["alarms"])
        self.ont_detail.setText(
            f"{details['ont_id']} · Zona {details['zone_id']} · {status} · {power}  |  "
            f"Ruta: {details['olt_id']} → {details['pon_port_id']} → {details['splitter_id']} "
            f"(1:{details['split_ratio']}) → {details['meter_id']}  |  "
            f"RX {details['rx_dbm']:.2f} dBm · TX {details['tx_dbm']:.1f} dBm · "
            f"tráfico {details['traffic_mbps']:.2f} Mbps  |  "
            f"energía {details['energy_kwh']:.3f} kWh · {alarm_count} eventos asociados"
        )

    def acknowledge_selected_alarm(self):
        table = self.tables.get("Alarmas y eventos")
        row = table.currentRow() if table else -1
        if row < 0 or not table.item(row, 0):
            self.statusBar().showMessage("Selecciona una alarma para reconocerla")
            return
        from database.repository import acknowledge_alarm
        acknowledge_alarm(self.simulation.conn, table.item(row, 0).text(), self.alarm_status_control.currentText())
        self.refresh()

    def _send_city(self, payload):
        try:
            if self.city_commands is not None:
                self.city_commands.put_nowait(payload)
        except (queue.Full, OSError):
            self.statusBar().showMessage("No se pudo enviar el mando al visor 3D")

    def _drain_city_selections(self):
        if self.city_selections is None:
            return
        while True:
            try:
                event = self.city_selections.get_nowait()
            except (queue.Empty, OSError):
                break
            self._selected_asset = event.get("asset_id") if isinstance(event, dict) else str(event)
            self.statusBar().showMessage(f"Activo seleccionado en visor 3D: {self._selected_asset}")
            self.stack.setCurrentIndex(7)
            self.page_title.setText(PAGES[7])
            for index, button in enumerate(self.nav_buttons):
                button.setProperty("active", index == 7)
                button.style().unpolish(button); button.style().polish(button)
            rows = self._asset_rows()
            for index, value in enumerate(rows):
                if value[0] == self._selected_asset:
                    table = self.tables["Equipos y activos"]
                    table.selectRow(index)
                    break

    def toggle_pause(self):
        self._paused = not self._paused
        self.pause_button.setText("Reanudar" if self._paused else "Pausar")
        self._send_city({"action": "pause", "paused": self._paused})
        self.refresh()

    def reset_simulation(self):
        answer = QMessageBox.question(self, "Reiniciar simulación", "Se reiniciarán el reloj y los estados simulados. ¿Continuar?",
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                      QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.simulation.reset()
        self._paused = False
        self.pause_button.setText("Pausar")
        self._send_city({"action": "reset"})
        self.refresh()

    def change_speed(self, index):
        self.simulation.engine.step_seconds = self.speed.itemData(index)

    def change_time(self, index):
        self._send_city({"action": "time", "mode": self.time_mode.itemData(index)})

    def change_layers(self, index):
        mode = self.layer_control.itemData(index)
        self._send_city({"action": "layers", "mode": mode})

    def _reset_gpon_page(self, _text):
        self._gpon_page = 0
        self.refresh()

    def _turn_gpon(self, amount):
        self._gpon_page = max(0, self._gpon_page + amount)
        self.refresh()

    def _refresh_fault_assets(self, *_):
        if not hasattr(self, "fault_asset"):
            return
        kinds = {
            "transformer_outage": [f"TX-{z}-01" for z in "ABCD"],
            "fiber_cut": [f"PON-{i:03d}" for i in range(1, 81)],
            "pon_saturation": [f"PON-{i:03d}" for i in range(1, 81)],
            "street_light_failure": [f"LAMP-{z}-{i}" for z in "ABCD" for i in range(4)],
            "traffic_light_failure": [f"TL-{z}-01" for z in "ABCD"],
        }
        self.fault_asset.clear()
        self.fault_asset.addItems(kinds[self.fault_kind.currentText()])

    def inject_fault(self):
        self.simulation.inject(self.fault_kind.currentText(), self.fault_asset.currentText())
        self.refresh()

    def restore_fault(self):
        self.simulation.restore(self.fault_kind.currentText(), self.fault_asset.currentText())
        self.refresh()

    def export_alarms(self):
        path, _ = QFileDialog.getSaveFileName(self, "Exportar eventos", "jongox_eventos.csv", "CSV (*.csv)")
        if not path:
            return
        rows = self.data.alarm_rows()
        with open(path, "w", newline="", encoding="utf-8-sig") as output:
            writer = csv.writer(output)
            writer.writerow(["ID", "Fecha UTC", "Zona", "Equipo", "Severidad", "Evento", "Evidencia"])
            writer.writerows(rows)
        self.statusBar().showMessage(f"CSV exportado: {Path(path).name} · {len(rows)} registros")

    def set_city_status(self, text):
        self.city_status.setText(text)


def run_dashboard(simulation):
    app = QApplication.instance() or QApplication(sys.argv)
    window = MonitoringDashboard(simulation)
    window.show()
    return app.exec()
