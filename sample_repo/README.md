# Sample User Management

A small Django project used as a realistic source tree for Python AST analysis.
It demonstrates Django authentication, model relationships, URL routing, and
the call chain `URL route -> view -> service -> repository`.

## Requirements

- Python 3.10 or newer
- pip

## Setup

From this directory (`sample_repo/`), create and activate a virtual environment,
then install the dependencies:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Apply migrations and create an administrator account:

```powershell
python manage.py migrate
python manage.py createsuperuser
```

Run the development server:

```powershell
python manage.py runserver
```

Open `http://127.0.0.1:8000/`. User-management pages require login. Sign in at
`http://127.0.0.1:8000/accounts/login/`. The project includes Django's built-in
authentication URL patterns.

## Tests

Run all tests from `sample_repo/`:

```powershell
python manage.py test
```

The test suite covers the profile model, user-management services, protected
and authenticated views, and URL resolution.

## Source layout

- `sample_project/`: project settings and root URL configuration.
- `users/models.py`: profile model linked one-to-one with Django's user model.
- `users/views.py`: login-protected user-management views.
- `users/services.py`: reusable user and profile business operations.
- `users/repository.py`: database query and persistence functions.
- `users/forms.py`: user creation and profile update forms.
- `users/tests/`: model, service, view, and URL tests.
