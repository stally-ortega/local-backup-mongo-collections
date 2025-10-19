import datetime
import os

def get_folder_size(path: str) -> str:
    """
    Calcula el tamaño total de los archivos en un directorio y lo formatea.

    :param path: Ruta del directorio a medir.
    :return: Cadena con el tamaño formateado (ej. '150.5 MB').
    """
    total_size = 0.0
    if not os.path.exists(path):
        return "0.0 B"
        
    for dirpath, _, filenames in os.walk(path):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            if not os.path.islink(fp):
                total_size += os.path.getsize(fp)

    # Formatea el tamaño en B, KB, MB, GB, etc.
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if total_size < 1024.0:
            return f"{total_size:3.1f} {unit}"
        total_size /= 1024.0
    return f"{total_size:3.1f} PB"

def is_last_day_of_month(date: datetime.date) -> bool:
    """
    Verifica si la fecha dada es el último día del mes.

    :param date: Objeto datetime.date a verificar.
    :return: True si es el último día del mes, False en caso contrario.
    """
    # Suma un día a la fecha actual y verifica si el mes cambia.
    return (date + datetime.timedelta(days=1)).month != date.month