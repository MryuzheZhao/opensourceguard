import subprocess


API_TOKEN = "demo-token-should-be-rotated"


def run_user_command(command):
    return subprocess.run(command, shell=True, capture_output=True, text=True)

