try:
    from setuptools import setup
except ImportError:
    from distutils.core import setup

setup(name="sim900", version="0.1", py_modules=["sim900"])
