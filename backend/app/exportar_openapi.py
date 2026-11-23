"""Escribe el contrato OpenAPI de la API en un archivo, sin levantar el servidor.

Uso:  python -m app.exportar_openapi ../frontend/packages/api/openapi.json
"""

import json
import sys
from pathlib import Path

from app.main import crear_app


def main() -> None:
    destino = Path(sys.argv[1] if len(sys.argv) > 1 else "openapi.json")
    esquema = crear_app().openapi()
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(esquema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"OpenAPI escrito en {destino} ({len(esquema.get('paths', {}))} rutas)")


if __name__ == "__main__":
    main()
