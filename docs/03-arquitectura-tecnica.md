# DenunciaBot — Arquitectura Técnica

**Documento de referencia para perfil técnico de la contraparte.**

Pensado para que el equipo técnico de la Secretaría (o un par técnico
designado) comprenda las decisiones de diseño, valide el cumplimiento
de buenas prácticas y pueda formular observaciones fundamentadas.

---

## 1. Vista general

DenunciaBot es una aplicación de tres capas, comunicada con servicios
externos por canales claramente delimitados.

```
                  ┌─────────────────────────────────────┐
                  │         Ciudadano (WhatsApp)        │
                  └──────────────────┬──────────────────┘
                                     │
                                     ▼
                  ┌─────────────────────────────────────┐
                  │        Meta Cloud API (WhatsApp     │
                  │        Business Platform)           │
                  └──────────────────┬──────────────────┘
                                     │ HTTPS + HMAC SHA-256
                                     ▼
       ┌──────────────────────────────────────────────────────┐
       │ Subdominio público (provisto por SERCOP Seguridad)   │
       │ Termina TLS y reenvía a 127.0.0.1:8000               │
       └──────────────────────┬───────────────────────────────┘
                              │
                              ▼
       ┌──────────────────────────────────────────────────────┐
       │ DenunciaBot — API (FastAPI / Python 3.11)            │
       │  - Endpoint /webhook (entrada de Meta)               │
       │  - Endpoint /alerta/{codigo} (consulta pública)      │
       │  - Endpoint /admin/* (panel administrativo)          │
       │  - Endpoint /metrics (observabilidad)                │
       └──────────────────────┬───────────────────────────────┘
                              │
            ┌─────────────────┼──────────────────┐
            ▼                 ▼                  ▼
   ┌────────────────┐ ┌───────────────┐ ┌──────────────────┐
   │ PostgreSQL 16  │ │  Redis 7      │ │ ClamAV (clamd)   │
   │  - alertas     │ │  - sesiones   │ │  - antivirus     │
   │  - evidencias  │ │  - cola jobs  │ │    de evidencias │
   │  - bitácora    │ │  - idempot.   │ │                  │
   │  - sesiones    │ └───────┬───────┘ └──────────────────┘
   │   (respaldo)   │         │
   └────────────────┘         ▼
                    ┌─────────────────────┐
                    │ Worker Dramatiq     │
                    │  - SMTP             │
                    │  - cierres a Meta   │
                    └─────────┬───────────┘
                              │
                              ▼
                    ┌─────────────────────┐
                    │ Buzón SMTP          │
                    │ institucional       │
                    │ (Secretaría)        │
                    └─────────────────────┘
```

## 2. Stack tecnológico

| Capa | Tecnología | Versión | Justificación |
|------|------------|---------|---------------|
| Lenguaje | Python | 3.11 | Soporte vigente hasta 2027, sintaxis moderna, ecosistema maduro |
| Framework web | FastAPI | 0.115 | Async nativo, validación con Pydantic, OpenAPI automático |
| ORM | SQLAlchemy | 2.0 | Estándar industrial, soporte async, control fino de transacciones |
| Driver de BD | asyncpg | 0.30 | Driver async oficial para PostgreSQL, alto rendimiento |
| Base de datos | PostgreSQL | 16 | Activos existentes en el SERCOP, soporte de JSONB, triggers PL/pgSQL |
| Migraciones | Alembic | 1.14 | Estándar para SQLAlchemy, idempotente, reversible |
| Validación | Pydantic | 2.10 | Tipado estático, integración con FastAPI |
| Cache + cola | Redis | 7 | Estándar industrial, TTL automático, atomicidad |
| Worker async | Dramatiq | 1.17 | Más simple que Celery, mejor mantenido para casos chicos |
| Cifrado | cryptography (Fernet) | 44 | Cifrado simétrico autenticado, librería oficial de PyCA |
| Antivirus | ClamAV (clamd) | 1.x | Solución de código abierto madura, ya provista por RHEL |
| Logs | structlog | 24.4 | Logs JSON estructurados, integración con SIEM |
| Métricas | prometheus-client | 0.21 | Formato OpenMetrics, estándar industrial |
| Rate limiting | slowapi | 0.1.9 | Integración nativa con FastAPI |
| Servidor ASGI | uvicorn + gunicorn | 0.32 / 23 | Estándar para FastAPI en producción |
| Plantillas | Jinja2 | 3.1 | Para el panel administrativo |
| Supervisión | systemd | — | Estándar en RHEL, gestión de servicios |

**Decisiones explícitas de NO uso:**

- **NO** se usa inteligencia artificial generativa. El bot es 100%
  determinista; cada respuesta es predecible y auditable.
- **NO** se usa Django ni Flask. FastAPI es la elección por sus
  capacidades async nativas.
- **NO** se usa SQLite. Solo PostgreSQL, alineado con la infraestructura
  existente del SERCOP.
- **NO** se usa pgcrypto. El cifrado vive en la aplicación con Fernet;
  la base de datos nunca conoce la clave maestra.

## 3. Modelo de datos

Cuatro tablas principales, todas en el esquema `public`.

### 3.1 alertas

Almacena las denuncias propiamente dichas. Los tres campos sensibles
(`institucion_denunciada`, `descripcion_hechos`, `personas_involucradas`)
se almacenan como `BYTEA` cifrado.

| Columna | Tipo | Notas |
|---------|------|-------|
| `id` | BIGINT identity | PK |
| `codigo_publico` | VARCHAR(20) UNIQUE | Formato `ALR-YYYY-XXXXXX` |
| `telefono_hash` | VARCHAR(64) | SHA-256 con pepper, no reversible |
| `institucion_denunciada` | BYTEA | Cifrado Fernet |
| `descripcion_hechos` | BYTEA | Cifrado Fernet |
| `personas_involucradas` | BYTEA NULL | Cifrado Fernet |
| `fecha_aproximada` | VARCHAR(50) | Texto, formato libre validado |
| `perjuicio_economico` | VARCHAR(100) NULL | Texto |
| `denuncia_previa_otra` | TEXT NULL | Texto |
| `estado` | VARCHAR(30) | Constraint: REGISTRADA/EN_REVISION/TRAMITADA/DESCARTADA |
| `timestamp_registro` | TIMESTAMPTZ | Auto |
| `timestamp_actualizacion` | TIMESTAMPTZ | Auto (trigger) |

### 3.2 alertas_evidencias

Metadata de los archivos adjuntos. El contenido binario vive en disco
con nombre UUID; en la base solo guardamos la ruta y el hash SHA-256.

| Columna | Tipo | Notas |
|---------|------|-------|
| `id` | BIGINT identity | PK |
| `alerta_id` | BIGINT FK | ON DELETE CASCADE |
| `nombre_original` | BYTEA | Nombre real cifrado con Fernet |
| `ruta_almacenamiento` | VARCHAR(500) | Path en disco (UUID + extensión) |
| `tipo_mime` | VARCHAR(100) | Validado contra lista blanca |
| `tamanio_bytes` | BIGINT | Constraint: 0 < tamaño ≤ 10 MB |
| `hash_sha256` | VARCHAR(64) | Integridad del contenido |
| `timestamp_subida` | TIMESTAMPTZ | Auto |

### 3.3 sesiones_activas

Respaldo de las conversaciones en curso. La fuente primaria está en
Redis con TTL automático (5 minutos); esta tabla queda como capacidad
de auditoría para eventos futuros.

### 3.4 bitacora_auditoria — INMUTABLE

Registro de TODOS los eventos del sistema. Acepta `INSERT` pero rechaza
`UPDATE` y `DELETE` mediante triggers PL/pgSQL.

| Columna | Tipo | Notas |
|---------|------|-------|
| `id` | BIGINT identity | PK |
| `alerta_id` | BIGINT FK NULL | ON DELETE SET NULL (preserva auditoría) |
| `evento` | VARCHAR(50) | 15 tipos catalogados |
| `actor` | VARCHAR(100) | "CIUDADANO" / "SISTEMA" / "ADMIN:xxx" / "META_API" |
| `detalle` | JSONB NULL | Sanitizado: NUNCA datos personales en claro |
| `timestamp` | TIMESTAMPTZ | Auto |

**Triggers de seguridad** instalados en la primera migración:

- `trg_bitacora_no_update`: lanza `RAISE EXCEPTION` ante cualquier UPDATE.
- `trg_bitacora_no_delete`: lanza `RAISE EXCEPTION` ante cualquier DELETE.

Estos triggers son verificables externamente: cualquier intento de
modificación —incluso por un usuario con privilegios— retorna error.

## 4. Garantías de seguridad

### 4.1 Confidencialidad

- **Cifrado en reposo de campos sensibles**: Fernet (AES-128-CBC +
  HMAC-SHA256) con clave de 32 bytes en `DENUNCIABOT_MASTER_KEY`.
- **Hash del teléfono con pepper**: SHA-256(pepper || número).
  El pepper es un secreto separado (`DENUNCIABOT_PHONE_PEPPER`) que
  impide ataques de fuerza bruta aunque la base de datos se filtre.
- **TLS obligatorio**: el bot solo recibe tráfico HTTPS (terminado por
  el reverse proxy de SERCOP Seguridad).
- **Comunicación con Meta**: TLS + `Authorization: Bearer <token>`.

### 4.2 Integridad

- **Validación HMAC del webhook**: cada POST de Meta se valida con
  HMAC-SHA256 sobre el cuerpo crudo antes de procesarlo. Sin firma
  válida → 401.
- **Bitácora inmutable**: triggers PL/pgSQL bloquean modificación.
- **Audit trail firmado**: exportación con hash encadenado SHA-256 y
  sello HMAC sobre el último hash.
- **Hash SHA-256 de cada evidencia**: detección de corrupción del
  archivo durante el almacenamiento.

### 4.3 Disponibilidad

- **Reintentos automáticos** con backoff exponencial en llamadas a Meta.
- **Cola Dramatiq** para SMTP y mensajes de cierre — sobreviven a caídas
  momentáneas de los servicios externos.
- **Idempotency** del webhook: los reintentos de Meta se descartan
  automáticamente para evitar duplicados.
- **Health checks** en `/health`, `/admin/health/db`, `/admin/health`.
- **Backup automático diario** de PostgreSQL con retención de 30 días.

### 4.4 Trazabilidad

- **Bitácora de eventos**: 15 tipos catalogados, inmutables.
- **Logs estructurados JSON** con sanitización automática de 24 campos
  considerados sensibles.
- **Métricas Prometheus**: 13 indicadores numéricos sin PII.
- **Audit trail criptográficamente firmado**: descargable, verificable
  externamente.

## 5. Despliegue

### 5.1 Infraestructura

- **Servidor**: RHEL 9.7, mismo donde corre Sercobot.
- **Python 3.11**: instalado vía `dnf` desde repositorios oficiales.
- **PostgreSQL 16**: ya en producción para Sercobot.
- **Redis 7**: a instalar vía `dnf`.
- **ClamAV**: opcional pero recomendado, instalable vía `dnf`.

### 5.2 Servicios systemd

Cuatro unidades de servicio:

| Unidad | Propósito |
|--------|-----------|
| `denunciabot.service` | API FastAPI bajo gunicorn (2 workers) |
| `denunciabot-worker.service` | Worker Dramatiq para SMTP y cierres |
| `denunciabot-cleanup.timer` | Limpia evidencias temporales cada 30 min |
| `denunciabot-backup.timer` | Backup diario de PostgreSQL a las 02:00 UTC |

Cada unidad lleva hardening completo: `NoNewPrivileges`,
`ProtectSystem=strict`, `ProtectHome=yes`, `PrivateTmp=yes` y
limitaciones de filesystem por `ReadWritePaths`.

### 5.3 Topología de red

```
Internet ─→ [Reverse proxy SERCOP] ─→ 127.0.0.1:8000 (denunciabot)
                                  └─→ otros servicios institucionales
```

El bot escucha exclusivamente en `127.0.0.1`. El subdominio público y
el certificado SSL son responsabilidad del equipo de seguridad
informática del SERCOP.

## 6. Operación

### 6.1 Métricas expuestas

`GET /metrics` (formato OpenMetrics, conectable a Prometheus):

- 9 counters (requests, alertas creadas, evidencias, duplicados, etc.)
- 2 histograms (latencia del webhook, latencia de Meta API)
- 2 gauges (alertas por estado, sesiones activas)

### 6.2 Logs

Salida a `journald` (vía systemd). Cada log es JSON estructurado con:
- timestamp ISO 8601 UTC
- nivel
- nombre del logger
- evento (clave determinística para alertas)
- contexto adicional sin datos personales

Conectable a SIEM institucional (Wazuh / Splunk / ELK) por syslog-ng o
filebeat (configuraciones de ejemplo en `RUNBOOK.md`).

### 6.3 Procedimientos documentados

Un documento operativo (`RUNBOOK.md`) cubre 14 escenarios:

1. Verificación rápida de salud
2. PostgreSQL inalcanzable
3. Redis inalcanzable
4. SMTP caído / notificaciones acumuladas
5. Meta API rechazando mensajes
6. Logs y debugging
7. Rotación de la clave maestra Fernet
8. Backup y restauración
9. Reinicio limpio
10. Limpieza de temporales
11. Métricas Prometheus
12. Integración con SIEM
13. Audit trail descargable
14. Tests de carga

## 7. Calidad y mantenimiento

- **125 pruebas automatizadas** (unitarias + integración).
- **Integración continua** en GitHub Actions con 3 jobs (unit, integration, lint).
- **Lineamientos de código**: Python 3.11 con type hints, formato `ruff`,
  validación `mypy` opcional.
- **Documentación inline** en cada módulo crítico explicando decisiones
  y restricciones.
- **Versionado semántico**: `0.1.0` para el MVP, incrementos minor para
  features, major para cambios incompatibles.

## 8. Repositorio y propiedad

- **Repositorio Git**: privado, en GitHub bajo cuenta del responsable
  técnico del SERCOP.
- **Propiedad intelectual**: la lógica institucional queda definida en
  acuerdo aparte (el convenio interinstitucional).
- **Auditabilidad del código**: la Secretaría puede revisar el código en
  cualquier momento bajo solicitud al SERCOP.

## 9. Limitaciones conocidas

| # | Limitación | Impacto | Mitigación |
|---|-----------|---------|------------|
| 1 | Panel administrativo con autenticación compartida (un solo token) | Sin trazabilidad por usuario individual | Eventual upgrade a OAuth/LDAP institucional |
| 2 | Sin priorización automática de denuncias | Personal revisa cronológicamente | Definir reglas de priorización post-piloto |
| 3 | Solo español | Excluye hablantes de idiomas indígenas | Hoja de ruta versión 2.0 |
| 4 | Caída de Redis interrumpe el flujo | Ciudadano debe reiniciar desde S0 | Mensaje degradado informativo |
| 5 | Sin integración con sistemas de la Secretaría | Datos quedan en sistema independiente | Definir interfaces post-piloto |

## 10. Anexo: trazabilidad técnica de una denuncia

Para que la contraparte comprenda concretamente qué pasa cuando un
ciudadano envía un mensaje:

1. WhatsApp del ciudadano → Meta Cloud API.
2. Meta envía POST con firma HMAC al subdominio del SERCOP.
3. El reverse proxy termina TLS y reenvía a `127.0.0.1:8000/webhook`.
4. DenunciaBot valida la firma HMAC con `META_APP_SECRET`. Sin firma
   válida → 401.
5. Verifica idempotency en Redis (descarta si Meta reenvía).
6. Parsea el payload con Pydantic.
7. Calcula `SHA-256(pepper || telefono)` para el identificador del
   ciudadano. El número en claro no se almacena.
8. Lee la sesión del ciudadano de Redis (o crea una nueva si es el
   primer contacto).
9. Procesa el mensaje a través del motor de estados (12 estados +
   3 auxiliares).
10. Si es el último paso (S10 confirmar), cifra los campos sensibles
    con Fernet, genera código público único y persiste en PostgreSQL
    dentro de una transacción.
11. Encola en Dramatiq:
    - Notificación SMTP al buzón de la Secretaría.
    - Mensaje de cierre con el código al ciudadano.
12. Responde 200 OK a Meta.
13. El worker Dramatiq procesa la cola con reintentos automáticos.
14. La bitácora registra cada evento (ALERTA_CREADA, MENSAJE_RECIBIDO,
    ESTADO_AVANZADO, NOTIFICACION_ENVIADA, etc.).
