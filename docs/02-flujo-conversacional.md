# DenunciaBot — Flujo Conversacional Completo

**Documento de referencia para validación por Comunicación y Legal.**

Este documento contiene **todos los mensajes** que recibirá el ciudadano
denunciante durante la conversación con el bot, en el orden exacto en
que serán emitidos por el sistema. Está pensado para revisión por:

- **Área de comunicación institucional** — verificar tono, claridad,
  ortografía, alineación con la voz institucional de la Secretaría.
- **Área legal / jurídica** — verificar consentimiento informado,
  cumplimiento normativo (LOPDP, LOTAIP), advertencias necesarias.

---

## 1. Diagrama del flujo

```
                       ┌──────────────────────┐
                       │   Ciudadano envía    │
                       │   primer mensaje     │
                       └──────────┬───────────┘
                                  │
                                  ▼
                          ┌───────────────┐
                          │ S1 BIENVENIDA │  Mensaje obligatorio
                          │ + requisitos  │  con consentimiento
                          └───────┬───────┘
                                  │
                                  ▼
                          ┌───────────────┐
                          │ S2 ACEPTACIÓN │  ¿Continúa? (SÍ/NO)
                          └───────┬───────┘
                                  │
                  ┌───────────────┴───────────────┐
                  │ NO                            │ SÍ
                  ▼                               ▼
            [CANCELADA]                  ┌───────────────┐
                                         │ S3 INSTITUCIÓN│  Texto libre 3..200
                                         └───────┬───────┘
                                                 │
                                                 ▼
                                         ┌───────────────┐
                                         │ S4 DESCRIPCIÓN│  Texto 30..2000
                                         └───────┬───────┘
                                                 │
                                                 ▼
                                         ┌───────────────┐
                                         │ S5 FECHA      │  dd/mm/aaaa,
                                         │  APROXIMADA   │  mm/aaaa, aaaa,
                                         └───────┬───────┘  "no recuerdo"
                                                 │
                                                 ▼
                                         ┌───────────────┐
                                         │ S6            │  Opcional,
                                         │ INVOLUCRADOS  │  "no conozco"
                                         └───────┬───────┘  válido
                                                 │
                                                 ▼
                                         ┌───────────────┐
                                         │ S7 PERJUICIO  │  Opcional,
                                         │  ECONÓMICO    │  "no aplica"
                                         └───────┬───────┘
                                                 │
                                                 ▼
                                         ┌───────────────┐
                                         │ S8 DENUNCIA   │  SÍ/NO
                                         │  PREVIA       │  Si SÍ: ¿cuál?
                                         └───────┬───────┘
                                                 │
                                                 ▼
                                         ┌───────────────┐
                                         │ S9 EVIDENCIAS │  PDF/JPG/PNG
                                         │               │  hasta 5×10 MB
                                         └───────┬───────┘
                                                 │
                                                 ▼
                                         ┌───────────────┐
                                         │ S10 VALIDACIÓN│  Confirmar /
                                         │  resumen      │  Editar / Cancelar
                                         └───────┬───────┘
                                                 │
                                                 ▼
                                         ┌───────────────┐
                                         │ S11 REGISTRO  │  Persistencia
                                         │  (automático) │  + notificación
                                         └───────┬───────┘
                                                 │
                                                 ▼
                                         ┌───────────────┐
                                         │ S12 CIERRE    │  Código de
                                         │  con código   │  seguimiento
                                         └───────────────┘
```

**Estados auxiliares** (no aparecen en el flujo principal):

- **Inactividad — aviso**: 4 minutos sin respuesta del ciudadano →
  mensaje recordatorio.
- **Inactividad — cierre**: 5 minutos sin respuesta → cierre automático
  sin guardar.
- **Cancelación voluntaria**: el ciudadano escribe "cancelar" en
  cualquier momento → cierre sin guardar.

---

## 2. Mensajes que envía el bot — texto exacto

### S1 — Bienvenida (mensaje obligatorio con consentimiento)

> **Bienvenido al sistema institucional de denuncias de corrupción**
>
> Este canal pertenece a la Secretaría General de Integridad Pública del
> Ecuador. A través de este chat usted podrá registrar de forma
> **confidencial** una denuncia ciudadana sobre presuntos hechos de
> corrupción en el sector público.
>
> **Antes de continuar, por favor lea con atención:**
>
> - Su número de teléfono **no** se almacena en claro.
> - Su denuncia es confidencial y se cifra antes de almacenarse.
> - Al finalizar recibirá un **código de seguimiento** único.
> - Puede escribir la palabra **cancelar** en cualquier momento para
>   terminar el proceso sin guardar la información.
> - Si no responde durante 5 minutos la sesión se cerrará automáticamente.
>
> Le solicitaremos los siguientes datos: institución denunciada,
> descripción de los hechos, fecha aproximada, personas involucradas
> (opcional), perjuicio económico (opcional), denuncia previa en otra
> entidad (opcional) y evidencias en formato PDF, JPG o PNG (opcional).

**Decisión pendiente — Legal:**
- ¿El consentimiento informado actual es suficiente?
- ¿Se requiere agregar referencia explícita a la **Ley Orgánica de
  Protección de Datos Personales** del Ecuador?
- ¿Se debe advertir sobre la responsabilidad penal de la denuncia
  falsa (Art. 268 COIP)?

### S2 — Solicitar aceptación

> ¿Acepta continuar con el registro de la denuncia bajo las condiciones
> indicadas?
>
> [Botón: **Sí, acepto**]   [Botón: **No, cancelar**]

### S2 — Reintento si la respuesta no se interpreta

> No pude interpretar su respuesta. Por favor responda con uno de los
> botones, o escriba **Sí** o **No**. (N intento(s) restante(s)).

Tras 3 intentos fallidos, la sesión se cierra automáticamente sin guardar.

### S3 — Institución denunciada

> **Paso 1 de 8.** Indique el nombre de la **institución, dependencia o
> entidad pública** sobre la cual presenta la denuncia.
>
> Ejemplos: "Ministerio de Salud Pública", "GAD Municipal de Quito",
> "Hospital del Seguro Social en Guayaquil".

Validación: mínimo 3 caracteres, máximo 200.

### S4 — Descripción de los hechos

> **Paso 2 de 8.** Describa de manera detallada los **hechos** que desea
> denunciar. Incluya, si los conoce: lugar, modalidad del presunto acto,
> montos involucrados, fechas relevantes y todo dato que considere útil
> para la investigación.
>
> Mínimo 30 caracteres, máximo 2000.

### S5 — Fecha aproximada

> **Paso 3 de 8.** Indique la **fecha aproximada** en que ocurrieron los
> hechos.
>
> Formatos válidos:
> - Día/mes/año (ej. 15/03/2025)
> - Mes/año (ej. 03/2025)
> - Solo año (ej. 2025)
> - La frase **no recuerdo**

### S6 — Personas involucradas (opcional)

> **Paso 4 de 8.** Si conoce a las **personas presuntamente involucradas**
> indique nombres, cargos o cualquier referencia que pueda ayudar.
>
> Si no las conoce, escriba **no conozco** o **prefiero no decir**.

### S7 — Perjuicio económico (opcional)

> **Paso 5 de 8.** Si conoce el **monto aproximado del perjuicio
> económico**, indíquelo (en dólares).
>
> Puede escribir un número, un rango ("entre 5000 y 10000") o
> **no aplica** / **no sé**.

### S8 — Denuncia previa en otra entidad

> **Paso 6 de 8.** ¿Ha presentado **anteriormente** esta misma denuncia
> ante otra entidad (Fiscalía, Contraloría, otra)?
>
> [Botón: **Sí**]   [Botón: **No**]

Si responde **Sí**:

> Indique brevemente **ante qué entidad** presentó la denuncia previa y,
> si lo recuerda, **cuándo** lo hizo.

### S9 — Evidencias

> **Paso 7 de 8.** Si dispone de **evidencias**, envíelas ahora.
>
> - Formatos aceptados: PDF, JPG, PNG
> - Tamaño máximo por archivo: 10 MB
> - Cantidad máxima: 5 archivos
>
> Envíe los archivos uno por uno. Cuando termine, pulse el botón
> **No tengo más** o escriba **no tengo**.

Por cada archivo aceptado:

> Archivo N de 5 máximo recibido correctamente. Puede enviar otro o
> escribir **no tengo** para continuar.

Si el archivo se rechaza por tipo:

> El archivo no fue aceptado: tipo X no permitido.
>
> Tipos permitidos: application/pdf, image/jpeg, image/png.
>
> Envíe otro archivo o escriba **no tengo** para continuar.

Si el archivo se rechaza por tamaño:

> El archivo no fue aceptado: pesa N MB y el máximo es 10 MB. Envíe otro
> archivo o escriba **no tengo** para continuar.

Si el archivo se rechaza por antivirus:

> El archivo no fue aceptado por motivos de seguridad. Envíe otro
> archivo o escriba **no tengo** para continuar.

### S10 — Resumen y validación

> **Paso 8 de 8 — Resumen de su denuncia**
>
> *Institución:* {valor}
> *Descripción:* {valor truncado a 300 caracteres}
> *Fecha aproximada:* {valor}
> *Personas involucradas:* {valor si se proporcionó}
> *Perjuicio económico:* {valor si se proporcionó}
> *Denuncia previa:* {valor si se proporcionó}
> *Evidencias adjuntas:* {número}
>
> Si confirma, registraremos su denuncia y le entregaremos un código de
> seguimiento. Si desea modificar algún dato, pulse **Editar**.
>
> [Botón: **Confirmar**]   [Botón: **Editar**]   [Botón: **Cancelar**]

### S12 — Cierre exitoso

> **Su denuncia ha sido registrada exitosamente.**
>
> *Código de seguimiento:* `ALR-2026-K7M2QH`
>
> Conserve este código: le permitirá consultar el estado de su denuncia
> con la entidad. La información ha sido cifrada y enviada a la unidad
> correspondiente para su revisión.
>
> Gracias por colaborar con la integridad pública del Ecuador.

### Cancelación voluntaria

> Hemos cancelado el proceso a su solicitud. Ninguna información fue
> guardada.
>
> Puede volver a escribirnos cuando lo desee.

### Inactividad — aviso a los 4 minutos

> Notamos que ha pasado tiempo sin recibir respuesta. Si no contesta en
> aproximadamente 1 minuto la sesión se cerrará automáticamente y no se
> guardará la información.

### Inactividad — cierre a los 5 minutos

> La sesión ha sido cerrada por inactividad. Ninguna información fue
> guardada. Puede volver a escribirnos cuando lo desee.

### Error técnico genérico

> Ocurrió un inconveniente técnico al procesar su mensaje. Por favor
> intente nuevamente en unos minutos. Si el problema persiste,
> comuníquese con la institución por los canales oficiales.

### Servicio temporalmente no disponible (Redis caído)

> Estamos teniendo una dificultad técnica momentánea. Por favor intente
> nuevamente en unos minutos.
>
> Si su denuncia es urgente, le sugerimos comunicarse adicionalmente con
> las autoridades competentes por los canales oficiales.

---

## 3. Aspectos sujetos a validación por la contraparte

### 3.1 Texto del consentimiento informado (S1)

- **Pendiente legal**: confirmar suficiencia ante LOPDP.
- **Pendiente comunicación**: tono, extensión, claridad para población
  con menor familiaridad con tecnología.

### 3.2 Advertencia sobre denuncia falsa

- ¿Se debe agregar una mención al artículo correspondiente del COIP?
- Ubicación sugerida: tras S2 (al aceptar), antes de S3.

### 3.3 Numeración de pasos

- Actualmente: "Paso N de 8". Si se modifica el flujo (agregar/quitar
  campos), esta numeración debe actualizarse.

### 3.4 Formato del código de seguimiento

- Formato propuesto: `ALR-YYYY-XXXXXX` donde XXXXXX son 6 caracteres
  alfanuméricos sin caracteres ambiguos (excluye 0/O/1/I/l).
- ¿La Secretaría tiene una nomenclatura propia de tickets que prefiera?

### 3.5 Categorización de la denuncia

- En la versión 1.0 no se solicita al ciudadano que clasifique su
  denuncia (corrupción administrativa, contratación pública, manejo de
  recursos, etc.).
- ¿La Secretaría requiere agregar esta categorización? Si es así,
  ¿con qué taxonomía?

### 3.6 Idioma

- Versión 1.0: solo español.
- ¿La Secretaría requiere atender en kichwa, shuar u otros idiomas
  indígenas? Implica multiplicar el contenido del documento por idioma.

### 3.7 Tono institucional

- El tono actual es formal, neutro, con uso de "usted". ¿Es coherente
  con la voz institucional de la Secretaría?

---

## 4. Próximos pasos sobre este documento

1. **Lectura por área de comunicación** → entrega de observaciones
   sobre tono, ortografía y claridad.
2. **Lectura por área legal** → entrega de observaciones sobre
   consentimiento informado, advertencias y referencias normativas.
3. **Acta de aprobación de textos** (puede formar parte del acta de la
   reunión).
4. **Actualización del código** del bot con los textos aprobados.
5. **Pruebas en sandbox de Meta** con los textos definitivos.
