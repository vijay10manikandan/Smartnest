from decimal import Decimal
from datetime import date, datetime
import urllib.parse

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.http import JsonResponse
from django.db.models import Sum
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from .models import (
    Building,
    Room,
    Tenant,
    AdvanceDetail,
    ElectricityReading,
    RentDetail,
)
from .forms import (
    TenantForm,
    AdvanceDetailForm,
    ElectricityReadingForm,
    RoomForm,
)


# ==============================================================================
# Helper Functions: Bill & Maintenance Calculations
# ==============================================================================

def get_room_maintenance_breakdown(room):
    """
    Returns (maintenance_amount, maintenance_display_string)
    based on the room's active category (Per Member vs Per Room).
    """
    if room.maintenance_type == 'PER_MEMBER':
        count = room.get_tenant_member_count()
        rate = room.maintenance_rate_per_member or Decimal('250.00')
        total_maint = Decimal(str(count)) * Decimal(str(rate))
        display_str = f"Maintenance: {count} members * {int(rate)} = ₹{total_maint:.2f}"
    else:
        total_maint = Decimal(str(room.maintenance_charges or Decimal('0.00')))
        display_str = f"Maintenance: ₹{total_maint:.2f}"

    return total_maint, display_str


def get_meter_grid_data():
    """Helper to prepare the 33-room electricity grid layout."""
    current_month_date = date.today().replace(day=1)
    all_rooms = Room.objects.select_related('building').all()
    reading_map = {}

    for room in all_rooms:
        record, _ = ElectricityReading.objects.get_or_create(
            room=room,
            month_year=current_month_date,
            defaults={
                'previous_reading': Decimal('0.00'),
                'current_reading': Decimal('0.00'),
                'rate_per_unit': Decimal('10.00'),
            }
        )
        room.current_reading = record.current_reading
        room.previous_reading = record.previous_reading
        reading_map[room.id] = record

    b1_a_rooms = [r for r in all_rooms if r.building.name == "Building-1" and r.room_number.startswith("A")]
    b1_b_rooms = [r for r in all_rooms if r.building.name == "Building-1" and r.room_number.startswith("B")]
    b1_c_rooms = [r for r in all_rooms if r.building.name == "Building-1" and r.room_number.startswith("C")]
    b2_rooms = [r for r in all_rooms if r.building.name == "Building-2"]

    b1_rows = []
    for i in range(10):
        b1_rows.append({
            'a': b1_a_rooms[i] if i < len(b1_a_rooms) else None,
            'b': b1_b_rooms[i] if i < len(b1_b_rooms) else None,
            'c': b1_c_rooms[i] if i < len(b1_c_rooms) else None,
        })

    return b1_rows, b2_rooms, reading_map, all_rooms


# ==============================================================================
# 1. Dashboard View
# ==============================================================================

# Smartnestapp/views.py inside dashboard_view
@login_required
def dashboard_view(request):
    current_month = date.today().replace(day=1)

    # 1. Room Metrics
    total_rooms = Room.objects.count()
    vacant_rooms = Room.objects.filter(is_vacant=True).count()
    occupied_rooms = total_rooms - vacant_rooms

    # 2. Rent Metrics (Total Rent, Total Billed, Total Collected, Pending Rent)
    rent_aggregates = RentDetail.objects.filter(month=current_month).aggregate(
        total_rent=Sum('rent_amount'),
        total_billed=Sum('total_amount'),
        total_collected=Sum('paid_amount'),
    )
    total_rent = rent_aggregates['total_rent'] or Decimal('0.00')
    total_billed = rent_aggregates['total_billed'] or Decimal('0.00')
    total_collected = rent_aggregates['total_collected'] or Decimal('0.00')
    pending_rent = max(Decimal('0.00'), total_billed - total_collected)

    # 3. Cash vs UPI Rent Collections
    cash_rent_collected = RentDetail.objects.filter(
        month=current_month, payment_method='CASH'
    ).aggregate(total=Sum('paid_amount'))['total'] or Decimal('0.00')

    upi_rent_collected = RentDetail.objects.filter(
        month=current_month, payment_method='UPI'
    ).aggregate(total=Sum('paid_amount'))['total'] or Decimal('0.00')

    # 4. Advance Metrics (Total, Cash, UPI)
    adv_aggregates = AdvanceDetail.objects.aggregate(
        total=Sum('amount_paid')
    )
    total_advance = adv_aggregates['total'] or Decimal('0.00')

    cash_advance = AdvanceDetail.objects.filter(
        payment_method='CASH'
    ).aggregate(total=Sum('amount_paid'))['total'] or Decimal('0.00')

    upi_advance = AdvanceDetail.objects.filter(
        payment_method='UPI'
    ).aggregate(total=Sum('amount_paid'))['total'] or Decimal('0.00')

    # 5. Building Electricity Units (Building-1 and Building-2 for current month)
    # Sums units_consumed for each building's rooms
    b1_readings = ElectricityReading.objects.filter(
        room__building__name__icontains="Building-1",
        month_year=current_month
    )
    b1_total_units = sum([r.units_consumed for r in b1_readings])

    b2_readings = ElectricityReading.objects.filter(
        room__building__name__icontains="Building-2",
        month_year=current_month
    )
    b2_total_units = sum([r.units_consumed for r in b2_readings])

    # 6. Rental Due and Rent Reminders (Unchanged)
    overdue_reminders = RentDetail.objects.filter(
        is_paid=False,
        month=current_month
    ).select_related('room', 'tenant', 'room__building')

    context = {
        'total_rooms': total_rooms,
        'vacant_rooms': vacant_rooms,
        'occupied_rooms': occupied_rooms,
        'total_rent': total_rent,
        'pending_rent': pending_rent,
        'total_advance': total_advance,
        'cash_advance': cash_advance,
        'upi_advance': upi_advance,
        'cash_rent_collected': cash_rent_collected,
        'upi_rent_collected': upi_rent_collected,
        'b1_total_units': b1_total_units,
        'b2_total_units': b2_total_units,
        'overdue_reminders': overdue_reminders,
    }
    return render(request, 'Smartnestapp/dashboard.html', context)


# ==============================================================================
# 2. Room Details View (Floor-wise & Default Configurations)
# ==============================================================================
@login_required
def room_details_view(request):
    current_month = date.today().replace(day=1)

    if request.method == "POST" and "modify_room_rent" in request.POST:
        room_id = request.POST.get("room_id")
        room = get_object_or_404(Room, id=room_id)

        room.monthly_rent = Decimal(str(request.POST.get("monthly_rent", "0.00") or 0))
        room.target_advance_amount = Decimal(str(request.POST.get("target_advance_amount", "0.00") or 0))
        room.is_vacant = ('is_vacant' in request.POST)

        m_type = request.POST.get("maintenance_type", "PER_ROOM")
        room.maintenance_type = m_type

        if m_type == "PER_MEMBER":
            rate = Decimal(str(request.POST.get("maintenance_rate_per_member", "250.00") or "250.00"))
            count = int(request.POST.get("member_count") or room.get_tenant_member_count() or 1)
            room.maintenance_rate_per_member = rate
            calculated_maint = rate * Decimal(str(count))
            room.maintenance_charges = calculated_maint
        else:
            fixed_amount = Decimal(str(request.POST.get("maintenance_fixed_amount", "500.00") or "500.00"))
            room.maintenance_charges = fixed_amount
            calculated_maint = fixed_amount

        room.save()

        # Connect with Rent Details for current month
        rent_obj, _ = RentDetail.objects.get_or_create(
            room=room,
            month=current_month,
            defaults={
                'tenant': room.current_tenant,
                'rent_amount': room.monthly_rent,
                'maintenance_charge': calculated_maint,
                'electricity_charge': Decimal('0.00'),
                'last_month_balance': Decimal('0.00'),
            }
        )
        rent_obj.rent_amount = room.monthly_rent
        rent_obj.maintenance_charge = calculated_maint
        rent_obj.save()

        messages.success(request, f"Room {room.room_number}: Maintenance ₹{calculated_maint:.2f} updated and synced to Rent Details.")
        return redirect("room_details")

    # Load structured floor-wise rooms
    buildings = Building.objects.all()
    structured_data = []
    for bldg in buildings:
        floors = {}
        for r in Room.objects.filter(building=bldg).order_by('room_number'):
            floors.setdefault(r.floor, []).append(r)

        structured_data.append({
            'building': bldg,
            'floors': floors
        })

    return render(request, 'Smartnestapp/room_details.html', {
        'structured_data': structured_data,
        'total_rooms_count': Room.objects.count()
    })


# ==============================================================================
# 3. Rent Details View (Billing & Payment Collections)
# ==============================================================================

# Smartnestapp/views.py
@login_required
def rent_details_view(request):
    today = date.today()
    current_month = today.replace(day=1)

    # 1. Update Rent Payment
    if request.method == 'POST' and 'update_rent_payment' in request.POST:
        room_id = request.POST.get('room_id')
        collected_amount = Decimal(str(request.POST.get('amount_paid', '0.00') or 0))
        collection_date_str = request.POST.get('collection_date')
        collection_date = date.fromisoformat(collection_date_str) if collection_date_str else today
        payment_method = request.POST.get('payment_method', 'UPI')

        room = get_object_or_404(Room, id=room_id)
        latest_elec = room.electricity_readings.filter(month_year=current_month).first()
        elec_amount = latest_elec.total_electricity_amount if latest_elec else Decimal('0.00')
        maint_amount, _ = get_room_maintenance_breakdown(room)

        rent_record, _ = RentDetail.objects.get_or_create(
            room=room,
            month=current_month,
            defaults={
                'tenant': room.current_tenant,
                'rent_amount': room.monthly_rent,
                'electricity_charge': elec_amount,
                'maintenance_charge': maint_amount,
                'paid_amount': Decimal('0.00'),
                'last_month_balance': Decimal('0.00'),
                'payment_method': payment_method,
            }
        )

        rent_record.tenant = room.current_tenant
        rent_record.rent_amount = room.monthly_rent
        rent_record.maintenance_charge = maint_amount
        rent_record.electricity_charge = elec_amount
        rent_record.paid_amount = collected_amount
        rent_record.collection_date = collection_date
        rent_record.payment_method = payment_method
        rent_record.save()  # Triggers calculate_total_bill and is_paid check

        messages.success(request, f"Updated Room {room.room_number}: Collected ₹{collected_amount} via {payment_method}")
        return redirect('rent_details')

    # 2. Gather Building Data
    all_rooms = Room.objects.select_related('building').prefetch_related('tenants', 'electricity_readings', 'rent_records').all()
    tenant_rooms_map = {}
    room_data_cache = {}

    for r in all_rooms:
        tenant = r.current_tenant
        latest_elec = r.electricity_readings.filter(month_year=current_month).first()
        elec_cost = latest_elec.total_electricity_amount if latest_elec else Decimal('0.00')
        maint_cost, _ = get_room_maintenance_breakdown(r)

        rent_record, _ = RentDetail.objects.get_or_create(
            room=r,
            month=current_month,
            defaults={
                'tenant': tenant,
                'rent_amount': r.monthly_rent,
                'maintenance_charge': maint_cost,
                'electricity_charge': elec_cost,
                'last_month_balance': Decimal('0.00'),
            }
        )
        rent_record.rent_amount = r.monthly_rent
        rent_record.maintenance_charge = maint_cost
        rent_record.electricity_charge = elec_cost
        rent_record.save()

        # Dynamic pending calculation: Total Billed - Amount Collected
        pending_balance = rent_record.current_balance_due

        info = {
            'room': r,
            'tenant': tenant,
            'rent': rent_record.rent_amount,
            'maintenance': rent_record.maintenance_charge,
            'electricity': rent_record.electricity_charge,
            'total': rent_record.total_amount,
            'collected': rent_record.paid_amount,
            'pending': pending_balance,
            'rent_record': rent_record,
        }
        room_data_cache[r.id] = info

        if tenant:
            key = (tenant.primary_name.strip().lower(), tenant.phone_number.strip())
            tenant_rooms_map.setdefault(key, []).append(info)

    building_data = []
    for b in Building.objects.all():
        rooms_info = []
        for r in [rm for rm in all_rooms if rm.building_id == b.id]:
            info = room_data_cache[r.id]
            tenant = info['tenant']
            is_multi = False

            if tenant:
                t_key = (tenant.primary_name.strip().lower(), tenant.phone_number.strip())
                is_multi = len(tenant_rooms_map.get(t_key, [])) > 1

            info['is_multi_room'] = is_multi
            rooms_info.append(info)

        building_data.append({
            'building': b,
            'rooms_info': rooms_info
        })

    return render(request, 'Smartnestapp/rent_details.html', {
        'building_data': building_data,
        'billing_month': current_month
    })

@login_required
def get_single_bill(request, room_id):
    """Generates Single Bill with payment acknowledgement and remaining pending balance."""
    room = get_object_or_404(Room, id=room_id)
    current_month = date.today().replace(day=1)
    tenant = room.current_tenant

    tenant_name = tenant.primary_name if tenant else "Tenant"
    tenant_phone = tenant.phone_number if tenant else ""

    clean_phone = ''.join(filter(str.isdigit, tenant_phone))
    if len(clean_phone) == 10:
        clean_phone = "91" + clean_phone

    rent_obj = RentDetail.objects.filter(room=room, month=current_month).first()
    rent_amount = Decimal(str(room.monthly_rent or 0.00))
    eb_amount = Decimal(str(rent_obj.electricity_charge if rent_obj else 0.00))
    maint_amount, maint_str = get_room_maintenance_breakdown(room)

    raw_balance = Decimal(str(rent_obj.last_month_balance if rent_obj else 0.00))
    last_month_pending = max(Decimal('0.00'), raw_balance)
    total_bill = rent_amount + eb_amount + maint_amount + last_month_pending

    paid_amt = Decimal(str(rent_obj.paid_amount if rent_obj else 0.00))
    balance_pending = max(Decimal('0.00'), total_bill - paid_amt)

    bill_lines = [
        f"Name: {tenant_name}",
        f"{current_month.strftime('%d/%m/%Y')} Room no {room.room_number} Rent: {rent_amount:.2f}",
        f"{room.room_number} EB: Amount: ₹{eb_amount:.2f}",
        f"{maint_str}",
        f"Last month balance: ₹{last_month_pending:.2f}",
        f"Total: ₹{total_bill:.2f}"
    ]

    # If any payment has been collected, append receipt line and remaining balance
    if paid_amt > Decimal('0.00'):
        c_date = rent_obj.collection_date.strftime('%d/%m/%Y') if (rent_obj and rent_obj.collection_date) else date.today().strftime('%d/%m/%Y')
        p_mode = rent_obj.payment_method if (rent_obj and rent_obj.payment_method) else "UPI"
        bill_lines.append(f"Received ({c_date}): ₹{paid_amt:.2f} via {p_mode}")
        bill_lines.append(f"Balance Pending: ₹{balance_pending:.2f}")

    bill_text = "\n".join(bill_lines)
    encoded = urllib.parse.quote(bill_text)
    whatsapp_url = f"https://api.whatsapp.com/send?phone={clean_phone}&text={encoded}" if clean_phone else f"https://api.whatsapp.com/send?text={encoded}"

    return JsonResponse({
        'room_number': room.room_number,
        'tenant_name': tenant_name,
        'bill_text': bill_text,
        'whatsapp_url': whatsapp_url,
        'total': float(total_bill)
    })

@login_required
def get_combined_bill(request, tenant_id):
    """Generates Combined Bill with total payments collected and final remaining balance."""
    tenant = get_object_or_404(Tenant, id=tenant_id)
    current_month = date.today().replace(day=1)

    clean_phone = ''.join(filter(str.isdigit, tenant.phone_number))
    if len(clean_phone) == 10:
        clean_phone = "91" + clean_phone

    all_matching_tenants = Tenant.objects.filter(
        primary_name__iexact=tenant.primary_name.strip(),
        phone_number__iexact=tenant.phone_number.strip(),
        is_active=True
    )
    rooms = Room.objects.filter(tenants__in=all_matching_tenants).distinct().order_by('room_number')

    bill_lines = [
        f"Name: {tenant.primary_name} (Combined Bill)",
        f"Billing Month: {current_month.strftime('%b %Y')}",
        "------------------------------------"
    ]

    grand_total = Decimal('0.00')
    total_prev_balance = Decimal('0.00')
    total_paid_collected = Decimal('0.00')

    for r in rooms:
        rent_obj = RentDetail.objects.filter(room=r, month=current_month).first()
        r_rent = Decimal(str(r.monthly_rent or 0.00))
        r_eb = Decimal(str(rent_obj.electricity_charge if rent_obj else 0.00))
        r_maint, r_maint_str = get_room_maintenance_breakdown(r)

        raw_bal = Decimal(str(rent_obj.last_month_balance if rent_obj else 0.00))
        total_prev_balance += max(Decimal('0.00'), raw_bal)

        if rent_obj:
            total_paid_collected += Decimal(str(rent_obj.paid_amount or 0.00))

        room_subtotal = r_rent + r_eb + r_maint
        grand_total += room_subtotal

        bill_lines.append(f"Room {r.room_number}:")
        bill_lines.append(f"  • Rent: ₹{r_rent:.2f}")
        bill_lines.append(f"  • EB: ₹{r_eb:.2f}")
        bill_lines.append(f"  • {r_maint_str}")
        bill_lines.append(f"  Subtotal: ₹{room_subtotal:.2f}\n")

    grand_total += total_prev_balance
    final_pending = max(Decimal('0.00'), grand_total - total_paid_collected)

    bill_lines.append("------------------------------------")
    bill_lines.append(f"Last month balance: ₹{total_prev_balance:.2f}")
    bill_lines.append(f"Total: ₹{grand_total:.2f}")

    if total_paid_collected > Decimal('0.00'):
        bill_lines.append(f"Received Total: ₹{total_paid_collected:.2f}")
        bill_lines.append(f"Balance Pending: ₹{final_pending:.2f}")

    combined_text = "\n".join(bill_lines)
    encoded = urllib.parse.quote(combined_text)
    whatsapp_url = f"https://api.whatsapp.com/send?phone={clean_phone}&text={encoded}" if clean_phone else f"https://api.whatsapp.com/send?text={encoded}"

    return JsonResponse({
        'tenant_name': tenant.primary_name,
        'bill_text': combined_text,
        'whatsapp_url': whatsapp_url,
        'total': float(grand_total)
    })


# ==============================================================================
# 4. Single & Combined Bill API Endpoints (WhatsApp / Preview)
# ==============================================================================

def get_room_maintenance_breakdown(room):
    """
    Returns (amount, display_string)
    Per Member: 'Maintenance: 3 members * 250 = ₹750.00'
    Per Room: 'Maintenance: ₹500.00'
    """
    if room.maintenance_type == 'PER_MEMBER':
        count = room.get_tenant_member_count()
        rate = room.maintenance_rate_per_member or Decimal('250.00')
        total_maint = Decimal(str(count)) * Decimal(str(rate))
        display_str = f"Maintenance: {count} members * {int(rate)} = ₹{total_maint:.2f}"
    else:
        total_maint = Decimal(str(room.maintenance_charges or Decimal('0.00')))
        display_str = f"Maintenance: ₹{total_maint:.2f}"
    return total_maint, display_str

@login_required
def get_single_bill(request, room_id):
    room = get_object_or_404(Room, id=room_id)
    current_month = date.today().replace(day=1)
    tenant = room.current_tenant

    tenant_name = tenant.primary_name if tenant else "Tenant"
    tenant_phone = tenant.phone_number if tenant else ""

    clean_phone = ''.join(filter(str.isdigit, tenant_phone))
    if len(clean_phone) == 10:
        clean_phone = "91" + clean_phone

    rent_obj = RentDetail.objects.filter(room=room, month=current_month).first()
    rent_amount = Decimal(str(room.monthly_rent or 0.00))
    eb_amount = Decimal(str(rent_obj.electricity_charge if rent_obj else 0.00))
    maint_amount, maint_str = get_room_maintenance_breakdown(room)

    raw_balance = Decimal(str(rent_obj.last_month_balance if rent_obj else 0.00))
    pending_balance = max(Decimal('0.00'), raw_balance)
    total_bill = rent_amount + eb_amount + maint_amount + pending_balance

    bill_lines = [
        f"Name: {tenant_name}",
        f"{current_month.strftime('%d/%m/%Y')} Room no {room.room_number} Rent: {rent_amount:.2f}",
        f"{room.room_number} EB: Amount: ₹{eb_amount:.2f}",
        f"{maint_str}",
        f"Last month balance: ₹{pending_balance:.2f}",
        f"Total: ₹{total_bill:.2f}"
    ]
    bill_text = "\n".join(bill_lines)
    encoded = urllib.parse.quote(bill_text)
    whatsapp_url = f"https://api.whatsapp.com/send?phone={clean_phone}&text={encoded}" if clean_phone else f"https://api.whatsapp.com/send?text={encoded}"

    return JsonResponse({
        'room_number': room.room_number,
        'tenant_name': tenant_name,
        'bill_text': bill_text,
        'whatsapp_url': whatsapp_url,
        'total': float(total_bill)
    })

@login_required
def get_combined_bill(request, tenant_id):
    """
    Pulls ALL rooms occupied by this tenant by matching their
    primary_name and phone_number across the database.
    """
    tenant = get_object_or_404(Tenant, id=tenant_id)
    current_month = date.today().replace(day=1)

    clean_phone = ''.join(filter(str.isdigit, tenant.phone_number))
    if len(clean_phone) == 10:
        clean_phone = "91" + clean_phone

    # Find all tenant entries with matching name and phone
    all_matching_tenants = Tenant.objects.filter(
        primary_name__iexact=tenant.primary_name.strip(),
        phone_number__iexact=tenant.phone_number.strip(),
        is_active=True
    )
    
    # Collect all rooms linked to these tenant entries
    rooms = Room.objects.filter(tenants__in=all_matching_tenants).distinct().order_by('room_number')

    bill_lines = [
        f"Name: {tenant.primary_name} (Combined Bill)",
        f"Billing Month: {current_month.strftime('%b %Y')}",
        "------------------------------------"
    ]

    grand_total = Decimal('0.00')
    total_pending_balance = Decimal('0.00')

    for r in rooms:
        rent_obj = RentDetail.objects.filter(room=r, month=current_month).first()
        r_rent = Decimal(str(r.monthly_rent or 0.00))
        r_eb = Decimal(str(rent_obj.electricity_charge if rent_obj else 0.00))
        r_maint, r_maint_str = get_room_maintenance_breakdown(r)

        raw_bal = Decimal(str(rent_obj.last_month_balance if rent_obj else 0.00))
        total_pending_balance += max(Decimal('0.00'), raw_bal)

        room_subtotal = r_rent + r_eb + r_maint
        grand_total += room_subtotal

        bill_lines.append(f"Room {r.room_number}:")
        bill_lines.append(f"  • Rent: ₹{r_rent:.2f}")
        bill_lines.append(f"  • EB: ₹{r_eb:.2f}")
        bill_lines.append(f"  • {r_maint_str}")
        bill_lines.append(f"  Subtotal: ₹{room_subtotal:.2f}\n")

    grand_total += total_pending_balance
    bill_lines.append("------------------------------------")
    bill_lines.append(f"Last month balance: ₹{total_pending_balance:.2f}")
    bill_lines.append(f"Total: ₹{grand_total:.2f}")

    combined_text = "\n".join(bill_lines)
    encoded = urllib.parse.quote(combined_text)
    whatsapp_url = f"https://api.whatsapp.com/send?phone={clean_phone}&text={encoded}" if clean_phone else f"https://api.whatsapp.com/send?text={encoded}"

    return JsonResponse({
        'tenant_name': tenant.primary_name,
        'bill_text': combined_text,
        'whatsapp_url': whatsapp_url,
        'total': float(grand_total)
    })


# ==============================================================================
# 5. Electricity Meter Readings (Prev, Current, Rollover & Final Submit)
# ==============================================================================
@login_required
def previous_month_reading_view(request):
    b1_rows, b2_rooms, reading_map, all_rooms = get_meter_grid_data()

    if request.method == 'POST':
        for room in all_rooms:
            prev_val = request.POST.get(f'prev_{room.id}')
            rec = reading_map.get(room.id)
            if rec and prev_val is not None and prev_val != '':
                rec.previous_reading = Decimal(prev_val)
                rec.save()

        messages.success(request, "Previous month readings updated in database!")
        return redirect('previous_month_reading')

    return render(request, 'Smartnestapp/previous_month_reading.html', {
        'b1_rows': b1_rows,
        'b2_rooms': b2_rooms,
        'reading_map': reading_map,
        'current_date': date.today().strftime('%d/%m/%Y'),
    })

@login_required
def current_month_reading_view(request):
    b1_rows, b2_rooms, reading_map, all_rooms = get_meter_grid_data()
    current_month_date = date.today().replace(day=1)

    if request.method == 'POST':
        action = request.POST.get('action')

        # 1. Save or Final Submit Current Readings
        if action in ['save_readings', 'final_submit']:
            for room in all_rooms:
                curr_val = request.POST.get(f'curr_{room.id}')
                rec = reading_map.get(room.id)
                if rec and curr_val is not None and curr_val != '':
                    rec.current_reading = Decimal(curr_val)
                    rec.save()  # Triggers auto-sync to RentDetail via model save()

            messages.success(request, "Current month readings recorded and linked to Electricity & Rent details!")
            return redirect('current_month_reading')

        # 2. Save to Previous Month (Rollover)
        elif action == 'save_to_previous':
            for room in all_rooms:
                rec = reading_map.get(room.id)
                if rec:
                    rec.previous_reading = rec.current_reading
                    rec.current_reading = Decimal('0.00')
                    rec.save()

            messages.success(request, "Current readings rolled over to Previous Month readings!")
            return redirect('current_month_reading')

        # 3. Clear All Current Readings
        elif action == 'clear_current':
            for room in all_rooms:
                rec = reading_map.get(room.id)
                if rec:
                    rec.current_reading = Decimal('0.00')
                    rec.save()

            messages.success(request, "All current month readings cleared to 0.")
            return redirect('current_month_reading')

    return render(request, 'Smartnestapp/current_month_reading.html', {
        'b1_rows': b1_rows,
        'b2_rooms': b2_rooms,
        'reading_map': reading_map,
        'current_date': date.today().strftime('%d/%m/%Y'),
    })

@login_required
def electricity_view(request):
    buildings = Building.objects.prefetch_related('rooms__electricity_readings').all()
    return render(request, 'Smartnestapp/electricity.html', {'buildings': buildings})


def edit_electricity_view(request, reading_id=None):
    reading = get_object_or_404(ElectricityReading, id=reading_id) if reading_id else None
    if request.method == 'POST':
        form = ElectricityReadingForm(request.POST, instance=reading)
        if form.is_valid():
            saved_reading = form.save()
            messages.success(request, f"Electricity reading for {saved_reading.room} saved!")
            return redirect('electricity')
    else:
        form = ElectricityReadingForm(instance=reading)
    return render(request, 'Smartnestapp/edit_form.html', {
        'form': form,
        'title': f"{'Edit' if reading else 'Add'} Electricity Meter Reading",
        'cancel_url': 'electricity'
    })


# ==============================================================================
# 6. Tenant & Advance Views
# ==============================================================================
@login_required
def tenant_details_view(request):
    tenants = Tenant.objects.select_related('room', 'room__building').all()
    return render(request, 'Smartnestapp/tenant_details.html', {'tenants': tenants})


def edit_tenant_view(request, tenant_id=None):
    tenant = get_object_or_404(Tenant, id=tenant_id) if tenant_id else None
    if request.method == 'POST':
        form = TenantForm(request.POST, instance=tenant)
        if form.is_valid():
            saved_tenant = form.save()
            room = saved_tenant.room
            room.is_vacant = not saved_tenant.is_active
            room.save()
            messages.success(request, f"Tenant {saved_tenant.primary_name} saved successfully!")
            return redirect('tenant_details')
    else:
        form = TenantForm(instance=tenant)
    return render(request, 'Smartnestapp/edit_form.html', {
        'form': form,
        'title': f"{'Edit' if tenant else 'Add'} Tenant Details",
        'cancel_url': 'tenant_details'
    })


def delete_tenant_view(request, tenant_id):
    tenant = get_object_or_404(Tenant, id=tenant_id)
    if request.method == 'POST':
        room = tenant.room
        tenant_name = tenant.primary_name
        tenant.delete()

        if not room.tenants.filter(is_active=True).exists():
            room.is_vacant = True
            room.save()

        messages.success(request, f"Tenant '{tenant_name}' deleted from database.")
    return redirect('tenant_details')

@login_required
def advance_details_view(request):
    advances = AdvanceDetail.objects.select_related('room', 'room__building', 'tenant').all().order_by('room__room_number')
    rooms = Room.objects.filter(is_vacant=False).select_related('building')

    # Handle "+ Record Advance" Modal submission
    if request.method == 'POST' and 'record_advance_submit' in request.POST:
        room_id = request.POST.get('room_id')
        room = get_object_or_404(Room, id=room_id)
        amount_paid = Decimal(str(request.POST.get('amount_paid', '0.00') or 0))
        payment_method = request.POST.get('payment_method', 'UPI')
        pay_date_str = request.POST.get('payment_date')
        payment_date = date.fromisoformat(pay_date_str) if pay_date_str else date.today()

        advance_record, _ = AdvanceDetail.objects.get_or_create(
            room=room,
            defaults={'tenant': room.current_tenant}
        )
        advance_record.tenant = room.current_tenant
        advance_record.amount_paid = amount_paid
        advance_record.payment_method = payment_method
        advance_record.payment_date = payment_date
        advance_record.save()  # Triggers automatic status calculation

        messages.success(request, f"Advance recorded for Room {room.room_number} via {payment_method}!")
        return redirect('advance_details')

    # Bulk Save Handler (if editing inline rows)
    if request.method == 'POST' and 'bulk_save_advances' in request.POST:
        updated_count = 0
        for adv in advances:
            paid_str = request.POST.get(f'paid_{adv.id}')
            method = request.POST.get(f'method_{adv.id}')
            pay_date_str = request.POST.get(f'date_{adv.id}')

            if paid_str is not None:
                adv.amount_paid = Decimal(paid_str)
            if method:
                adv.payment_method = method
            if pay_date_str:
                adv.payment_date = date.fromisoformat(pay_date_str)

            adv.save()  # Auto updates status
            updated_count += 1

        messages.success(request, f"Saved {updated_count} advance records to database!")
        return redirect('advance_details')

    return render(request, 'Smartnestapp/advance_details.html', {
        'advances': advances,
        'rooms': rooms,
        'today_date': date.today().strftime('%Y-%m-%d'),
    })


def edit_advance_view(request, advance_id=None):
    advance = get_object_or_404(AdvanceDetail, id=advance_id) if advance_id else None
    if request.method == 'POST':
        form = AdvanceDetailForm(request.POST, instance=advance)
        if form.is_valid():
            form.save()
            messages.success(request, "Advance details saved successfully!")
            return redirect('advance_details')
    else:
        form = AdvanceDetailForm(instance=advance)
    return render(request, 'Smartnestapp/edit_form.html', {
        'form': form,
        'title': f"{'Edit' if advance else 'Add'} Advance Record",
        'cancel_url': 'advance_details'
    })


def delete_advance_view(request, advance_id):
    advance = get_object_or_404(AdvanceDetail, id=advance_id)
    if request.method == 'POST':
        room_info = str(advance.room)
        advance.delete()
        messages.success(request, f"Advance record for {room_info} deleted.")
    return redirect('advance_details')
def update_rent_collection_view(request, record_id):
    rent_record = get_object_or_404(RentDetail, id=record_id)
    if request.method == 'POST':
        form = RentDetailUpdateForm(request.POST, instance=rent_record)
        if form.is_valid():
            record = form.save(commit=False)
            record.calculate_total_bill()
            record.is_paid = (record.paid_amount >= record.total_amount)
            record.save()
            messages.success(request, f"Rent updated for Room {record.room.room_number}!")
            return redirect('rent_details')
    else:
        form = RentDetailUpdateForm(instance=rent_record)
    return render(request, 'Smartnestapp/update_rent.html', {'form': form, 'rent_record': rent_record})

# Smartnestapp/views.py

def custom_login_view(request):
    # If already logged in, redirect straight to dashboard
    if request.user.is_authenticated:
        return redirect('dashboard')

    error_message = None

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '').strip()

        user = authenticate(request, username=username, password=password)

        if user is not None:
            # Correct credentials -> Log in and establish session
            login(request, user)
            
            # Ensure session cookie expires when browser closes
            request.session.set_expiry(0)

            # Redirect to originally requested page or dashboard
            next_url = request.GET.get('next') or 'dashboard'
            return redirect(next_url)
        else:
            # Incorrect credentials -> Stay on login page and display error
            error_message = "Invalid username or password. Please try again."

    return render(request, 'Smartnestapp/login.html', {'error_message': error_message})


def custom_logout_view(request):
    logout(request)
    return redirect('login')