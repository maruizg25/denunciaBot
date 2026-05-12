"""
Catálogo de mensajes que el bot envía al ciudadano.

Todos los textos están centralizados aquí para que:
  - Las áreas de comunicación y legal puedan revisar redacción sin
    tocar lógica de la máquina.
  - El motor solo se preocupe por QUÉ enviar, no por CÓMO redactarlo.
  - Sea trivial cambiar tono, agregar acuses de recibo, o traducir.

Formato WhatsApp soportado:
  *negrita* | _itálica_ | ~tachado~ | ```código```

Tono: institucional formal, sobrio, respetuoso. Sin emojis.
"""

from __future__ import annotations

from typing import Final

# =========================================================================
# Constantes — etiquetas de botones, comandos
# =========================================================================

# IDs (vienen de vuelta en el webhook al pulsar un botón)
BTN_ID_ACEPTAR: Final[str] = "aceptar"
BTN_ID_RECHAZAR: Final[str] = "rechazar"
BTN_ID_CONFIRMAR: Final[str] = "confirmar"
BTN_ID_EDITAR: Final[str] = "editar"
BTN_ID_CANCELAR: Final[str] = "cancelar"
BTN_ID_SI: Final[str] = "si"
BTN_ID_NO: Final[str] = "no"
BTN_ID_TERMINAR_EVIDENCIAS: Final[str] = "terminar_evidencias"

# Etiquetas visibles
BTN_LBL_ACEPTAR: Final[str] = "Sí, acepto"
BTN_LBL_RECHAZAR: Final[str] = "No, cancelar"
BTN_LBL_CONFIRMAR: Final[str] = "Confirmar"
BTN_LBL_EDITAR: Final[str] = "Editar"
BTN_LBL_CANCELAR: Final[str] = "Cancelar"
BTN_LBL_SI: Final[str] = "Sí"
BTN_LBL_NO: Final[str] = "No"
BTN_LBL_TERMINAR_EVIDENCIAS: Final[str] = "No tengo más"

# Palabra clave para cancelar desde texto libre
COMANDO_CANCELAR: Final[str] = "cancelar"


# =========================================================================
# S1 — Bienvenida y consentimiento
# =========================================================================

def bienvenida() -> str:
    return (
        "*Bienvenido al sistema institucional de denuncias de corrupción*\n"
        "\n"
        "Este canal pertenece a la Secretaría General de Integridad Pública "
        "del Ecuador. A través de este chat usted podrá registrar de forma "
        "*confidencial* una denuncia ciudadana sobre presuntos hechos de "
        "corrupción en el sector público.\n"
        "\n"
        "*Antes de continuar, por favor lea con atención:*\n"
        "\n"
        "• Su número de teléfono *no* se almacena en claro.\n"
        "• Su denuncia es confidencial y se cifra antes de almacenarse.\n"
        "• Al finalizar recibirá un *código de seguimiento* único.\n"
        "• Puede escribir la palabra *cancelar* en cualquier momento para "
        "terminar el proceso sin guardar la información.\n"
        "• Si no responde durante 5 minutos la sesión se cerrará "
        "automáticamente.\n"
        "\n"
        "Le solicitaremos los siguientes datos: institución denunciada, "
        "descripción de los hechos, fecha aproximada, personas involucradas "
        "(opcional), perjuicio económico (opcional), denuncia previa en otra "
        "entidad (opcional) y evidencias en formato PDF, JPG o PNG (opcional)."
    )


def solicitar_aceptacion() -> str:
    return (
        "¿Acepta continuar con el registro de la denuncia bajo las "
        "condiciones indicadas?"
    )


# =========================================================================
# S2 — Reintento de aceptación / cancelación voluntaria
# =========================================================================

def aceptacion_invalida(intentos_restantes: int) -> str:
    if intentos_restantes <= 0:
        return (
            "No fue posible interpretar su respuesta. "
            "Hemos cerrado la sesión sin guardar información. "
            "Puede volver a escribirnos cuando lo desee."
        )
    return (
        "No pude interpretar su respuesta. Por favor responda con uno de "
        f"los botones, o escriba *Sí* o *No*. ({intentos_restantes} "
        "intento(s) restante(s))."
    )


# =========================================================================
# S3 — Institución
# =========================================================================

def solicitar_institucion() -> str:
    return (
        "*Paso 1 de 8.* Indique el nombre de la *institución, dependencia o "
        "entidad pública* sobre la cual presenta la denuncia.\n"
        "\n"
        "Ejemplos: \"Ministerio de Salud Pública\", \"GAD Municipal de "
        "Quito\", \"Hospital del Seguro Social en Guayaquil\"."
    )


def institucion_invalida(intentos_restantes: int, motivo: str) -> str:
    base = f"{motivo}"
    if intentos_restantes > 0:
        return f"{base} Por favor intente nuevamente ({intentos_restantes} restante(s))."
    return (
        f"{base} Hemos cerrado la sesión sin guardar información. "
        "Puede volver a escribirnos cuando lo desee."
    )


# =========================================================================
# S4 — Descripción
# =========================================================================

def solicitar_descripcion() -> str:
    return (
        "*Paso 2 de 8.* Describa de manera detallada los *hechos* que desea "
        "denunciar. Incluya, si los conoce: lugar, modalidad del presunto "
        "acto, montos involucrados, fechas relevantes y todo dato que "
        "considere útil para la investigación.\n"
        "\n"
        "Mínimo 30 caracteres, máximo 2000."
    )


def descripcion_invalida(intentos_restantes: int, motivo: str) -> str:
    return institucion_invalida(intentos_restantes, motivo)


# =========================================================================
# S5 — Fecha aproximada
# =========================================================================

def solicitar_fecha() -> str:
    return (
        "*Paso 3 de 8.* Indique la *fecha aproximada* en que ocurrieron los "
        "hechos.\n"
        "\n"
        "Formatos válidos:\n"
        "• Día/mes/año (ej. 15/03/2025)\n"
        "• Mes/año (ej. 03/2025)\n"
        "• Solo año (ej. 2025)\n"
        "• La frase *no recuerdo*"
    )


def fecha_invalida(intentos_restantes: int, motivo: str) -> str:
    return institucion_invalida(intentos_restantes, motivo)


# =========================================================================
# S6 — Personas involucradas (opcional)
# =========================================================================

def solicitar_involucrados() -> str:
    return (
        "*Paso 4 de 8.* Si conoce a las *personas presuntamente involucradas* "
        "indique nombres, cargos o cualquier referencia que pueda ayudar.\n"
        "\n"
        "Si no las conoce, escriba *no conozco* o *prefiero no decir*."
    )


# =========================================================================
# S7 — Perjuicio económico (opcional)
# =========================================================================

def solicitar_perjuicio() -> str:
    return (
        "*Paso 5 de 8.* Si conoce el *monto aproximado del perjuicio "
        "económico*, indíquelo (en dólares).\n"
        "\n"
        "Puede escribir un número, un rango (\"entre 5000 y 10000\") o "
        "*no aplica* / *no sé*."
    )


# =========================================================================
# S8 — Denuncia previa
# =========================================================================

def solicitar_denuncia_previa() -> str:
    return (
        "*Paso 6 de 8.* ¿Ha presentado *anteriormente* esta misma denuncia "
        "ante otra entidad (Fiscalía, Contraloría, otra)?"
    )


def solicitar_entidad_previa() -> str:
    return (
        "Indique brevemente *ante qué entidad* presentó la denuncia previa "
        "y, si lo recuerda, *cuándo* lo hizo."
    )


def denuncia_previa_invalida(intentos_restantes: int) -> str:
    if intentos_restantes <= 0:
        return (
            "No fue posible interpretar su respuesta. "
            "Hemos cerrado la sesión sin guardar información."
        )
    return (
        "Por favor responda con los botones, o escriba *Sí* o *No*. "
        f"({intentos_restantes} intento(s) restante(s))."
    )


# =========================================================================
# S9 — Evidencias
# =========================================================================

def solicitar_evidencias(max_archivos: int, max_mb: int) -> str:
    return (
        "*Paso 7 de 8.* Si dispone de *evidencias*, envíelas ahora.\n"
        "\n"
        f"• Formatos aceptados: PDF, JPG, PNG\n"
        f"• Tamaño máximo por archivo: {max_mb} MB\n"
        f"• Cantidad máxima: {max_archivos} archivos\n"
        "\n"
        "Envíe los archivos uno por uno. Cuando termine, pulse el botón "
        "*No tengo más* o escriba *no tengo*."
    )


def evidencia_aceptada(numero: int, total: int) -> str:
    return (
        f"Archivo {numero} de {total} máximo recibido correctamente. "
        "Puede enviar otro o escribir *no tengo* para continuar."
    )


def evidencia_rechazada_tipo(mime_actual: str, permitidos: list[str]) -> str:
    return (
        f"El archivo no fue aceptado: tipo *{mime_actual}* no permitido.\n"
        "\n"
        f"Tipos permitidos: {', '.join(permitidos)}.\n"
        "\n"
        "Envíe otro archivo o escriba *no tengo* para continuar."
    )


def evidencia_rechazada_tamanio(mb: float, max_mb: int) -> str:
    return (
        f"El archivo no fue aceptado: pesa {mb:.1f} MB y el máximo es "
        f"{max_mb} MB. Envíe otro archivo o escriba *no tengo* para continuar."
    )


def evidencia_rechazada_antivirus() -> str:
    return (
        "El archivo no fue aceptado por motivos de seguridad. "
        "Envíe otro archivo o escriba *no tengo* para continuar."
    )


def evidencia_limite_alcanzado(max_archivos: int) -> str:
    return (
        f"Ha alcanzado el límite de {max_archivos} archivos. "
        "Continuamos al siguiente paso."
    )


# =========================================================================
# S10 — Validación y resumen
# =========================================================================

def mostrar_resumen(
    institucion: str,
    descripcion: str,
    fecha: str,
    involucrados: str | None,
    perjuicio: str | None,
    denuncia_previa: str | None,
    num_evidencias: int,
) -> str:
    """Resumen para confirmación. La descripción se trunca para que el mensaje
    no exceda los 4096 chars permitidos por WhatsApp."""
    desc_corta = descripcion if len(descripcion) <= 300 else descripcion[:297] + "..."
    lineas = [
        "*Paso 8 de 8 — Resumen de su denuncia*",
        "",
        f"*Institución:* {institucion}",
        f"*Descripción:* {desc_corta}",
        f"*Fecha aproximada:* {fecha}",
    ]
    if involucrados:
        lineas.append(f"*Personas involucradas:* {involucrados}")
    if perjuicio:
        lineas.append(f"*Perjuicio económico:* {perjuicio}")
    if denuncia_previa:
        lineas.append(f"*Denuncia previa:* {denuncia_previa}")
    lineas.append(f"*Evidencias adjuntas:* {num_evidencias}")
    lineas.append("")
    lineas.append(
        "Si confirma, registraremos su denuncia y le entregaremos un código "
        "de seguimiento. Si desea modificar algún dato, pulse *Editar*."
    )
    return "\n".join(lineas)


def validacion_invalida(intentos_restantes: int) -> str:
    if intentos_restantes <= 0:
        return (
            "No fue posible interpretar su respuesta. "
            "Hemos cerrado la sesión sin guardar información."
        )
    return (
        "Por favor pulse uno de los botones: *Confirmar*, *Editar* o "
        f"*Cancelar*. ({intentos_restantes} intento(s) restante(s))."
    )


def solicitar_campo_a_editar() -> str:
    return (
        "¿Qué dato desea modificar? Escriba: "
        "*institución*, *descripción*, *fecha*, *involucrados*, "
        "*perjuicio*, *denuncia previa* o *evidencias*."
    )


# =========================================================================
# S12 — Cierre exitoso
# =========================================================================

def cierre_exitoso(codigo_publico: str) -> str:
    return (
        "*Su denuncia ha sido registrada exitosamente.*\n"
        "\n"
        f"*Código de seguimiento:* `{codigo_publico}`\n"
        "\n"
        "Conserve este código: le permitirá consultar el estado de su "
        "denuncia con la entidad. La información ha sido cifrada y enviada "
        "a la unidad correspondiente para su revisión.\n"
        "\n"
        "Gracias por colaborar con la integridad pública del Ecuador."
    )


# =========================================================================
# Cancelaciones y timeouts
# =========================================================================

def cancelado_por_usuario() -> str:
    return (
        "Hemos cancelado el proceso a su solicitud. "
        "Ninguna información fue guardada.\n"
        "\n"
        "Puede volver a escribirnos cuando lo desee."
    )


def inactividad_aviso(minutos_restantes: int = 1) -> str:
    return (
        "Notamos que ha pasado tiempo sin recibir respuesta. "
        f"Si no contesta en aproximadamente {minutos_restantes} minuto la "
        "sesión se cerrará automáticamente y no se guardará la información."
    )


def inactividad_cierre() -> str:
    return (
        "La sesión ha sido cerrada por inactividad. "
        "Ninguna información fue guardada. "
        "Puede volver a escribirnos cuando lo desee."
    )


# =========================================================================
# Errores genéricos / fuera de flujo
# =========================================================================

def comando_no_reconocido() -> str:
    return (
        "Por favor envíe una respuesta para continuar con el proceso, "
        "o escriba *cancelar* para terminar."
    )


def error_interno() -> str:
    """Mensaje genérico cuando ocurre un error técnico. NUNCA detalles internos."""
    return (
        "Ocurrió un inconveniente técnico al procesar su mensaje. "
        "Por favor intente nuevamente en unos minutos. "
        "Si el problema persiste, comuníquese con la institución por "
        "los canales oficiales."
    )


def fuera_de_horario() -> str:
    """Reservado para uso futuro si se quiere restringir horario de atención."""
    return (
        "Este canal recibe mensajes las 24 horas. Si su denuncia es de "
        "carácter urgente, le sugerimos comunicarse adicionalmente con "
        "las autoridades competentes."
    )
