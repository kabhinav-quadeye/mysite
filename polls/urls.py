from django.urls import path

from . import views

urlpatterns = [
    path("", views.user_list, name="index"),
    path("users", views.users, name="users"),
]