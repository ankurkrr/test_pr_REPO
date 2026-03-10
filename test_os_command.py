# test_os_command.py

import os


def delete_file(filename):

    # Dangerous command execution
    os.system("rm -rf " + filename)