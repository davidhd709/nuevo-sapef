"""Pruebas del endpoint de salud y del formato de errores."""

from fastapi.testclient import TestClient

from app.core import salud as modulo_salud
from app.main import app

cliente = TestClient(app)


def test_salud_ok_con_base_disponible(monkeypatch):
    monkeypatch.setattr(
        modulo_salud, "comprobar_base_de_datos", lambda: {"postgres": "17.2", "postgis": "3.5.0"}
    )
    respuesta = cliente.get("/api/v1/salud")
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["estado"] == "ok"
    assert cuerpo["postgis"] == "3.5.0"
    assert "X-Request-Id" in respuesta.headers


def test_salud_degradada_sin_base(monkeypatch):
    def sin_base():
        raise ConnectionError("contraseña=secreta host=db")

    monkeypatch.setattr(modulo_salud, "comprobar_base_de_datos", sin_base)
    respuesta = cliente.get("/api/v1/salud")
    assert respuesta.status_code == 503
    assert respuesta.json()["base_de_datos"] == "no disponible"
    # El detalle del error nunca llega al cliente.
    assert "secreta" not in respuesta.text


def test_ruta_inexistente_responde_problem_json():
    respuesta = cliente.get("/api/v1/no-existe")
    assert respuesta.status_code == 404
    assert respuesta.headers["content-type"].startswith("application/problem+json")
    cuerpo = respuesta.json()
    assert cuerpo["status"] == 404
    assert "requestId" in cuerpo
