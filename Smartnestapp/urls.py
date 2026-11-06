"""
URL configuration for Smartnest project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.urls import path
from . import views

urlpatterns = [
    path('login/', views.custom_login_view, name='login'),
    path('logout/', views.custom_logout_view, name='logout'),
    
    path('', views.dashboard_view, name='dashboard'),
    path('expenses/', views.expense_details_view, name='expense_details'),
    # Rent Details
    path('rooms/', views.room_details_view, name='room_details'),
    path('rent-details/', views.rent_details_view, name='rent_details'),
    path('api/bill/single/<int:room_id>/', views.get_single_bill, name='get_single_bill'),
    path('api/bill/combined/<int:tenant_id>/', views.get_combined_bill, name='get_combined_bill'),
    # Advance Details
    path('advance-details/', views.advance_details_view, name='advance_details'),
    path('advance-details/add/', views.edit_advance_view, name='add_advance'),
    path('advance-details/edit/<int:advance_id>/', views.edit_advance_view, name='edit_advance'),
    path('api/rent-detail/<int:pk>/set-nil/', views.set_eb_nil, name='set_eb_nil'),
    # Electricity Readings
    path('electricity/', views.electricity_view, name='electricity'),
    path('electricity/add/', views.edit_electricity_view, name='add_electricity'),
    path('electricity/edit/<int:reading_id>/', views.edit_electricity_view, name='edit_electricity'),
    path('previous-month-reading/', views.previous_month_reading_view, name='previous_month_reading'),
    path('current-month-reading/', views.current_month_reading_view, name='current_month_reading'),
    path('advance-details/delete/<int:advance_id>/', views.delete_advance_view, name='delete_advance'),
    # Tenants
    path('tenants/', views.tenant_details_view, name='tenant_details'),
    path('tenants/add/', views.edit_tenant_view, name='add_tenant'),
    path('tenants/edit/<int:tenant_id>/', views.edit_tenant_view, name='edit_tenant'),
    path('tenants/delete/<int:tenant_id>/', views.delete_tenant_view, name='delete_tenant'),
]