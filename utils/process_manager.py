# Storage global untuk mengontrol pembatalan/stop proses per chat_id
active_processes: dict[int, bool] = {}


def start_process(chat_id: int):
    active_processes[chat_id] = True


def stop_process(chat_id: int):
    active_processes[chat_id] = False


def is_process_active(chat_id: int) -> bool:
    return active_processes.get(chat_id, False)


def clear_process(chat_id: int):
    active_processes.pop(chat_id, None)