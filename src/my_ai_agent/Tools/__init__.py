from .file_tools import (
    edit_file,
    find_files,
    list_directory,
    read_file,
    search_text,
    write_file,
)
from .shell_tools import execute_shell
from .system_tools import (
    get_current_time,
    get_system_info,
    multiply,

)
TOOLS = [
    execute_shell,
    list_directory,
    find_files,
    search_text,
    read_file,
    write_file,
    edit_file,
    get_current_time,
    get_system_info,
    multiply,
]
