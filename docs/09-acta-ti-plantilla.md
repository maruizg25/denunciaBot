# ACTA DE REUNIÓN — TI Secretaría: infraestructura DenunciaBot

> Plantilla para llenar durante la reunión. Imprimir dos copias (SERCOP + Secretaría). Firmar al cierre.

---

## Datos generales

**Fecha:** _____ / _____ / _____

**Hora de inicio:** ______ : ______

**Hora de cierre:** ______ : ______

**Lugar:** ____________________________________________________

**Modalidad:** [ ] Presencial   [ ] Virtual   [ ] Mixta

**Convocada por:** ____________________________________________

**Objetivo:** acordar el provisionamiento de infraestructura para despliegue productivo de DenunciaBot.

---

## Asistentes

### Por SERCOP

| Nombre completo | Cargo | Correo / Extensión | Firma |
|---|---|---|---|
| Jonathan Mauricio Ruiz Sánchez | Analista de Operaciones de Innovación Tecnológica 2 | jonathan.ruiz@sercop.gob.ec | __________ |
| ________________________ | ________________________ | ________________________ | __________ |

### Por la Secretaría General de Integridad Pública

| Nombre completo | Cargo / Rol | Correo / Extensión | Firma |
|---|---|---|---|
| ________________________ | Coordinador Infraestructura TI | ________________________ | __________ |
| ________________________ | Admin servidores Linux | ________________________ | __________ |
| ________________________ | DBA PostgreSQL | ________________________ | __________ |
| ________________________ | Admin de correo | ________________________ | __________ |
| ________________________ | Seguridad / SOC | ________________________ | __________ |
| ________________________ | Otro: __________________ | ________________________ | __________ |

---

## Documentos presentados

- [ ] Doc. 03 — Arquitectura técnica
- [ ] Doc. 07 — Guía técnica de dominio
- [ ] Doc. 08 — Agenda de esta reunión
- [ ] Doc. 09 — Esta acta

**Otros documentos entregados:** ____________________________________

---

## 1. Servidor asignado

| Atributo | Valor acordado |
|---|---|
| Hostname / IP | _____________________________________ |
| Sistema operativo | _____________________________________ |
| Recursos (CPU / RAM / Disco) | _____________________________________ |
| Usuario de servicio creado | _____________________________________ |
| Directorio de instalación | _____________________________________ |
| Acceso (SSH key / VPN / bastión) | _____________________________________ |
| Plazo de entrega | _____________________________________ |
| Responsable directo | _____________________________________ |

**Paquetes instalados:**

- [ ] python3.11
- [ ] python3.11-devel, python3.11-pip
- [ ] gcc, gcc-c++, openssl-devel, libffi-devel
- [ ] postgresql-devel
- [ ] redis (`systemctl enable --now redis`)
- [ ] clamav, clamd (opcional): __________
- [ ] Otros: __________________________________________________

---

## 2. Base de datos

| Atributo | Valor acordado |
|---|---|
| Host / puerto Postgres | _____________________________________ |
| Versión Postgres | _____________________________________ |
| Nombre de la BD | _____________________________________ |
| Usuario owner | _____________________________________ |
| Charset / collation | _____________________________________ |
| Conexiones máximas asignadas | _____________________________________ |
| Canal de entrega de credenciales | _____________________________________ |
| Plazo de entrega | _____________________________________ |
| Responsable | _____________________________________ |

---

## 3. Red y exposición pública

| Atributo | Valor acordado |
|---|---|
| Subdominio público asignado | _____________________________________ |
| Autoridad certificadora del TLS | _____________________________________ |
| Reverse proxy / terminador TLS | _____________________________________ |
| Puerto interno escuchado por el bot | 127.0.0.1:8000 |
| Egress habilitado a `graph.facebook.com:443` | [ ] Sí  [ ] Pendiente |
| Egress habilitado al SMTP institucional | [ ] Sí  [ ] Pendiente |
| Ingress restringido (opcional) | [ ] A rangos IP de Meta  [ ] Abierto |
| Plazo de entrega | _____________________________________ |
| Responsable | _____________________________________ |

---

## 4. Casilla institucional del bot (saliente)

| Atributo | Valor acordado |
|---|---|
| Dirección del remitente (bot) | _____________________________________ |
| Modalidad | [ ] SMTP user/password  [ ] Relay por IP whitelist |
| Host SMTP | _____________________________________ |
| Puerto SMTP | _____________________________________ |
| TLS | [ ] STARTTLS  [ ] SSL implícito  [ ] Sin TLS |
| SPF/DKIM configurado | [ ] Sí  [ ] Pendiente |
| Buzón destinatario | _____________________________________ |
| ¿Es lista de distribución? | [ ] Sí  [ ] No |
| Canal de entrega de credenciales | _____________________________________ |
| Plazo de entrega | _____________________________________ |
| Responsable | _____________________________________ |

---

## 5. Seguridad y SOC

| Acuerdo | Estado |
|---|---|
| Whitelisting de procesos del bot en el SOC | [ ] Acordado  [ ] Pendiente: __________ |
| Documentación del subdominio en inventario institucional | [ ] Acordado  [ ] Pendiente: __________ |
| Política de rotación de la master key Fernet | Frecuencia: __________ Responsable: __________ |
| Integración logs con SIEM institucional | [ ] Sí, plataforma: __________  [ ] No por ahora |
| Acceso del personal SERCOP al servidor | [ ] Solo Mau (jonathan.ruiz)  [ ] Lista adicional: __________ |

---

## 6. Tickets internos abiertos

| # ticket | Área | Descripción breve | Asignado a | Plazo |
|---|---|---|---|---|
| ______ | Infra | ____________________________________ | __________ | ______ |
| ______ | DBA | ____________________________________ | __________ | ______ |
| ______ | Red | ____________________________________ | __________ | ______ |
| ______ | Correo | ____________________________________ | __________ | ______ |
| ______ | SOC | ____________________________________ | __________ | ______ |

---

## 7. Compromisos por SERCOP

- [ ] Coordinar despliegue inicial con TI de la Secretaría una vez recibido el servidor.
- [ ] Entregar guía técnica de dominio (doc. 07) al equipo de operación.
- [ ] Acompañar puesta en producción durante la primera semana (atención prioritaria).
- [ ] Documentar cualquier procedimiento ad-hoc en `RUNBOOK.md`.
- [ ] Notificar al SOC de cualquier prueba que pudiera disparar alertas.

---

## 8. Compromisos por la Secretaría

- [ ] Provisionar infraestructura según secciones 1-4 de esta acta.
- [ ] Designar punto focal técnico de la Secretaría para escalación.
- [ ] Confirmar buzón destinatario (`integridad@secretaria.gob.ec`) como activo y monitoreado.
- [ ] Capacitación al equipo de revisión de denuncias (fecha tentativa: __________).

---

## 9. Riesgos y bloqueos identificados

| Riesgo / bloqueo | Impacto | Mitigación acordada |
|---|---|---|
| ________________________________ | ________________ | ________________________________ |
| ________________________________ | ________________ | ________________________________ |
| ________________________________ | ________________ | ________________________________ |

---

## 10. Próxima reunión / hito

**Fecha tentativa:** _____ / _____ / _____ a las ______ : ______

**Objetivo de la siguiente reunión:** _____________________________

**Convocatoria a cargo de:** ________________________________

---

## 11. Observaciones finales

Espacio libre para comentarios, decisiones que no encajan en las secciones anteriores, dudas que quedaron pendientes.

```
____________________________________________________________________

____________________________________________________________________

____________________________________________________________________

____________________________________________________________________

____________________________________________________________________
```

---

## Firmas de cierre

**Por SERCOP:** ____________________________________  Fecha: ____ / ____ / ____

**Por la Secretaría:** ____________________________________  Fecha: ____ / ____ / ____
