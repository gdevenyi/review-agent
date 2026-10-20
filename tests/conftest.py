import tempfile

import pytest

# Keep pytest temp dirs off the /tmp RAM disk.
tempfile.tempdir = "/var/tmp"


@pytest.fixture
def world(tmp_path):
    """Seam 1 world: fake GitHub, fake Engine, local origin. See harness.py."""
    from harness import make_world

    return make_world(tmp_path)
