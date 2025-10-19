# MongoDB Backup Script

![MongoDB Backup](https://img.shields.io/badge/MongoDB-Backup-green?style=for-the-badge&logo=mongodb)
![Python](https://img.shields.io/badge/Python-3.8%2B-blue?style=for-the-badge&logo=python)
![Telegram](https://img.shields.io/badge/Telegram-Bot-lightblue?style=for-the-badge&logo=telegram)

Este script en Python realiza **backups locales automáticos** de una base de datos MongoDB (incluso si está en Atlas). Soporta dos tipos de backups: **semanal** y **mensual**, con notificaciones automáticas vía Telegram para éxito o errores. Es ideal para automatizar con un programador de tareas, ya que valida internamente cuándo ejecutar cada tipo de backup.

## Descripción

El script exporta colecciones específicas de tu base de datos MongoDB a archivos locales en formato JSON. 

- **Backup Semanal**: Se ejecuta en el día configurado (por defecto, viernes) o forzado manualmente.
- **Backup Mensual**: Se ejecuta automáticamente al final del mes o forzado manualmente.
- **Notificaciones**: Envía alertas a un chat de Telegram sobre el estado del backup (éxito o error).
- **Automatización**: Diseñado para correr diariamente; el script decide internamente si procede con el backup basado en la fecha.

¡Simple, eficiente y con alertas en tiempo real!

## Requisitos

Para ejecutar el script, necesitas:

- **Python 3+**: Con la librería `python-telegram-bot`.
- **Herramientas de MongoDB**: Descarga las Database Tools desde [aquí](https://www.mongodb.com/try/download/database-tools). Asegúrate de que `mongodump` esté en tu PATH.
- **Telegram**:
  - Token de un bot creado con BotFather.
  - ID del chat donde recibirás las notificaciones (puede ser un grupo o canal).

## Instalación

1. Clona este repositorio:
   ```
   git clone https://github.com/tu-usuario/tu-repositorio.git
   cd tu-repositorio
   ```

2. Instala la librería requerida:
   ```
   pip install python-telegram-bot
   ```

3. Configura el archivo `config.json` (ver sección de Configuración abajo).

## Configuración

Crea o edita el archivo `config.json` en la raíz del proyecto con la siguiente estructura. Reemplaza los valores con los tuyos:

```json
{
    "MONGODB_URI": "mongodb://[usuario]:[contraseña]@[host]:[puerto]/[nombre_bd]",
    "DATABASE_NAME": "nombre_de_tu_bd",
    "COLLECTIONS_TO_BACKUP": [
        "coleccion_usuarios",
        "coleccion_productos",
        "otra_coleccion_importante"
    ],
    "LOCAL_BACKUP_PATH": "C:/Backups/MongoDB",
    "TELEGRAM_TOKEN": "TU_TOKEN_DE_BOTFATHER",
    "TELEGRAM_CHAT_ID": "-100123456789",
    "WEEKLY_BACKUP_DAY": "Friday"
}
```

- **`MONGODB_URI`**: URI de conexión a tu base de datos MongoDB.
- **`DATABASE_NAME`**: Nombre de la base de datos.
- **`COLLECTIONS_TO_BACKUP`**: Lista de colecciones a respaldar.
- **`LOCAL_BACKUP_PATH`**: Ruta local donde se guardarán los backups.
- **`TELEGRAM_TOKEN`**: Token de tu bot de Telegram.
- **`TELEGRAM_CHAT_ID`**: ID del chat (usa un bot como @userinfobot para obtenerlo).
- **`WEEKLY_BACKUP_DAY`**: Día de la semana para el backup semanal (en inglés: Monday, Tuesday, etc.).

## Uso

1. Ejecuta el script principal:
   ```
   python main.py
   ```

2. Verifica el funcionamiento: Deberás ver notificaciones en la consola y en el chat de Telegram sobre el estado del backup.

### Opciones Avanzadas

- **Forzar Backup Semanal**:
  ```
  python main.py --type weekly
  ```

- **Forzar Backup Mensual**:
  ```
  python main.py --type monthly
  ```

El script valida automáticamente:
- Si es el día configurado en `WEEKLY_BACKUP_DAY`, ejecuta el semanal.
- Si es fin de mes (calculado por Python), ejecuta el mensual.

## Automatización

Para backups diarios automáticos:
- Usa un programador de tareas como **Cron** (Linux/Mac) o **Task Scheduler** (Windows).
- Configura para ejecutar `python main.py` diariamente. El script manejará internamente si procede con el backup basado en la fecha.

Ejemplo en Cron (Linux/Mac):
```
0 2 * * * /ruta/a/python /ruta/al/main.py
```
(Ejecuta a las 2 AM todos los días).

## Notificaciones

- **Éxito**: Mensaje en Telegram y consola confirmando el backup completado.
- **Error**: Alerta detallada sobre cualquier problema (e.g., conexión fallida o error en mongodump).
- Las notificaciones se envían automáticamente usando el bot configurado.

## Contribuciones

¡Siéntete libre de forkear y mejorar! Abre issues o pull requests para sugerencias.

## Licencia

MIT License - Usa y modifica libremente.