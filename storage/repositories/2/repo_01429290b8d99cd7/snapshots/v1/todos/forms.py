from django import forms
from django.contrib.auth.forms import UserCreationForm

from .models import Todo


class TodoForm(forms.ModelForm):
    class Meta:
        model = Todo
        fields = ["title"]
        widgets = {
            "title": forms.TextInput(
                attrs={"placeholder": "Nayi task likho...", "autofocus": True}
            )
        }


class RegisterForm(UserCreationForm):
    pass
