"""
Máquina de estados conversacional de DenunciaBot.

ARQUITECTURA — separación de responsabilidades:

  El motor es PURO y SÍNCRONO. No habla con BD, Redis ni Meta directamente.
  Recibe la sesión actual + el mensaje entrante y devuelve:
    - la nueva sesión (o None si terminó),
    - una lista de `Accion` que el ORQUESTADOR (capa de services) ejecuta.

  Cada acción es un dataclass `frozen`: AccionEnviarTexto, AccionEnviarBotones,
  AccionGuardarSesion, AccionEliminarSesion, AccionRegistrarDenuncia, etc.
  El servicio que llama al motor traduce esas acciones a llamadas reales
  (httpx hacia Meta, INSERT en PostgreSQL, SET en Redis).

  Ventaja: el motor se testea sin BD ni Meta. Tests unitarios puros.

CONVENCIONES:
  - `sesion=None` significa "primer contacto" — el motor arranca en S0/S1.
  - `permanecer_en` mantiene el estado y normalmente acompaña un reintento.
  - El comando "cancelar" se atrapa antes de cualquier despacho por estado.
  - Los reintentos se cuentan en `sesion.intentos_estado` y al exceder
    `MAX_INTENTOS_VALIDACION` se cancela la sesión automáticamente.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Literal, Union

from app.conversacion import mensajes
from app.conversacion.estados import (
    EstadoSesion,
    es_terminal,
    permite_cancelar,
    siguiente_estado,
)
from app.conversacion.validadores import (
    es_comando_cancelar,
    es_indicador_no_tengo_mas,
    validar_aceptacion,
    validar_confirmacion,
    validar_denuncia_previa,
    validar_descripcion,
    validar_entidad_previa,
    validar_evidencia,
    validar_fecha,
    validar_institucion,
    validar_involucrados,
    validar_perjuicio,
)

# =========================================================================
# Tipos de entrada
# =========================================================================

@dataclass(frozen=True)
class EvidenciaEntrante:
    """Metadata de un archivo adjunto ya descargado por el orquestador.

    El binario y la ruta temporal los conserva el servicio. El motor solo
    necesita validar tipo y tamaño y, si todo OK, encolar la metadata en
    el buffer de la sesión para que S11 finalmente lo persista.
    """

    media_id: str
    mime: str
    tamanio_bytes: int
    nombre_original: str
    ruta_temporal: str  # path donde el orquestador guardó los bytes


@dataclass(frozen=True)
class Mensaje:
    """Input normalizado desde el webhook.

    Puede portar texto, un id de botón pulsado, una evidencia descargada,
    o combinación. Todos los campos son opcionales — el motor decide qué
    usar según el estado actual.
    """

    texto: str | None = None
    boton_id: str | None = None
    evidencia: EvidenciaEntrante | None = None
    message_id_meta: str | None = None  # para marcar como leído


@dataclass(frozen=True)
class Sesion:
    """Snapshot inmutable de una sesión en curso."""

    telefono_hash: str
    destinatario: str  # número en formato E.164 sin '+', para enviar mensajes
    estado_actual: EstadoSesion
    datos: dict[str, Any] = field(default_factory=dict)
    intentos_estado: int = 0


# =========================================================================
# Acciones — el motor las devuelve, el orquestador las ejecuta
# =========================================================================

@dataclass(frozen=True)
class AccionEnviarTexto:
    destinatario: str
    texto: str


@dataclass(frozen=True)
class AccionEnviarBotones:
    destinatario: str
    texto: str
    botones: tuple[tuple[str, str], ...]  # ((id, label), ...)


@dataclass(frozen=True)
class AccionMarcarLeido:
    message_id: str


@dataclass(frozen=True)
class AccionGuardarSesion:
    sesion: Sesion


@dataclass(frozen=True)
class AccionEliminarSesion:
    telefono_hash: str


@dataclass(frozen=True)
class AccionRegistrarDenuncia:
    """El servicio: genera código, cifra campos, persiste alerta + evidencias,
    inserta bitácora, encola notificación SMTP, y al terminar envía a
    Meta el mensaje de cierre con el código generado."""

    telefono_hash: str
    destinatario: str
    datos: dict[str, Any]


@dataclass(frozen=True)
class AccionRegistrarBitacora:
    evento: str
    detalle: dict[str, Any]
    alerta_id: int | None = None
    actor: str = "CIUDADANO"


Accion = Union[
    AccionEnviarTexto,
    AccionEnviarBotones,
    AccionMarcarLeido,
    AccionGuardarSesion,
    AccionEliminarSesion,
    AccionRegistrarDenuncia,
    AccionRegistrarBitacora,
]


@dataclass(frozen=True)
class ResultadoMotor:
    """Lo que el orquestador recibe: la nueva sesión (o None si terminó) y
    la lista ordenada de acciones a ejecutar."""

    nueva_sesion: Sesion | None
    acciones: tuple[Accion, ...]


# =========================================================================
# Claves del diccionario `sesion.datos` — usadas a lo largo del flujo
# =========================================================================

K_INSTITUCION = "institucion"
K_DESCRIPCION = "descripcion"
K_FECHA = "fecha"
K_INVOLUCRADOS = "involucrados"
K_PERJUICIO = "perjuicio"
K_DENUNCIA_PREVIA = "denuncia_previa"     # texto descriptivo o None
K_TIENE_DENUNCIA_PREVIA = "tiene_denuncia_previa"  # "SI"/"NO" intermedio
K_EVIDENCIAS = "evidencias"               # lista de dicts (metadata de cada adjunto)


# =========================================================================
# Punto de entrada principal
# =========================================================================

def procesar_mensaje(
    sesion: Sesion | None,
    mensaje: Mensaje,
    *,
    telefono_hash: str,
    destinatario: str,
    max_intentos: int = 3,
    max_evidencias: int = 5,
    tamanio_max_bytes: int = 10 * 1024 * 1024,
    mimes_permitidos: frozenset[str] = frozenset(
        {"application/pdf", "image/jpeg", "image/png"}
    ),
) -> ResultadoMotor:
    """Procesa un mensaje entrante y devuelve el resultado del motor.

    Args:
        sesion: snapshot actual (o None si es primer contacto).
        mensaje: input normalizado.
        telefono_hash: hash del teléfono, usado por el orquestador y bitácora.
        destinatario: número E.164 sin '+' para enviar respuestas a Meta.
        max_intentos: reintentos por estado antes de cancelar.
        max_evidencias / tamanio_max_bytes / mimes_permitidos: límites de S9.
    """
    acciones_iniciales: list[Accion] = []
    if mensaje.message_id_meta:
        acciones_iniciales.append(AccionMarcarLeido(mensaje.message_id_meta))

    # --- Caso 0: primer contacto ---
    if sesion is None:
        return _iniciar_sesion(
            telefono_hash=telefono_hash,
            destinatario=destinatario,
            acciones_iniciales=acciones_iniciales,
        )

    # --- Caso 1: estado terminal — ignorar mensajes posteriores ---
    if es_terminal(sesion.estado_actual):
        return ResultadoMotor(
            nueva_sesion=sesion,
            acciones=tuple(acciones_iniciales),
        )

    # --- Caso 2: comando "cancelar" detectado en estado cancelable ---
    if permite_cancelar(sesion.estado_actual) and es_comando_cancelar(
        mensaje.texto, mensaje.boton_id
    ):
        return _cancelar(
            sesion,
            destinatario,
            acciones_iniciales,
            motivo="usuario",
        )

    # --- Caso 3: despacho por estado actual ---
    despachadores = {
        EstadoSesion.S2_ACEPTACION: _procesar_S2,
        EstadoSesion.S3_INSTITUCION: _procesar_S3,
        EstadoSesion.S4_DESCRIPCION: _procesar_S4,
        EstadoSesion.S5_FECHA: _procesar_S5,
        EstadoSesion.S6_INVOLUCRADOS: _procesar_S6,
        EstadoSesion.S7_PERJUICIO: _procesar_S7,
        EstadoSesion.S8_DENUNCIA_PREVIA: _procesar_S8,
        EstadoSesion.S9_EVIDENCIA: _procesar_S9,
        EstadoSesion.S10_VALIDACION: _procesar_S10,
    }
    handler = despachadores.get(sesion.estado_actual)
    if handler is None:
        # Estado activo sin handler — bug o estado inalcanzable. Cancelamos
        # de forma defensiva en vez de quedarnos colgados.
        return _cancelar(
            sesion,
            destinatario,
            acciones_iniciales,
            motivo="estado_invalido",
        )

    return handler(
        sesion=sesion,
        mensaje=mensaje,
        destinatario=destinatario,
        max_intentos=max_intentos,
        max_evidencias=max_evidencias,
        tamanio_max_bytes=tamanio_max_bytes,
        mimes_permitidos=mimes_permitidos,
        acciones_previas=acciones_iniciales,
    )


# =========================================================================
# Helpers de construcción
# =========================================================================

def _iniciar_sesion(
    telefono_hash: str,
    destinatario: str,
    acciones_iniciales: list[Accion],
) -> ResultadoMotor:
    """Crea sesión nueva y manda bienvenida + pregunta de aceptación."""
    nueva = Sesion(
        telefono_hash=telefono_hash,
        destinatario=destinatario,
        estado_actual=EstadoSesion.S2_ACEPTACION,
        datos={},
        intentos_estado=0,
    )
    acciones: list[Accion] = list(acciones_iniciales)
    acciones.append(AccionEnviarTexto(destinatario, mensajes.bienvenida()))
    acciones.append(
        AccionEnviarBotones(
            destinatario,
            mensajes.solicitar_aceptacion(),
            botones=(
                (mensajes.BTN_ID_ACEPTAR, mensajes.BTN_LBL_ACEPTAR),
                (mensajes.BTN_ID_RECHAZAR, mensajes.BTN_LBL_RECHAZAR),
            ),
        )
    )
    acciones.append(AccionGuardarSesion(nueva))
    acciones.append(
        AccionRegistrarBitacora(
            evento="SESION_INICIADA",
            detalle={"estado": EstadoSesion.S2_ACEPTACION.value},
            actor="SISTEMA",
        )
    )
    return ResultadoMotor(nueva_sesion=nueva, acciones=tuple(acciones))


def _cancelar(
    sesion: Sesion,
    destinatario: str,
    acciones_previas: list[Accion],
    motivo: Literal["usuario", "agotamiento", "estado_invalido"],
) -> ResultadoMotor:
    """Cancela la sesión actual y borra el rastro mutable."""
    acciones: list[Accion] = list(acciones_previas)
    acciones.append(AccionEnviarTexto(destinatario, mensajes.cancelado_por_usuario()))
    acciones.append(AccionEliminarSesion(sesion.telefono_hash))
    acciones.append(
        AccionRegistrarBitacora(
            evento="SESION_CANCELADA",
            detalle={
                "motivo": motivo,
                "estado_al_cancelar": sesion.estado_actual.value,
                "intentos": sesion.intentos_estado,
            },
            actor="CIUDADANO" if motivo == "usuario" else "SISTEMA",
        )
    )
    return ResultadoMotor(nueva_sesion=None, acciones=tuple(acciones))


def _reintentar(
    sesion: Sesion,
    destinatario: str,
    texto_error: str,
    max_intentos: int,
    acciones_previas: list[Accion],
) -> ResultadoMotor:
    """Permanece en el mismo estado, incrementa el contador de intentos.
    Si se excede `max_intentos`, cancela en lugar de reintentar."""
    nuevos_intentos = sesion.intentos_estado + 1
    if nuevos_intentos >= max_intentos:
        return _cancelar(sesion, destinatario, acciones_previas, motivo="agotamiento")

    nueva = replace(sesion, intentos_estado=nuevos_intentos)
    acciones: list[Accion] = list(acciones_previas)
    acciones.append(AccionEnviarTexto(destinatario, texto_error))
    acciones.append(AccionGuardarSesion(nueva))
    acciones.append(
        AccionRegistrarBitacora(
            evento="VALIDACION_FALLIDA",
            detalle={
                "estado": sesion.estado_actual.value,
                "intentos": nuevos_intentos,
            },
            actor="SISTEMA",
        )
    )
    return ResultadoMotor(nueva_sesion=nueva, acciones=tuple(acciones))


def _avanzar(
    sesion: Sesion,
    nuevo_estado: EstadoSesion,
    datos_actualizados: dict[str, Any] | None,
    destinatario: str,
    texto_siguiente: str,
    botones_siguiente: tuple[tuple[str, str], ...] | None,
    acciones_previas: list[Accion],
) -> ResultadoMotor:
    """Cambia de estado, resetea intentos, envía el siguiente prompt."""
    datos = dict(sesion.datos)
    if datos_actualizados:
        datos.update(datos_actualizados)

    nueva = Sesion(
        telefono_hash=sesion.telefono_hash,
        destinatario=sesion.destinatario,
        estado_actual=nuevo_estado,
        datos=datos,
        intentos_estado=0,
    )
    acciones: list[Accion] = list(acciones_previas)
    if botones_siguiente:
        acciones.append(
            AccionEnviarBotones(destinatario, texto_siguiente, botones_siguiente)
        )
    else:
        acciones.append(AccionEnviarTexto(destinatario, texto_siguiente))
    acciones.append(AccionGuardarSesion(nueva))
    acciones.append(
        AccionRegistrarBitacora(
            evento="ESTADO_AVANZADO",
            detalle={
                "desde": sesion.estado_actual.value,
                "hasta": nuevo_estado.value,
            },
            actor="SISTEMA",
        )
    )
    return ResultadoMotor(nueva_sesion=nueva, acciones=tuple(acciones))


# =========================================================================
# Handlers por estado
# Cada uno tiene la misma firma para que el dispatch sea uniforme.
# =========================================================================

def _procesar_S2(
    sesion: Sesion,
    mensaje: Mensaje,
    destinatario: str,
    max_intentos: int,
    acciones_previas: list[Accion],
    **kwargs: Any,
) -> ResultadoMotor:
    """S2: aceptación de términos. SÍ → S3; NO → cancelar."""
    res = validar_aceptacion(mensaje.texto, mensaje.boton_id)

    if not res.valido:
        return _reintentar(
            sesion,
            destinatario,
            mensajes.aceptacion_invalida(
                intentos_restantes=max_intentos - sesion.intentos_estado - 1
            ),
            max_intentos,
            acciones_previas,
        )

    if res.valor_normalizado == "NO":
        return _cancelar(sesion, destinatario, acciones_previas, motivo="usuario")

    # SÍ → avanza a S3
    return _avanzar(
        sesion,
        EstadoSesion.S3_INSTITUCION,
        datos_actualizados=None,
        destinatario=destinatario,
        texto_siguiente=mensajes.solicitar_institucion(),
        botones_siguiente=None,
        acciones_previas=acciones_previas,
    )


def _procesar_S3(
    sesion: Sesion,
    mensaje: Mensaje,
    destinatario: str,
    max_intentos: int,
    acciones_previas: list[Accion],
    **kwargs: Any,
) -> ResultadoMotor:
    """S3: institución denunciada."""
    res = validar_institucion(mensaje.texto)
    if not res.valido:
        return _reintentar(
            sesion,
            destinatario,
            mensajes.institucion_invalida(
                intentos_restantes=max_intentos - sesion.intentos_estado - 1,
                motivo=res.motivo or "Entrada no válida.",
            ),
            max_intentos,
            acciones_previas,
        )
    return _avanzar(
        sesion,
        EstadoSesion.S4_DESCRIPCION,
        datos_actualizados={K_INSTITUCION: res.valor_normalizado},
        destinatario=destinatario,
        texto_siguiente=mensajes.solicitar_descripcion(),
        botones_siguiente=None,
        acciones_previas=acciones_previas,
    )


def _procesar_S4(
    sesion: Sesion,
    mensaje: Mensaje,
    destinatario: str,
    max_intentos: int,
    acciones_previas: list[Accion],
    **kwargs: Any,
) -> ResultadoMotor:
    """S4: descripción de hechos."""
    res = validar_descripcion(mensaje.texto)
    if not res.valido:
        return _reintentar(
            sesion,
            destinatario,
            mensajes.descripcion_invalida(
                intentos_restantes=max_intentos - sesion.intentos_estado - 1,
                motivo=res.motivo or "Entrada no válida.",
            ),
            max_intentos,
            acciones_previas,
        )
    return _avanzar(
        sesion,
        EstadoSesion.S5_FECHA,
        datos_actualizados={K_DESCRIPCION: res.valor_normalizado},
        destinatario=destinatario,
        texto_siguiente=mensajes.solicitar_fecha(),
        botones_siguiente=None,
        acciones_previas=acciones_previas,
    )


def _procesar_S5(
    sesion: Sesion,
    mensaje: Mensaje,
    destinatario: str,
    max_intentos: int,
    acciones_previas: list[Accion],
    **kwargs: Any,
) -> ResultadoMotor:
    """S5: fecha aproximada."""
    res = validar_fecha(mensaje.texto)
    if not res.valido:
        return _reintentar(
            sesion,
            destinatario,
            mensajes.fecha_invalida(
                intentos_restantes=max_intentos - sesion.intentos_estado - 1,
                motivo=res.motivo or "Fecha no reconocida.",
            ),
            max_intentos,
            acciones_previas,
        )
    return _avanzar(
        sesion,
        EstadoSesion.S6_INVOLUCRADOS,
        datos_actualizados={K_FECHA: res.valor_normalizado},
        destinatario=destinatario,
        texto_siguiente=mensajes.solicitar_involucrados(),
        botones_siguiente=None,
        acciones_previas=acciones_previas,
    )


def _procesar_S6(
    sesion: Sesion,
    mensaje: Mensaje,
    destinatario: str,
    max_intentos: int,
    acciones_previas: list[Accion],
    **kwargs: Any,
) -> ResultadoMotor:
    """S6: personas involucradas (opcional)."""
    res = validar_involucrados(mensaje.texto)
    if not res.valido:
        return _reintentar(
            sesion,
            destinatario,
            mensajes.comando_no_reconocido() + " " + (res.motivo or ""),
            max_intentos,
            acciones_previas,
        )
    return _avanzar(
        sesion,
        EstadoSesion.S7_PERJUICIO,
        datos_actualizados={K_INVOLUCRADOS: res.valor_normalizado},
        destinatario=destinatario,
        texto_siguiente=mensajes.solicitar_perjuicio(),
        botones_siguiente=None,
        acciones_previas=acciones_previas,
    )


def _procesar_S7(
    sesion: Sesion,
    mensaje: Mensaje,
    destinatario: str,
    max_intentos: int,
    acciones_previas: list[Accion],
    **kwargs: Any,
) -> ResultadoMotor:
    """S7: perjuicio económico (opcional)."""
    res = validar_perjuicio(mensaje.texto)
    if not res.valido:
        return _reintentar(
            sesion,
            destinatario,
            mensajes.comando_no_reconocido() + " " + (res.motivo or ""),
            max_intentos,
            acciones_previas,
        )
    return _avanzar(
        sesion,
        EstadoSesion.S8_DENUNCIA_PREVIA,
        datos_actualizados={K_PERJUICIO: res.valor_normalizado},
        destinatario=destinatario,
        texto_siguiente=mensajes.solicitar_denuncia_previa(),
        botones_siguiente=(
            (mensajes.BTN_ID_SI, mensajes.BTN_LBL_SI),
            (mensajes.BTN_ID_NO, mensajes.BTN_LBL_NO),
        ),
        acciones_previas=acciones_previas,
    )


def _procesar_S8(
    sesion: Sesion,
    mensaje: Mensaje,
    destinatario: str,
    max_intentos: int,
    acciones_previas: list[Accion],
    **kwargs: Any,
) -> ResultadoMotor:
    """S8: ¿denuncia previa? Si SÍ y aún no se ha pedido entidad → pedir.
    Si SÍ y ya hay entidad → guardar y avanzar. Si NO → avanzar."""
    # Sub-paso: si ya marcamos "tiene_denuncia_previa=SI" pero falta la entidad,
    # estamos esperando texto libre con la entidad.
    if sesion.datos.get(K_TIENE_DENUNCIA_PREVIA) == "SI" and K_DENUNCIA_PREVIA not in sesion.datos:
        res_entidad = validar_entidad_previa(mensaje.texto)
        if not res_entidad.valido:
            return _reintentar(
                sesion,
                destinatario,
                res_entidad.motivo or "Texto no válido.",
                max_intentos,
                acciones_previas,
            )
        return _avanzar(
            sesion,
            EstadoSesion.S9_EVIDENCIA,
            datos_actualizados={K_DENUNCIA_PREVIA: res_entidad.valor_normalizado},
            destinatario=destinatario,
            texto_siguiente=mensajes.solicitar_evidencias(
                max_archivos=kwargs.get("max_evidencias", 5),
                max_mb=int(kwargs.get("tamanio_max_bytes", 10 * 1024 * 1024) // (1024 * 1024)),
            ),
            botones_siguiente=None,
            acciones_previas=acciones_previas,
        )

    # Primer ingreso a S8: validar SÍ/NO
    res = validar_denuncia_previa(mensaje.texto, mensaje.boton_id)
    if not res.valido:
        return _reintentar(
            sesion,
            destinatario,
            mensajes.denuncia_previa_invalida(
                intentos_restantes=max_intentos - sesion.intentos_estado - 1
            ),
            max_intentos,
            acciones_previas,
        )

    if res.valor_normalizado == "NO":
        return _avanzar(
            sesion,
            EstadoSesion.S9_EVIDENCIA,
            datos_actualizados={
                K_TIENE_DENUNCIA_PREVIA: "NO",
                K_DENUNCIA_PREVIA: None,
            },
            destinatario=destinatario,
            texto_siguiente=mensajes.solicitar_evidencias(
                max_archivos=kwargs.get("max_evidencias", 5),
                max_mb=int(kwargs.get("tamanio_max_bytes", 10 * 1024 * 1024) // (1024 * 1024)),
            ),
            botones_siguiente=None,
            acciones_previas=acciones_previas,
        )

    # SÍ → permanecer en S8 con sub-flag activado para pedir la entidad
    datos = dict(sesion.datos)
    datos[K_TIENE_DENUNCIA_PREVIA] = "SI"
    nueva = Sesion(
        telefono_hash=sesion.telefono_hash,
        destinatario=sesion.destinatario,
        estado_actual=EstadoSesion.S8_DENUNCIA_PREVIA,
        datos=datos,
        intentos_estado=0,  # reseteamos porque la pregunta es distinta
    )
    acciones: list[Accion] = list(acciones_previas)
    acciones.append(AccionEnviarTexto(destinatario, mensajes.solicitar_entidad_previa()))
    acciones.append(AccionGuardarSesion(nueva))
    return ResultadoMotor(nueva_sesion=nueva, acciones=tuple(acciones))


def _procesar_S9(
    sesion: Sesion,
    mensaje: Mensaje,
    destinatario: str,
    max_intentos: int,
    acciones_previas: list[Accion],
    max_evidencias: int,
    tamanio_max_bytes: int,
    mimes_permitidos: frozenset[str],
    **kwargs: Any,
) -> ResultadoMotor:
    """S9: evidencias adjuntas. Acumula hasta max_evidencias o "no tengo más"."""
    evidencias_actuales: list[dict[str, Any]] = list(
        sesion.datos.get(K_EVIDENCIAS, [])
    )

    # Caso A: llegó un archivo
    if mensaje.evidencia is not None:
        if len(evidencias_actuales) >= max_evidencias:
            # No debería pasar porque deberíamos haber avanzado, pero defensivo
            return _avanzar_a_S10(sesion, destinatario, acciones_previas)

        res = validar_evidencia(
            tamanio_bytes=mensaje.evidencia.tamanio_bytes,
            mime=mensaje.evidencia.mime,
            mimes_permitidos=mimes_permitidos,
            tamanio_max_bytes=tamanio_max_bytes,
        )
        if not res.valido:
            texto_rechazo = _mensaje_rechazo_evidencia(res, tamanio_max_bytes, mimes_permitidos)
            # No cuenta como reintento del estado: el ciudadano puede mandar otro
            acciones: list[Accion] = list(acciones_previas)
            acciones.append(AccionEnviarTexto(destinatario, texto_rechazo))
            acciones.append(
                AccionRegistrarBitacora(
                    evento="EVIDENCIA_RECHAZADA",
                    detalle={"motivo": res.motivo, "mime": mensaje.evidencia.mime},
                    actor="SISTEMA",
                )
            )
            return ResultadoMotor(nueva_sesion=sesion, acciones=tuple(acciones))

        # Aceptada — agrega al buffer
        evidencias_actuales.append(
            {
                "media_id": mensaje.evidencia.media_id,
                "nombre_original": mensaje.evidencia.nombre_original,
                "mime": res.mime_normalizado,
                "tamanio_bytes": mensaje.evidencia.tamanio_bytes,
                "ruta_temporal": mensaje.evidencia.ruta_temporal,
            }
        )
        datos = dict(sesion.datos)
        datos[K_EVIDENCIAS] = evidencias_actuales
        nueva = replace(sesion, datos=datos, intentos_estado=0)

        acciones = list(acciones_previas)
        # ¿Llegamos al máximo? → avanzar
        if len(evidencias_actuales) >= max_evidencias:
            acciones.append(
                AccionEnviarTexto(
                    destinatario,
                    mensajes.evidencia_limite_alcanzado(max_evidencias),
                )
            )
            return _avanzar_a_S10(
                replace(nueva, intentos_estado=0),
                destinatario,
                acciones,
            )
        acciones.append(
            AccionEnviarTexto(
                destinatario,
                mensajes.evidencia_aceptada(
                    numero=len(evidencias_actuales), total=max_evidencias
                ),
            )
        )
        acciones.append(AccionGuardarSesion(nueva))
        acciones.append(
            AccionRegistrarBitacora(
                evento="EVIDENCIA_RECIBIDA",
                detalle={"numero": len(evidencias_actuales)},
                actor="SISTEMA",
            )
        )
        return ResultadoMotor(nueva_sesion=nueva, acciones=tuple(acciones))

    # Caso B: el ciudadano dijo "no tengo más"
    if es_indicador_no_tengo_mas(mensaje.texto, mensaje.boton_id):
        return _avanzar_a_S10(sesion, destinatario, acciones_previas)

    # Caso C: cualquier otra cosa — recordatorio
    acciones = list(acciones_previas)
    acciones.append(AccionEnviarTexto(destinatario, mensajes.comando_no_reconocido()))
    return ResultadoMotor(nueva_sesion=sesion, acciones=tuple(acciones))


def _procesar_S10(
    sesion: Sesion,
    mensaje: Mensaje,
    destinatario: str,
    max_intentos: int,
    acciones_previas: list[Accion],
    **kwargs: Any,
) -> ResultadoMotor:
    """S10: confirmar / editar / cancelar."""
    res = validar_confirmacion(mensaje.texto, mensaje.boton_id)
    if not res.valido:
        return _reintentar(
            sesion,
            destinatario,
            mensajes.validacion_invalida(
                intentos_restantes=max_intentos - sesion.intentos_estado - 1
            ),
            max_intentos,
            acciones_previas,
        )

    if res.valor_normalizado == "cancelar":
        return _cancelar(sesion, destinatario, acciones_previas, motivo="usuario")

    if res.valor_normalizado == "editar":
        # Volvemos a S3 preservando las evidencias ya validadas. Los campos
        # textuales se re-recolectan desde cero.
        datos_solo_evidencias = {K_EVIDENCIAS: sesion.datos.get(K_EVIDENCIAS, [])}
        nueva = Sesion(
            telefono_hash=sesion.telefono_hash,
            destinatario=sesion.destinatario,
            estado_actual=EstadoSesion.S3_INSTITUCION,
            datos=datos_solo_evidencias,
            intentos_estado=0,
        )
        acciones: list[Accion] = list(acciones_previas)
        acciones.append(
            AccionEnviarTexto(destinatario, mensajes.solicitar_institucion())
        )
        acciones.append(AccionGuardarSesion(nueva))
        acciones.append(
            AccionRegistrarBitacora(
                evento="ESTADO_AVANZADO",
                detalle={
                    "desde": EstadoSesion.S10_VALIDACION.value,
                    "hasta": EstadoSesion.S3_INSTITUCION.value,
                    "motivo": "edicion_por_usuario",
                },
                actor="CIUDADANO",
            )
        )
        return ResultadoMotor(nueva_sesion=nueva, acciones=tuple(acciones))

    # Confirmar → emitir AccionRegistrarDenuncia. NO guardamos la sesión
    # en S11 porque el orquestador la eliminará tras commit exitoso.
    # Si el registro falla, la sesión queda intacta en S10 (Redis) y el
    # ciudadano puede pulsar Confirmar de nuevo sin reescribir datos.
    acciones: list[Accion] = list(acciones_previas)
    acciones.append(
        AccionRegistrarDenuncia(
            telefono_hash=sesion.telefono_hash,
            destinatario=destinatario,
            datos=dict(sesion.datos),
        )
    )
    return ResultadoMotor(nueva_sesion=None, acciones=tuple(acciones))


# =========================================================================
# Helpers menores
# =========================================================================

def _avanzar_a_S10(
    sesion: Sesion,
    destinatario: str,
    acciones_previas: list[Accion],
) -> ResultadoMotor:
    """Construye el resumen y manda a S10 con botones."""
    datos = sesion.datos
    resumen = mensajes.mostrar_resumen(
        institucion=datos.get(K_INSTITUCION, "—"),
        descripcion=datos.get(K_DESCRIPCION, "—"),
        fecha=datos.get(K_FECHA, "—"),
        involucrados=datos.get(K_INVOLUCRADOS),
        perjuicio=datos.get(K_PERJUICIO),
        denuncia_previa=datos.get(K_DENUNCIA_PREVIA),
        num_evidencias=len(datos.get(K_EVIDENCIAS, [])),
    )
    return _avanzar(
        sesion,
        EstadoSesion.S10_VALIDACION,
        datos_actualizados=None,
        destinatario=destinatario,
        texto_siguiente=resumen,
        botones_siguiente=(
            (mensajes.BTN_ID_CONFIRMAR, mensajes.BTN_LBL_CONFIRMAR),
            (mensajes.BTN_ID_EDITAR, mensajes.BTN_LBL_EDITAR),
            (mensajes.BTN_ID_CANCELAR, mensajes.BTN_LBL_CANCELAR),
        ),
        acciones_previas=acciones_previas,
    )


def _mensaje_rechazo_evidencia(
    res, tamanio_max_bytes: int, mimes_permitidos: frozenset[str]
) -> str:
    """Construye el texto a enviar cuando una evidencia es rechazada."""
    if res.motivo == "tipo_no_permitido":
        return mensajes.evidencia_rechazada_tipo(
            mime_actual=res.detalle or "<desconocido>",
            permitidos=sorted(mimes_permitidos),
        )
    if res.motivo == "tamanio_excedido":
        mb_max = tamanio_max_bytes // (1024 * 1024)
        try:
            mb_actual = float(res.detalle.split()[0]) if res.detalle else 0.0
        except (ValueError, AttributeError):
            mb_actual = 0.0
        return mensajes.evidencia_rechazada_tamanio(mb=mb_actual, max_mb=mb_max)
    return mensajes.evidencia_rechazada_antivirus()


# =========================================================================
# Manejador de timeouts — el orquestador lo llama desde un job programado
# =========================================================================

def procesar_timeout(
    sesion: Sesion,
    fase: Literal["aviso", "cierre"],
) -> ResultadoMotor:
    """Genera las acciones para los timeouts de inactividad.

    Args:
        sesion: snapshot actual.
        fase: 'aviso' (a los 4 min) o 'cierre' (a los 5 min).
    """
    if fase == "aviso":
        acciones: list[Accion] = [
            AccionEnviarTexto(sesion.destinatario, mensajes.inactividad_aviso()),
            AccionRegistrarBitacora(
                evento="SESION_EXPIRADA",
                detalle={"fase": "aviso", "estado": sesion.estado_actual.value},
                actor="SISTEMA",
            ),
        ]
        # No cambiamos de estado; el aviso es transitorio.
        return ResultadoMotor(nueva_sesion=sesion, acciones=tuple(acciones))

    # fase == "cierre"
    acciones = [
        AccionEnviarTexto(sesion.destinatario, mensajes.inactividad_cierre()),
        AccionEliminarSesion(sesion.telefono_hash),
        AccionRegistrarBitacora(
            evento="SESION_EXPIRADA",
            detalle={"fase": "cierre", "estado": sesion.estado_actual.value},
            actor="SISTEMA",
        ),
    ]
    return ResultadoMotor(nueva_sesion=None, acciones=tuple(acciones))
