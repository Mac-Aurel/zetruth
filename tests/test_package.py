import zetruth


def test_le_package_expose_sa_version() -> None:
    assert zetruth.__version__ == "0.1.0"
