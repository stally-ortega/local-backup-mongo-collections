import datetime
import logging
import os
import subprocess
import shutil

from telegram_sender import send_telegram_message
from utils import get_folder_size

async def execute_mongodump(config: dict, backup_type: str) -> None:
    """
    Ejecuta el proceso de 'mongodump' para las colecciones definidas y gestiona
    las notificaciones de inicio, éxito y error.

    :param config: Diccionario de configuración.
    :param backup_type: 'monthly' o 'weekly' para nombrar la carpeta.
    """
    db_name = config["DATABASE_NAME"]
    uri = config["MONGODB_URI"]
    collections = config["COLLECTIONS_TO_BACKUP"]
    base_path = config["LOCAL_BACKUP_PATH"]
    
    # Generar el nombre de la carpeta de backup
    now = datetime.datetime.now()
    if backup_type == 'monthly':
        folder_name = f"backup_mensual_{now.strftime('%Y-%m')}"
    else:  # weekly
        folder_name = f"backup_semanal_{now.strftime('%Y-%m-%d')}"
        
    output_path = os.path.join(base_path, folder_name)
    
    # Crear la carpeta de salida si no existe
    os.makedirs(output_path, exist_ok=True)

    # 1. Notificación de Inicio
    start_message = (
        f"🚨 **INICIO DE BACKUP {backup_type.upper()}**\n"
        f"Base de Datos: `{db_name}`\n"
        f"Ruta de destino: `{output_path}`\n"
        f"Colecciones a respaldar: `{len(collections)}`\n"
        f"Colecciones a respaldar:\n"
        + "\n".join([f"      - `{c}`" for c in collections]) + "\n"
    )
    await send_telegram_message(config, start_message)
    
    logging.info(f"Iniciando backup tipo '{backup_type}' en: {output_path}")

    start_time = datetime.datetime.now()
    success_count = 0
    error_details = []
    
    # 2. Bucle para cada colección
    collection_sizes = {}
    for collection in collections:
        # Construir el comando mongodump
        command = [
            'mongodump',
            '--uri', uri,
            '--db', db_name,
            '--collection', collection,
            '--out', output_path,
            '--gzip'
        ]

        logging.info(f"Respaldando colección: {collection}...")
        
        try:
            # Ejecutar el comando mongodump
            result = subprocess.run(
                command, 
                capture_output=True, 
                text=True, 
                check=True
            )
            success_count += 1
            logging.info(f"Colección {collection} respaldada exitosamente.")
            bson_file = os.path.join(output_path, db_name, f"{collection}.bson.gz")
            if os.path.exists(bson_file):
                collection_sizes[collection] = os.path.getsize(bson_file) / (1024 * 1024)  # En MB

        except subprocess.CalledProcessError as e:
            # Captura errores del subproceso (mongodump falla)
            error_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            command_str = " ".join(command)
            free_space = shutil.disk_usage(output_path).free / (1024 * 1024 * 1024)  # En GB
            
            # Guardar stderr en un archivo de texto
            error_file = os.path.join(output_path, f"error_{collection}_{now.strftime('%Y%m%d_%H%M%S')}.txt")
            with open(error_file, 'w', encoding='utf-8') as f:
                f.write(e.stderr)
            
            error_msg = (
                f"❌ **ERROR EN BACKUP** ❌\n"
                f"Fecha/Hora: {error_time}\n"
                f"Colección afectada: `{collection}`\n"
                f"Comando ejecutado: `{command_str}`\n"
                f"Código de retorno: {e.returncode}\n"
                f"Salida de error guardada en: [archivo adjunto](#{os.path.basename(error_file)})\n"
                f"Espacio disponible: {free_space:.2f} GB\n"
                f"Posible causa: "
            )
            if e.returncode == 1:
                error_msg += "Fallo de conexión o autenticación."
            elif e.returncode == 100:
                error_msg += "Comando no reconocido o PATH incorrecto."
            else:
                error_msg += "Error desconocido, revisar salida de error."
            error_details.append(error_msg)
            await send_telegram_message(config, error_msg, error_file)  # Enviar mensaje con archivo adjunto
            
            logging.error(f"Error al respaldar {collection}: {e.stderr}")
            
        except FileNotFoundError:
            # Captura si 'mongodump' no está en el PATH
            error_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            error_msg = (
                f"❌ **ERROR FATAL EN BACKUP** ❌\n"
                f"Fecha/Hora: {error_time}\n"
                f"Problema: El comando `mongodump` no se encontró.\n"
                f"Asegúrate de que 'MongoDB Database Tools' estén instalados y en tu variable de entorno PATH.\n"
                f"Espacio disponible: {shutil.disk_usage(output_path).free / (1024 * 1024 * 1024):.2f} GB"
            )
            error_details.append(error_msg)
            await send_telegram_message(config, error_msg)  # No hay archivo adjunto en este caso
            logging.critical(error_msg)
            break
        
    # 3. Notificación Final
    end_time = datetime.datetime.now()
    duration = end_time - start_time
    final_message = ""
    if error_details:
        final_message += "🔴 **BACKUP FALLIDO (con errores)** 🔴\n"
        final_message += f"Colecciones exitosas: {success_count}/{len(collections)}\n"
        final_message += f"Ruta: `{output_path}`\n\n"
        final_message += "\n-- DETALLES DE ERRORES --\n\n"
        final_message += "\n\n".join(error_details)
        await send_telegram_message(config, final_message)
    else:
        total_size = get_folder_size(output_path)
        total, used, free = shutil.disk_usage(base_path)
        initial_free_space = free / (1024 * 1024 * 1024)  # En GB (antes del backup, aproximado)
        final_free_space = shutil.disk_usage(base_path).free / (1024 * 1024 * 1024)  # En GB
        version_process = subprocess.run(['mongodump', '--version'], capture_output=True, text=True)
        mongodump_version = version_process.stdout.splitlines()[0] if version_process.returncode == 0 else "No disponible"

        final_message += "✅ **BACKUP EXITOSO** ✅\n"
        final_message += f"Tipo: **{backup_type.upper()}**\n"
        final_message += f"Total de Colecciones: {success_count}\n"
        final_message += f"Peso total de la copia: **{total_size}**\n"
        final_message += f"Inicio: {start_time.strftime('%Y-%m-%d %H:%M:%S')} | Fin: {end_time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        final_message += f"Duración: {duration}\n"
        final_message += f"Versión de mongodump: {mongodump_version}\n"
        final_message += f"Espacio disponible: {initial_free_space:.2f} GB (antes) | {final_free_space:.2f} GB (después)\n"
        final_message += "Tamaños por colección:\n"
        final_message += "\n".join([f"      - {k}: {v:.2f} MB" for k, v in collection_sizes.items()]) + "\n"
        final_message += f"Ruta local: `{output_path}`"
        await send_telegram_message(config, final_message)
        
    logging.info(f"Proceso de backup finalizado. Errores detectados: {len(error_details) > 0}")