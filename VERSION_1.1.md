# JONGOX SMART CITY 3D — Version 1.1

Copia preparada para publicar en GitHub. Incluye la interfaz de control con botones de alto contraste aplicada al visor 3D.

## Inicio rápido (Windows / Python 3.11)

```powershell
py -3.11 -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m scripts.seed_city
python main.py
```

No se incluyen bases de datos locales, registros, cachés ni archivos de respaldo. La ciudad se genera al iniciar con `python -m scripts.seed_city`.

