# DenunciaBot — Resumen para TI Secretaría

**Convenio SERCOP – Secretaría General de Integridad Pública | Junio 2026**

---

## ¿Qué es?

Chatbot institucional sobre **WhatsApp** que recolecta denuncias ciudadanas de corrupción siguiendo un flujo conversacional de **8 preguntas** (institución, descripción, fecha, involucrados, perjuicio, denuncia previa, evidencias, confirmación). Cada denuncia recibe un código único de seguimiento (`ALR-2026-XXXXXX`) que el ciudadano conserva.

**Sin IA generativa.** Flujo 100% determinista y auditable.

---

## Estado actual del proyecto

| Componente | Estado |
|---|---|
| Flujo conversacional (12 estados) | ✅ Operativo |
| Integración Meta WhatsApp Cloud API | ✅ Validada end-to-end |
| Cifrado de campos sensibles (Fernet) | ✅ Implementado |
| Bitácora inmutable a nivel de BD | ✅ Implementada |
| Panel administrativo web (fallback) | ✅ Funcional |
| API REST para consumo de la Secretaría | 🔧 Próximo sprint |
| Consulta pública por código | ✅ Funcional |
| Notificación SMTP institucional | ✅ Lista, depende de buzón |
| Backups automatizados + métricas Prometheus | ✅ Configurados |
| Pruebas automatizadas (unitarias) | ✅ 180/180 verde |
| Infraestructura productiva | ⏳ **Solicitando a TI Secretaría** |

---

## Lo que se solicita a TI hoy

### 1. Servidor RHEL 9.7

- **Preferible:** el mismo de Sercobot (recursos compartidos, aislamiento por usuario).
- 2 vCPU / 4 GB RAM / 40 GB disco.
- Usuario de servicio `denunciabot` (sin shell interactivo).
- Instalar vía `dnf`: `python3.11`, `redis`, `gcc`, `openssl-devel`, `libffi-devel`, `postgresql-devel`. Opcional: `clamav`.

### 2. Base de datos PostgreSQL

- Sobre el clúster Postgres 16 existente.
- BD `denunciabot`, usuario `denunciabot` como owner, UTF-8.

### 3. Subdominio público + TLS

- Sugerido: `denuncia.secretaria.gob.ec`.
- Certificado y terminación TLS gestionados por el equipo de seguridad institucional.
- El bot escucha solo en `127.0.0.1:8000`; el TLS termina en el reverse proxy.
- Egress requerido: `graph.facebook.com:443` (Meta), `smtp.sercop.gob.ec:587` (correo).

### 4. Casilla de correo institucional para el bot

- Cuenta de servicio dedicada (sugerido: `denunciabot@sercop.gob.ec`).
- Solo envío saliente (no IMAP/POP).
- **Preferible:** relay autenticado por IP en lugar de password en disco.
- Buzón destinatario ya conocido: `integridad@secretaria.gob.ec` (idealmente lista de distribución).

---

## Arquitectura en una imagen

```
  Ciudadano (WhatsApp)
         ↓
    Meta Cloud API
         ↓ HTTPS
  Reverse proxy institucional  (gestiona TLS)
         ↓
  Servidor RHEL 9.7
  ┌──────────────────────────────────────────┐
  │  API FastAPI    Worker Dramatiq          │
  │  (gunicorn)     (SMTP + cierres)         │
  │       ↓              ↓                    │
  │  PostgreSQL 16   Redis 7                  │
  │  (compartido)    (sesiones + cola)        │
  └──────────────────────────────────────────┘
         ↓                ↓
    correo institucional   métricas Prometheus
```

---

## Operación día a día

- 1 proceso API + 1 worker, ambos bajo **systemd**.
- Logs JSON estructurado vía `journald` → compatibles con SIEM.
- Healthcheck: `GET /health`. Métricas: `GET /metrics` (Prometheus).
- Backups automatizados con cifrado AES-256 (timer systemd).
- Redespliegue: `git pull && alembic upgrade head && systemctl restart` (< 30 s).
- Procedimientos de troubleshooting documentados en `RUNBOOK.md` (14 secciones).

---

## Seguridad

- **Capa 1:** rate limit por IP (slowapi, 120 req/min).
- **Capa 2:** validación HMAC-SHA256 de cada webhook entrante (sin firma → 401).
- **Capa 3:** validación Pydantic del payload.
- **Capa 4:** validadores conversacionales con max 3 intentos por estado.
- **En reposo:** cifrado Fernet en campos sensibles; hash con sal del teléfono (LOPDP Art. 10).
- **Auditoría:** bitácora inmutable a nivel SQL (triggers bloquean UPDATE/DELETE); export firmado con HMAC para descargas legales.

---

## Modelo de consumo (separación de responsabilidades)

- **SERCOP entrega:** bot conversacional + base de datos + **API REST documentada, autenticada y auditada** (`/api/v1/alertas`, `/api/v1/audit-trail`, etc.) para que la Secretaría consuma desde su propio frontend.
- **Secretaría desarrolla:** interfaz operativa propia integrada con su SSO institucional, identidad visual y procedimientos internos de revisión.
- **Autenticación API:** clave por consumidor (`X-API-Key`) emitida y rotada por SERCOP; cada llamada queda en bitácora.
- **Panel admin SERCOP:** disponible como fallback institucional mientras la Secretaría arma su frontend.

## Compromiso de SERCOP

- Despliegue inicial en el servidor de la Secretaría.
- **Entrega de contrato API REST documentado** (ver doc. 11) para el equipo de desarrollo de la Secretaría.
- Acompañamiento durante la primera semana de operación.
- Documentación operativa (`RUNBOOK.md`, doc. 07).
- Capacitación al equipo de revisión de denuncias.

---

## Contactos

| Quién | Cargo | Correo |
|---|---|---|
| Jonathan Mauricio Ruiz Sánchez | Analista de Operaciones de Innovación Tecnológica 2 — SERCOP | jonathan.ruiz@sercop.gob.ec |
| Paúl Vásquez | Jefe directo SERCOP | _____________________________ |

**Repositorio:** `github.com/maruizg25/denunciabot` (público — sin secretos en código)

**Documentación técnica completa:** `docs/` del repositorio (10 documentos institucionales).
