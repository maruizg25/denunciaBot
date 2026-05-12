"""
Schemas Pydantic para la entidad Alerta — RESERVADO para uso futuro.

Actualmente vacío a propósito. El bot no expone API REST de alertas en el
MVP: el flujo es uni-direccional (WhatsApp → BD → SMTP) y los CSVs se
generan vía `scripts/export_alertas.py`.

Cuando se agregue:
  - Panel admin con listado/búsqueda de denuncias
  - API REST para integración con otros sistemas institucionales
  - Endpoint público de consulta de estado por código de seguimiento

…los schemas de entrada/salida deben definirse aquí. Sugerencias:

    class AlertaResumen(BaseModel):
        codigo_publico: str
        estado: str
        timestamp_registro: datetime

    class AlertaDetalle(AlertaResumen):
        institucion_denunciada: str
        descripcion_hechos: str
        fecha_aproximada: str | None
        # ... el resto de campos DESCIFRADOS

    class EstadoUpdate(BaseModel):
        nuevo_estado: Literal["EN_REVISION", "TRAMITADA", "DESCARTADA"]
        nota: str | None = None

IMPORTANTE: cualquier schema que exponga campos sensibles requiere
auth obligatoria en el endpoint. NO crear un endpoint público de detalle
de denuncias sin verificación.
"""
