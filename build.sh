#!/usr/bin/env bash 
set -o errexit 
 
pip install -r requirements.txt 
python manage.py collectstatic --no-input 
python manage.py migrate

# Create or reset your superuser credentials automatically
python -c "
import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Smartnest.settings')
django.setup()
from django.contrib.auth.models import User

username = 'vijay'
password = 'Mvijay212021'

u, created = User.objects.get_or_create(username=username)
u.set_password(password)
u.is_superuser = True
u.is_staff = True
u.is_active = True
u.save()
print(f'*** SUCCESS: Admin account {username} updated successfully! ***')
"