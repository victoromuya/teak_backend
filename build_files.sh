#!/bin/bash

pip install -r requirements.txt
python3.9 manage.py collectstatic --no-input --clear
 
python manage.py migrate
