"""Pruebas unitarias de reglas puras del dominio de seguridad."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.core.config import Configuracion
from app.modulos.seguridad import dominio


def test_politica_clave_valida_y_rechazos():
    dominio.validar_fortaleza_clave("ClaveFuerte99", "admin")

    for debil in ("Corta1A", "sinmayuscula1", "SINMINUSCULA1", "SinDigitosAbc", "MiAdmin2026!"):
        with pytest.raises(dominio.ErrorDominioSeguridad) as exc:
            dominio.validar_fortaleza_clave(debil, "admin")
        assert exc.value.status_code == 422


def test_bloqueo_por_cinco_intentos_fallidos():
    ahora = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)
    intentos = 0
    bloqueado_hasta = None
    for _ in range(4):
        intentos, bloqueado_hasta = dominio.calcular_estado_fallo_login(intentos, 5, 15, ahora)
        assert bloqueado_hasta is None

    intentos, bloqueado_hasta = dominio.calcular_estado_fallo_login(intentos, 5, 15, ahora)
    assert intentos == 5
    assert bloqueado_hasta == ahora + timedelta(minutes=15)
    assert dominio.evaluar_bloqueo(bloqueado_hasta, ahora + timedelta(minutes=1)) is True
    assert dominio.evaluar_bloqueo(bloqueado_hasta, ahora + timedelta(minutes=16)) is False


def test_evaluacion_acceso_sede():
    sede_mt = dominio.SedeEvaluacion(id=1, codigo="montelibano", nombre="Montelíbano", activa=True)
    sede_inactiva = dominio.SedeEvaluacion(id=3, codigo="inactiva", nombre="Inactiva", activa=False)

    with pytest.raises(dominio.ErrorDominioSeguridad) as sin_header:
        dominio.evaluar_acceso_sede(None, sede_mt, {1})
    assert sin_header.value.status_code == 400

    with pytest.raises(dominio.ErrorDominioSeguridad) as inexistente:
        dominio.evaluar_acceso_sede("otra", None, {1})
    assert inexistente.value.status_code == 403

    with pytest.raises(dominio.ErrorDominioSeguridad) as inactiva:
        dominio.evaluar_acceso_sede("inactiva", sede_inactiva, {1, 3})
    assert inactiva.value.status_code == 403

    with pytest.raises(dominio.ErrorDominioSeguridad) as no_asignada:
        dominio.evaluar_acceso_sede("montelibano", sede_mt, {2})
    assert no_asignada.value.status_code == 403

    assert dominio.evaluar_acceso_sede("montelibano", sede_mt, {1, 2}) == sede_mt


def test_permisos_y_consolidado():
    assert dominio.usuario_tiene_permiso({"seguridad.usuario.ver"}, "seguridad.usuario.ver")
    assert not dominio.usuario_tiene_permiso({"seguridad.usuario.ver"}, "seguridad.rol.editar")
    assert dominio.filtrar_sedes_consolidado([1, 2], {"tablero.consolidado.ver"}) == [1, 2]

    with pytest.raises(dominio.ErrorDominioSeguridad) as sin_perm:
        dominio.filtrar_sedes_consolidado([1], {"activos.luminaria.ver"})
    assert sin_perm.value.status_code == 403


def test_sanitizacion_diff_auditoria_elimina_secretos():
    antes, despues = dominio.construir_diff_auditoria(
        {"nombre": "Ana", "hash_clave": "secret1", "detalle": {"token": "abc"}},
        {"nombre": "Ana Maria", "clave_nueva": "X123", "activo": True},
    )
    assert antes == {"nombre": "Ana", "detalle": {}}
    assert despues == {"nombre": "Ana Maria", "activo": True}


def test_firma_token_acceso_y_cifrado_envio():
    secreto = "secreto-de-pruebas-super-largo-y-seguro-2026"
    ahora_ts = 1_800_000_000
    token = dominio.firmar_token_acceso({"sub": "10", "exp": ahora_ts + 60}, secreto)
    assert dominio.verificar_token_acceso(token, secreto, ahora_ts) == {
        "sub": "10",
        "exp": ahora_ts + 60,
    }
    assert dominio.verificar_token_acceso(token, secreto, ahora_ts + 61) is None
    assert dominio.verificar_token_acceso(token + "x", secreto, ahora_ts) is None
    assert dominio.verificar_token_acceso(token, "otro-secreto", ahora_ts) is None

    cifrado = dominio.cifrar_token_envio("mi-token-recuperacion", secreto)
    assert "mi-token-recuperacion" not in cifrado
    assert dominio.descifrar_token_envio(cifrado, secreto) == "mi-token-recuperacion"
    assert dominio.descifrar_token_envio(cifrado, "otro-secreto") is None


def test_configuracion_rechaza_secreto_debil_en_produccion():
    with pytest.raises(ValidationError):
        Configuracion(entorno="produccion")
    with pytest.raises(ValidationError):
        Configuracion(entorno="produccion", secret_key="corto")
    cfg = Configuracion(
        entorno="produccion",
        secret_key="9f8e7d6c5b4a39281726354453627180abcdef123456",
    )
    assert cfg.cookie_segura_efectiva is True
    # Staging también va detrás de HTTPS; solo desarrollo emite la cookie sin Secure.
    assert Configuracion(entorno="pruebas").cookie_segura_efectiva is True
    assert Configuracion(entorno="desarrollo").cookie_segura_efectiva is False
    assert Configuracion(entorno="pruebas", cookie_segura=False).cookie_segura_efectiva is False
