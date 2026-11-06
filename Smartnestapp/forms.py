from django import forms
from .models import Room, Tenant, AdvanceDetail, ElectricityReading, RentDetail


class RoomForm(forms.ModelForm):
    class Meta:
        model = Room
        fields = [
            'building', 
            'room_number', 
            'floor', 
            'monthly_rent', 
            'maintenance_type', 
            'maintenance_charges', 
            'maintenance_rate_per_member', 
            'target_advance_amount', 
            'is_vacant'
        ]
        widgets = {
            'building': forms.Select(attrs={'class': 'form-select'}),
            'room_number': forms.TextInput(attrs={'class': 'form-control'}),
            'floor': forms.TextInput(attrs={'class': 'form-control'}),
            'monthly_rent': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'maintenance_type': forms.Select(attrs={'class': 'form-select'}),
            'maintenance_charges': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'maintenance_rate_per_member': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'target_advance_amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'is_vacant': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class TenantForm(forms.ModelForm):
    class Meta:
        model = Tenant
        fields = ['room', 'primary_name', 'phone_number', 'members_names', 'lease_start_date', 'is_active']
        widgets = {
            'room': forms.Select(attrs={'class': 'form-select'}),
            'primary_name': forms.TextInput(attrs={'class': 'form-control'}),
            'phone_number': forms.TextInput(attrs={'class': 'form-control'}),
            'members_names': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'e.g. John, Sarah, Mike'}),
            'lease_start_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class AdvanceDetailForm(forms.ModelForm):
    class Meta:
        model = AdvanceDetail
        fields = [
            'room',
            'tenant',
            'agreement_advance',
            'cash_amount',
            'upi_amount',
            'amount_paid',
            'paid_date',           # Changed from payment_date
            'pending_advance',
        ]
        widgets = {
            'room': forms.Select(attrs={'class': 'form-select'}),
            'tenant': forms.Select(attrs={'class': 'form-select'}),
            'agreement_advance': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'cash_amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'upi_amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'amount_paid': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'paid_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),  # Changed from payment_date
            'pending_advance': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'readonly': 'readonly'}),
        }


class ElectricityReadingForm(forms.ModelForm):
    class Meta:
        model = ElectricityReading
        fields = ['room', 'month_year', 'previous_reading', 'current_reading', 'rate_per_unit']
        widgets = {
            'room': forms.Select(attrs={'class': 'form-select'}),
            'month_year': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'previous_reading': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'current_reading': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'rate_per_unit': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
        }


class RentDetailUpdateForm(forms.ModelForm):
    class Meta:
        model = RentDetail
        fields = [
            'rent_amount', 
            'electricity_charge', 
            'maintenance_charge', 
            'last_month_balance', 
            'paid_amount', 
            'is_paid'
        ]
        widgets = {
            'rent_amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'electricity_charge': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'maintenance_charge': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'last_month_balance': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'paid_amount': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'is_paid': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


# Backward-compatibility alias so legacy views referencing RentCollectionUpdateForm do not fail
RentCollectionUpdateForm = RentDetailUpdateForm