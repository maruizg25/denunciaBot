# Documentación institucional — DenunciaBot

Este directorio contiene la documentación dirigida a la **contraparte
institucional** (Secretaría General de Integridad Pública) para el
levantamiento formal de requisitos y la validación del flujo del bot.

Los documentos están pensados para imprimirse o convertirse a PDF y
llevarse a la reunión presencial. El tono es formal, en español
ecuatoriano, y asume conocimiento institucional pero NO conocimiento
técnico profundo.

## Índice de documentos

| # | Archivo | Para quién | Cuándo usarlo |
|---|---------|------------|---------------|
| 01 | [resumen-ejecutivo](01-resumen-ejecutivo.md) | Autoridad de la Secretaría | Apertura de la reunión, lectura previa |
| 02 | [flujo-conversacional](02-flujo-conversacional.md) | Comunicación + Legal | Validación de cada mensaje del bot |
| 03 | [arquitectura-tecnica](03-arquitectura-tecnica.md) | Perfil técnico de la contraparte | Si la contraparte tiene un par técnico |
| 04 | [seguridad-y-privacidad](04-seguridad-y-privacidad.md) | Jurídico + Seguridad informática | Validación de cumplimiento LOPDP |
| 05 | [agenda-y-cuestionario](05-agenda-y-cuestionario.md) | El responsable técnico SERCOP | Para conducir la reunión |
| 06 | [acta-reunion-plantilla](06-acta-reunion-plantilla.md) | Ambas partes | Para llenar EN VIVO durante la reunión |

## Cómo usarlos

### Antes de la reunión (Mau)

1. Imprime los 6 documentos (idealmente a doble cara, anillado).
2. Lee de corrido el doc. 05 (agenda) — es tu guion.
3. Familiarízate con el doc. 02 (flujo) — vas a recorrerlo en voz alta.
4. Anota en el doc. 05 las respuestas tentativas que ya tengas (ej. si
   ya sabes a qué buzón llegarán las notificaciones).

### Durante la reunión

1. Entrega copias impresas de los docs. 01, 02 y 06 al menos.
2. Si hay perfil técnico, entrega también el doc. 03.
3. Si hay perfil legal/seguridad, entrega también el doc. 04.
4. Tú conducís siguiendo el doc. 05.
5. **Llenas el doc. 06 en vivo** con los acuerdos tomados.

### Después de la reunión

1. Pasa el doc. 06 a limpio (digital), escanéalo firmado.
2. Distribuye copias firmadas por correo a ambas partes.
3. Convierte las decisiones de la sección 2 del doc. 06 en cambios
   concretos del código del bot.
4. Comparte el cronograma acordado (doc. 06 sección 5) con tu equipo
   en SERCOP.

## Cómo convertir a PDF

Cualquiera de estas opciones funciona:

```bash
# Opción 1 — pandoc (si está instalado)
pandoc 01-resumen-ejecutivo.md -o 01-resumen-ejecutivo.pdf

# Opción 2 — visor de Markdown del navegador → Imprimir → Guardar como PDF
# (abre el .md en VSCode o IDE con preview, usa Cmd+P)

# Opción 3 — todos a la vez con un script:
for f in *.md; do
    pandoc "$f" -o "${f%.md}.pdf" --pdf-engine=xelatex
done
```

Para una presentación institucional más formal, considera usar un
template de pandoc con membrete o convertir vía Microsoft Word con la
plantilla institucional del SERCOP.

## Mantenimiento de estos documentos

Estos documentos son la **versión 1.0**, previa a la reunión. Después
de la reunión:

- Si los textos cambian (doc. 02), actualizar tanto este documento como
  el código del bot.
- Si la arquitectura cambia (doc. 03), actualizar también `RUNBOOK.md`.
- Si los procedimientos cambian, actualizar la sección correspondiente
  del doc. 04.

Versionar las modificaciones en commits separados con prefijo `docs:`
para que sea fácil rastrear el historial documental.
