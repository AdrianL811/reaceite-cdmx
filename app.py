"""Punto de entrada.

Desarrollo:   python app.py            (abre http://localhost:5000)
Producción:   gunicorn -w 1 --threads 8 -b 0.0.0.0:$PORT app:app
"""
import os

from reaceite import create_app

app = create_app()

if __name__ == "__main__":
    puerto = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=puerto, debug=False, threaded=True)
