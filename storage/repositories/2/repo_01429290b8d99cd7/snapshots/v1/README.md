# Simple Django Todo App (with Auth)

Chhota sa todo project: register, login, logout aur apni personal todo list (add / done / delete).

## Run kaise kare

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

Phir browser me kholo: http://127.0.0.1:8000/

## Pages

- `/` : todo list (login zaroori)
- `/register/` : naya account
- `/accounts/login/` : login
- Logout: navbar me Logout button
- `/admin/` : admin panel (`python manage.py createsuperuser` se admin banao)
