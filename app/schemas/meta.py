"""
Modelos Pydantic para parsear webhooks de Meta Cloud API (WhatsApp Business).

Solo modelamos los campos que usa el bot. Meta puede mandar muchas más cosas
(estados de entrega, plantillas, contactos, etc.) que ignoramos: por eso
todos los modelos tienen `extra="ignore"` y los campos opcionales abundan.

Estructura general del payload entrante:

    MetaWebhookPayload
    └─ entry: list[MetaEntry]
       └─ changes: list[MetaChange]
          └─ value: MetaValue
             ├─ messages: list[MetaMessage]   (solo si es un mensaje real)
             └─ statuses: list[MetaStatus]    (ignorados por el bot)

Cada `MetaMessage` puede ser:
  - texto plano (`type="text"`)
  - botón interactivo (`type="interactive"`)
  - imagen (`type="image"`)
  - documento PDF (`type="document"`)
  - otros que el bot no maneja (sticker, location, audio, video, etc.)
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


_BASE_CFG = ConfigDict(extra="ignore", populate_by_name=True)


# =========================================================================
# Contenidos por tipo de mensaje
# =========================================================================

class MetaText(BaseModel):
    model_config = _BASE_CFG
    body: str = ""


class MetaButtonReply(BaseModel):
    model_config = _BASE_CFG
    id: str
    title: str = ""


class MetaListReply(BaseModel):
    model_config = _BASE_CFG
    id: str
    title: str = ""
    description: str | None = None


class MetaInteractive(BaseModel):
    model_config = _BASE_CFG
    type: Literal["button_reply", "list_reply"] | str
    button_reply: MetaButtonReply | None = None
    list_reply: MetaListReply | None = None


class MetaImage(BaseModel):
    model_config = _BASE_CFG
    id: str
    mime_type: str = "image/jpeg"
    sha256: str | None = None
    caption: str | None = None


class MetaDocument(BaseModel):
    model_config = _BASE_CFG
    id: str
    mime_type: str = "application/pdf"
    sha256: str | None = None
    filename: str | None = None
    caption: str | None = None


# =========================================================================
# Mensaje entrante
# =========================================================================

class MetaMessage(BaseModel):
    """Un mensaje recibido del ciudadano.

    `from_` se mapea desde el campo `from` del JSON (palabra reservada en Python).
    `timestamp` viene como string (segundos epoch).
    """

    model_config = _BASE_CFG

    from_: str = Field(alias="from")
    id: str
    timestamp: str
    type: str  # "text" | "interactive" | "image" | "document" | otros

    text: MetaText | None = None
    interactive: MetaInteractive | None = None
    image: MetaImage | None = None
    document: MetaDocument | None = None


class MetaContact(BaseModel):
    model_config = _BASE_CFG
    wa_id: str
    profile: dict[str, Any] | None = None  # contiene 'name', no nos importa


class MetaMetadata(BaseModel):
    model_config = _BASE_CFG
    display_phone_number: str | None = None
    phone_number_id: str | None = None


# =========================================================================
# Status (deliveries, reads) — los ignoramos pero los modelamos para no fallar
# =========================================================================

class MetaStatus(BaseModel):
    model_config = _BASE_CFG
    id: str
    recipient_id: str | None = None
    status: str
    timestamp: str | None = None


# =========================================================================
# Envoltura
# =========================================================================

class MetaValue(BaseModel):
    model_config = _BASE_CFG
    messaging_product: str | None = None
    metadata: MetaMetadata | None = None
    contacts: list[MetaContact] = Field(default_factory=list)
    messages: list[MetaMessage] = Field(default_factory=list)
    statuses: list[MetaStatus] = Field(default_factory=list)


class MetaChange(BaseModel):
    model_config = _BASE_CFG
    field: str | None = None
    value: MetaValue


class MetaEntry(BaseModel):
    model_config = _BASE_CFG
    id: str | None = None
    changes: list[MetaChange] = Field(default_factory=list)


class MetaWebhookPayload(BaseModel):
    """Raíz del payload que Meta envía al webhook POST."""

    model_config = _BASE_CFG
    object: str | None = None
    entry: list[MetaEntry] = Field(default_factory=list)

    def mensajes_planos(self) -> list[MetaMessage]:
        """Atraviesa la estructura y devuelve solo los `MetaMessage`.

        Para volúmenes grandes esto sería ineficiente; en nuestro caso cada
        webhook trae típicamente 1 mensaje, así que aplanar es trivial.
        """
        salida: list[MetaMessage] = []
        for entry in self.entry:
            for change in entry.changes:
                salida.extend(change.value.messages)
        return salida
