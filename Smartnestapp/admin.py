from django.contrib import admin
from .models import Building, Room, Tenant, AdvanceDetail, ElectricityReading, RentDetail

@admin.register(Building)
class BuildingAdmin(admin.ModelAdmin):
    list_display = ('name', 'total_rooms_count')

@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ('room_number', 'building', 'monthly_rent', 'maintenance_charges', 'target_advance_amount', 'is_vacant')
    list_filter = ('building', 'is_vacant')
    search_fields = ('room_number', 'building__name')

@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ('primary_name', 'phone_number', 'room', 'total_members_count', 'is_active', 'lease_start_date')
    list_filter = ('is_active', 'room__building')
    search_fields = ('primary_name', 'phone_number')

@admin.register(AdvanceDetail)
class AdvanceDetailAdmin(admin.ModelAdmin):
    list_display = (
        'room',
        'tenant',
        'agreement_advance',
        'cash_amount',
        'upi_amount',
        'amount_paid',
        'pending_advance',
        'payment_method',
        'paid_date',
    )
    list_filter = (
        'payment_method',
        'paid_date',
    )
    search_fields = (
        'room__room_number',
        'tenant__primary_name',
        'tenant__name',
    )

@admin.register(ElectricityReading)
class ElectricityReadingAdmin(admin.ModelAdmin):
    list_display = ('room', 'month_year', 'previous_reading', 'current_reading', 'units_consumed', 'rate_per_unit', 'total_electricity_amount')
    list_filter = ('month_year', 'room__building')

@admin.register(RentDetail)
class RentDetailAdmin(admin.ModelAdmin):
    list_display = ('room', 'tenant', 'month', 'rent_amount', 'maintenance_charge', 'electricity_charge', 'total_amount', 'paid_amount', 'is_paid')
    list_filter = ('month', 'is_paid')