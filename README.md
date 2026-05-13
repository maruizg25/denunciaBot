# DenunciaBot

Chatbot de WhatsApp para la recepción de denuncias ciudadanas de corrupción de la
**Secretaría General de Integridad Pública del Ecuador**. Convenio interinstitucional
sin costo con el **SERCOP** (Servicio Nacional de Contratación Pública).

## Descripción

DenunciaBot guía al ciudadano por un flujo conversacional determinista en WhatsApp
(12 estados, S0 a S12) para recolectar de manera estructurada los elementos de una
denuncia de corrupción: institución, descripción, fecha, personas involucradas,
perjuicio económico, denuncia previa y evidencias adjuntas (PDF/JPG/PNG). Al
finalizar, persiste la alerta con sus campos sensibles cifrados, genera un código
público de seguimiento y notifica por correo institucional.

**Principios no negociables:**

- 100% determinista, **sin IA generativa**. Máquina de estados pura.
- El número de teléfono del denunciante **nunca** se almacena en claro.
- Campos sensibles cifrados en la aplicación con Fernet (la base de datos nunca ve la clave).
- Bitácora de auditoría inmutable (trigger SQL bloquea UPDATE/DELETE).
- Validación HMAC de cada webhook entrante de Meta antes de procesarlo.
- Escaneo antivirus de evidencias subidas (ClamAV).

## Stack técnico

| Capa | Tecnología |
|------|-----------|
| Lenguaje | Python 3.11 |
| Framework web | FastAPI |
| ORM | SQLAlchemy 2.x async + asyncpg |
| Base de datos | PostgreSQL 16 |
| Sesiones + cola | Redis 7 |
| Worker async | Dramatiq |
| Validación | Pydantic 2 |
| Migraciones | Alembic |
| HTTP cliente | httpx |
| Cifrado | cryptography (Fernet) |
| Logs | structlog (JSON) |
| Rate limiting | slowapi |
| Antivirus | ClamAV (clamd) |
| Servidor ASGI | uvicorn + gunicorn |
| Supervisión | systemd |

**No usamos:** Django, Flask, ORM síncrono, sqlite, Nginx (el TLS lo gestiona el
equipo de seguridad de SERCOP).

## Requisitos

- Python 3.11+
- PostgreSQL 16 (local con Docker en dev; en el servidor RHEL ya instalado)
- Redis 7 (igual: Docker en dev, paquete RPM en prod)
- Docker Desktop (solo para dev en macOS) — o instala Postgres y Redis con `brew`
- ClamAV (opcional, recomendado en producción)

## Instalación

### Quickstart en macOS (desarrollo, con Docker)

El stack local usa Docker para PostgreSQL y Redis — no hace falta instalarlos
con brew. Solo necesitas Python 3.11+ y Docker Desktop.

```bash
# 1. Clonar y entrar
git clone <repo> denunciabot && cd denunciabot

# 2. Crear venv e instalar dependencias (producción + dev)
make install-dev

# 3. Levantar PostgreSQL y Redis con Docker
make up

# 4. Configurar .env
cp .env.example .env
# Generar claves criptográficas (copia los valores al .env):
python -c "from cryptography.fernet import Fernet; print('MASTER_KEY:', Fernet.generate_key().decode())"
python -c "import secrets; print('PEPPER:', secrets.token_urlsafe(32))"
# Editar .env con esos valores + credenciales de Meta + SMTP

# 5. Inicializar la BD (corre migraciones + verifica triggers)
make init-db

# 6. Correr tests
make test

# 7. Levantar el bot (en una terminal)
make run

# 8. Levantar el worker SMTP + cierres (en otra terminal)
make worker
```

Lista completa de comandos: `make help`.

### Panel admin (opcional)

Si configuras `ADMIN_TOKEN` en `.env`, el panel queda accesible en
http://localhost:8000/admin/login. Sin token configurado, los endpoints
HTML devuelven 503.

```bash
python -c "import secrets; print('ADMIN_TOKEN:', secrets.token_urlsafe(48))"
# Copiar el valor a .env y reiniciar
```

Funcionalidad: listado paginado con filtros, detalle con descifrado
Fernet al vuelo, cambio de estado auditado en bitácora, sesión cookie
con HMAC válida por 8 horas.

### Endpoint público de consulta de estado

Los ciudadanos pueden consultar el estado de su denuncia con el código:

```
GET https://tu-subdominio.gob.ec/alerta/ALR-2026-K7M2QH
```

Devuelve `{codigo, estado, fecha_registro}` sin datos sensibles.
Rate-limited a 30/min por IP.

### Instalación en producción (RHEL 9.7)

PostgreSQL 16 ya está instalado en el servidor. Falta agregar Python 3.11
(Sercobot usa 3.8, no se toca):

```bash
sudo dnf install -y python3.11 python3.11-devel python3.11-pip \
                    gcc gcc-c++ openssl-devel libffi-devel \
                    postgresql-devel make redis
```

Opcional pero recomendado (escaneo antivirus de evidencias):

```bash
sudo dnf install -y clamav clamav-update clamd
sudo freshclam
sudo systemctl enable --now clamd@scan
```

Luego clonar el repo, crear venv, configurar `.env`, copiar los units
systemd y arrancar:

```bash
cd /opt/denunciabot
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# (editar .env con secretos reales y permisos 0o600)
python scripts/init_db.py
sudo cp denunciabot.service denunciabot-worker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now denunciabot denunciabot-worker
sudo systemctl status denunciabot
```

## Variables de entorno

Todas las variables están documentadas en [`.env.example`](.env.example). Las
más críticas:

- `DENUNCIABOT_MASTER_KEY` — clave Fernet para cifrar campos sensibles.
- `DENUNCIABOT_PHONE_PEPPER` — pepper secreto para hash de teléfonos.
- `META_APP_SECRET` — para validar firma HMAC del webhook.
- `META_ACCESS_TOKEN` — token de la app de WhatsApp Business.
- `DATABASE_URL` — connection string PostgreSQL con driver `asyncpg`.
- `REDIS_URL` — Redis para sesiones y cola Dramatiq.
- `SMTP_TO` — buzón institucional que recibe la notificación de cada denuncia.

## Comandos básicos

```bash
# Levantar servicio API (desarrollo)
uvicorn app.main:app --reload

# Levantar servicio API (producción, gestionado por systemd)
gunicorn app.main:app -w 2 -k uvicorn.workers.UvicornWorker -b 127.0.0.1:8000

# Levantar worker Dramatiq (envío SMTP, escaneo de archivos)
dramatiq app.services.notificacion_service

# Migraciones
alembic revision --autogenerate -m "descripcion"
alembic upgrade head
alembic downgrade -1

# Tests
pytest
pytest --cov=app --cov-report=term-missing

# Exportar denuncias a CSV (MVP sin panel admin)
python scripts/export_alertas.py --desde 2026-01-01 --hasta 2026-12-31
```

## Dependencias de desarrollo

Para testing y herramientas locales, instalar por encima de `requirements.txt`:

```bash
pip install pytest==8.3.4 pytest-asyncio==0.25.0 pytest-cov==6.0.0 \
            httpx==0.28.1 faker==33.1.0 ruff==0.8.4 mypy==1.13.0
```

## Estructura del proyecto

```
denunciabot/
├── app/
│   ├── main.py              # Entry point FastAPI
│   ├── config.py            # Settings (pydantic-settings)
│   ├── database.py          # Engine async + session
│   ├── models/              # SQLAlchemy ORM
│   ├── schemas/             # Pydantic (webhook Meta, alertas)
│   ├── core/                # Seguridad, cliente Meta, códigos
│   ├── conversacion/        # Máquina de estados S0–S12
│   ├── services/            # Lógica de negocio + SMTP
│   ├── api/                 # Endpoints FastAPI
│   └── utils/               # Logging
├── alembic/                 # Migraciones
├── tests/
├── scripts/                 # init_db, export_alertas
├── .env.example
├── requirements.txt
└── denunciabot.service      # Unit systemd
```

## Seguridad

- El bot escucha **solo en `127.0.0.1`**. El subdominio público y el certificado
  TLS son gestionados por el equipo de seguridad de SERCOP.
- Cada POST al webhook se valida con HMAC-SHA256 usando `META_APP_SECRET` antes
  de procesar el cuerpo. Sin firma válida → `401 Unauthorized`.
- Campos sensibles (`institucion_denunciada`, `descripcion_hechos`,
  `personas_involucradas`, `nombre_original` de evidencias) se cifran con
  `cryptography.Fernet` y se almacenan como `BYTEA`. La clave nunca llega a la BD.
- Teléfonos: se calcula `SHA-256(pepper || telefono_e164)` y solo el hash se persiste.
- La tabla `bitacora_auditoria` solo permite `INSERT`. Un trigger PL/pgSQL lanza
  excepción ante `UPDATE` o `DELETE` (incluido superusuario operando vía cliente).
- Evidencias se guardan en disco con nombre = `UUID v4` + extensión genérica; el
  nombre original va cifrado en la fila.
- Los logs son JSON estructurado vía `structlog` y se sanitizan antes de emitirse
  (nunca incluyen el teléfono ni el texto de la denuncia).

## Estado

**Versión:** 0.0.1 — MVP en construcción.
**Producción:** pendiente despliegue.

## Autor

**Jonathan Mauricio Ruiz Sánchez** (Mau) — Analista de Operaciones de Innovación
Tecnológica 2, SERCOP.
