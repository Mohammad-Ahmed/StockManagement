#!/usr/bin/env bash
set -o errexit

pip install -r requirements.txt
python initialize_database.py
