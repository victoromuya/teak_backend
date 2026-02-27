#!/bin/bash

# Load conda into current shell
source ~/opt/anaconda3/etc/profile.d/conda.sh

echo "Deactivating conda..."
conda deactivate

echo "Activating desktop venv..."
source ~/Desktop/tikbackend/tikenv/bin/activate