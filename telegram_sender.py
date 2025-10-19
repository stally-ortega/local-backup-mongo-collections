import os
from typing import Optional
from telegram import Bot
from telegram.error import TelegramError
from telegram.helpers import escape_markdown
import logging

async def send_telegram_message(config: dict, message: str, file_path: Optional[str] = None) -> None:
    """
    Envía un mensaje al chat de Telegram configurado, con la opción de adjuntar un archivo.

    :param config: Diccionario de configuración con TELEGRAM_TOKEN y TELEGRAM_CHAT_ID.
    :param message: El mensaje de texto a enviar.
    :param file_path: Ruta opcional al archivo a adjuntar (por ejemplo, un archivo .txt de error).
    """
    token = config.get("TELEGRAM_TOKEN")
    chat_id = config.get("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        logging.warning("Advertencia: No se pudo enviar el mensaje. Token o Chat ID de Telegram no configurados.")
        return

    # Crea una instancia del Bot de Telegram
    bot = Bot(token=token)

    try:
        # Escapa el mensaje para evitar problemas con Markdown
        escaped_message = escape_markdown(message, version=2)
        
        # Envía el mensaje de texto con MarkdownV2
        _ = await bot.send_message(chat_id=chat_id, text=escaped_message, parse_mode='MarkdownV2')
        logging.info("Mensaje de Telegram enviado exitosamente.")

        # Si se proporciona un archivo, envíalo como documento
        if file_path and os.path.exists(file_path):
            with open(file_path, 'rb') as document:
                _ = await bot.send_document(chat_id=chat_id, document=document, filename=os.path.basename(file_path))
                logging.info(f"Archivo adjunto {os.path.basename(file_path)} enviado exitosamente.")
        elif file_path and not os.path.exists(file_path):
            logging.warning(f"No se pudo encontrar el archivo adjunto: {file_path}")

    except TelegramError as e:
        logging.error(f"Error al enviar el mensaje de Telegram: {e}")
        # Intenta enviar sin Markdown si falla
        try:
            _ = await bot.send_message(chat_id=chat_id, text=message)
            logging.info("Mensaje enviado exitosamente sin formato Markdown.")
        except TelegramError as e2:
            logging.error(f"Error al reintentar sin Markdown: {e2}")
    except Exception as e:
        logging.error(f"Error desconocido al intentar enviar el mensaje de Telegram: {e}")