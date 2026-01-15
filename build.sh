#!/usr/bin/env bash
set -o errexit

pip install -r requirements.txt
python manage.py collectstatic --no-input
python manage.py migrate

# 自動建立超級使用者 (如果已存在會略過或報錯，但因為有 || true 所以不會讓部署失敗)
python manage.py createsuperuser --noinput || true
