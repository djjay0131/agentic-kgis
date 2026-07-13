def test_packages_import() -> None:
    import kg_contracts
    import kg_eval
    import kgis

    assert kg_contracts.__name__ == "kg_contracts"
    assert kgis.__name__ == "kgis"
    assert kg_eval.__name__ == "kg_eval"
