#!/bin/bash
# python -m unittest test_module1 test_module2
# python -m unittest test_module.TestClass
# python -m unittest test_module.TestClass.test_method
python3 -m unittest -k test_crypto test_fastapi.py

