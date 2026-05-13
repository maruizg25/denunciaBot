"""
Tests del generador/verificador de audit trail.

Estos tests son puros (sin BD) — verifican que la cadena de hashes
detecta tampering y que el verificador es estricto.
"""

from __future__ import annotations

import json

import pytest

from app.services.audit_trail import (
    _hash_fila,
    verificar_audit_trail,
)


SECRET = "test-audit-secret-no-usar-en-produccion"


def _construir_trail_valido() -> list[str]:
    """Construye manualmente un trail de 3 filas con cadena válida."""
    import hashlib

    header = {
        "__header": True,
        "version": "1",
        "generado_en": "2026-05-12T00:00:00Z",
        "filtros": {"desde": None, "hasta": None},
    }
    header_line = json.dumps(header, ensure_ascii=False)
    hash_actual = hashlib.sha256(
        json.dumps(header, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    filas_raw = [
        {"id": 1, "alerta_id": None, "evento": "SESION_INICIADA", "actor": "SISTEMA", "detalle": None, "timestamp": "2026-05-12T10:00:00+00:00"},
        {"id": 2, "alerta_id": 5, "evento": "ALERTA_CREADA", "actor": "SISTEMA", "detalle": {"codigo_publico": "ALR-2026-AAAAAA"}, "timestamp": "2026-05-12T10:05:00+00:00"},
        {"id": 3, "alerta_id": 5, "evento": "ALERTA_ACTUALIZADA", "actor": "ADMIN:abc12345", "detalle": {"estado_anterior": "REGISTRADA", "estado_nuevo": "EN_REVISION"}, "timestamp": "2026-05-12T11:00:00+00:00"},
    ]

    lineas_filas = []
    for fila in filas_raw:
        hash_actual = _hash_fila(fila, hash_actual)
        salida = {**fila, "__hash": hash_actual}
        lineas_filas.append(json.dumps(salida, ensure_ascii=False))

    import hmac
    sello = {
        "__sello": True,
        "filas_totales": len(filas_raw),
        "ultimo_hash": hash_actual,
        "hmac_sha256": hmac.new(SECRET.encode(), hash_actual.encode(), hashlib.sha256).hexdigest(),
        "finalizado_en": "2026-05-12T12:00:00Z",
    }
    sello_line = json.dumps(sello, ensure_ascii=False)

    return [header_line, *lineas_filas, sello_line]


class TestVerificacionTrail:
    def test_trail_valido_verifica(self) -> None:
        lineas = _construir_trail_valido()
        ok, motivo = verificar_audit_trail(lineas, SECRET)
        assert ok, f"trail válido falló: {motivo}"
        assert motivo == "ok"

    def test_fila_modificada_detectada(self) -> None:
        """Si alguien edita 'detalle' de una fila intermedia, el verificador
        debe detectar que el hash ya no cuadra."""
        lineas = _construir_trail_valido()
        # Modificar la fila 2 (índice 2 incluyendo header en 0): cambiar el detalle
        fila_2 = json.loads(lineas[2])
        fila_2["detalle"] = {"codigo_publico": "ALR-2026-FALSIF"}
        lineas[2] = json.dumps(fila_2, ensure_ascii=False)

        ok, motivo = verificar_audit_trail(lineas, SECRET)
        assert not ok
        assert "hash inconsistente" in motivo

    def test_fila_borrada_detectada_via_contador(self) -> None:
        """Si alguien borra una fila del medio, el contador del sello
        deja de coincidir."""
        lineas = _construir_trail_valido()
        # Borrar fila intermedia (sin actualizar sello)
        lineas.pop(2)

        ok, motivo = verificar_audit_trail(lineas, SECRET)
        assert not ok

    def test_secret_incorrecto_detecta_falsificacion(self) -> None:
        lineas = _construir_trail_valido()
        ok, motivo = verificar_audit_trail(lineas, "otro-secret-incorrecto")
        assert not ok
        assert "HMAC" in motivo or "secret" in motivo.lower()

    def test_sello_alterado_detectado(self) -> None:
        """Si alguien cambia el hmac del sello, falla la verificación."""
        lineas = _construir_trail_valido()
        sello = json.loads(lineas[-1])
        sello["hmac_sha256"] = "0" * 64
        lineas[-1] = json.dumps(sello)

        ok, motivo = verificar_audit_trail(lineas, SECRET)
        assert not ok

    def test_trail_vacio_rechazado(self) -> None:
        ok, motivo = verificar_audit_trail([], SECRET)
        assert not ok
        assert "vacío" in motivo.lower()

    def test_header_faltante_detectado(self) -> None:
        lineas = _construir_trail_valido()
        # Reemplazar header por una fila normal
        lineas[0] = lineas[1]
        ok, motivo = verificar_audit_trail(lineas, SECRET)
        assert not ok


class TestHashFila:
    def test_hash_es_deterministico(self) -> None:
        fila = {"id": 1, "evento": "TEST", "detalle": {"a": 1, "b": 2}}
        h1 = _hash_fila(fila, "abc")
        h2 = _hash_fila(fila, "abc")
        assert h1 == h2

    def test_hash_cambia_con_diferente_anterior(self) -> None:
        fila = {"id": 1, "evento": "TEST"}
        h1 = _hash_fila(fila, "abc")
        h2 = _hash_fila(fila, "def")
        assert h1 != h2

    def test_hash_cambia_con_diferente_fila(self) -> None:
        h1 = _hash_fila({"id": 1}, "abc")
        h2 = _hash_fila({"id": 2}, "abc")
        assert h1 != h2

    def test_orden_de_claves_no_afecta(self) -> None:
        """JSON canónico debe normalizar el orden de claves."""
        h1 = _hash_fila({"a": 1, "b": 2}, "x")
        h2 = _hash_fila({"b": 2, "a": 1}, "x")
        assert h1 == h2
