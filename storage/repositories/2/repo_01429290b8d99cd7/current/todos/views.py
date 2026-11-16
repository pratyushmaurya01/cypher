from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import RegisterForm, TodoForm
from .models import Todo


def register(request):
    if request.user.is_authenticated:
        return redirect("todo_list")
    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect("todo_list")
    else:
        form = RegisterForm()
    return render(request, "registration/register.html", {"form": form})


@login_required
def todo_list(request):
    if request.method == "POST":
        form = TodoForm(request.POST)
        if form.is_valid():
            todo = form.save(commit=False)
            todo.user = request.user
            todo.save()
            return redirect("todo_list")
    else:
        form = TodoForm()
    todos = Todo.objects.filter(user=request.user)
    return render(request, "todos/todo_list.html", {"form": form, "todos": todos})


@login_required
@require_POST
def toggle_todo(request, pk):
    todo = get_object_or_404(Todo, pk=pk, user=request.user)
    todo.is_done = not todo.is_done
    todo.save()
    return redirect("todo_list")


@login_required
@require_POST
def delete_todo(request, pk):
    todo = get_object_or_404(Todo, pk=pk, user=request.user)
    todo.delete()
    return redirect("todo_list")
