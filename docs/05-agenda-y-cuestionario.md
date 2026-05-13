# Agenda de Reunión + Cuestionario de Levantamiento de Requisitos

**Reunión:** Levantamiento de requisitos funcionales y validación de
flujo — DenunciaBot.

**Asistentes esperados:**
- **SERCOP**: Jonathan Mauricio Ruiz Sánchez (responsable técnico).
- **Secretaría General de Integridad Pública**: punto focal funcional,
  representante legal/jurídico, representante de comunicación, contraparte
  técnica (si la designan).

**Duración estimada:** 90 a 120 minutos.

**Material a llevar:**

- Resumen ejecutivo impreso (doc. 01).
- Flujo conversacional impreso (doc. 02) — con espacio para anotaciones.
- Arquitectura técnica (doc. 03) — opcional, según perfil de asistentes.
- Seguridad y privacidad (doc. 04) — para la persona de legal/seguridad.
- Computadora con el bot funcionando para hacer una demostración en vivo.

---

## Agenda (90–120 min)

| Bloque | Tiempo | Contenido |
|--------|--------|-----------|
| 0 — Apertura | 5 min | Presentación de asistentes y objetivo de la reunión |
| 1 — Contexto y estado | 10 min | Resumen ejecutivo (doc. 01). Qué se ha construido. |
| 2 — Demostración en vivo | 15 min | Simulación del flujo completo desde un WhatsApp de prueba |
| 3 — Validación del flujo | 25 min | Recorrido por cada mensaje (doc. 02). Observaciones de comunicación. |
| 4 — Validación legal | 20 min | Consentimiento informado, advertencias normativas (doc. 04) |
| 5 — Definiciones de la Secretaría | 20 min | Cuestionario funcional (sección 1 más abajo) |
| 6 — Definiciones operativas | 15 min | Procedimientos institucionales (sección 2 más abajo) |
| 7 — Acuerdos y próximos pasos | 10 min | Llenar el acta de reunión (doc. 06) |

---

## Cuestionario de levantamiento

### Sección 1 — Definiciones funcionales

Preguntas que requieren una decisión formal de la Secretaría. Sin estas
respuestas no es posible avanzar al despliegue productivo.

#### 1.1 Buzón institucional para notificaciones

**Pregunta:** ¿A qué buzón de correo electrónico debe llegar la
notificación de cada nueva denuncia?

- [ ] Una sola dirección genérica (ej. denuncias@secretaria.gob.ec)
- [ ] Varias direcciones simultáneas (lista)
- [ ] Una sola dirección con redistribución interna posterior

**Respuesta acordada:** ________________________

#### 1.2 Personal autorizado al panel administrativo

**Pregunta:** ¿Cuántas personas y con qué roles tendrán acceso al panel
administrativo?

- Roles: [ ] solo lectura  [ ] lectura + cambio de estado  [ ] todo
- Cantidad estimada de personas: ____
- Modalidad de rotación de personal autorizado: ____________

**Implicancia técnica:** la versión 1.0 usa un token compartido. Si la
Secretaría requiere auth por usuario individual, se planifica en la
hoja de ruta versión 2.0.

#### 1.3 Procedimiento de revisión

**Pregunta:** Una vez recibida la notificación de una denuncia, ¿cuál
es el procedimiento que sigue la Secretaría?

Por escribir aquí:

  ____________________________________________________________

  ____________________________________________________________

**Sub-preguntas:**

- ¿Tiempo de respuesta institucional objetivo? (24h / 48h / semana)
- ¿Quién es el primer responsable de la revisión?
- ¿Existe un flujo de aprobación interna antes de pasar a TRAMITADA?

#### 1.4 Estados de la denuncia

**Pregunta:** Los estados propuestos por defecto son:
**REGISTRADA → EN_REVISION → TRAMITADA / DESCARTADA**.

- [ ] Mantener los 4 estados propuestos.
- [ ] Agregar estados intermedios (especificar): ____________
- [ ] Renombrar alguno (especificar): ____________

#### 1.5 Categorización de la denuncia

**Pregunta:** ¿La Secretaría requiere que el ciudadano categorice su
denuncia al presentarla (corrupción administrativa, contratación
pública, manejo de recursos, conflicto de interés, etc.)?

- [ ] **No**, mantener el flujo actual (texto libre).
- [ ] **Sí**, agregar una pregunta con opciones predefinidas.

Si la respuesta es sí, ¿con qué taxonomía? Lista de opciones:

  ____________________________________________________________

#### 1.6 Priorización de denuncias

**Pregunta:** ¿Hay denuncias que requieren atención inmediata?

- [ ] No — todas se tratan por orden cronológico.
- [ ] Sí — criterios de priorización: ____________

Si hay priorización, ¿qué medio de notificación adicional se requiere?

- [ ] Solo correo (igual que las demás).
- [ ] Correo + SMS al responsable.
- [ ] Correo + canal de mensajería institucional (Telegram, Teams, etc.).

#### 1.7 Atención en idiomas indígenas

**Pregunta:** ¿La Secretaría requiere atender denuncias en idiomas
distintos al español (kichwa, shuar, otros)?

- [ ] No — solo español en la versión 1.0.
- [ ] Sí — idiomas requeridos: ____________

**Implicancia**: cada idioma duplica el catálogo de mensajes (doc. 02) y
requiere validación por hablantes nativos.

#### 1.8 Encuesta de satisfacción

**Pregunta:** ¿Se desea enviar una encuesta corta al ciudadano N horas
después del cierre, para medir la calidad del canal?

- [ ] No.
- [ ] Sí, en N horas: ____ con preguntas: ____________

#### 1.9 Integración con sistemas existentes

**Pregunta:** ¿Cuenta la Secretaría con sistemas existentes a los cuales
DenunciaBot deba integrarse?

- [ ] No — DenunciaBot es autónomo.
- [ ] Sistema de gestión documental (especificar): ____________
- [ ] Sistema de tickets / mesa de ayuda (especificar): ____________
- [ ] Otro: ____________

**Implicancia**: la integración bidireccional implica desarrollar APIs o
exportes periódicos. Definir mecanismo (REST / webhook saliente / archivo).

#### 1.10 Acuerdos de servicio (SLA)

**Pregunta:** ¿Hay un SLA institucional al que el canal deba comprometerse?

- Disponibilidad mínima: ____% mensual
- Ventana de mantenimiento permitida: ____________
- Tiempo de respuesta máximo ante incidente: ____ horas

**Compromiso del SERCOP en la versión 1.0**: operación 24/7 mejor
esfuerzo, sin compromiso contractual de disponibilidad. Si la Secretaría
requiere SLA formal, definir consecuencias y reciprocidad.

### Sección 2 — Definiciones operativas

#### 2.1 Designación del punto focal técnico

Nombre y datos de contacto: ____________________________________

#### 2.2 Designación del punto focal funcional

Nombre y datos de contacto: ____________________________________

#### 2.3 Procedimiento ante incidente de seguridad

**Pregunta:** Si SERCOP detecta un incidente que afecta la
confidencialidad o integridad de los datos (ej. intento de spoofing
recurrente), ¿a quién se notifica en la Secretaría y en qué plazo?

  ____________________________________________________________

#### 2.4 Política de retención

**Pregunta:** ¿Cuánto tiempo deben mantenerse las denuncias en el
sistema antes de pasar a archivo histórico?

- [ ] Indefinidamente.
- [ ] N años: ____ con archivo a: ____________

#### 2.5 Auditorías programadas

**Pregunta:** ¿La Secretaría realiza auditorías periódicas internas? ¿En
qué frecuencia y qué información requieren del sistema?

  ____________________________________________________________

#### 2.6 Comunicación al ciudadano (canales adicionales)

**Pregunta:** Además del bot, ¿la Secretaría planea publicitar otros
canales de denuncia? Necesario para que el bot pueda referirlos en
mensajes de error si está caído.

  ____________________________________________________________

### Sección 3 — Validación de textos (cubrir junto con doc. 02)

Cada mensaje del flujo (S1 a S12) requiere aprobación. Use el documento
02 impreso como hoja de trabajo. Conclusiones a registrar:

- [ ] Texto de bienvenida (S1) — aprobado / con observaciones / a
      reescribir.
- [ ] Texto de cada paso S3 a S10 — aprobados / con observaciones.
- [ ] Texto de cancelación voluntaria — aprobado / con observaciones.
- [ ] Texto de inactividad — aprobado / con observaciones.
- [ ] Texto de cierre exitoso — aprobado / con observaciones.

### Sección 4 — Validación de seguridad y privacidad (cubrir junto con doc. 04)

- [ ] Marco normativo aplicable revisado por área legal.
- [ ] Esquema de cifrado validado por área de seguridad.
- [ ] Política de retención acordada.
- [ ] Procedimientos institucionales identificados (sección 9 del doc. 04).
- [ ] Compromisos institucionales aceptados (secciones 10 y 11 del doc. 04).

---

## Conducción sugerida de la reunión

### Tips para Mau (conducción)

**Antes de la reunión**:

1. Imprime los 6 documentos. Llévalos con marca-páginas.
2. Llega 15 minutos antes para verificar que tu computadora puede
   conectarse al wifi institucional y que el bot funciona.
3. Si llevas demo en vivo: prueba que tu número de WhatsApp pueda
   alcanzar el endpoint sandbox de Meta. Una falla aquí desinfla la
   reunión.
4. Ten una libreta para tomar nota de **toda** observación, incluso
   las que parezcan menores — luego se traducirán en cambios concretos.

**Durante la reunión**:

1. **No te disculpes anticipadamente** por el alcance limitado de la
   versión 1.0. Es deliberado: empezar pequeño, iterar con feedback.
2. **No prometas** plazos sin haberlos validado con tu equipo. Si te
   piden algo, anota como acción pendiente.
3. **Si hay desacuerdo sobre el flujo**, no defiendas — registra la
   observación y aclara que se ajustará. La validación de comunicación
   y legal manda sobre las decisiones técnicas iniciales.
4. **Si surgen requerimientos nuevos** (Bloque 4 del plan: priorización,
   multi-idioma, integraciones), documéntalos como **hoja de ruta** —
   no comprometas que entran en la versión 1.0.
5. **Si surgen requerimientos no técnicos** (procedimientos internos,
   designaciones), regístralos como pendientes de la Secretaría.

**Al cerrar**:

1. Llena el acta de reunión (doc. 06) **en vivo** con los asistentes.
2. Lee en voz alta los acuerdos antes de cerrar.
3. Define próxima reunión o fecha de entrega de observaciones por
   escrito (máximo 1 semana).

### Posibles preguntas difíciles y respuestas sugeridas

**P: "¿Y si el ciudadano denuncia falsamente para perjudicar a alguien?"**

R: El bot **no** verifica la veracidad — eso es responsabilidad del
procedimiento institucional de la Secretaría. El bot solo recolecta y
trasmite. En el consentimiento se puede agregar una advertencia
explícita sobre la responsabilidad penal de la denuncia falsa (Art. 268
COIP). El hash del teléfono permite identificar reincidencia si la
Secretaría desarrolla un procedimiento al respecto.

**P: "¿Cómo nos garantizan que SERCOP no accederá al contenido de las
denuncias?"**

R: Técnicamente: la clave de descifrado está en custodia del SERCOP por
necesidad operativa (para descifrar en el panel administrativo). El
control real es la **bitácora inmutable**: cada acceso al panel queda
registrado con identificador de sesión, en una tabla que no admite
modificación. La Secretaría puede auditar en cualquier momento
descargando el audit trail firmado. Si se requiere un nivel de garantía
superior (HSM, separación de funciones, etc.), se planifica para
versión 2.0.

**P: "¿Y si Meta cambia su API o nos suspende?"**

R: Riesgo real. Mitigaciones:
- Las denuncias ya registradas no dependen de Meta — están en la base
  de datos del SERCOP.
- La hoja de ruta puede incluir un canal alternativo (Telegram, web
  pública con captcha, llamada con voz a texto).
- El bot está diseñado modularmente: cambiar el canal de entrada
  implica un nuevo módulo, no rehacer todo.

**P: "¿Cuánto se demora el despliegue después de esta reunión?"**

R: Depende de tres factores:
1. Velocidad de aprobación de textos por comunicación y legal (días a
   semanas).
2. Provisión del subdominio y certificado por SERCOP Seguridad
   (1 semana típicamente).
3. Aprobación de la aplicación en Meta Business (varios días, depende
   de Meta).

Estimación realista: **3 a 4 semanas** a producción tras esta reunión,
si todo fluye normalmente.
