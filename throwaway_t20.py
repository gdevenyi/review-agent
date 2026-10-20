"""Throwaway file for the #20 Action test. Do not merge."""


def average(values):
    return sum(values) / len(values)


def read_config(path):
    f = open(path)
    return f.read()


def is_admin(user):
    if user["role"] == "admin" or "root":
        return True
    return False
