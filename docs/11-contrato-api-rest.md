# Contrato API REST — DenunciaBot

> Contrato de consumo entre **SERCOP (proveedor)** y el **equipo de desarrollo de la Secretaría General de Integridad Pública (consumidor)**.
>
> Versión: **v1 — borrador para revisión en la reunión del 2 de junio 2026.**

---

## 1. Modelo de consumo

- **SERCOP entrega:** bot conversacional + base de datos + esta API REST.
- **Secretaría desarrolla:** frontend operativo (web, móvil, integraciones) sobre esta API, con SSO institucional y procedimientos internos propios.
- **Versionado:** prefijo `/api/v1/`. Cambios incompatibles → `/api/v2/` con período de coexistencia mínimo de 90 días.

## 2. Base URL

| Entorno | URL |
|---|---|
| Producción | `https://denuncia.secretaria.gob.ec/api/v1` |
| Staging | `https://denuncia-staging.secretaria.gob.ec/api/v1` |
| Local (dev) | `http://127.0.0.1:8000/api/v1` |

## 3. Autenticación

**Mecanismo:** clave por consumidor (API key) en encabezado HTTP.

```
GET /api/v1/alertas HTTP/1.1
X-API-Key: dnb_live_a1b2c3d4...
```

- SERCOP emite una `X-API-Key` distinta por (consumidor, entorno). Ej: dev y prod tienen claves separadas.
- Rotación trimestral, revocable inmediata ante incidente.
- Cada llamada se registra en `bitacora_auditoria` con el identificador de la clave (no se loguea la clave entera, solo prefijo + hash).
- **Sin clave válida → `401 Unauthorized`. Clave revocada → `403 Forbidden`.**

> La autenticación de los **funcionarios de la Secretaría hacia su propio frontend** la maneja la Secretaría (SSO, JWT, lo que decida). No es responsabilidad de SERCOP.

## 4. Convenciones generales

- **Formato:** JSON. `Content-Type: application/json`.
- **Códigos HTTP:** `200` éxito, `201` creación, `204` éxito sin cuerpo, `400` request inválido, `401` sin auth, `403` auth válida pero sin permiso, `404` no encontrado, `409` conflicto de estado, `422` validación, `429` rate limit, `500` error interno.
- **Errores:** envelope consistente:
  ```json
  {
    "error": {
      "codigo": "ALERTA_NO_ENCONTRADA",
      "mensaje": "No existe denuncia con el código indicado.",
      "detalle": {}
    }
  }
  ```
- **Fechas:** ISO 8601 UTC (`2026-06-02T14:30:00Z`).
- **Paginación:** estilo `page` + `size`; respuesta incluye `total`, `page`, `size`, `data`.
- **Rate limit:** 600 req/min por API key. Header de respuesta `X-RateLimit-Remaining`.

## 5. Endpoints (alcance v1)

### 5.1 Listar denuncias

```
GET /api/v1/alertas?estado=REGISTRADA&desde=2026-01-01&hasta=2026-06-30&page=1&size=50
```

**Filtros opcionales:** `estado`, `desde`, `hasta`, `page` (default 1), `size` (default 50, máx 200).

**Respuesta 200:**
```json
{
  "data": [
    {
      "codigo_publico": "ALR-2026-MJY3LW",
      "estado": "REGISTRADA",
      "fecha_registro": "2026-05-14T14:47:19Z",
      "fecha_actualizacion": "2026-05-14T14:47:19Z",
      "num_evidencias": 0
    }
  ],
  "total": 1,
  "page": 1,
  "size": 50
}
```

> **Solo metadata, sin campos sensibles descifrados.** Para detalle ver 5.2.

### 5.2 Detalle de una denuncia

```
GET /api/v1/alertas/{codigo_publico}
```

**Respuesta 200:**
```json
{
  "codigo_publico": "ALR-2026-MJY3LW",
  "estado": "REGISTRADA",
  "fecha_registro": "2026-05-14T14:47:19Z",
  "fecha_actualizacion": "2026-05-14T14:47:19Z",
  "institucion_denunciada": "Ministerio de Salud Pública",
  "descripcion_hechos": "Texto descifrado al vuelo de los hechos...",
  "fecha_aproximada_hechos": "15/03/2025",
  "personas_involucradas": "Juan Pérez, director administrativo",
  "perjuicio_economico": "aprox. 50000 USD",
  "denuncia_previa_otra_entidad": null,
  "evidencias": [
    {
      "id": "ev_a1b2c3",
      "nombre_original": "factura_falsificada.pdf",
      "mime_type": "application/pdf",
      "tamanio_bytes": 421337,
      "fecha_subida": "2026-05-14T14:45:02Z"
    }
  ]
}
```

> Los campos sensibles vienen **descifrados al vuelo** por SERCOP (que custodia la master key Fernet). El consumidor los recibe en claro sobre TLS — responsabilidad de la Secretaría protegerlos en su lado.

### 5.3 Cambiar estado

```
PATCH /api/v1/alertas/{codigo_publico}/estado
Content-Type: application/json

{
  "estado_nuevo": "EN_REVISION",
  "actor": "maria.perez@secretaria.gob.ec",
  "comentario": "Asignada a la dirección de investigaciones."
}
```

**Estados válidos:** `REGISTRADA` → `EN_REVISION` → `TRAMITADA` o `DESCARTADA`. Transiciones inválidas → `409 Conflict`.

**Respuesta 200:**
```json
{
  "codigo_publico": "ALR-2026-MJY3LW",
  "estado_anterior": "REGISTRADA",
  "estado_nuevo": "EN_REVISION",
  "fecha_cambio": "2026-06-02T15:30:00Z",
  "bitacora_id": 1234
}
```

> El campo `actor` es el correo institucional del funcionario que hace el cambio según el SSO de la Secretaría. SERCOP lo registra textualmente en la bitácora pero no lo verifica — la Secretaría es responsable de asegurar que `actor` corresponde al usuario autenticado en su frontend.

### 5.4 Descargar evidencia

```
GET /api/v1/alertas/{codigo_publico}/evidencias/{evidencia_id}
```

Devuelve el archivo binario con `Content-Type` original (`application/pdf`, `image/jpeg`, `image/png`). El `Content-Disposition` lleva el nombre original descifrado.

### 5.5 Export firmado de audit trail

```
GET /api/v1/audit-trail?desde=2026-01-01&hasta=2026-06-30
```

**Respuesta 200:**
```json
{
  "desde": "2026-01-01T00:00:00Z",
  "hasta": "2026-06-30T23:59:59Z",
  "registros": [ ... ],
  "firma_hmac_sha256": "a1b2c3d4...",
  "generado": "2026-06-02T16:00:00Z"
}
```

Verificable independientemente con el secret `AUDIT_HMAC_SECRET` (compartido con auditoría por canal seguro). Útil para procesos legales.

### 5.6 Estadísticas agregadas

```
GET /api/v1/stats?desde=2026-01-01&hasta=2026-06-30
```

**Respuesta 200:**
```json
{
  "total_denuncias": 142,
  "por_estado": {
    "REGISTRADA": 12,
    "EN_REVISION": 47,
    "TRAMITADA": 73,
    "DESCARTADA": 10
  },
  "promedio_dias_resolucion": 8.3
}
```

Sin PII. Útil para tableros públicos o reportes ejecutivos.

## 6. Garantías SERCOP

- **Disponibilidad mejor esfuerzo 24/7**, sin SLA contractual en v1 (definir con la Secretaría en posterior addendum).
- **Latencia objetivo:** `GET` < 300 ms p95, `PATCH` < 500 ms p95.
- **Versionado semántico** del contrato. Cambios breaking solo con `/api/v2/` y aviso ≥ 90 días.
- **Documentación OpenAPI 3.x** publicada en `/api/v1/openapi.json` y `/api/v1/docs` (Swagger UI).
- **Logs y bitácora** disponibles para la Secretaría bajo solicitud auditable.

## 7. Responsabilidades de la Secretaría

- **Custodiar la `X-API-Key`** como secreto (variable de entorno, vault, no en código).
- **Implementar autenticación de funcionarios** en su frontend (SSO o equivalente).
- **Reportar uso de campos descifrados** según su propia política de protección de datos.
- **Enviar el `actor` correcto** en cada `PATCH /estado`. SERCOP confía en lo que mande.
- **Notificar incidentes de seguridad** (clave filtrada, accesos sospechosos) en máximo 24 horas para rotación de la clave.

## 8. Roadmap (post-v1)

| Feature | Versión objetivo |
|---|---|
| Webhooks salientes (notificación push a la Secretaría cuando hay nueva denuncia) | v1.1 |
| Búsqueda por contenido descifrado | v1.2 |
| Comentarios de revisión asociados a la denuncia | v1.3 |
| OAuth 2.0 client credentials en vez de API key | v2.0 |
| GraphQL como alternativa al REST | Evaluar tras 6 meses |

## 9. Para revisar HOY en la reunión

- [ ] La Secretaría confirma que los endpoints 5.1–5.6 cubren su caso de uso.
- [ ] Se acuerda formato de `actor` en `PATCH /estado` (correo / cédula / id SSO).
- [ ] Se define quién en SERCOP emite las `X-API-Key` y por qué canal seguro se entregan.
- [ ] Se acuerda fecha tentativa de entrega de v1: ___________________
- [ ] Devs de la Secretaría confirman tecnología de su frontend para definir CORS y compatibilidad.

## 10. Próximos pasos

1. **SERCOP — Mau:** implementa endpoints 5.1–5.6 sobre la lógica ya existente del panel admin (la mayoría reutilizable). Sprint estimado: 2 semanas.
2. **Secretaría:** prepara entorno dev y prueba con `X-API-Key` de staging.
3. **Ambos:** sesión de revisión técnica de la API a la semana de entrega del borrador.
