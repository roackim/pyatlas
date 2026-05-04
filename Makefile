VENV_DIR ?= .venv
PYTHON ?= python3
VENV_PYTHON := $(VENV_DIR)/bin/python
PIP := $(VENV_PYTHON) -m pip
PYINSTALLER := $(VENV_DIR)/bin/pyinstaller

.PHONY: help venv install build-binary build run-venv clean distclean run

help:
	@echo "Targets:"
	@echo "  make venv         Create local virtual environment"
	@echo "  make install      Install atlas dependencies into .venv"
	@echo "  make build-binary Build standalone ./bin/atlas with PyInstaller"
	@echo "  make build        Run atlas.py with current INPUT/OUTPUT/MANIFEST"
	@echo "  make clean        Remove build artifacts"
	@echo "  make distclean    Remove build artifacts and .venv"

venv:
	$(PYTHON) -m venv $(VENV_DIR)

install: venv
	$(PIP) install --upgrade pip
	$(PIP) install -r deps.txt

build-binary: install
	$(PYINSTALLER) --noconfirm --clean --onefile --name atlas --distpath ./bin --workpath ./.pyinstaller atlas.py

build:
	$(VENV_PYTHON) atlas.py -i $(INPUT) -r $(OUTPUT) -m $(MANIFEST)

clean:
	rm -rf bin build .pyinstaller atlas.spec __pycache__ atlas/__pycache__

distclean: clean
	rm -rf $(VENV_DIR)
