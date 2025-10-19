import json
import logging
import sys

def load_config(config_file: str = 'config.json') -> dict:
    """
    Carga la configuración desde el archivo JSON especificado.

    :param config_file: Ruta al archivo de configuración.
    :return: Diccionario con la configuración.
    :raises FileNotFoundError: Si el archivo de configuración no se encuentra.
    :raises json.JSONDecodeError: Si el archivo JSON está malformado.
    """
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        logging.error(f"Error: Archivo de configuración '{config_file}' no encontrado.")
        sys.exit(1)
    except json.JSONDecodeError as e:
        logging.error(f"Error: Archivo de configuración JSON malformado. Detalle: {e}")
        sys.exit(1)