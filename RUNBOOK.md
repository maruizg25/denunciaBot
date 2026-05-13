# RUNBOOK — DenunciaBot

Guía operativa para el equipo que mantiene DenunciaBot en producción.
Cubre los escenarios más probables que requieren intervención manual.

---

## Índice

1. [Verificación rápida de salud](#1-verificación-rápida-de-salud)
2. [PostgreSQL inalcanzable](#2-postgresql-inalcanzable)
3. [Redis inalcanzable](#3-redis-inalcanzable)
4. [SMTP caído / notificaciones encoladas sin entregar](#4-smtp-caído--notificaciones-encoladas-sin-entregar)
5. [Meta API rechazando mensajes](#5-meta-api-rechazando-mensajes)
6. [Logs y debugging](#6-logs-y-debugging)
7. [Rotación de la master key Fernet](#7-rotación-de-la-master-key-fernet)
8. [Backup y restauración de PostgreSQL](#8-backup-y-restauración-de-postgresql)
9. [Reinicio limpio del servicio](#9-reinicio-limpio-del-servicio)
10. [Limpieza de archivos temporales huérfanos](#10-limpieza-de-archivos-temporales-huérfanos)

---

## 1. Verificación rápida de salud

```bash
# Servicio API responde
curl http://127.0.0.1:8000/health

# BD responde
curl http://127.0.0.1:8000/admin/health/db

# Conteos básicos
curl http://127.0.0.1:8000/admin/stats

# Estado de systemd
sudo systemctl status denunciabot
sudo systemctl status denunciabot-worker

# Cola de Dramatiq pendiente
redis-cli LLEN "dramatiq:notificaciones"
```

Si los 5 pasos pasan, el sistema está sano.

---

## 2. PostgreSQL inalcanzable

**Síntomas**
- `/admin/health/db` devuelve 500.
- Logs muestran `OperationalError` o `ConnectionRefusedError`.
- Los webhooks de Meta acumulan logs `excepcion_no_capturada`.

**Diagnóstico**

```bash
sudo systemctl status postgresql
sudo journalctl -u postgresql -n 100
psql -U denunciabot -h localhost -d denunciabot -c "SELECT 1"
```

**Acciones**

1. **Si PostgreSQL está caído**: `sudo systemctl restart postgresql`.
2. **Si está corriendo pero no acepta conexiones**: revisar `pg_hba.conf` y `postgresql.conf` (`listen_addresses`).
3. **Si llegamos al límite de conexiones**: aumentar `max_connections` en `postgresql.conf` (default 100 — para nuestro volumen, 50 suele ser suficiente).
4. **Si la BD está corrupta**: restaurar desde el backup más reciente (ver §8).

**Comportamiento del bot durante la caída**: cada webhook que llega se procesa hasta `obtener_sesion` (Redis sigue funcionando), luego el orquestador intenta commit y falla. La sesión Redis NO cambia (rollback). El ciudadano no recibe respuesta y Meta reintenta — los mensajes NO se pierden, pero la UX se degrada.

---

## 3. Redis inalcanzable

**Síntomas**
- Los ciudadanos reciben el mensaje "Estamos teniendo una dificultad técnica momentánea" (de `servicio_no_disponible`).
- Logs muestran `webhook_redis_caido` o `sesion_redis_caido_al_leer`.

**Diagnóstico**

```bash
sudo systemctl status redis
redis-cli ping             # debe responder PONG
sudo journalctl -u redis -n 50
```

**Acciones**

1. **Reiniciar Redis**: `sudo systemctl restart redis`.
2. **Verificar memoria**: `redis-cli INFO memory | grep used_memory_human`. Si Redis se quedó sin memoria, ajustar `maxmemory` en `/etc/redis/redis.conf`.
3. **Verificar appendonly**: para que las sesiones sobrevivan a un reinicio del propio Redis, `appendonly yes` debe estar en la config (en nuestro `docker-compose.yml` ya lo está; en RHEL revisar `/etc/redis/redis.conf`).

**Comportamiento del bot durante la caída**: el webhook detecta el error, envía mensaje degradado al ciudadano y aborta sin tocar BD. Las sesiones en curso se pierden (los ciudadanos tienen que volver a empezar). La denuncias YA REGISTRADAS no se afectan.

---

## 4. SMTP caído / notificaciones encoladas sin entregar

**Síntomas**
- Las denuncias se registran (aparecen en `/admin/stats`) pero el equipo institucional no recibe correos.
- Logs del worker muestran `smtp_envio_falla`.

**Diagnóstico**

```bash
# Estado del worker
sudo systemctl status denunciabot-worker
sudo journalctl -u denunciabot-worker -n 100

# Cola de pendientes
redis-cli LLEN "dramatiq:notificaciones"
redis-cli LLEN "dramatiq:notificaciones.DQ"   # dead letter queue

# Probar SMTP manualmente
python -c "
import smtplib
with smtplib.SMTP('smtp.sercop.gob.ec', 587, timeout=10) as s:
    s.starttls()
    print(s.noop())
"
```

**Acciones**

1. **Si el worker está caído**: `sudo systemctl restart denunciabot-worker`.
2. **Si SMTP rechaza**: verificar credenciales en `.env` (`SMTP_USERNAME`, `SMTP_PASSWORD`), políticas SPF/DKIM del dominio.
3. **Reprocesar mensajes en la DLQ** (cuando SMTP esté operativo):

   ```bash
   # Dramatiq guarda los mensajes muertos en una cola separada (.DQ)
   redis-cli LRANGE "dramatiq:notificaciones.DQ" 0 -1
   # Para re-encolarlos:
   redis-cli RPOPLPUSH "dramatiq:notificaciones.DQ" "dramatiq:notificaciones"
   # Repetir hasta vaciar la DQ
   ```

4. **Si el SMTP estará caído mucho tiempo**: contemplar exportar las alertas a CSV y enviarlas manualmente (`make export FILE=urgentes.csv`).

---

## 5. Meta API rechazando mensajes

**Síntomas**
- Los logs muestran `meta_request_4xx` recurrente, especialmente con status 401 o 403.
- Los ciudadanos envían mensajes pero no reciben respuesta.

**Diagnóstico**

```bash
# Buscar errores recientes
sudo journalctl -u denunciabot -n 500 | grep meta_request

# Probar el token a mano
curl -X POST "https://graph.facebook.com/v18.0/$META_PHONE_NUMBER_ID/messages" \
  -H "Authorization: Bearer $META_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"messaging_product":"whatsapp","to":"NUMERO_DE_PRUEBA","type":"text","text":{"body":"prueba"}}'
```

**Acciones**

1. **401 sostenido**: el `META_ACCESS_TOKEN` expiró o fue revocado. Generar uno nuevo en developers.facebook.com → tu app → Configurations → System User → generate token.
2. **403**: el número de WhatsApp Business puede haber sido suspendido. Revisar https://business.facebook.com.
3. **429 sostenido**: rate limit. Revisar volumen anormal de mensajes — posible spam o ataque. Ver §6.

Tras actualizar el `.env`:

```bash
sudo systemctl restart denunciabot
```

---

## 6. Logs y debugging

Los logs van a `journald` (configurado en los units systemd) en formato JSON estructurado.

**Comandos típicos**

```bash
# Stream en vivo
sudo journalctl -u denunciabot -f

# Últimos 200 mensajes
sudo journalctl -u denunciabot -n 200

# Filtrar por nivel
sudo journalctl -u denunciabot -p err

# Filtrar por evento específico (los nuestros son JSON con clave "event")
sudo journalctl -u denunciabot -o json | jq 'select(.MESSAGE | contains("alerta_registrada"))'

# Últimas 24 horas
sudo journalctl -u denunciabot --since "24 hours ago"
```

**Eventos útiles para buscar**

| Evento | Significado |
|--------|-------------|
| `webhook_firma_invalida` | Posible intento de spoofing — investigar |
| `webhook_redis_caido` | Redis dejó de responder |
| `alerta_registrada` | Nueva denuncia registrada exitosamente |
| `smtp_envio_falla` | Notificación SMTP fallida |
| `meta_request_4xx` | Meta rechazó un request — revisar token |
| `evidencia_antivirus_rechazada` | ClamAV detectó archivo sospechoso |
| `webhook_duplicado_ignorado` | Idempotency funcionó (no es un error) |

---

## 7. Rotación de la master key Fernet

**Cuándo hacerlo**
- Sospecha de compromiso del `.env`.
- Política institucional (típico: anual).
- Salida de un administrador con acceso al servidor.

**Procedimiento**

⚠️ **CRÍTICO**: si rotas la clave sin re-cifrar los datos existentes, las denuncias antiguas se vuelven ilegibles para siempre. La rotación SIEMPRE requiere migración de datos.

```bash
# 1. Generar nueva clave
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# 2. Hacer backup ANTES de tocar nada
pg_dump -U denunciabot -F c -f /backups/pre-rotacion-$(date +%Y%m%d).dump denunciabot

# 3. Detener el servicio
sudo systemctl stop denunciabot denunciabot-worker

# 4. Script de re-cifrado (crear y ejecutar):
#    Lee con la clave VIEJA, re-cifra con la NUEVA, actualiza filas.
#    NO está incluido en el repo — escribir ad-hoc cuando se necesite.

# 5. Actualizar .env con la nueva clave
sudo nano /opt/denunciabot/.env  # cambiar DENUNCIABOT_MASTER_KEY

# 6. Reiniciar
sudo systemctl start denunciabot denunciabot-worker

# 7. Verificar que el descifrado funciona
python scripts/export_alertas.py --salida /tmp/post-rotacion.csv
# Inspeccionar el CSV — los textos deben verse legibles
```

**Pepper del teléfono**: NO se debe rotar nunca, ya que invalidaría todos los hashes existentes y se pierde la correlación entre sesiones y denuncias previas. Si está comprometido, considerarlo "quemado" y planear migración total.

---

## 8. Backup y restauración de PostgreSQL

**Backup automático recomendado (cron)**

```cron
# /etc/cron.d/denunciabot-backup
0 2 * * *  postgres  pg_dump -F c -f /var/backups/denunciabot/$(date +\%Y\%m\%d).dump denunciabot
0 3 * * *  postgres  find /var/backups/denunciabot -name '*.dump' -mtime +30 -delete
```

**Restauración**

```bash
# Stopear el servicio
sudo systemctl stop denunciabot denunciabot-worker

# Dropear la BD actual (¡PELIGROSO!)
sudo -u postgres dropdb denunciabot

# Recrear y restaurar
sudo -u postgres createdb denunciabot
sudo -u postgres pg_restore -d denunciabot /var/backups/denunciabot/YYYYMMDD.dump

# Verificar
python scripts/init_db.py   # no debería aplicar migraciones (ya están)

# Reiniciar
sudo systemctl start denunciabot denunciabot-worker
```

---

## 9. Reinicio limpio del servicio

```bash
# Reinicio ordenado: API primero, worker después (o al revés)
sudo systemctl restart denunciabot
sudo systemctl restart denunciabot-worker

# Verificar arranque
sudo systemctl status denunciabot
curl http://127.0.0.1:8000/health
```

Si el servicio no arranca:

1. Revisar logs: `sudo journalctl -u denunciabot -n 100`.
2. Causa más común: `.env` con valor inválido. Pydantic falla al arranque con un mensaje claro indicando qué variable.
3. Segunda causa más común: BD no migrada. Correr `python scripts/init_db.py`.

---

## 10. Limpieza de archivos temporales huérfanos

Los archivos descargados de Meta se guardan en `<EVIDENCIAS_DIR>/tmp/` mientras espera la confirmación del ciudadano. Si el bot crashea o el ciudadano cancela, esos archivos pueden quedar huérfanos.

**Cron de limpieza**

```cron
# /etc/cron.d/denunciabot-cleanup
*/30 * * * *  denunciabot  find /var/lib/denunciabot/evidencias/tmp -type f -mmin +30 -delete
```

Borra cualquier archivo en `tmp/` con más de 30 minutos de antigüedad. Como las sesiones expiran a los 5 min, 30 min es un margen seguro.

**Limpieza manual**

```bash
find /var/lib/denunciabot/evidencias/tmp -type f -mmin +60 -delete
# Verifica con: find /var/lib/denunciabot/evidencias/tmp -type f -mmin +60 | wc -l
```

---

## Escalación

Si nada de lo anterior resuelve el problema:

1. Recolectar:
   - `sudo journalctl -u denunciabot -u denunciabot-worker --since "1 hour ago" > /tmp/diag.log`
   - `curl http://127.0.0.1:8000/admin/stats > /tmp/stats.json`
   - `git log --oneline -10` (para saber qué versión está corriendo)
2. Contactar al desarrollador responsable con esos artefactos.
3. Si la denuncia es crítica y el bot está caído, recordar al ciudadano (via comunicación institucional) los canales alternativos: Fiscalía, Contraloría, página web de la Secretaría.
