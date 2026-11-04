from django.core.management.base import BaseCommand
from decimal import Decimal
from Smartnestapp.models import Building, Room

class Command(BaseCommand):
    help = 'Populates Building-1 (A1-A10, B1-B10, C1-C5) and Building-2 (R1-R4, R5-R8)'

    def handle(self, *args, **kwargs):
        self.stdout.write("Configuring buildings and rooms...")

        # 1. Buildings
        b1, _ = Building.objects.get_or_create(name="Building-1", defaults={'address': 'Main Complex'})
        b2, _ = Building.objects.get_or_create(name="Building-2", defaults={'address': 'Annex Complex'})

        # 2. Building-1 Setup (25 Rooms)
        # Ground Floor: A1 to A10
        for i in range(1, 11):
            Room.objects.update_or_create(
                building=b1, room_number=f"A{i}",
                defaults={
                    'floor': 'Ground Floor',
                    'monthly_rent': Decimal('8500.00'),
                    'maintenance_charges': Decimal('500.00'),
                    'target_advance_amount': Decimal('25000.00'),
                    'is_vacant': False if i <= 7 else True
                }
            )

        # First Floor: B1 to B10
        for i in range(1, 11):
            Room.objects.update_or_create(
                building=b1, room_number=f"B{i}",
                defaults={
                    'floor': 'First Floor',
                    'monthly_rent': Decimal('9000.00'),
                    'maintenance_charges': Decimal('500.00'),
                    'target_advance_amount': Decimal('25000.00'),
                    'is_vacant': False if i <= 8 else True
                }
            )

        # 2nd Floor: C1 to C5
        for i in range(1, 6):
            Room.objects.update_or_create(
                building=b1, room_number=f"C{i}",
                defaults={
                    'floor': '2nd Floor',
                    'monthly_rent': Decimal('9500.00'),
                    'maintenance_charges': Decimal('500.00'),
                    'target_advance_amount': Decimal('30000.00'),
                    'is_vacant': False if i <= 3 else True
                }
            )

        # 3. Building-2 Setup (8 Rooms)
        # Ground Floor: R1 to R4
        for i in range(1, 5):
            Room.objects.update_or_create(
                building=b2, room_number=f"R{i}",
                defaults={
                    'floor': 'Ground Floor',
                    'monthly_rent': Decimal('12000.00'),
                    'maintenance_charges': Decimal('800.00'),
                    'target_advance_amount': Decimal('40000.00'),
                    'is_vacant': False if i <= 3 else True
                }
            )

        # First Floor: R5 to R8
        for i in range(5, 9):
            Room.objects.update_or_create(
                building=b2, room_number=f"R{i}",
                defaults={
                    'floor': 'First Floor',
                    'monthly_rent': Decimal('12500.00'),
                    'maintenance_charges': Decimal('800.00'),
                    'target_advance_amount': Decimal('40000.00'),
                    'is_vacant': False if i <= 7 else True
                }
            )

        self.stdout.write(self.style.SUCCESS("All 33 rooms created with custom floors and numbering!"))