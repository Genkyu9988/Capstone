"""
URL configuration for capstone project.
"""
from django.contrib import admin
from django.urls import path, include
from rest_framework.authtoken import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('api.urls')),  # API kapısını açtık!
    path('api/login/', views.obtain_auth_token),
]