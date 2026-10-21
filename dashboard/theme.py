"""Shared visual style for the monitoring center."""

STYLE = """
QMainWindow,QWidget { background:#0b1220; color:#e2e8f0; font:10pt 'Segoe UI'; }
QFrame#Sidebar { background:#101a2b; border-right:1px solid #26364d; }
QLabel#Brand { color:#7dd3fc; font-size:16pt; font-weight:700; }
QLabel#Subbrand { color:#94a3b8; font-size:9pt; }
QLabel#PageTitle { color:#f1f5f9; font-size:19pt; font-weight:600; }
QLabel#Status { color:#86efac; padding:5px 10px; border:1px solid #24564a; border-radius:8px; }
QFrame#Card,QGroupBox { background:#111c2e; border:1px solid #24364d; border-radius:9px; }
QGroupBox { margin-top:10px; padding:12px; font-weight:600; color:#7dd3fc; }
QLabel#Metric { color:#7dd3fc; font-size:20pt; font-weight:700; }
QLabel#MetricTitle { color:#94a3b8; font-size:9pt; }
QPushButton,QComboBox,QLineEdit,QSpinBox { background:#17263a; border:1px solid #344a64; border-radius:5px; padding:7px; }
QPushButton:hover { background:#1e3a56; border-color:#38bdf8; }
QPushButton[nav="true"] { text-align:left; padding:10px; border:0; }
QPushButton[active="true"] { background:#123554; color:#7dd3fc; border-left:3px solid #38bdf8; }
QTableWidget { background:#0f1929; alternate-background-color:#142136; gridline-color:#25364b; border:1px solid #24364d; }
QHeaderView::section { background:#16263a; color:#bfdbfe; padding:7px; border:0; }
QStatusBar { background:#101a2b; color:#94a3b8; }
"""
