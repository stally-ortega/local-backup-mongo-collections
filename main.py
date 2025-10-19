import argparse
import asyncio
import datetime
import logging
import sys

from config_loader import load_config
from backup_executor import execute_mongodump
from utils import is_last_day_of_month
from telegram_sender import send_telegram_message

# Configuración del logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

async def main():
    """
    Función principal que determina y ejecuta el backup según la lógica de fecha.
    """
    parser = argparse.ArgumentParser(
        description="Gestor de Backups de MongoDB (mensual y semanal) con notificaciones por Telegram."
    )
    
    # Argumento opcional para forzar un tipo de backup desde el cron/scheduler
    parser.add_argument(
        '--type', 
        type=str, 
        choices=['monthly', 'weekly'],
        help="Tipo de backup a ejecutar: 'monthly' o 'weekly' (opcional, se determina automáticamente si no se especifica)."
    )
    args = parser.parse_args()
    
    config = load_config()
    current_date = datetime.date.today()
    current_day_name = current_date.strftime('%A')
    
    # Lógica de validación automática
    should_run_monthly = False
    should_run_weekly = False
    
    # Validación para backup mensual
    if is_last_day_of_month(current_date) or (args and args.type == 'monthly'):
        logging.info("Validación: Es el último día del mes o forzado como mensual. Ejecutando backup mensual.")
        should_run_monthly = True
    else:
        logging.info("Validación: No es el último día del mes ni forzado como mensual. Omitiendo backup mensual.")
    
    # Validación para backup semanal
    configured_day = config.get("WEEKLY_BACKUP_DAY")
    if current_day_name == configured_day or (args and args.type == 'weekly'):
        logging.info(f"Validación: Es el día configurado ({configured_day}) o forzado como semanal. Ejecutando backup semanal.")
        should_run_weekly = True
    else:
        logging.info(f"Validación: No es el día configurado ({configured_day}) ni forzado como semanal. Omitiendo backup semanal.")
    
    # Ejecución Real
    if not (should_run_monthly or should_run_weekly):
        logging.info("No se cumplen condiciones para ejecutar ningún backup. Saliendo.")
        sys.exit(0)
    
    try:
        if should_run_monthly:
            await execute_mongodump(config, 'monthly')
        if should_run_weekly:
            await execute_mongodump(config, 'weekly')
    except Exception as e:
        # Captura cualquier error inesperado del script Python en sí
        critical_error = (
            "🔥🔥 **ERROR CRÍTICO DEL SCRIPT PYTHON** 🔥🔥\n"
            f"El proceso falló por un error inesperado. Tipo: `{type(e).__name__}`\n"
            f"Detalle: ```{str(e)}```"
        )
        await send_telegram_message(config, critical_error)
        logging.critical(f"Error crítico en la ejecución principal: {e}")
        sys.exit(1)

if __name__ == '__main__':
    asyncio.run(main())