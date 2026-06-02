# Guía técnica de dominio — DenunciaBot

> **Nota arquitectónica (junio 2026):** el **modelo objetivo** de consumo por la Secretaría es **API REST documentada** (ver [`docs/11-contrato-api-rest.md`](11-contrato-api-rest.md)). La Secretaría desarrolla su propio frontend con su SSO e identidad institucional. El panel administrativo web descrito más abajo se mantiene como **fallback** durante la transición.
>
> Documento para **dominar el sistema** y **explicarlo a otros** (IT institucional, Coordinador, auditores). No reemplaza a:
> - [`docs/03-arquitectura-tecnica.md`](03-arquitectura-tecnica.md) — referencia detallada de arquitectura.
> - [`docs/04-seguridad-y-privacidad.md`](04-seguridad-y-privacidad.md) — cumplimiento legal y custodia.
> - [`RUNBOOK.md`](../RUNBOOK.md) — procedimientos operativos de troubleshooting.
>
> Esta guía es el **puente didáctico** que los une.

---

## Tabla de contenido

1. [Cómo usar esta guía](#1-cómo-usar-esta-guía)
2. [Modelo mental — los 5 conceptos clave](#2-modelo-mental--los-5-conceptos-clave)
3. [Mapa de procesos: qué corre, dónde y para qué](#3-mapa-de-procesos-qué-corre-dónde-y-para-qué)
4. [Mapa del código: cómo está organizado el repo](#4-mapa-del-código-cómo-está-organizado-el-repo)
5. [El viaje de un mensaje: paso a paso por el código](#5-el-viaje-de-un-mensaje-paso-a-paso-por-el-código)
6. [Modelo de datos: las 5 tablas y por qué existen](#6-modelo-de-datos-las-5-tablas-y-por-qué-existen)
7. [Las 4 capas de seguridad: defensa en profundidad](#7-las-4-capas-de-seguridad-defensa-en-profundidad)
8. [Operación 101: los 12 comandos que SIEMPRE necesitarás](#8-operación-101-los-12-comandos-que-siempre-necesitarás)
9. [Cómo extender el bot: 4 recetas comunes](#9-cómo-extender-el-bot-4-recetas-comunes)
10. [Glosario técnico para conversaciones con IT](#10-glosario-técnico-para-conversaciones-con-it)
11. [Ejercicios para verificar tu dominio](#11-ejercicios-para-verificar-tu-dominio)

---

## 1. Cómo usar esta guía

**Audiencia primaria:** quien opere y extienda el bot (tú).
**Audiencia secundaria:** equipo de TI de la Secretaría (servidor, BD, red).

Lee secciones 2–7 en orden si nunca has trabajado con un bot conversacional. Si ya manejas el dominio, salta a la sección 9 (extensión) o 11 (ejercicios).

Para IT institucional, las secciones más útiles son: **3** (qué corre dónde), **6** (BD), **8** (operación), y referencias a [`RUNBOOK.md`](../RUNBOOK.md) para troubleshooting.

---

## 2. Modelo mental — los 5 conceptos clave

Si dominas estos 5, dominas el bot.

### 2.1 Máquina de estados conversacional (no es IA)

El bot no "entiende" lenguaje natural. Tiene una **tabla de 12 estados** (`S0` a `S12`). En cada estado:

1. Recibe un mensaje del ciudadano.
2. Valida la entrada con reglas fijas (`app/conversacion/validadores.py`).
3. Si la entrada es válida → avanza al siguiente estado y envía una pregunta predefinida.
4. Si la entrada es inválida → reintenta con orientación, hasta 3 veces, después cierra la sesión.

El estado actual se guarda en Redis (rápido) y se respalda en PostgreSQL.

> ✅ **Por qué importa:** el flujo es 100% predecible. No hay alucinaciones ni respuestas "creativas". El audito puede reproducir cualquier conversación a partir del estado y los validadores.

### 2.2 Webhook entrante con validación HMAC

WhatsApp Meta envía cada mensaje del ciudadano como un **POST HTTP** a una URL pública del bot (`/webhook`). Antes de procesarlo, el bot verifica una **firma criptográfica** (`X-Hub-Signature-256`) usando el `META_APP_SECRET` compartido con Meta. Sin firma válida → **401 Unauthorized**.

> ✅ **Por qué importa:** sin esto, cualquiera con la URL pública podría inyectar denuncias falsas.

### 2.3 Cifrado de campos sensibles con Fernet

Los campos `institucion_denunciada`, `descripcion_hechos`, `personas_involucradas` y los **nombres originales** de evidencias **no se guardan en texto plano** en la BD. Se cifran con Fernet (AES-128-CBC + HMAC-SHA256) usando una clave maestra que vive en `.env` (`DENUNCIABOT_MASTER_KEY`).

La BD ve solo bytes opacos. Si alguien hace `SELECT * FROM alertas` solo ve binario ilegible. Para descifrar necesita la master key, que **nunca toca la BD**.

> ✅ **Por qué importa:** garantía legal de confidencialidad incluso ante un dump no autorizado de la BD.

### 2.4 Hash con sal del teléfono del denunciante

El número telefónico del ciudadano **nunca se almacena**. Solo se guarda:

```
SHA-256(PEPPER_SECRETO || telefono_e164)
```

El `PEPPER` vive en `.env` (`DENUNCIABOT_PHONE_PEPPER`). Sin él, no se puede revertir el hash ni siquiera por fuerza bruta.

> ✅ **Por qué importa:** principio de minimización (LOPDP Art. 10): solo almacenamos lo necesario. La identidad del denunciante queda protegida.

### 2.5 Bitácora de auditoría inmutable a nivel de BD

Cada operación significativa (creación de denuncia, cambio de estado, intento de cancelación) se registra en la tabla `bitacora_auditoria`. Esta tabla tiene **dos triggers PL/pgSQL** que **bloquean `UPDATE` y `DELETE`** incluso ejecutados por superusuario:

```sql
trg_bitacora_no_update BEFORE UPDATE ON bitacora_auditoria
trg_bitacora_no_delete BEFORE DELETE ON bitacora_auditoria
```

Cualquier intento lanza una excepción y aborta. La única operación permitida es `INSERT`.

> ✅ **Por qué importa:** garantía legal de no-repudio. Aunque alguien con acceso de admin a la BD quiera "borrar el rastro" de una denuncia, el motor PostgreSQL lo impide.

---

## 3. Mapa de procesos: qué corre, dónde y para qué

En producción, el bot se compone de **5 procesos** corriendo en el servidor RHEL institucional. Es importante distinguirlos:

```
┌─────────────────────────────────────────────────────────────────┐
│                  Servidor RHEL 9.7 institucional                │
│                                                                  │
│  ┌───────────────────────┐    ┌────────────────────────────┐   │
│  │  API FastAPI          │    │  Worker Dramatiq           │   │
│  │  (gunicorn + uvicorn) │    │  (procesa cola SMTP        │   │
│  │  systemd:             │    │   + cierres con reintento) │   │
│  │  denunciabot.service  │    │  systemd:                  │   │
│  │  127.0.0.1:8000       │    │  denunciabot-worker.service│   │
│  └──────────┬────────────┘    └────────────┬───────────────┘   │
│             │                              │                    │
│             ↓                              ↓                    │
│  ┌──────────────────────┐   ┌───────────────────────────┐      │
│  │ PostgreSQL 16        │   │ Redis 7                   │      │
│  │ (compartido con      │   │ (sesiones + cola Dramatiq)│      │
│  │  Sercobot, pero BD   │   │ instalado vía dnf         │      │
│  │  separada)           │   │                           │      │
│  │ systemd:             │   │ systemd:                  │      │
│  │ postgresql.service   │   │ redis.service             │      │
│  └──────────────────────┘   └───────────────────────────┘      │
│                                                                  │
│  ┌────────────────────────────────────────────────────────┐    │
│  │  Timers periódicos systemd                              │    │
│  │  - denunciabot-backup.timer    (dump BD a /var/backups) │    │
│  │  - denunciabot-cleanup.timer   (borra tmp huérfanos)    │    │
│  └────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
                                ↓ HTTPS
┌─────────────────────────────────────────────────────────────────┐
│        Reverse proxy institucional (TLS terminator)              │
│        denuncia.secretaria.gob.ec                                │
└─────────────────────────────────────────────────────────────────┘
                                ↓
                       Internet pública → Meta WhatsApp Cloud API
                       (graph.facebook.com)
```

### Por qué API y worker están separados

- **La API** debe responder rápido al webhook de Meta (Meta exige ACK en < 5 segundos; si no, reintenta y se duplican).
- **El SMTP** y los **cierres con reintento** son operaciones que pueden tardar 30s o fallar y reintentarse. Si se ejecutaran dentro del handler del webhook, bloquearían la respuesta.
- Por eso la API **encola** los trabajos pesados en Redis, y el **worker Dramatiq** los procesa de forma asíncrona en otro proceso.

### Qué encola la API y qué hace el worker

| Tarea encolada | Origen | Acción del worker |
|---|---|---|
| `enviar_notificacion_alerta` | Al confirmar S10, cierra denuncia | Envía correo SMTP a `integridad@secretaria.gob.ec` con datos descifrados |
| `cerrar_alerta_con_reintento` | Confirmación S10 | Espera commit, luego limpia sesión + manda código por WhatsApp |
| `limpiar_sesiones_expiradas` | Timer cleanup | Borra sesiones con > 5 min de inactividad |

---

## 4. Mapa del código: cómo está organizado el repo

```
denunciaBot/
├── app/                          ← TODO el código de aplicación está aquí
│   ├── main.py                   ← Punto de entrada FastAPI (lee config, monta routers)
│   ├── config.py                 ← Settings tipadas con pydantic-settings (lee .env)
│   ├── database.py               ← Engine async SQLAlchemy + factory de sesiones
│   ├── metrics.py                ← Métricas Prometheus
│   │
│   ├── api/                      ← Endpoints HTTP
│   │   ├── webhook.py            ← POST /webhook (Meta), GET /webhook (verificación)
│   │   ├── admin.py              ← Panel admin web (HTML + cookies firmadas HMAC)
│   │   ├── consulta.py           ← GET /alerta/{codigo} (consulta pública)
│   │   └── health.py             ← /health, /admin/health
│   │
│   ├── conversacion/             ← Máquina de estados (corazón del bot)
│   │   ├── estados.py            ← Tabla de los 12 estados S0..S12
│   │   ├── motor.py              ← Lógica del flujo (procesar_mensaje)
│   │   ├── validadores.py        ← Reglas de validación por estado
│   │   └── mensajes.py           ← Textos exactos que envía el bot
│   │
│   ├── services/                 ← Lógica de negocio + I/O
│   │   ├── orquestador.py        ← Ejecuta las acciones del motor (BD + Redis + Meta)
│   │   ├── sesion_service.py     ← CRUD sesiones (Redis)
│   │   ├── alerta_service.py     ← Persistencia de denuncias en BD
│   │   ├── notificacion_service.py ← Workers Dramatiq (SMTP, cierres)
│   │   ├── idempotency_service.py  ← Evita procesar el mismo mensaje 2 veces
│   │   └── evidencia_service.py  ← Antivirus + persistencia de adjuntos
│   │
│   ├── core/                     ← Primitivas criptográficas y clientes externos
│   │   ├── security.py           ← Fernet, hash teléfono, HMAC, cookies firmadas
│   │   ├── meta_client.py        ← Cliente HTTP de Meta Graph API
│   │   └── codigo_publico.py     ← Generador de códigos ALR-2026-XXXXXX
│   │
│   ├── models/                   ← Modelos SQLAlchemy (mapeo BD)
│   │   ├── alerta.py             ← Tabla alertas + estados
│   │   ├── sesion.py             ← Tabla sesiones_activas + enum EstadoSesion
│   │   ├── bitacora.py           ← Tabla bitacora_auditoria
│   │   └── evidencia.py          ← Tabla alertas_evidencias
│   │
│   ├── schemas/                  ← Pydantic schemas (validación request/response)
│   │   └── meta.py               ← Estructura del payload de Meta
│   │
│   ├── templates/                ← Jinja2 (panel admin HTML)
│   └── utils/
│       └── logger.py             ← structlog (logs JSON estructurados)
│
├── alembic/                      ← Migraciones BD
│   ├── env.py                    ← Conecta alembic con app.config
│   └── versions/
│       └── 2026_05_11_2200-0001_inicial_crea_esquema_denunciabot.py
│                                 ← TODA la creación de tablas + triggers vive ahí
│
├── tests/                        ← Tests pytest (180 unitarios + 11 integración)
│   ├── test_motor.py             ← Máquina de estados
│   ├── test_validadores.py       ← Cada validador
│   ├── test_webhook.py           ← HTTP + HMAC
│   ├── test_admin.py             ← Panel admin
│   ├── test_consulta.py          ← Endpoint público
│   ├── test_metrics.py           ← Prometheus
│   ├── test_audit_trail.py       ← Export firmado
│   └── integration/              ← Tests con Postgres+Redis reales
│
├── scripts/                      ← Tareas operativas
│   ├── init_db.py                ← Aplica migraciones + valida triggers
│   ├── backup_db.py              ← pg_dump cifrado a directorio destino
│   ├── export_alertas.py         ← CSV de denuncias (con o sin descifrar)
│   ├── limpiar_temporales.py     ← Borra archivos huérfanos > 30 min
│   ├── load_test.py              ← Smoke test de carga (100 webhooks concurrentes)
│   └── generar_presentacion.py   ← Genera .pptx para la Secretaría
│
├── docs/                         ← Documentación institucional
│   └── (este archivo + los otros 6)
│
├── *.service / *.timer           ← Units systemd (5 archivos)
├── docker-compose.yml            ← Postgres + Redis para DEV (no para prod)
├── alembic.ini                   ← Config Alembic
├── pytest.ini                    ← Config pytest
├── requirements.txt              ← Dependencias Python pinned
├── .env.example                  ← Template del .env (NO commitear .env real)
├── README.md                     ← Quickstart
└── RUNBOOK.md                    ← Procedimientos de troubleshooting
```

**Si tienes que tocar el comportamiento del bot:** empieza por `app/conversacion/motor.py`.
**Si tienes que cambiar una pregunta o mensaje:** `app/conversacion/mensajes.py`.
**Si tienes que cambiar qué validar:** `app/conversacion/validadores.py`.
**Si tienes que agregar un nuevo endpoint admin:** `app/api/admin.py`.

---

## 5. El viaje de un mensaje: paso a paso por el código

Sigamos un "hola" desde que el ciudadano lo manda hasta que ve la respuesta del bot. Cada paso te dice dónde mirar.

### Paso 1: WhatsApp → Meta → Webhook

El ciudadano escribe "hola" desde WhatsApp. Meta lo recibe, lo serializa como JSON, le agrega una firma HMAC y lo manda como `POST /webhook` al subdominio público.

### Paso 2: API recibe el POST — `app/api/webhook.py:91-146`

```python
@router.post("/webhook")
async def recibir_webhook(request: Request, ...):
    cuerpo = await request.body()           # bytes crudos
    if not validar_firma_meta(cuerpo, ...):  # HMAC SHA-256
        raise HTTPException(401)            # firma inválida → rechaza
    payload = MetaWebhookPayload.model_validate_json(cuerpo)  # Pydantic
    for mensaje_meta in payload.mensajes_planos():
        await _procesar_mensaje(mensaje_meta, db)
    return {"status": "ok"}
```

> **Por qué `200 OK` siempre** (excepto firma inválida): si devolviéramos 5xx, Meta reintentaría y creamos denuncias duplicadas. Mejor procesar y loguear errores que devolver fallo a Meta.

### Paso 3: Idempotencia — `app/services/idempotency_service.py`

Meta puede reenviar el mismo mensaje (mismo `wamid`) si no recibe nuestro 200 a tiempo. Antes de procesarlo:

```python
if not await intentar_marcar_procesado(mensaje_meta.id):
    return  # ya fue procesado, ignoramos silenciosamente
```

El `wamid` se guarda en Redis con TTL de 24 h.

### Paso 4: Hash del teléfono — `app/core/security.py`

El número del ciudadano se hashea antes de tocar la BD:

```python
telefono_hash = crypto.hash_telefono(telefono_e164)
# Equivalente a:
# SHA-256(PEPPER || "593987654321")
```

A partir de aquí, **dentro del sistema solo circula el hash**, nunca el número.

### Paso 5: Buscar sesión actual — `app/services/sesion_service.py`

Pregunta a Redis: "¿tengo una conversación en curso para este telefono_hash?"

- Si **NO** → primer contacto, motor arranca en S0.
- Si **SÍ** → carga el estado actual y los datos parciales recolectados.

### Paso 6: Motor procesa el mensaje — `app/conversacion/motor.py:procesar_mensaje`

Es una **función pura sin I/O**: recibe `(sesion, mensaje, telefono_hash)`, devuelve `ResultadoMotor(sesion_nueva, acciones)`.

Para "hola" sin sesión previa:

```
S0_INICIO → S1_BIENVENIDA → S2_ACEPTACION
```

Acciones generadas:
- `AccionEnviarTexto(bienvenida + condiciones)`
- `AccionEnviarBotones("¿Acepta continuar?", [Sí, No])`
- `AccionGuardarSesion(estado=S2_ACEPTACION)`
- `AccionRegistrarBitacora(evento=SESION_INICIADA)`

> **Por qué función pura:** simplifica testing brutalmente. Los 70+ tests de `test_motor.py` no requieren BD, Redis ni red.

### Paso 7: Orquestador ejecuta las acciones — `app/services/orquestador.py:ejecutar`

Toma la lista de acciones del motor y las ejecuta en orden, en **una transacción**:

```python
async with db.begin():
    for accion in resultado.acciones:
        await _ejecutar_accion(accion, db)
    await db.commit()
```

Si una acción falla (ej. Meta rechaza el envío), rollback. La sesión NO queda guardada en estado inconsistente.

### Paso 8: Envío a Meta — `app/core/meta_client.py`

Cada `AccionEnviarTexto`/`AccionEnviarBotones` se traduce a un POST HTTPS:

```
POST https://graph.facebook.com/v18.0/{PHONE_ID}/messages
Authorization: Bearer {META_ACCESS_TOKEN}
Body: {"messaging_product":"whatsapp", "to":"593...", "type":"text", ...}
```

Meta devuelve 200 si lo aceptó. Errores 4xx (token expirado, número no permitido, etc.) se loguean y se distingue entre **permanentes** (no reintentar) y **transitorios** (reintentar).

### Paso 9: Persistencia de la sesión

`AccionGuardarSesion` se ejecuta y guarda el estado nuevo en Redis (TTL 5 min) y en la tabla `sesiones_activas`.

### Paso 10: El ciudadano ve la respuesta

WhatsApp recibe el push de Meta y muestra los dos mensajes (bienvenida + botones) al ciudadano. El ciudadano pulsa "Sí" → vuelve al paso 1.

---

## 6. Modelo de datos: las 5 tablas y por qué existen

> Para schema detallado ver [`docs/03-arquitectura-tecnica.md`](03-arquitectura-tecnica.md#3-modelo-de-datos). Aquí solo el "por qué".

### `alertas` — denuncias confirmadas

Cada denuncia confirmada en S10 genera una fila. Campos sensibles (`institucion_denunciada`, `descripcion_hechos`, `personas_involucradas`) son `BYTEA` cifrados con Fernet. El `codigo_publico` (ej. `ALR-2026-MJY3LW`) es lo único que el ciudadano conoce y comparte.

### `alertas_evidencias` — archivos adjuntos

Cada archivo PDF/JPG/PNG enviado. El nombre original va **cifrado** en `nombre_original`. El archivo físico vive en disco bajo un UUID v4 sin pistas del contenido.

### `sesiones_activas` — conversaciones en curso

Mientras el ciudadano responde S0→S10, su progreso queda aquí. Cuando confirma → la fila se borra. Si abandona y pasan 5 min → también se borra (timer cleanup). Redis tiene la copia caliente; PostgreSQL la respalda.

### `bitacora_auditoria` — registro inmutable

Cada evento significativo: `SESION_INICIADA`, `ESTADO_AVANZADO`, `VALIDACION_FALLIDA`, `SESION_CANCELADA`, `ALERTA_CREADA`, `ESTADO_ADMIN_CAMBIADO`. Triggers PL/pgSQL impiden modificación o borrado. **Es la garantía legal del sistema**.

### `wamids_procesados` (en Redis, no en BD)

IDs de mensajes de Meta ya vistos, con TTL 24 h. Evita procesar duplicados cuando Meta reintenta.

---

## 7. Las 4 capas de seguridad: defensa en profundidad

```
Mensaje entrante de Meta
        ↓
┌─────────────────────────────────────────┐
│ CAPA 1 — Rate limiting (slowapi)        │  120 req/min por IP
└─────────────────────────────────────────┘
        ↓
┌─────────────────────────────────────────┐
│ CAPA 2 — Validación HMAC                │  X-Hub-Signature-256
│ (cualquier petición sin firma → 401)    │  con META_APP_SECRET
└─────────────────────────────────────────┘
        ↓
┌─────────────────────────────────────────┐
│ CAPA 3 — Validación de schema Pydantic  │  Si el payload no es
│ (payloads malformados → 200 ignored)    │  WhatsApp válido, se ignora
└─────────────────────────────────────────┘
        ↓
┌─────────────────────────────────────────┐
│ CAPA 4 — Validadores conversacionales   │  3 intentos por estado;
│ (texto absurdo rechazado, max intentos) │  superados → sesión descartada
└─────────────────────────────────────────┘
        ↓
   Procesa la denuncia
```

Datos en reposo:

```
┌─────────────────────────────────────────┐
│ Cifrado Fernet — campos sensibles       │  Master key NO en BD
└─────────────────────────────────────────┘
┌─────────────────────────────────────────┐
│ Hash con sal — teléfono                 │  Pepper NO en BD
└─────────────────────────────────────────┘
┌─────────────────────────────────────────┐
│ Trigger SQL — bitácora inmutable        │  Bloquea UPDATE/DELETE
└─────────────────────────────────────────┘
┌─────────────────────────────────────────┐
│ Filesystem permisos 0700 — evidencias   │  Solo usuario denunciabot
└─────────────────────────────────────────┘
```

---

## 8. Operación 101: los 12 comandos que SIEMPRE necesitarás

> Asumen que estás en RHEL como el usuario `denunciabot` con acceso a `/opt/denunciabot`.

### 1. ¿Está vivo el servicio?

```bash
sudo systemctl status denunciabot
sudo systemctl status denunciabot-worker
curl http://127.0.0.1:8000/health
```

### 2. Ver logs en vivo

```bash
sudo journalctl -u denunciabot -f
sudo journalctl -u denunciabot-worker -f
```

### 3. Reiniciar limpio (orden importa)

```bash
sudo systemctl restart denunciabot-worker   # primero el worker
sudo systemctl restart denunciabot          # luego la API
```

### 4. Aplicar migraciones pendientes

```bash
cd /opt/denunciabot
source .venv/bin/activate
alembic upgrade head
```

### 5. Backup manual de la BD

```bash
python scripts/backup_db.py --destino /var/backups/denunciabot
# Genera un .sql.gz cifrado con AES-256
```

### 6. Ver denuncias recientes (sin datos sensibles)

```bash
sudo -u postgres psql denunciabot
> SELECT id, codigo_publico, estado, timestamp_registro
  FROM alertas ORDER BY id DESC LIMIT 20;
```

### 7. Contar denuncias por estado

```sql
SELECT estado, COUNT(*) FROM alertas GROUP BY estado;
```

### 8. Verificar que la bitácora sigue inmutable

```sql
DELETE FROM bitacora_auditoria WHERE id = 1;
-- Debe responder: ERROR: La bitácora de auditoría es inmutable
```

### 9. Ver tareas en cola Dramatiq

```bash
redis-cli -n 1 LLEN dramatiq:notificaciones
redis-cli -n 1 LLEN dramatiq:cierres
```

### 10. Recargar configuración tras editar `.env`

```bash
# .env se lee solo al arrancar. Tras cambios hay que reiniciar:
sudo systemctl restart denunciabot denunciabot-worker
```

### 11. Métricas Prometheus

```bash
curl http://127.0.0.1:8000/metrics | grep -E "alertas_creadas|webhook_requests|estado_transiciones"
```

### 12. Verificación rápida de servicios dependientes

```bash
systemctl status postgresql        # BD
systemctl status redis             # Cola + sesiones
systemctl status clamd@scan        # Antivirus (si está habilitado)
```

> Para troubleshooting de errores específicos consulta [`RUNBOOK.md`](../RUNBOOK.md).

---

## 9. Cómo extender el bot: 4 recetas comunes

### Receta 1: Cambiar el texto de una pregunta

**Caso típico:** la Secretaría quiere reformular la pregunta de "personas involucradas".

1. Abre `app/conversacion/mensajes.py`.
2. Busca `def solicitar_involucrados()`.
3. Edita el texto del `return`.
4. Corre los tests: `pytest tests/test_motor.py` (verifica que el flujo siga funcionando).
5. Reinicia: `sudo systemctl restart denunciabot`.

**No requiere migración BD.** No toca la estructura de datos.

### Receta 2: Agregar una validación más estricta a un campo

**Caso típico:** la Secretaría quiere que en S3 se exija que la institución empiece con palabra clave ("Ministerio", "GAD", "Hospital", etc.).

1. Abre `app/conversacion/validadores.py`.
2. Busca `def validar_institucion(...)`.
3. Agrega tu regla DESPUÉS de las existentes:
   ```python
   PALABRAS_CLAVE = ("ministerio", "gad", "hospital", "secretaría", ...)
   if not any(p in valor.lower() for p in PALABRAS_CLAVE):
       return ResultadoValidacion(False, motivo="Indique una institución pública con palabra clave...")
   ```
4. Agrega un test en `tests/test_validadores.py::TestInstitucion`.
5. Corre: `pytest tests/test_validadores.py`.
6. Reinicia.

### Receta 3: Cambiar el destinatario del correo institucional

**Caso típico:** Secretaría cambia de buzón.

1. Edita `.env` (en producción `/opt/denunciabot/.env`):
   ```
   SMTP_TO=nuevo-buzon@secretaria.gob.ec
   ```
2. Reinicia el worker (no la API):
   ```bash
   sudo systemctl restart denunciabot-worker
   ```

### Receta 4: Agregar un nuevo estado a la denuncia (ej. `EN_INVESTIGACION`)

**Caso típico:** la Secretaría quiere un estado adicional entre `EN_REVISION` y `TRAMITADA`.

1. Edita el `CHECK` de `alertas.estado` en una **nueva migración Alembic**:
   ```bash
   alembic revision -m "agregar estado en_investigacion a alertas"
   # Edita el archivo generado:
   op.execute("ALTER TABLE alertas DROP CONSTRAINT ck_alertas_estado_valido")
   op.execute("ALTER TABLE alertas ADD CONSTRAINT ck_alertas_estado_valido CHECK (estado IN ('REGISTRADA', 'EN_REVISION', 'EN_INVESTIGACION', 'TRAMITADA', 'DESCARTADA'))")
   ```
2. Edita el enum en `app/models/alerta.py::EstadoAlerta`.
3. Edita el panel admin `app/api/admin.py` para permitir transicionar a ese estado.
4. Edita los tests.
5. Aplica: `alembic upgrade head` y reinicia.

---

## 10. Glosario técnico para conversaciones con IT

| Término | Qué significa en este proyecto |
|---|---|
| **Fernet** | Estándar de cifrado simétrico autenticado (AES-128-CBC + HMAC-SHA256). Una clave Fernet es 32 bytes en base64url. |
| **HMAC-SHA256** | Hash con clave compartida. Se usa para validar que Meta envió el webhook y para firmar exports de bitácora. |
| **Pepper** | Sal secreta global aplicada antes del hash. Distinto a "salt" por usuario porque queremos hash determinístico (mismo número → mismo hash). |
| **Webhook** | URL pública del bot a la que Meta envía POSTs cuando hay un mensaje entrante. |
| **wamid** | "WhatsApp Message ID". ID único que asigna Meta a cada mensaje. Lo usamos para idempotencia. |
| **WABA** | "WhatsApp Business Account". Cuenta que agrupa números de WhatsApp Business. La nuestra es `374235592445310`. |
| **Phone Number ID** | Identificador de un número de WhatsApp dentro de una WABA. El nuestro es `414712255048880`. |
| **Verify Token** | String arbitrario que Meta nos envía en el GET inicial de verificación. Lo configuramos en ambos lados (Meta dashboard + `.env`). |
| **App Secret** | Secreto de la app de Meta. Se usa para firmar los webhooks. NUNCA se expone. |
| **System User Token** | Token de Meta que NO expira, generado para una cuenta de servicio. El que usamos hoy es temporal (~24h). |
| **asyncpg** | Driver async de PostgreSQL para Python. Más rápido que psycopg2 y permite usar `async/await`. |
| **SQLAlchemy 2.x async** | ORM que usamos sobre asyncpg. Permite definir modelos Python y traducirlos a SQL. |
| **Pydantic** | Librería de validación de datos. Genera schemas Python con verificación automática. |
| **FastAPI** | Framework web async para Python. Define rutas como funciones decoradas. |
| **Dramatiq** | Cola de tareas asíncronas sobre Redis. Más simple que Celery. |
| **slowapi** | Librería de rate-limiting para FastAPI. |
| **alembic** | Sistema de migraciones para SQLAlchemy. Cada cambio de schema es un archivo `.py` versionado. |
| **systemd** | Sistema de init de Linux. Nuestros servicios viven como units `.service` y timers `.timer`. |
| **journalctl** | Comando para leer logs de systemd. |
| **gunicorn** | Servidor WSGI/ASGI de producción. Lo usamos con workers Uvicorn. |
| **uvicorn** | Servidor ASGI nativo (no requiere gunicorn en dev). |
| **ClamAV** | Antivirus open source. El bot lo usa para escanear evidencias subidas. |
| **structlog** | Librería de logs estructurados (JSON) en lugar de texto plano. |
| **Prometheus** | Sistema de métricas. Exponemos en `/metrics`. |
| **Idempotencia** | Garantía de que ejecutar la misma operación N veces produce el mismo resultado que ejecutarla 1 vez. |
| **Bitácora inmutable** | Tabla SQL donde solo se permite INSERT — UPDATE y DELETE están bloqueados a nivel de motor. |

---

## 11. Ejercicios para verificar tu dominio

Si puedes responder estas preguntas sin abrir el código, dominas el sistema. Si no, abre el archivo indicado y profundiza.

### Nivel 1 — Comprensión general

1. ¿Por qué el bot tiene 12 estados y no 8 (uno por pregunta)?
   *(pista: piensa qué hace S0, S1, S11, S12 — no son preguntas al ciudadano)*

2. ¿Qué pasa si Meta nos envía dos veces el mismo mensaje porque no recibió nuestro 200 a tiempo?
   *(pista: `app/services/idempotency_service.py`)*

3. ¿Por qué la respuesta del bot a un POST de Meta es siempre 200 OK, aún cuando el procesamiento interno haya fallado?
   *(pista: comentario en `app/api/webhook.py:15`)*

### Nivel 2 — Operación

4. Si el servidor SMTP cae temporalmente, ¿qué pasa con las denuncias confirmadas?
   *(pista: cola Dramatiq + retries; ver `RUNBOOK.md` sección 4)*

5. Si necesitas migrar la BD a otro servidor, ¿qué archivos/datos debes copiar?
   *(pista: `scripts/backup_db.py` + `.env` + `/var/lib/denunciabot/evidencias`)*

6. ¿Cómo rotas la `MASTER_KEY` sin perder acceso a las denuncias antiguas?
   *(pista: `RUNBOOK.md` sección 7 — requiere re-cifrar todo)*

### Nivel 3 — Extensión

7. La Secretaría te pide agregar una pregunta opcional sobre "región de la denuncia" (Costa, Sierra, Oriente, Galápagos). ¿Qué archivos editas?
   *(estados.py, motor.py, validadores.py, mensajes.py, alembic versión nueva, models/alerta.py, tests)*

8. ¿Cómo agregarías un endpoint admin para exportar todas las denuncias de un mes en CSV?
   *(pista: hay un script ya hecho `scripts/export_alertas.py`; lo expones vía `app/api/admin.py`)*

9. ¿Qué pasaría si pones el bot a procesar denuncias detrás de un load balancer con 2 réplicas? ¿Qué componentes funcionarían y cuáles no?
   *(pista: PostgreSQL es shared, Redis es shared, pero los evidencias en `/var/lib/denunciabot/evidencias` son LOCAL. Necesitarías NFS o S3)*

### Nivel 4 — Seguridad

10. Si un funcionario malicioso con acceso de superusuario a la BD quiere **eliminar el rastro** de una denuncia, ¿qué bloqueos enfrenta? ¿Cómo lo detectarías?
    *(pista: triggers PL/pgSQL + audit trail firmado HMAC; ver `docs/04-seguridad`)*

11. Si filtras el `.env` por accidente en git público, ¿qué exactamente está comprometido y qué acciones tomar?
    *(pista: master key → todas las denuncias descifrables; pepper → teléfonos brute-forceables; app secret → forjar webhooks; admin token → acceso panel)*

12. ¿Cómo podrías demostrar legalmente que una denuncia con código `ALR-2026-XXXXXX` fue presentada en una fecha específica y nunca modificada?
    *(pista: `bitacora_auditoria` + export firmado vía `/admin/audit-trail` con `AUDIT_HMAC_SECRET`)*

---

## Próximos pasos sugeridos para ti

1. **Hoy:** lee secciones 2, 3 y 5. Resuelve ejercicios del nivel 1.
2. **Esta semana:** profundiza en `app/conversacion/motor.py` y resuelve nivel 2 y 3.
3. **Antes del despliegue:** lee `RUNBOOK.md` completo y practica cada procedimiento al menos una vez en dev.
4. **Para la presentación a IT:** llévales la sección 3 (mapa de procesos) y sección 6 (BD). El resto les sobra hasta que operen.

---

## Para IT de la Secretaría — versión TL;DR

Si solo tienen 5 minutos:

- **Stack:** Python 3.11 + FastAPI + PostgreSQL 16 + Redis 7, sobre RHEL 9.7.
- **Procesos:** 1 API (gunicorn + uvicorn) + 1 worker (dramatiq) + 2 timers (backup + cleanup), todos bajo systemd.
- **Red:** escucha en `127.0.0.1:8000`. El TLS lo termina el reverse proxy institucional.
- **BD:** un schema `denunciabot` en el mismo Postgres de Sercobot. ~5 tablas, una de ellas inmutable a nivel de trigger.
- **Seguridad:** 4 capas (rate limit + HMAC + Pydantic + validadores), cifrado Fernet en reposo, hash con sal para teléfonos.
- **Logs:** JSON estructurado vía journald. Compatibles con SIEM.
- **Métricas:** Prometheus en `/metrics`.
- **Backups:** pg_dump cifrado AES-256 cada noche, configurable en `denunciabot-backup.timer`.

Cualquier troubleshooting → `RUNBOOK.md` en el repo.
