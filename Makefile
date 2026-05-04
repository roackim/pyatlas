VENV_DIR ?= .venv
PYTHON ?= python3
VENV_PYTHON := $(VENV_DIR)/bin/python
PIP := $(VENV_PYTHON) -m pip
PYINSTALLER := $(VENV_DIR)/bin/pyinstaller

.PHONY: help venv install build clean distclean

help:
	@echo "Targets:"
	@echo "  make venv         Create local virtual environment"
	@echo "  make install      Install atlas dependencies into .venv"
	@echo "  make build 	   Build standalone ./bin/atlas with PyInstaller"
	@echo "  make clean        Remove build artifacts"
	@echo "  make distclean    Remove build artifacts and .venv"

venv:
	$(PYTHON) -m venv $(VENV_DIR)

install: venv
	$(PIP) install --upgrade pip
	$(PIP) install -r deps.txt

build: install
	$(PYINSTALLER) --noconfirm --clean --onefile --name atlas --distpath ./bin --workpath ./.pyinstaller atlas.py

clean:
	rm -rf bin build .pyinstaller atlas.spec __pycache__ atlas/__pycache__

distclean: clean
	rm -rf $(VENV_DIR)
