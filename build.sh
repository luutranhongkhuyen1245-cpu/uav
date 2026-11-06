#!/usr/bin/env bash
# Exit on error
set -o errexit

# Upgrade pip
pip install --upgrade pip

# Install PyTorch CPU first to save disk space and build time on Render Free
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu

# Install remaining dependencies
pip install -r requirements.txt

# Run migrations and collect static files
python fire_detection/manage.py collectstatic --no-input
python fire_detection/manage.py migrate

