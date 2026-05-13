# DenunciaBot — Resumen Ejecutivo

**Proyecto:** Sistema institucional de recepción de denuncias ciudadanas
de corrupción a través de WhatsApp.

**Convenio:** Interinstitucional, sin costo, entre el Servicio Nacional
de Contratación Pública (SERCOP) y la Secretaría General de Integridad
Pública del Ecuador.

**Versión del documento:** 1.0
**Fecha:** 2026-05
**Responsable técnico:** Jonathan Mauricio Ruiz Sánchez — Analista de
Operaciones de Innovación Tecnológica 2, SERCOP.

---

## 1. Antecedentes

La Secretaría General de Integridad Pública requiere un canal accesible
y seguro para que la ciudadanía denuncie hechos de presunta corrupción
en el sector público ecuatoriano. WhatsApp es el medio de mensajería de
mayor penetración a nivel nacional, por lo que se identifica como el
canal idóneo para alcanzar al mayor número de denunciantes potenciales.

En el marco del convenio interinstitucional vigente, el SERCOP aporta la
plataforma técnica y operativa para este canal, sin costo para la
Secretaría, aprovechando la infraestructura ya en producción del sistema
**Sercobot** (atención de consultas de contratación pública).

## 2. Objetivo

Construir y operar un chatbot de WhatsApp Business que permita al
ciudadano:

- Presentar una denuncia de corrupción de manera guiada, en pasos breves
  y claros.
- Adjuntar evidencias en formato PDF, JPG o PNG.
- Recibir un código único de seguimiento.
- Consultar el estado de su denuncia con dicho código, sin necesidad de
  registrarse en otro sistema.

Y permitir a la Secretaría:

- Recibir notificación inmediata de cada nueva denuncia.
- Revisar las denuncias con descifrado controlado por personal autorizado.
- Mantener una bitácora inmutable de cada operación para fines de
  auditoría interna o externa.

## 3. Principios de diseño

| # | Principio | Implementación |
|---|-----------|----------------|
| 1 | **Determinismo total** | El bot opera como una máquina de estados pura. No utiliza inteligencia artificial generativa. Cada decisión es trazable y reproducible. |
| 2 | **Confidencialidad por diseño** | El número de teléfono del denunciante nunca se almacena en claro. Los campos sensibles (institución, descripción, personas) se cifran antes de persistirse. |
| 3 | **Trazabilidad inmutable** | Cada evento (mensaje recibido, alerta creada, cambio de estado) queda registrado en una bitácora de auditoría que no admite modificación ni eliminación, garantizado a nivel de base de datos. |
| 4 | **Resiliencia operativa** | El sistema tolera fallas momentáneas de sus dependencias (base de datos, cola de mensajes, API de Meta) sin perder denuncias en curso. |
| 5 | **Auditabilidad externa** | Capacidad de exportar el registro completo con firma criptográfica, permitiendo a un auditor externo verificar la integridad sin acceso al sistema. |
| 6 | **Sin costo para la Secretaría** | Toda la infraestructura técnica corre sobre activos del SERCOP. La Secretaría aporta el dominio público y el procedimiento institucional de revisión. |

## 4. Alcance funcional (versión 1.0)

### 4.1 Incluido

- Flujo conversacional de 8 pasos para recolección de denuncias.
- Validación de fechas, longitudes y formatos antes de aceptar datos.
- Recepción y escaneo antivirus de evidencias (hasta 5 archivos × 10 MB).
- Cifrado simétrico de campos sensibles con clave maestra en custodia
  del SERCOP.
- Notificación por correo electrónico a un buzón institucional designado
  por la Secretaría, por cada denuncia registrada.
- Panel administrativo web mínimo para consulta y cambio de estado
  (Registrada → En revisión → Tramitada / Descartada).
- Endpoint público de consulta de estado por código (sin datos sensibles).
- Bitácora de auditoría inmutable.
- Exportación de bitácora firmada para auditoría externa.
- Métricas operativas en formato estándar (Prometheus / OpenMetrics).
- Mensaje de cancelación voluntaria en cualquier momento del flujo.
- Cierre automático por inactividad (5 minutos sin respuesta).

### 4.2 No incluido en la versión 1.0

- Panel administrativo completo con roles, permisos y auditoría por
  usuario individual (uso compartido del panel en la versión 1.0).
- Categorización automática o priorización de denuncias por gravedad.
- Atención en idiomas distintos al español (kichwa, shuar y otros).
- Integración bidireccional con sistemas de gestión documental de la
  Secretaría.
- Encuesta de satisfacción al ciudadano posterior al registro.

Cada uno de estos puntos puede incorporarse a la hoja de ruta tras la
firma del acuerdo de alcance en la presente reunión.

## 5. Estado actual del proyecto

Al momento de la presente reunión, la infraestructura técnica del bot
se encuentra **construida, probada en entorno local y desplegable**.
Las cifras de avance:

- 8 incrementos de desarrollo entregados (git commits).
- Aproximadamente 13 500 líneas de código en Python 3.11.
- 125 pruebas automatizadas (86 unitarias + 13 de integración + otras).
- Integración continua configurada en GitHub Actions.
- Documentación operativa (runbook) con 14 escenarios resueltos.
- Cuatro unidades de servicio systemd para despliegue en RHEL 9.7.

**Pendientes para entrar en operación**:

1. Validación de los textos del flujo conversacional por parte del
   área de comunicación institucional.
2. Validación legal del consentimiento informado mostrado al ciudadano
   al iniciar la conversación.
3. Provisión de subdominio con certificado SSL por el área de
   seguridad informática del SERCOP.
4. Registro de la aplicación en Meta for Developers y aprobación del
   plantilla de mensajes.
5. Definición del buzón de correo institucional para las notificaciones.
6. Definición del responsable institucional de la revisión de denuncias.
7. Designación del personal autorizado para el panel administrativo.

## 6. Solicitudes a la contraparte

Para avanzar al despliegue productivo, se requiere de la Secretaría:

1. Aprobación de los textos del flujo conversacional (documento 02).
2. Aprobación del esquema de seguridad y privacidad (documento 04).
3. Designación de un punto focal técnico para coordinación.
4. Designación del buzón institucional para notificaciones.
5. Confirmación del procedimiento de manejo de cada denuncia recibida.
6. Acuerdo sobre tiempos de respuesta institucional a una denuncia.
7. Definición del tratamiento de denuncias no calificadas (no constituye
   hecho de corrupción, fuera de competencia, etc.).

## 7. Próximos hitos propuestos

| Hito | Responsable | Plazo sugerido |
|------|-------------|----------------|
| Aprobación de textos y flujo | Secretaría | Inmediato |
| Provisión de subdominio + SSL | SERCOP (seguridad) | 1 semana |
| Registro en Meta Business | SERCOP (técnico) | 1 semana |
| Pruebas en entorno de homologación | SERCOP + Secretaría | 2 semanas |
| Lanzamiento controlado (pilotaje) | Conjunto | 3 a 4 semanas |
| Lanzamiento público | Conjunto | A definir |

## 8. Contacto

**SERCOP — Equipo técnico**
- Jonathan Mauricio Ruiz Sánchez
- Analista de Operaciones de Innovación Tecnológica 2

Los documentos complementarios (flujo conversacional, arquitectura,
seguridad, agenda detallada y plantilla de acta) se entregan junto con
este resumen ejecutivo.
