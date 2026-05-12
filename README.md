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

### Desarrollo local (macOS)

- Python 3.11+
- PostgreSQL 16
- Redis 7
- `brew install python@3.11 postgresql@16 redis`

### Producción (RHEL 9.7)

PostgreSQL 16 ya está instalado en el servidor. Falta agregar Python 3.11 (Sercobot
usa 3.8, no se toca):

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

## Instalación

```bash
# 1. Clonar y entrar al directorio
git clone <repo> denunciabot && cd denunciabot

# 2. Crear entorno virtual
python3.11 -m venv .venv
source .venv/bin/activate

# 3. Instalar dependencias
pip install --upgrade pip
pip install -r requirements.txt

# 4. Configurar variables de entorno
cp .env.example .env
# Generar la clave maestra Fernet:
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Generar el pepper para hash de teléfonos:
python -c "import secrets; print(secrets.token_urlsafe(32))"
# Editar .env y completar todos los valores

# 5. Crear base de datos
createdb denunciabot

# 6. Correr migraciones
alembic upgrade head

# 7. Levantar el servicio
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
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
