# Agenda — Reunión con TI de la Secretaría: infraestructura para DenunciaBot

**Objetivo:** acordar el provisionamiento de la infraestructura institucional necesaria para llevar DenunciaBot a producción.

**Asistentes esperados:**
- **SERCOP**: Jonathan Mauricio Ruiz Sánchez (responsable técnico DenunciaBot), Paul *[Apellido]* (jefe directo) — opcional.
- **Secretaría General de Integridad Pública**: Coordinador de Infraestructura TI, Administrador de servidores Linux, DBA PostgreSQL, Administrador de correo, responsable de seguridad de red (si aplica).

**Duración estimada:** 60 minutos.

**Material a llevar:**

- Doc. 03 — Arquitectura técnica (impreso, marca-páginas en secciones 5 y 6).
- Doc. 07 — Guía técnica de dominio (impreso o digital, secciones 3, 6, 8 marcadas).
- Esta agenda (doc. 08) impresa para el conductor.
- Doc. 09 — Acta de reunión TI (para llenar en vivo).
- Laptop con el bot funcionando localmente para demo opcional (Mailpit + ngrok activos).

---

## Agenda (60 minutos)

| Bloque | Tiempo | Contenido |
|---|---|---|
| 0 — Apertura | 3 min | Presentación rápida de asistentes y objetivo |
| 1 — Estado del proyecto | 5 min | Qué se construyó, qué se validó, qué falta |
| 2 — Demo del bot (opcional) | 7 min | Mostrar el flujo end-to-end con un caso real |
| 3 — Mapa de procesos | 5 min | Qué procesos correrán en el servidor (doc. 07 sec. 3) |
| 4 — Requerimiento de infraestructura | 20 min | Servidor, BD, red, correo — punto por punto |
| 5 — Preguntas de TI hacia SERCOP | 10 min | Lo que TI necesita saber para operar |
| 6 — Compromisos y tickets | 8 min | Quién hace qué, en qué plazo |
| 7 — Cierre | 2 min | Llenar acta y firmar |

---

## Estado del proyecto (apertura — 5 min)

> Mensaje clave para abrir: "El bot funciona técnicamente. Lo único que falta es la infraestructura institucional para despliegue."

**Listo y validado:**

- Flujo conversacional completo (12 estados, 8 preguntas al ciudadano).
- 180 pruebas unitarias en verde.
- Integración con Meta WhatsApp Cloud API funcional (demo end-to-end con código `ALR-2026-MJY3LW`).
- Cifrado de campos sensibles, hash con sal del teléfono, bitácora inmutable.
- Panel administrativo web, consulta pública por código.
- Notificación SMTP al cierre de denuncia.
- Backups automatizados, métricas Prometheus, audit trail firmado.

**Pendiente (depende de TI Secretaría):**

- Servidor con stack instalado.
- Base de datos asignada.
- Subdominio público con TLS.
- Casilla institucional para envío del bot.

---

## Requerimiento de infraestructura (bloque 4 — 20 min)

Para cada bloque: presentar la solicitud, escuchar capacidad de TI, anotar plazo y responsable en el acta (doc. 09).

### 4.1 Servidor

| Recurso | Solicitado | Acordado |
|---|---|---|
| Sistema operativo | RHEL 9.7 (preferible el mismo de Sercobot) | __________ |
| Recursos | 2 vCPU / 4 GB RAM / 40 GB disco | __________ |
| Usuario de servicio | `denunciabot` (sin shell interactivo) | __________ |
| Directorio de instalación | `/opt/denunciabot` | __________ |
| Paquetes a instalar (`dnf`) | `python3.11`, `redis`, `gcc`, `openssl-devel`, `libffi-devel`, `postgresql-devel` | __________ |
| Paquete opcional | `clamav`, `clamd` (escaneo antivirus de evidencias) | __________ |
| Plazo estimado de provisionamiento | ____ días | __________ |

**Nota técnica:** Python 3.11 debe coexistir con Python 3.8 (usado por Sercobot). No reemplazar.

### 4.2 Base de datos PostgreSQL

| Recurso | Solicitado | Acordado |
|---|---|---|
| Clúster | El mismo Postgres 16 de Sercobot | __________ |
| Base de datos | `denunciabot` | __________ |
| Usuario propietario | `denunciabot` | __________ |
| Privilegios | Owner sobre la BD, sin acceso a otras del clúster | __________ |
| Charset / Collation | UTF-8 / es_EC.UTF-8 | __________ |
| Conexiones máximas asignadas | 20 simultáneas | __________ |
| Canal de entrega de credenciales | _________________________ | __________ |

### 4.3 Red y exposición pública

| Recurso | Solicitado | Acordado |
|---|---|---|
| Subdominio público | Sugerido: `denuncia.secretaria.gob.ec` | __________ |
| Certificado TLS | Gestionado y renovado por equipo de seguridad de SERCOP | __________ |
| Terminación TLS | En reverse proxy institucional; el bot escucha solo en `127.0.0.1:8000` | __________ |
| Egress permitido | `graph.facebook.com:443` (Meta), `smtp.sercop.gob.ec:587` (correo) | __________ |
| Ingress permitido | HTTPS público hacia el subdominio (rangos públicos de Meta) | __________ |

### 4.4 Casilla institucional para envío del bot

| Recurso | Solicitado | Acordado |
|---|---|---|
| Cuenta dedicada | Sugerido: `denunciabot@sercop.gob.ec` (cuenta de servicio) | __________ |
| Tipo de acceso | Solo SMTP saliente, no IMAP/POP | __________ |
| Modalidad | Credenciales SMTP **o** relay autenticado por IP (preferido) | __________ |
| Buzón destinatario | `integridad@secretaria.gob.ec` — confirmar si es lista de distribución | __________ |
| SPF/DKIM | Validar registros DNS para evitar entrega a spam | __________ |

### 4.5 Excepciones de SOC para procesos del bot

Durante la operación normal, los procesos `python3.11`, `gunicorn`, `dramatiq` corriendo bajo `/opt/denunciabot` no deberían disparar alertas. Coordinar:

- [ ] Whitelisting de procesos del bot en el SOC.
- [ ] Documentación del subdominio público como destino conocido en el inventario.

---

## Preguntas de TI hacia SERCOP (bloque 5 — 10 min)

Anticipa estas preguntas. Respuestas sugeridas en la columna derecha.

| Pregunta esperada de TI | Respuesta sugerida |
|---|---|
| ¿Cómo se despliega una nueva versión? | `git pull` + `alembic upgrade head` + `systemctl restart denunciabot denunciabot-worker`. Tiempo total ~30 segundos. Sin downtime perceptible. |
| ¿Dónde van los logs? | JSON estructurado vía `structlog`, escritos a `journald`. Acceso con `journalctl -u denunciabot`. Compatibles con SIEM institucional. |
| ¿Cómo monitorean la salud? | Endpoint `/health` para readiness, `/metrics` para Prometheus. Métricas clave documentadas en `RUNBOOK.md` sección 11. |
| ¿Qué pasa si SMTP se cae? | Las denuncias se persisten en BD igual. El correo queda encolado en Dramatiq con reintentos exponenciales (4 intentos en ~30 segundos). Si tras 4 intentos sigue fallando, queda en dead-letter — se procesa cuando SMTP vuelve. |
| ¿Cómo backupean la BD? | `pg_dump` automatizado vía `denunciabot-backup.timer`, cifrado con AES-256. Frecuencia configurable. Procedimiento de restauración en `RUNBOOK.md` sección 8. |
| ¿Quién está de on-call? | Por definir con la Secretaría. Versión 1.0 es "mejor esfuerzo" sin SLA contractual. |
| ¿Cómo rotan secretos? | Procedimiento documentado en `RUNBOOK.md` sección 7 (master key Fernet). Pasos manuales coordinados con SERCOP. |
| ¿Qué hace el bot si Meta se cae? | Las denuncias en curso se mantienen en estado intermedio. Cuando Meta vuelve, el ciudadano puede continuar. Sesiones que pasan más de 5 min sin avance se descartan automáticamente. |
| ¿Hay límites de tasa? | Sí, 120 req/min por IP a nivel del bot (slowapi). Meta tiene los suyos (~1000 mensajes/segundo). |
| ¿Cómo se accede al panel admin? | URL: `https://denuncia.secretaria.gob.ec/admin/login`. Token compartido entregado por canal seguro. Sesión expira en 8h. |

---

## Demo opcional del bot (bloque 2 — 7 min)

Solo si hay equipo / proyector. Mostrar:

1. La URL pública vía ngrok respondiendo a `/health`.
2. Enviar "hola" desde un WhatsApp personal al número de la app.
3. Completar el flujo S0 → S12 hasta recibir código de seguimiento.
4. Mostrar en DBeaver la denuncia recién creada con campos cifrados (BYTEA opaco).
5. Abrir el panel admin → mostrar la misma denuncia con campos descifrados al vuelo.
6. Mostrar Mailpit con el correo institucional capturado.
7. Demostrar que `DELETE FROM bitacora_auditoria` falla con error del trigger.

> Si no hay tiempo para demo, dejar para una segunda reunión técnica. No insistir.

---

## Compromisos a documentar (bloque 6 — 8 min)

| Compromiso | Responsable | Plazo | Estado |
|---|---|---|---|
| Crear usuario `denunciabot` en RHEL | TI Secretaría | _____ | [ ] |
| Instalar paquetes (`python3.11`, `redis`, etc.) | TI Secretaría | _____ | [ ] |
| Crear BD + usuario PostgreSQL | DBA Secretaría | _____ | [ ] |
| Solicitar y configurar subdominio + TLS | Seguridad Secretaría | _____ | [ ] |
| Crear casilla `denunciabot@sercop.gob.ec` (o equivalente) | Admin de correo | _____ | [ ] |
| Confirmar buzón `integridad@secretaria.gob.ec` como lista de distribución | Secretaría | _____ | [ ] |
| Entregar credenciales por canal seguro | TI Secretaría | _____ | [ ] |
| Whitelisting en SOC de procesos del bot | Seguridad | _____ | [ ] |
| Desplegar bot en RHEL (cargo SERCOP) | SERCOP — Mau | _____ | [ ] |
| Validación de despliegue end-to-end | Ambos | _____ | [ ] |

---

## Tips para Mau (conducción)

- **El bot ya funciona.** No tienes que defender la viabilidad. Esta reunión es de provisionamiento, no de evaluación.
- **No tecnicismos innecesarios.** TI institucional no necesita saber qué es Fernet o Dramatiq. Sí necesita saber: 2 procesos, 1 BD, 1 puerto, 1 buzón.
- **No prometas plazos por TI.** Si te dicen "esto toma 2 semanas", anótalo. Si tu estimación era 1, no contradigas en vivo.
- **Anota nombre + cargo + correo de cada persona que asignen.** Para escalar cuando se atasque algo.
- **Si surge una pregunta que no sabes responder**, anótala como pendiente. Es mejor que improvisar mal.

## Posibles preguntas difíciles

**P: "¿Por qué no usar el servidor de Sercobot directamente?"**

R: Es exactamente lo que pedimos. Mismo servidor RHEL, mismo clúster Postgres, distinto usuario y distinta BD para aislamiento lógico. No requerimos hardware adicional.

**P: "¿Por qué Python 3.11 si Sercobot usa 3.8?"**

R: DenunciaBot usa dependencias modernas que requieren 3.11+. Las dos versiones de Python coexisten sin conflicto en RHEL (paquetes paralelos `python38` y `python311`).

**P: "¿Por qué necesitan Redis si ya tienen PostgreSQL?"**

R: Redis maneja las sesiones conversacionales en curso (TTL de minutos) y la cola de tareas asíncronas. Es órdenes de magnitud más rápido que Postgres para este caso de uso. Hacer todo en Postgres genera latencia inaceptable bajo carga.

**P: "¿Y si el bot recibe ataques DDoS?"**

R: Tres capas: (1) rate-limit a nivel del bot (slowapi), (2) WAF/CDN del reverse proxy institucional, (3) los webhooks vienen solo de rangos de IP de Meta — podría restringirse el ingress a esos rangos.

**P: "¿Pueden ver los logs en tiempo real desde su lado (SERCOP)?"**

R: Los logs viven en el servidor de la Secretaría. SERCOP solo accede con cuenta documentada y vía SSH coordinado. La Secretaría puede integrar el journal con su SIEM (procedimiento en `RUNBOOK.md` sección 12).
