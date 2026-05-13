# DenunciaBot — Seguridad y Privacidad de Datos

**Documento de referencia para áreas Jurídica y de Seguridad de la
información.**

Pensado para responder de manera explícita y verificable a las
preguntas que normalmente formulan estas áreas en proyectos
gubernamentales que manejan datos personales sensibles.

---

## 1. Marco normativo aplicable

| Norma | Aplicabilidad | Cumplimiento |
|-------|---------------|--------------|
| **Constitución del Ecuador, Art. 66 num. 19** (derecho a la protección de datos personales) | Sí — datos del denunciante | Cifrado en reposo, minimización, consentimiento informado |
| **Ley Orgánica de Protección de Datos Personales (LOPDP)** | Sí — datos personales y sensibles | Ver §3 a §7 |
| **Ley Orgánica de Transparencia y Acceso a la Información Pública (LOTAIP)** | Sí — operación institucional | Bitácora de auditoría disponible para entes de control |
| **Código Orgánico Integral Penal (COIP), Art. 268** (denuncia falsa) | Aplicable al denunciante | Advertencia explícita en el consentimiento (a definir, ver doc. 02) |
| **Normas ISO 27001** (gestión de seguridad de la información) | Buena práctica de referencia | Implementación cubre los principios de confidencialidad, integridad y disponibilidad |

## 2. Clasificación de los datos

### 2.1 Datos de identificación del denunciante

| Dato | Clasificación | Tratamiento |
|------|---------------|-------------|
| Número de teléfono (WhatsApp `wa_id`) | **DATO PERSONAL** | NUNCA se almacena en claro. Solo se guarda `SHA-256(pepper \|\| número)` |
| Nombre (de perfil WhatsApp) | DATO PERSONAL | NO se almacena. Meta lo envía pero el bot lo descarta. |
| IP de origen del request | DATO TÉCNICO | Logs operativos con retención limitada |

### 2.2 Datos de la denuncia

| Dato | Clasificación | Tratamiento |
|------|---------------|-------------|
| Institución denunciada | DATO INSTITUCIONAL | Cifrado en reposo (Fernet) |
| Descripción de los hechos | **DATO SENSIBLE** | Cifrado en reposo (Fernet) |
| Fecha aproximada | DATO TEMPORAL | En claro (no es sensible) |
| Personas involucradas | **DATO SENSIBLE — incluye terceros** | Cifrado en reposo (Fernet) |
| Perjuicio económico | DATO CUANTITATIVO | En claro |
| Denuncia previa en otra entidad | DATO PROCESAL | En claro |
| Evidencias (archivos) | **DATO SENSIBLE** | En disco con nombre UUID + permisos restrictivos. Nombre original cifrado. |

### 2.3 Datos operativos

| Dato | Clasificación | Tratamiento |
|------|---------------|-------------|
| Código público de seguimiento | IDENTIFICADOR TÉCNICO | Sin valor por sí mismo |
| Estado de la alerta | DATO PROCESAL | En claro |
| Bitácora de eventos | DATO DE AUDITORÍA | Inmutable, sin contenido sensible |

## 3. Principios de protección de datos aplicados

### 3.1 Minimización (Art. 10 LOPDP)

Se recolecta **únicamente** la información necesaria para tramitar la
denuncia:

- **NO** se solicita nombre, cédula ni dirección del denunciante.
- **NO** se almacena la fotografía de perfil de WhatsApp.
- **NO** se solicitan datos que no sean relevantes al hecho.

### 3.2 Calidad del dato (Art. 11 LOPDP)

Los campos textuales se validan antes de aceptarse:

- Longitudes mínimas y máximas razonables.
- Fechas válidas y no futuras.
- Tipos MIME y tamaños de archivo controlados.

### 3.3 Confidencialidad (Art. 14 LOPDP)

- **Cifrado simétrico Fernet** (AES-128-CBC + HMAC-SHA256) sobre los
  campos sensibles.
- Clave maestra de 32 bytes en custodia exclusiva del SERCOP, almacenada
  en variable de entorno con permisos `0o600` (solo lectura por el
  usuario del servicio).
- La clave **nunca** se almacena en la base de datos ni en logs.

### 3.4 Integridad (Art. 14 LOPDP)

- **Bitácora inmutable**: implementada con triggers PL/pgSQL que bloquean
  `UPDATE` y `DELETE` a nivel de base de datos. Verificable por cualquier
  cliente SQL (intento de modificar = excepción).
- **Audit trail criptográfico**: exportable bajo demanda, con hash
  encadenado SHA-256 y sello HMAC final que detecta modificación
  retroactiva.
- **Hash SHA-256** de cada archivo de evidencia.

### 3.5 Disponibilidad (Art. 14 LOPDP)

- **Backup automático diario** con retención de 30 días.
- **Idempotency** del webhook (Meta no causa duplicados ante reintentos).
- **Cola de tareas** con reintentos automáticos para SMTP y mensajes
  de cierre.

### 3.6 Consentimiento informado (Art. 7 LOPDP)

Antes de iniciar la recolección, el bot presenta el mensaje S1 que
incluye:

- Identificación del responsable (Secretaría General de Integridad
  Pública).
- Finalidad del tratamiento (registro de denuncia de corrupción).
- Categorías de datos a recolectar (lista explícita).
- Carácter confidencial del tratamiento.
- Derecho a cancelar en cualquier momento.

Solo si el ciudadano responde **"Sí, acepto"** se continúa al paso S3.

**Pendiente de validación legal**: ver `02-flujo-conversacional.md` §3.1.

## 4. Custodia de claves criptográficas

### 4.1 Clave maestra Fernet (`DENUNCIABOT_MASTER_KEY`)

- Generación: aleatoria, 32 bytes, codificación base64.
- Almacenamiento: única copia en el archivo `.env` del servidor de
  producción, con permisos `0o600` y dueño `denunciabot:denunciabot`.
- **NO** se sube al repositorio Git (excluida vía `.gitignore`).
- **NO** se comparte con la Secretaría (responsabilidad de custodia
  del SERCOP).

### 4.2 Pepper del teléfono (`DENUNCIABOT_PHONE_PEPPER`)

- Mismo régimen de custodia que la clave maestra.
- **DEBE SER DISTINTO** a la clave maestra.
- Si se filtrara únicamente el contenido de la base, sin el pepper no
  es posible reconstruir el número de teléfono original.

### 4.3 Secret de firma de audit trail (`AUDIT_HMAC_SECRET`)

- Mismo régimen.
- DISTINTO a las dos anteriores.
- Su compromiso permite falsificar exports pero no compromete datos
  almacenados ni acceso al panel.

### 4.4 Token del panel admin (`ADMIN_TOKEN`)

- Compartido entre el personal autorizado de la Secretaría.
- Almacenamiento: gestor de contraseñas institucional.
- Rotación recomendada: cada 90 días o ante salida de un autorizado.

### 4.5 Procedimiento de rotación

Documentado en `RUNBOOK.md §7`. Requiere coordinación entre SERCOP y la
Secretaría para evitar pérdida de acceso a datos previos.

## 5. Retención y eliminación

| Dato | Retención | Criterio |
|------|-----------|----------|
| Alertas | **Sin eliminación automática** | Cada denuncia es un acto institucional permanente; la Secretaría definirá política de archivo histórico |
| Bitácora de auditoría | **Sin eliminación** | Garantía técnica: triggers PL/pgSQL bloquean DELETE |
| Sesiones en Redis | 5 minutos (TTL automático) | Conversación viva, datos efímeros |
| Archivos temporales | 30 minutos (cron) | Adjuntos descargados de Meta pero no asociados a una denuncia confirmada |
| Logs en journald | Default systemd (configurable) | Operación, no contiene PII |
| Backups | 30 días en disco local | Recuperación ante incidentes |

**Pendiente de definir con la Secretaría**: política de archivo
histórico de denuncias antiguas (> N años).

## 6. Acceso y autorización

### 6.1 Acceso del ciudadano

- A su denuncia: vía endpoint público `GET /alerta/{codigo}`. Devuelve
  únicamente estado y fecha de registro, sin datos sensibles.
- Al contenido completo: NO disponible al ciudadano en esta versión.
  Si la Secretaría requiere ofrecer este servicio, debe definir el
  mecanismo de autenticación adicional (PIN, etc.).

### 6.2 Acceso del personal de la Secretaría

- Via panel administrativo en `/admin/login`.
- Autenticación con token compartido (a evolucionar a auth por usuario
  en versión 2.0 si la Secretaría lo requiere).
- Operaciones disponibles:
  - Listar denuncias con filtros.
  - Ver detalle con descifrado.
  - Cambiar estado (REGISTRADA → EN_REVISION → TRAMITADA / DESCARTADA).
  - Descargar audit trail firmado.

### 6.3 Acceso técnico del SERCOP

- Operación: equipo de operaciones del SERCOP — acceso a logs,
  métricas, base de datos.
- **NO** se descifran datos sensibles fuera del panel administrativo.
- Las acciones del personal técnico quedan registradas en logs del
  sistema operativo y en la bitácora.

### 6.4 Auditoría externa

- La Secretaría puede solicitar el audit trail firmado en cualquier
  momento (a través del panel).
- El audit trail es verificable offline por un auditor con
  `AUDIT_HMAC_SECRET`.

## 7. Análisis de riesgos y mitigaciones

### 7.1 Riesgo: filtración de la base de datos

**Escenario**: un atacante obtiene acceso al volcado de PostgreSQL.

**Mitigaciones implementadas**:

- Campos sensibles cifrados con Fernet → sin la clave maestra el
  contenido es ilegible.
- Teléfono hasheado con pepper → sin el pepper no es reversible aun
  forzando todas las combinaciones de números ecuatorianos.

**Daño potencial residual**: metadatos (códigos, timestamps, estados,
hashes de teléfono) quedan visibles. No revelan identidad pero
permitirían inferir actividad agregada.

### 7.2 Riesgo: compromiso del servidor

**Escenario**: un atacante toma control del proceso `denunciabot`.

**Mitigaciones implementadas**:

- Hardening systemd: `NoNewPrivileges`, `ProtectSystem=strict`,
  `ProtectHome`, `PrivateTmp`.
- Usuario sin shell ni privilegios elevados.
- `ReadWritePaths` limita escritura a directorios específicos.

**Daño potencial**: el atacante tendría las claves cifrado en memoria.
Mitigación adicional: monitoreo de procesos y alertas SIEM.

### 7.3 Riesgo: denegación de servicio

**Escenario**: un atacante envía miles de requests al webhook.

**Mitigaciones implementadas**:

- Rate limiting: 120 requests/minuto por IP (configurable).
- Validación HMAC antes de cualquier procesamiento → un atacante sin el
  app secret no puede invocar el motor.
- Idempotency: reintentos no acumulan trabajo.

### 7.4 Riesgo: ataque vía evidencias

**Escenario**: un atacante adjunta un archivo malicioso (PDF con
exploit, imagen polígloto, etc.).

**Mitigaciones implementadas**:

- Validación de MIME type contra lista blanca.
- Validación de tamaño máximo.
- Escaneo con ClamAV (cuando está habilitado).
- Almacenamiento en disco con permisos `0o600`, sin ejecución posible.
- El bot **nunca** ejecuta el contenido del archivo.

### 7.5 Riesgo: spoofing del webhook

**Escenario**: un atacante envía POST falsos al endpoint del webhook.

**Mitigaciones implementadas**:

- Validación HMAC SHA-256 estricta antes de cualquier procesamiento.
- Cualquier firma inválida → 401, log estructurado para SIEM.

### 7.6 Riesgo: modificación retroactiva de la bitácora

**Escenario**: alguien con acceso administrativo a la base intenta
"borrar" o "cambiar" un evento ya registrado.

**Mitigaciones implementadas**:

- Triggers PL/pgSQL bloquean UPDATE y DELETE — error a nivel de motor
  de base de datos.
- Audit trail con hash encadenado: aunque alguien deshabilitara el
  trigger, la modificación de una fila propaga a todas las posteriores
  y es detectable.

### 7.7 Riesgo: denuncia falsa

**Escenario**: un ciudadano presenta una denuncia con información falsa.

**Mitigaciones existentes**:

- Advertencia explícita en el consentimiento (pendiente afinar texto
  según indicación legal — ver doc. 02 §3.2).
- Trazabilidad: el hash del teléfono permite identificar reincidencia
  si la Secretaría desarrolla un procedimiento al respecto.

**No es competencia del bot detectar falsedad**: corresponde al
procedimiento institucional de la Secretaría.

## 8. Cumplimiento de buenas prácticas

| Práctica | Estado |
|----------|--------|
| Defensa en profundidad | ✓ Múltiples capas (HMAC, cifrado, hardening, ratelimit) |
| Principio del menor privilegio | ✓ Usuario sin privilegios, paths restringidos |
| Falla cerrada (fail-secure) | ✓ Firma inválida → 401; clave inválida → arranque falla |
| Logs sin PII | ✓ Sanitizador automático de 24 campos sensibles |
| Backups verificados | ✓ Backup diario; restauración documentada |
| Secretos fuera del código | ✓ Variables de entorno, `.env` excluido del repo |
| Cifrado en tránsito | ✓ TLS obligatorio (a cargo de SERCOP Seguridad) |
| Cifrado en reposo | ✓ Fernet a nivel de aplicación |
| Auditoría inmutable | ✓ Triggers PL/pgSQL + audit trail firmado |
| Reintentos idempotentes | ✓ Webhook idempotency con Redis NX |
| Plan de respuesta a incidentes | ✓ RUNBOOK con 14 escenarios resueltos |

## 9. Procedimientos institucionales sugeridos

A definir conjuntamente entre SERCOP y la Secretaría:

1. **Procedimiento de manejo de cada denuncia**: una vez recibida la
   notificación SMTP, ¿quién la revisa, en qué plazo, con qué criterios?

2. **Procedimiento de cambio de estado**: ¿qué requisitos formales hay
   para pasar una denuncia a TRAMITADA o DESCARTADA?

3. **Procedimiento ante denuncia urgente**: ¿hay categorías que
   requieren respuesta inmediata? ¿Cómo se identifican?

4. **Procedimiento ante intento de spoofing detectado**: si los logs
   reportan firmas inválidas recurrentes, ¿quién investiga?

5. **Procedimiento ante salida de personal autorizado**: rotación
   inmediata del `ADMIN_TOKEN`.

6. **Procedimiento de archivo histórico**: política de retención
   de denuncias antiguas (físico, lógico, exportación a archivo de
   gestión documental).

7. **Procedimiento de auditoría interna**: frecuencia de descarga del
   audit trail, verificación de la cadena de hashes.

## 10. Compromisos asumidos por SERCOP

- Operación 24/7 del bot (mejor esfuerzo, sin SLA contractual).
- Mantenimiento de la infraestructura técnica.
- Backups y restauraciones.
- Custodia de las claves criptográficas.
- Notificación a la Secretaría ante incidentes que afecten la
  confidencialidad o integridad de los datos.
- Provisión del subdominio y certificado TLS.
- Soporte técnico al personal autorizado de la Secretaría.

## 11. Compromisos solicitados a la Secretaría

- Designación del personal autorizado al panel administrativo.
- Custodia del `ADMIN_TOKEN` y rotación ante cambios de personal.
- Procedimiento institucional de revisión de denuncias.
- Notificación al SERCOP ante incidentes que afecten al canal.
- Designación de buzón SMTP institucional para notificaciones.
- Aprobación formal de los textos (doc. 02) y del presente esquema de
  seguridad.
