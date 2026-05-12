"""
Tests del motor de conversación.

El motor es puro y síncrono — no requiere mocks de I/O. Solo verificamos
que las acciones emitidas y las transiciones de estado son correctas.
"""

from __future__ import annotations

import pytest

from app.conversacion import mensajes as MSG
from app.conversacion.motor import (
    AccionEliminarSesion,
    AccionEnviarBotones,
    AccionEnviarTexto,
    AccionGuardarSesion,
    AccionMarcarLeido,
    AccionRegistrarDenuncia,
    EvidenciaEntrante,
    K_DESCRIPCION,
    K_EVIDENCIAS,
    K_INSTITUCION,
    Mensaje,
    Sesion,
    procesar_mensaje,
    procesar_timeout,
)
from app.models.sesion import EstadoSesion


# =========================================================================
# Helpers
# =========================================================================

def _avanzar(sesion: Sesion | None, **mensaje_kwargs) -> tuple[Sesion | None, tuple]:
    """Atajo para invocar procesar_mensaje con telefono/destinatario fijos."""
    resultado = procesar_mensaje(
        sesion=sesion,
        mensaje=Mensaje(**mensaje_kwargs),
        telefono_hash="a" * 64,
        destinatario="593991234567",
    )
    return resultado.nueva_sesion, resultado.acciones


def _accion(acciones: tuple, tipo: type) -> object | None:
    """Devuelve la primera acción del tipo dado, o None."""
    for a in acciones:
        if isinstance(a, tipo):
            return a
    return None


# =========================================================================
# Primer contacto (S0 → S2)
# =========================================================================

class TestPrimerContacto:
    def test_sin_sesion_envia_bienvenida(self) -> None:
        sesion, acciones = _avanzar(None, texto="hola")
        assert sesion is not None
        assert sesion.estado_actual == EstadoSesion.S2_ACEPTACION
        assert _accion(acciones, AccionEnviarTexto) is not None
        assert _accion(acciones, AccionEnviarBotones) is not None

    def test_marca_leido_si_hay_message_id(self) -> None:
        _, acciones = _avanzar(None, texto="hola", message_id_meta="wamid.abc")
        leido = _accion(acciones, AccionMarcarLeido)
        assert leido is not None
        assert leido.message_id == "wamid.abc"

    def test_guarda_sesion_inicial(self) -> None:
        _, acciones = _avanzar(None, texto="hola")
        guardar = _accion(acciones, AccionGuardarSesion)
        assert guardar is not None
        assert guardar.sesion.estado_actual == EstadoSesion.S2_ACEPTACION
        assert guardar.sesion.intentos_estado == 0


# =========================================================================
# S2 — Aceptación
# =========================================================================

class TestS2Aceptacion:
    def _sesion_en_s2(self) -> Sesion:
        return Sesion(
            telefono_hash="a" * 64,
            destinatario="593991234567",
            estado_actual=EstadoSesion.S2_ACEPTACION,
        )

    def test_acepta_con_boton_avanza_a_s3(self) -> None:
        sesion, _ = _avanzar(self._sesion_en_s2(), boton_id=MSG.BTN_ID_ACEPTAR)
        assert sesion.estado_actual == EstadoSesion.S3_INSTITUCION

    def test_acepta_con_texto_si(self) -> None:
        sesion, _ = _avanzar(self._sesion_en_s2(), texto="sí")
        assert sesion.estado_actual == EstadoSesion.S3_INSTITUCION

    def test_rechazo_cancela(self) -> None:
        sesion, acciones = _avanzar(self._sesion_en_s2(), boton_id=MSG.BTN_ID_RECHAZAR)
        assert sesion is None
        assert _accion(acciones, AccionEliminarSesion) is not None

    def test_intento_invalido_incrementa_contador(self) -> None:
        sesion, _ = _avanzar(self._sesion_en_s2(), texto="quizás")
        assert sesion.estado_actual == EstadoSesion.S2_ACEPTACION
        assert sesion.intentos_estado == 1


# =========================================================================
# Reintentos y cancelación por agotamiento
# =========================================================================

class TestReintentos:
    def test_tres_intentos_invalidos_cancela(self) -> None:
        sesion = Sesion(
            telefono_hash="a" * 64,
            destinatario="593991234567",
            estado_actual=EstadoSesion.S3_INSTITUCION,
        )
        for _ in range(3):
            resultado = procesar_mensaje(
                sesion=sesion, mensaje=Mensaje(texto="X"),
                telefono_hash="a" * 64, destinatario="593991234567",
            )
            if resultado.nueva_sesion is None:
                break
            sesion = resultado.nueva_sesion
        assert resultado.nueva_sesion is None, "debió cancelar"
        assert _accion(resultado.acciones, AccionEliminarSesion) is not None

    def test_intento_exitoso_resetea_contador(self) -> None:
        # Primero un intento fallido
        sesion = Sesion(
            telefono_hash="a" * 64, destinatario="593991234567",
            estado_actual=EstadoSesion.S3_INSTITUCION,
        )
        sesion, _ = _avanzar(sesion, texto="X")
        assert sesion.intentos_estado == 1

        # Ahora válido → debe avanzar y resetear
        sesion, _ = _avanzar(sesion, texto="Ministerio válido")
        assert sesion.estado_actual == EstadoSesion.S4_DESCRIPCION
        assert sesion.intentos_estado == 0


# =========================================================================
# Cancelación voluntaria
# =========================================================================

class TestCancelacionVoluntaria:
    def test_cancelar_desde_s3(self) -> None:
        sesion = Sesion(
            telefono_hash="a" * 64, destinatario="593991234567",
            estado_actual=EstadoSesion.S3_INSTITUCION,
        )
        sesion, acciones = _avanzar(sesion, texto="cancelar")
        assert sesion is None
        assert _accion(acciones, AccionEliminarSesion) is not None


# =========================================================================
# Flujo feliz completo S0 → S10
# =========================================================================

class TestFlujoFelizCompleto:
    def test_camino_completo(self) -> None:
        sesion, _ = _avanzar(None, texto="hola")
        sesion, _ = _avanzar(sesion, boton_id=MSG.BTN_ID_ACEPTAR)
        sesion, _ = _avanzar(sesion, texto="Ministerio de Salud Pública")
        sesion, _ = _avanzar(sesion, texto="Descripción detallada de los hechos denunciados con suficiente contexto.")
        sesion, _ = _avanzar(sesion, texto="15/03/2025")
        sesion, _ = _avanzar(sesion, texto="Juan Pérez, director")
        sesion, _ = _avanzar(sesion, texto="aprox 50000")
        sesion, _ = _avanzar(sesion, boton_id=MSG.BTN_ID_NO)  # sin denuncia previa
        sesion, _ = _avanzar(sesion, texto="no tengo")        # sin evidencias

        assert sesion.estado_actual == EstadoSesion.S10_VALIDACION
        assert sesion.datos[K_INSTITUCION] == "Ministerio de Salud Pública"
        assert "Descripción detallada" in sesion.datos[K_DESCRIPCION]


# =========================================================================
# S10 — Confirmar / Editar / Cancelar
# =========================================================================

class TestS10:
    def _sesion_en_s10(self, evidencias: list | None = None) -> Sesion:
        return Sesion(
            telefono_hash="a" * 64, destinatario="593991234567",
            estado_actual=EstadoSesion.S10_VALIDACION,
            datos={
                K_INSTITUCION: "GAD Municipal",
                K_DESCRIPCION: "X" * 40,
                "fecha": "2025",
                "involucrados": None,
                "perjuicio": None,
                "denuncia_previa": None,
                K_EVIDENCIAS: evidencias or [],
            },
        )

    def test_confirmar_emite_registrar(self) -> None:
        sesion, acciones = _avanzar(
            self._sesion_en_s10(), boton_id=MSG.BTN_ID_CONFIRMAR,
        )
        assert sesion is None  # motor delega al orquestador la eliminación
        registrar = _accion(acciones, AccionRegistrarDenuncia)
        assert registrar is not None
        assert registrar.datos[K_INSTITUCION] == "GAD Municipal"

    def test_editar_vuelve_a_s3_preservando_evidencias(self) -> None:
        ev = [{"media_id": "x", "mime": "image/png"}]
        sesion, _ = _avanzar(self._sesion_en_s10(ev), boton_id=MSG.BTN_ID_EDITAR)
        assert sesion.estado_actual == EstadoSesion.S3_INSTITUCION
        assert sesion.datos[K_EVIDENCIAS] == ev
        # Los demás campos se borraron para re-recolectar
        assert K_INSTITUCION not in sesion.datos
        assert K_DESCRIPCION not in sesion.datos

    def test_cancelar_termina(self) -> None:
        sesion, acciones = _avanzar(
            self._sesion_en_s10(), boton_id=MSG.BTN_ID_CANCELAR,
        )
        assert sesion is None
        assert _accion(acciones, AccionEliminarSesion) is not None


# =========================================================================
# S9 — Evidencias
# =========================================================================

class TestS9Evidencias:
    def _sesion_en_s9(self, evidencias_buffer: list | None = None) -> Sesion:
        datos = {
            K_INSTITUCION: "X",
            K_DESCRIPCION: "Y" * 40,
            "fecha": "2025",
            K_EVIDENCIAS: evidencias_buffer or [],
        }
        return Sesion(
            telefono_hash="a" * 64, destinatario="593991234567",
            estado_actual=EstadoSesion.S9_EVIDENCIA, datos=datos,
        )

    def test_no_tengo_avanza_a_s10(self) -> None:
        sesion, _ = _avanzar(self._sesion_en_s9(), texto="no tengo")
        assert sesion.estado_actual == EstadoSesion.S10_VALIDACION

    def test_evidencia_valida_se_acumula(self) -> None:
        ev = EvidenciaEntrante(
            media_id="m1", mime="application/pdf",
            tamanio_bytes=100_000, nombre_original="doc.pdf",
            ruta_temporal="/tmp/x.tmp",
        )
        sesion, _ = _avanzar(self._sesion_en_s9(), evidencia=ev)
        assert sesion.estado_actual == EstadoSesion.S9_EVIDENCIA
        assert len(sesion.datos[K_EVIDENCIAS]) == 1
        assert sesion.datos[K_EVIDENCIAS][0]["media_id"] == "m1"

    def test_evidencia_tipo_invalido_no_se_acumula(self) -> None:
        ev = EvidenciaEntrante(
            media_id="m1", mime="application/zip",
            tamanio_bytes=100_000, nombre_original="doc.zip",
            ruta_temporal="/tmp/x.tmp",
        )
        sesion, _ = _avanzar(self._sesion_en_s9(), evidencia=ev)
        assert sesion.estado_actual == EstadoSesion.S9_EVIDENCIA
        assert sesion.datos[K_EVIDENCIAS] == []  # no se agregó

    def test_quinta_evidencia_avanza_a_s10(self) -> None:
        # Llenamos el buffer hasta el máximo permitido (default=5)
        buffer = [{"media_id": f"m{i}", "mime": "image/png"} for i in range(4)]
        ev = EvidenciaEntrante(
            media_id="m5", mime="image/png",
            tamanio_bytes=50_000, nombre_original="img.png",
            ruta_temporal="/tmp/x.tmp",
        )
        sesion, _ = _avanzar(self._sesion_en_s9(buffer), evidencia=ev)
        assert sesion.estado_actual == EstadoSesion.S10_VALIDACION
        assert len(sesion.datos[K_EVIDENCIAS]) == 5


# =========================================================================
# Timeouts
# =========================================================================

class TestTimeouts:
    def test_aviso_no_termina_sesion(self) -> None:
        sesion = Sesion(
            telefono_hash="a" * 64, destinatario="593991234567",
            estado_actual=EstadoSesion.S4_DESCRIPCION,
        )
        r = procesar_timeout(sesion, fase="aviso")
        assert r.nueva_sesion is not None
        assert r.nueva_sesion.estado_actual == EstadoSesion.S4_DESCRIPCION

    def test_cierre_elimina_sesion(self) -> None:
        sesion = Sesion(
            telefono_hash="a" * 64, destinatario="593991234567",
            estado_actual=EstadoSesion.S4_DESCRIPCION,
        )
        r = procesar_timeout(sesion, fase="cierre")
        assert r.nueva_sesion is None
        assert _accion(r.acciones, AccionEliminarSesion) is not None


# =========================================================================
# Estados terminales
# =========================================================================

class TestEstadoTerminal:
    def test_mensaje_a_sesion_terminal_se_ignora(self) -> None:
        # No debería pasar en la práctica (la sesión se borra al terminar),
        # pero el motor debe ser defensivo.
        sesion = Sesion(
            telefono_hash="a" * 64, destinatario="593991234567",
            estado_actual=EstadoSesion.CANCELADA,
        )
        r = procesar_mensaje(
            sesion=sesion, mensaje=Mensaje(texto="hola"),
            telefono_hash="a" * 64, destinatario="593991234567",
        )
        assert r.nueva_sesion == sesion  # no cambia
