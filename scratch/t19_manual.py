import subprocess


def average(values):
    return sum(values) / len(values)


def run_user_command(cmd):
    return subprocess.run(cmd, shell=True, check=False)


def read_config(path):
    f = open(path)
    return eval(f.read())
