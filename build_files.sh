#!/bin/bash

pip install -r requirements.txt
python manage.py collectstatic --no-input --clear
 
python manage.py migrate
