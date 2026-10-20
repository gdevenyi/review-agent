import tempfile

# Keep pytest temp dirs off the /tmp RAM disk.
tempfile.tempdir = "/var/tmp"
