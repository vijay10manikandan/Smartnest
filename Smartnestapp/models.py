from django.db import models
from django.utils import timezone
from datetime import date
from decimal import Decimal


class Building(models.Model):
    name = models.CharField(max_length=100)
    address = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.name

    @property
    def total_rooms_count(self):
        return self.rooms.count()


class Room(models.Model):
    MAINTENANCE_TYPES = [
        ('PER_ROOM', 'Per Room'),
        ('PER_MEMBER', 'Per Member'),
    ]

    building = models.ForeignKey(Building, on_delete=models.CASCADE, related_name='rooms')
    room_number = models.CharField(max_length=20)
    floor = models.CharField(max_length=50)
    monthly_rent = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    target_advance_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    is_vacant = models.BooleanField(default=False)

    # Maintenance settings
    maintenance_type = models.CharField(max_length=20, choices=MAINTENANCE_TYPES, default='PER_ROOM')
    maintenance_charges = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('500.00'))
    maintenance_rate_per_member = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('250.00'))

    def __str__(self):
        return f"{self.room_number} ({self.building.name})"

    @property
    def current_tenant(self):
        """Fetches the active tenant living in this room."""
        return self.tenants.filter(is_active=True).first() or self.tenants.first()

    def get_tenant_member_count(self):
        """
        Pulls tenant member count directly from the Tenant tab.
        Calculates 1 (Primary Tenant) + number of co-occupants in members_names.
        """
        tenant = self.current_tenant
        if tenant:
            total = tenant.total_occupants_count
            return max(1, total - 1)
        return 1

    def calculate_maintenance_charge(self, override_count=None):
        """Calculates maintenance based on the active option."""
        if self.maintenance_type == 'PER_MEMBER':
            count = override_count if override_count is not None else self.get_tenant_member_count()
            rate = self.maintenance_rate_per_member or Decimal('250.00')
            return Decimal(str(count)) * Decimal(str(rate))
        return Decimal(str(self.maintenance_charges or Decimal('0.00')))


class Tenant(models.Model):
    room = models.ForeignKey(Room, related_name='tenants', on_delete=models.CASCADE)
    primary_name = models.CharField(max_length=150)
    phone_number = models.CharField(max_length=15)
    members_names = models.TextField(help_text="Comma-separated co-occupant names (e.g., John, Sarah)", blank=True)
    lease_start_date = models.DateField(default=timezone.now)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.primary_name} ({self.room.room_number})"

    @property
    def total_members_count(self):
        """Counts co-occupants from the comma-separated string."""
        if not self.members_names or not self.members_names.strip():
            return 0
        return len([name for name in self.members_names.split(',') if name.strip()])

    @property
    def total_occupants_count(self):
        """
        Total count displayed in Tenant Tab count column:
        1 (Primary Tenant) + Co-occupants.
        """
        return 1 + self.total_members_count


class AdvanceDetail(models.Model):
    room = models.ForeignKey('Room', on_delete=models.CASCADE, related_name='advance_records')
    tenant = models.ForeignKey('Tenant', on_delete=models.SET_NULL, null=True, blank=True)
    agreement_advance = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    
    # Split payment fields for Advance
    cash_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    upi_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    payment_method = models.CharField(max_length=20, default='UPI')
    paid_date = models.DateField(null=True, blank=True)
    pending_advance = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))

    def save(self, *args, **kwargs):
        self.amount_paid = (self.cash_amount or Decimal('0.00')) + (self.upi_amount or Decimal('0.00'))
        if self.cash_amount > Decimal('0.00') and self.upi_amount > Decimal('0.00'):
            self.payment_method = 'SPLIT'
        elif self.cash_amount > Decimal('0.00'):
            self.payment_method = 'CASH'
        else:
            self.payment_method = 'UPI'
        self.pending_advance = max(Decimal('0.00'), (self.agreement_advance or Decimal('0.00')) - self.amount_paid)
        super().save(*args, **kwargs)


class ElectricityReading(models.Model):
    room = models.ForeignKey(Room, related_name='electricity_readings', on_delete=models.CASCADE)
    month_year = models.DateField(help_text="First day of billing month (e.g., 2026-10-01)")
    previous_reading = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    current_reading = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    rate_per_unit = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal('10.00'))
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('room', 'month_year')

    def __str__(self):
        return f"{self.room.room_number} - {self.month_year.strftime('%b %Y')}"

    @property
    def units_consumed(self):
        return max(Decimal('0.00'), self.current_reading - self.previous_reading)

    @property
    def total_electricity_amount(self):
        return self.units_consumed * self.rate_per_unit

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Automatically synchronize the calculated EB amount to RentDetail
        try:
            billing_month = self.month_year.replace(day=1)
            rent_obj, _ = RentDetail.objects.get_or_create(
                room=self.room,
                month=billing_month,
                defaults={'rent_amount': self.room.monthly_rent}
            )
            rent_obj.electricity_charge = self.total_electricity_amount
            rent_obj.save()
        except Exception:
            pass


class RentDetail(models.Model):
    room = models.ForeignKey('Room', on_delete=models.CASCADE, related_name='rent_records')
    tenant = models.ForeignKey('Tenant', on_delete=models.SET_NULL, null=True, blank=True)
    month = models.DateField()
    rent_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    maintenance_charge = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    electricity_charge = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    last_month_balance = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    
    # Payment breakdown
    cash_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    upi_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    paid_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    payment_method = models.CharField(max_length=20, default='UPI')
    collection_date = models.DateField(null=True, blank=True)
    
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    current_balance_due = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    is_paid = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        self.paid_amount = (self.cash_amount or Decimal('0.00')) + (self.upi_amount or Decimal('0.00'))
        if self.cash_amount > Decimal('0.00') and self.upi_amount > Decimal('0.00'):
            self.payment_method = 'SPLIT'
        elif self.cash_amount > Decimal('0.00'):
            self.payment_method = 'CASH'
        else:
            self.payment_method = 'UPI'

        self.total_amount = (self.rent_amount or Decimal('0.00')) + \
                            (self.maintenance_charge or Decimal('0.00')) + \
                            (self.electricity_charge or Decimal('0.00')) + \
                            (self.last_month_balance or Decimal('0.00'))
        self.current_balance_due = max(Decimal('0.00'), self.total_amount - self.paid_amount)
        self.is_paid = (self.current_balance_due == Decimal('0.00'))
        super().save(*args, **kwargs)
class MonthlyExpense(models.Model):
    month = models.CharField(max_length=20, default="Nov 2026") # e.g., 'Nov 2026'
    
    # 11 Editable expense fields
    grt_payment_active = models.BooleanField(default=True)
    grt_payment = models.DecimalField(max_digits=10, decimal_places=2, default=25000.00)
    
    tneb_active = models.BooleanField(default=True)
    tneb_payment = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    
    mani_chit_1_active = models.BooleanField(default=True)
    mani_chit_1 = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    
    mani_chit_2_active = models.BooleanField(default=True)
    mani_chit_2 = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    
    indira_chit_active = models.BooleanField(default=True)
    indira_chit = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    
    dhamayanthi_milk_chit_active = models.BooleanField(default=True)
    dhamayanthi_milk_chit = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    
    gas_cylinder_active = models.BooleanField(default=True)
    gas_cylinder = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    
    groceries_active = models.BooleanField(default=True)
    groceries = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    
    hardwares_active = models.BooleanField(default=True)
    hardwares = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    
    broadband_3_active = models.BooleanField(default=True)
    broadband_recharge_3 = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    
    other_expenses_active = models.BooleanField(default=True)
    other_expenses = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    
    updated_at = models.DateTimeField(auto_now=True)

    def total_expense(self):
        total = 0
        if self.grt_payment_active: total += self.grt_payment
        if self.tneb_active: total += self.tneb_payment
        if self.mani_chit_1_active: total += self.mani_chit_1
        if self.mani_chit_2_active: total += self.mani_chit_2
        if self.indira_chit_active: total += self.indira_chit
        if self.dhamayanthi_milk_chit_active: total += self.dhamayanthi_milk_chit
        if self.gas_cylinder_active: total += self.gas_cylinder
        if self.groceries_active: total += self.groceries
        if self.hardwares_active: total += self.hardwares
        if self.broadband_3_active: total += self.broadband_recharge_3
        if self.other_expenses_active: total += self.other_expenses
        return total

    def __str__(self):
        return f"Expenses ({self.month})"