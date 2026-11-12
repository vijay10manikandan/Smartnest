from django.db import close_old_connections
from decimal import Decimal
from datetime import date, datetime
import urllib.parse
from .models import MonthlyExpense
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.db.models import Sum, Prefetch
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from .models import (
    Building,
    Room,
    Tenant,
    AdvanceDetail,
    ElectricityReading,
    RentDetail,
    MonthlyExpense,
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
        month=current_month
    ).aggregate(total=Sum('cash_amount'))['total'] or Decimal('0.00')

    upi_rent_collected = RentDetail.objects.filter(
        month=current_month
    ).aggregate(total=Sum('upi_amount'))['total'] or Decimal('0.00')

    # 4. Advance Metrics (Cash vs UPI)
    adv_aggregates = AdvanceDetail.objects.aggregate(
        total_adv=Sum('amount_paid'),
        cash_adv=Sum('cash_amount'),
        upi_adv=Sum('upi_amount')
    )
    total_advance = adv_aggregates['total_adv'] or Decimal('0.00')
    cash_advance = adv_aggregates['cash_adv'] or Decimal('0.00')
    upi_advance = adv_aggregates['upi_adv'] or Decimal('0.00')

    # 5. Building Electricity Units (Building-1 and Building-2 for current month)
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

    # 6. Rental Due and Rent Reminders
    overdue_reminders = RentDetail.objects.filter(
        is_paid=False,
        month=current_month
    ).select_related('room', 'tenant', 'room__building')

    # 7. Monthly Expenses Calculation
    # Dynamic search matching "Nov 2026" or whichever month is active
    current_month_str = current_month.strftime('%b %Y')  # e.g., 'Nov 2026'
    expense = MonthlyExpense.objects.filter(month=current_month_str).first()
    
    if not expense:
        expense = MonthlyExpense.objects.first()
        
    total_expenses = Decimal(str(expense.total_expense())) if expense else Decimal('0.00')

    # 8. Net Profit Calculation (Total Collected - Total Expenses)
    net_profit = total_collected - total_expenses
    is_profit = net_profit >= Decimal('0.00')

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
        'total_expenses': total_expenses,
        'net_profit': net_profit,
        'is_profit': is_profit,
    }
    return render(request, 'Smartnestapp/dashboard.html', context)
@login_required
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
# 2. Room Details View (Floor-wise & Default Configurations)
# ==============================================================================
@login_required
def room_view(request):
    room_details_view = room_view
    # Ensure any stale/dropped NeonDB SSL connection is cleared before querying
    close_old_connections()

    if request.method == 'POST':
        room_id = request.POST.get('room_id')
        room = get_object_or_404(Room, id=room_id)

        # 1. Handle Inline Rent Edit Modal (1. Per Room vs 2. Per Member)
        if 'update_room_rent' in request.POST:
            rent_type = request.POST.get('rent_type', 'PER_ROOM')
            room.rent_type = rent_type
            if rent_type == 'PER_MEMBER':
                room.rent_rate_per_member = Decimal(str(request.POST.get('rent_rate_per_member', '0.00') or 0))
            else:
                room.monthly_rent = Decimal(str(request.POST.get('monthly_rent', '0.00') or 0))
            room.save(update_fields=['rent_type', 'monthly_rent', 'rent_rate_per_member'])
            messages.success(request, f"Room {room.room_number}: Rent updated ({room.get_rent_type_display()}).")
            return redirect(request.path)

        # 2. Handle Modify Room Modal (Target Advance & Maintenance)
        if 'modify_room' in request.POST:
            room.target_advance_amount = Decimal(str(request.POST.get('target_advance_amount', '0.00') or 0))
            maint_type = request.POST.get('maintenance_type', 'PER_ROOM')
            room.maintenance_type = maint_type
            if maint_type == 'PER_MEMBER':
                room.maintenance_rate_per_member = Decimal(str(request.POST.get('maintenance_rate_per_member', '0.00') or 0))
            else:
                room.maintenance_charges = Decimal(str(request.POST.get('maintenance_charges', '0.00') or 0))
            room.save(update_fields=[
                'target_advance_amount',
                'maintenance_type',
                'maintenance_charges',
                'maintenance_rate_per_member'
            ])
            messages.success(request, f"Room {room.room_number}: Details updated.")
            return redirect(request.path)

    # Single optimized query for all buildings & rooms
    all_rooms = list(Room.objects.select_related('building').all().order_by('room_number'))
    buildings = list(Building.objects.all())

    building_data = [
        {
            'building': b,
            'rooms': [r for r in all_rooms if r.building_id == b.id]
        }
        for b in buildings
    ]

    return render(request, 'Smartnestapp/room.html', {
        'building_data': building_data,
        'buildings': buildings,
        'rooms': all_rooms,
        'all_rooms': all_rooms,
    })


# ==============================================================================
# 3. Rent Details View (Billing & Payment Collections)
# ==============================================================================
def get_tenant_member_count(tenant):
    """Counts only the comma-separated members listed in members_names."""
    if not tenant:
        return 0
    members_str = getattr(tenant, 'members_names', '') or ''
    if members_str.strip():
        members_list = [m.strip() for m in members_str.replace('\n', ',').split(',') if m.strip()]
        return len(members_list)
    return 0
# Smartnestapp/views.py
def extract_numeric_by_keywords(instance, keywords):
    """
    Scans all database fields on a model instance for matching keywords
    and returns the first positive Decimal value found.
    """
    if not instance:
        return Decimal('0.00')
    
    for field in instance._meta.fields:
        fname = field.name.lower()
        if any(kw in fname for kw in keywords):
            val = getattr(instance, field.name, None)
            if val is not None and str(val).strip() != '':
                try:
                    d = Decimal(str(val))
                    if d > Decimal('0.00'):
                        return d
                except Exception:
                    pass
    return Decimal('0.00')

def get_room_rent_value(room):
    """
    Computes monthly rent based on Room Details:
    - If PER_MEMBER: count from members_names * rent_rate_per_member
    - If PER_ROOM: monthly_rent
    """
    if not room:
        return Decimal('0.00')

    r_type = str(getattr(room, 'rent_type', 'PER_ROOM') or 'PER_ROOM').strip().upper()
    if r_type == 'PER_MEMBER':
        rate = Decimal(str(getattr(room, 'rent_rate_per_member', '0.00') or 0))
        tenant = getattr(room, 'current_tenant', None)
        persons = get_tenant_member_count(tenant)
        return rate * Decimal(str(persons))

    return Decimal(str(getattr(room, 'monthly_rent', '0.00') or 0))
def get_room_maint_value(room):
    """
    Computes maintenance based on Room Details:
    - If PER_MEMBER: count from members_names * maintenance_rate_per_member
    - If PER_ROOM: maintenance_charges
    """
    if not room:
        return Decimal('0.00')

    m_type = str(getattr(room, 'maintenance_type', 'PER_ROOM') or 'PER_ROOM').strip().upper()
    if m_type == 'PER_MEMBER':
        rate = Decimal(str(getattr(room, 'maintenance_rate_per_member', '0.00') or 0))
        tenant = getattr(room, 'current_tenant', None)
        persons = get_tenant_member_count(tenant)
        return rate * Decimal(str(persons))

    return Decimal(str(getattr(room, 'maintenance_charges', '0.00') or 0))
def recalculate_rent_record(rent_record, room=None, tenant=None, default_elec=Decimal('0.00'), preserve_pending=False):
    """Computes totals and pending balance using dynamic Rent and Maintenance values."""
    if room:
        rent_record.rent_amount = get_room_rent_value(room)
        rent_record.maintenance_charge = get_room_maint_value(room)
    if tenant is not None:
        rent_record.tenant = tenant
    if rent_record.electricity_charge is None:
        rent_record.electricity_charge = default_elec
    if rent_record.last_month_balance is None:
        rent_record.last_month_balance = Decimal('0.00')

    rent_record.total_amount = (
        (rent_record.rent_amount or Decimal('0.00')) +
        (rent_record.maintenance_charge or Decimal('0.00')) +
        (rent_record.electricity_charge or Decimal('0.00')) +
        (rent_record.last_month_balance or Decimal('0.00'))
    )
    rent_record.paid_amount = (
        (rent_record.cash_amount or Decimal('0.00')) +
        (rent_record.upi_amount or Decimal('0.00'))
    )
    if not preserve_pending:
        rent_record.current_balance_due = max(Decimal('0.00'), rent_record.total_amount - rent_record.paid_amount)
    rent_record.save()

def get_room_target_advance(room):
    """Pulls target advance amount directly from Room model."""
    if not room:
        return Decimal('0.00')
    val = getattr(room, 'target_advance_amount', None)
    if val is not None:
        try:
            return Decimal(str(val))
        except (ValueError, TypeError):
            pass
    return Decimal('0.00')

@login_required
def rent_details_view(request):
    today = date.today()
    current_month = today.replace(day=1)

    if request.method == 'POST':
        rent_record_id = request.POST.get('rent_record_id')
        rent_record = get_object_or_404(RentDetail, id=rent_record_id)

        # 1. Update Rent Payment (Cash & UPI Split)
        if 'update_rent_payment' in request.POST:
            cash_paid = Decimal(str(request.POST.get('cash_amount', '0.00') or 0))
            upi_paid = Decimal(str(request.POST.get('upi_amount', '0.00') or 0))
            collection_date_str = request.POST.get('collection_date')
            collection_date = date.fromisoformat(collection_date_str) if collection_date_str else today

            rent_record.cash_amount = cash_paid
            rent_record.upi_amount = upi_paid
            rent_record.collection_date = collection_date
            recalculate_rent_record(rent_record)
            messages.success(request, f"Room {rent_record.room.room_number}: Received Cash ₹{cash_paid}, UPI ₹{upi_paid}")
            return redirect('rent_details')

        # 2. Update Electricity
        if 'update_electricity' in request.POST:
            new_eb = Decimal(str(request.POST.get('electricity_charge', '0.00') or 0))
            rent_record.electricity_charge = new_eb
            recalculate_rent_record(rent_record)
            messages.success(request, f"Updated Room {rent_record.room.room_number} Electricity to ₹{new_eb}")
            return redirect('rent_details')

        # 3. Set Electricity to Nil (0)
        if 'nil_electricity' in request.POST:
            rent_record.electricity_charge = Decimal('0.00')
            recalculate_rent_record(rent_record)
            messages.success(request, f"Room {rent_record.room.room_number} Electricity set to Nil (₹0.00)")
            return redirect('rent_details')

        # 4. Update Last Month Balance
        if 'update_last_month_balance' in request.POST:
            new_lmb = Decimal(str(request.POST.get('last_month_balance', '0.00') or 0))
            rent_record.last_month_balance = new_lmb
            recalculate_rent_record(rent_record)
            messages.success(request, f"Updated Room {rent_record.room.room_number} Last Month Balance to ₹{new_lmb}")
            return redirect('rent_details')

        # 5. Set Last Month Balance to Nil (0)
        if 'nil_last_month_balance' in request.POST:
            rent_record.last_month_balance = Decimal('0.00')
            recalculate_rent_record(rent_record)
            messages.success(request, f"Room {rent_record.room.room_number} Last Month Balance set to Nil (₹0.00)")
            return redirect('rent_details')

        # 6. Update Pending Balance Manually
        if 'update_pending_balance' in request.POST:
            new_pending = Decimal(str(request.POST.get('current_balance_due', '0.00') or 0))
            rent_record.current_balance_due = new_pending
            rent_record.save()
            messages.success(request, f"Updated Room {rent_record.room.room_number} Pending Balance to ₹{new_pending}")
            return redirect('rent_details')

        # 7. Push Pending Balance into Last Month Balance (keeping Rent, Maint & EB unchanged)
        if 'push_pending_to_lmb' in request.POST:
            pending_amt = rent_record.current_balance_due or Decimal('0.00')
            if pending_amt > Decimal('0.00'):
                rent_record.last_month_balance = (rent_record.last_month_balance or Decimal('0.00')) + pending_amt
                rent_record.current_balance_due = Decimal('0.00')
                rent_record.total_amount = (
                    (rent_record.rent_amount or Decimal('0.00')) +
                    (rent_record.maintenance_charge or Decimal('0.00')) +
                    (rent_record.electricity_charge or Decimal('0.00')) +
                    rent_record.last_month_balance
                )
                rent_record.save()
                messages.success(request, f"Room {rent_record.room.room_number}: Pushed ₹{pending_amt} to Last Month Balance.")
            return redirect('rent_details')

    # Gather All Rooms Data
    all_rooms = Room.objects.select_related('building').prefetch_related('electricity_readings', 'rent_records').all()
    tenant_rooms_map = {}
    room_data_cache = {}

    for r in all_rooms:
        tenant = getattr(r, 'current_tenant', None)
        latest_elec = r.electricity_readings.filter(month_year=current_month).first()
        elec_cost = latest_elec.total_electricity_amount if latest_elec else Decimal('0.00')
        maint_cost = get_room_maint_value(r)

        rent_record, created = RentDetail.objects.get_or_create(
            room=r,
            month=current_month,
            defaults={
                'tenant': tenant,
                'rent_amount': getattr(r, 'monthly_rent', Decimal('0.00')),
                'maintenance_charge': maint_cost,
                'electricity_charge': elec_cost,
                'last_month_balance': Decimal('0.00'),
            }
        )

        # Preserve manually edited or pushed pending balance if already shifted
        is_shifted_or_manual = (
            not created and
            (rent_record.last_month_balance or Decimal('0.00')) > Decimal('0.00') and
            (rent_record.current_balance_due or Decimal('0.00')) == Decimal('0.00') and
            (rent_record.paid_amount or Decimal('0.00')) < (rent_record.total_amount or Decimal('0.00'))
        )
        recalculate_rent_record(
            rent_record,
            room=r,
            tenant=tenant,
            default_elec=elec_cost,
            preserve_pending=is_shifted_or_manual
        )

        t_name = getattr(tenant, 'primary_name', None) or getattr(tenant, 'name', '')
        t_phone = getattr(tenant, 'phone_number', None) or getattr(tenant, 'phone', '')

        coll_date = rent_record.collection_date or today
        coll_date_str = coll_date.strftime("%d/%m/%Y")
        bill_date_str = current_month.strftime("%d/%m/%Y")

        info = {
            'room': r,
            'tenant': tenant,
            'tenant_name': t_name,
            'tenant_phone': t_phone,
            'bill_date': bill_date_str,
            'collection_date_str': coll_date_str,
            'rent': rent_record.rent_amount,
            'maintenance': rent_record.maintenance_charge,
            'electricity': rent_record.electricity_charge,
            'last_month_balance': rent_record.last_month_balance,
            'total': rent_record.total_amount,
            'collected': rent_record.paid_amount,
            'cash_amount': rent_record.cash_amount,
            'upi_amount': rent_record.upi_amount,
            'pending': rent_record.current_balance_due,
            'payment_method': rent_record.payment_method,
            'rent_record': rent_record,
        }
        room_data_cache[r.id] = info

        if t_name and t_phone:
            key = (str(t_name).strip().lower(), str(t_phone).strip())
            tenant_rooms_map.setdefault(key, []).append(info)

    building_data = []
    all_modal_records = []
    for b in Building.objects.all():
        rooms_info = []
        for r in [rm for rm in all_rooms if rm.building_id == b.id]:
            info = room_data_cache.get(r.id)
            if not info:
                continue
            t_name = info['tenant_name']
            t_phone = info['tenant_phone']
            is_multi = False
            if t_name and t_phone:
                t_key = (str(t_name).strip().lower(), str(t_phone).strip())
                is_multi = len(tenant_rooms_map.get(t_key, [])) > 1

            info['is_multi_room'] = is_multi
            rooms_info.append(info)
            all_modal_records.append(info)

        building_data.append({
            'building': b,
            'rooms_info': rooms_info
        })

    return render(request, 'Smartnestapp/rent_details.html', {
        'building_data': building_data,
        'all_modal_records': all_modal_records,
        'billing_month': current_month,
        'today': today
    })

@login_required
def set_eb_nil(request, pk):
    if request.method == "POST":
        rent_record = get_object_or_404(RentDetail, pk=pk)
        rent_record.electricity_charge = Decimal('0.00')
        rent_record.save()
        return JsonResponse({"success": True})
    return JsonResponse({"success": False, "error": "Invalid method"}, status=400)
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
    # 1. Fetch distinct months formatted as dates
    # Gets all distinct months present in the readings
    dates = (
        ElectricityReading.objects.dates('month_year', 'month', order='DESC')
    )
    # Build list of strings like "Oct 2026", "Nov 2026"
    months = [d.strftime('%b %Y') for d in dates]

    # 2. Handle deleting all records for the selected month
    if request.method == 'POST' and 'delete_month' in request.POST:
        target_month_str = request.POST.get('target_month')  # e.g., "Oct 2026"
        if target_month_str:
            try:
                from datetime import datetime
                parsed_date = datetime.strptime(target_month_str, '%b %Y')
                deleted_count, _ = ElectricityReading.objects.filter(
                    month_year__year=parsed_date.year,
                    month_year__month=parsed_date.month
                ).delete()
                messages.success(request, f"Successfully removed all {deleted_count} readings for {target_month_str}!")
            except Exception as e:
                messages.error(request, f"Error deleting records: {e}")
            return redirect('electricity')

    # 3. Check if user selected a month in the dropdown filter
    selected_month = request.GET.get('month', '')
    readings_qs = ElectricityReading.objects.all().order_by('-month_year')

    if selected_month:
        try:
            from datetime import datetime
            parsed_date = datetime.strptime(selected_month, '%b %Y')
            readings_qs = readings_qs.filter(
                month_year__year=parsed_date.year,
                month_year__month=parsed_date.month
            )
        except Exception:
            pass

    # 4. Prefetch filtered readings into room.filtered_readings
    buildings = Building.objects.prefetch_related(
        Prefetch(
            'rooms__electricity_readings',
            queryset=readings_qs,
            to_attr='filtered_readings'
        )
    ).all()

    return render(request, 'Smartnestapp/electricity.html', {
        'buildings': buildings,
        'months': months,
        'selected_month': selected_month
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
def set_nil_last_month_balance_api(request, rent_record_id):
    """Sets last month balance to 0.00 and recalculates total."""
    rent_record = get_object_or_404(RentDetail, id=rent_record_id)
    rent_record.last_month_balance = Decimal('0.00')
    rent_record.save()
    return JsonResponse({'success': True, 'last_month_balance': '0.00'})

@login_required
def shift_pending_to_lmb_api(request, rent_record_id):
    """
    Push action: Shifts the pending balance into last month balance,
    adjusting payments/total so pending clears.
    """
    rent_record = get_object_or_404(RentDetail, id=rent_record_id)
    pending_to_shift = rent_record.current_balance_due or Decimal('0.00')
    
    # Add pending to last month balance
    rent_record.last_month_balance = (rent_record.last_month_balance or Decimal('0.00')) + pending_to_shift
    rent_record.current_balance_due = Decimal('0.00')
    rent_record.save()
    return JsonResponse({'success': True})
@login_required
def advance_details_view(request):
    today = date.today()

    if request.method == 'POST' and 'update_advance' in request.POST:
        adv_id = request.POST.get('advance_id')
        cash_paid = Decimal(str(request.POST.get('cash_amount', '0.00') or 0))
        upi_paid = Decimal(str(request.POST.get('upi_amount', '0.00') or 0))
        paid_date_str = request.POST.get('paid_date')
        try:
            paid_date = date.fromisoformat(paid_date_str) if paid_date_str else today
        except ValueError:
            paid_date = today

        adv = get_object_or_404(AdvanceDetail, id=adv_id)
        adv.agreement_advance = get_room_target_advance(adv.room)
        adv.cash_amount = cash_paid
        adv.upi_amount = upi_paid
        adv.paid_date = paid_date
        adv.save()
        messages.success(request, f"Updated advance for Room {adv.room.room_number}: Received Cash ₹{cash_paid}, UPI ₹{upi_paid}")
        return redirect('advance_details')

    all_rooms = Room.objects.select_related('building').all()
    for rm in all_rooms:
        target_adv = get_room_target_advance(rm)
        adv_obj, _ = AdvanceDetail.objects.get_or_create(
            room=rm,
            defaults={
                'tenant': getattr(rm, 'current_tenant', None),
                'agreement_advance': target_adv,
            }
        )
        adv_obj.agreement_advance = target_adv
        adv_obj.tenant = getattr(rm, 'current_tenant', None)
        tot_paid = (adv_obj.cash_amount or Decimal('0.00')) + (adv_obj.upi_amount or Decimal('0.00'))
        adv_obj.amount_paid = tot_paid
        adv_obj.pending_advance = max(Decimal('0.00'), target_adv - tot_paid)
        adv_obj.save()

    advances = AdvanceDetail.objects.select_related('room', 'tenant', 'room__building').all().order_by('room__room_number')
    return render(request, 'Smartnestapp/advance_details.html', {'advances': advances, 'today': today})


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
def pwa_manifest(request):
    manifest_data = {
        "name": "SmartNest",
        "short_name": "SmartNest",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#212529",
        "theme_color": "#212529",
        "orientation": "portrait",
        "icons": [
            {
                "src": "https://cdn-icons-png.flaticon.com/512/609/609803.png",
                "sizes": "192x192",
                "type": "image/png",
                "purpose": "any maskable"
            },
            {
                "src": "https://cdn-icons-png.flaticon.com/512/609/609803.png",
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "any maskable"
            }
        ]
    }
    return JsonResponse(manifest_data, content_type="application/manifest+json")

def pwa_sw(request):
    js_content = (
        "self.addEventListener('install', (e) => self.skipWaiting());\n"
        "self.addEventListener('activate', (e) => clients.claim());\n"
        "self.addEventListener('fetch', (e) => {\n"
        "  e.respondWith(fetch(e.request).catch(() => caches.match(e.request)));\n"
        "});"
    )
    return HttpResponse(js_content, content_type="application/javascript")

@login_required
def expense_details_view(request):
    close_old_connections()
    today = date.today()
    current_month = today.replace(day=1)

    if request.method == 'POST':
        all_expenses = MonthlyExpense.objects.all()
        for exp in all_expenses:
            is_checked = f"active_{exp.id}" in request.POST
            raw_amt = request.POST.get(f"amount_{exp.id}", "").strip()

            if hasattr(exp, 'is_active'):
                exp.is_active = is_checked
            elif hasattr(exp, 'active'):
                exp.active = is_checked

            if is_checked and raw_amt:
                try:
                    exp.amount = Decimal(raw_amt)
                except Exception:
                    exp.amount = Decimal('0.00')
            elif not is_checked:
                exp.amount = Decimal('0.00')
            exp.save()

        messages.success(request, "Expenses updated successfully.")
        return redirect(request.path)

    expenses = MonthlyExpense.objects.all().order_by('id')
    for exp in expenses:
        exp.checked_state = getattr(exp, 'is_active', getattr(exp, 'active', False))
        exp.label_text = (
            getattr(exp, 'description', None)
            or getattr(exp, 'expense_description', None)
            or getattr(exp, 'name', None)
            or str(exp)
        )

    total_expense = sum((e.amount or Decimal('0.00')) for e in expenses if e.checked_state)

    return render(request, 'Smartnestapp/expenses.html', {
        'expenses': expenses,
        'total_expense': total_expense,
        'billing_month': current_month,
    })
@login_required
def combined_bill_view(request, tenant_id):
    today = date.today()
    current_month = today.replace(day=1)
    tenant = get_object_or_404(Tenant, id=tenant_id)
    
    t_phone = getattr(tenant, 'phone_number', '') or getattr(tenant, 'phone', '')
    t_name = getattr(tenant, 'primary_name', '') or getattr(tenant, 'name', '')

    all_tenant_ids = []
    if t_phone:
        all_tenant_ids = list(Tenant.objects.filter(phone_number=t_phone).values_list('id', flat=True))
    if not all_tenant_ids and t_name:
        all_tenant_ids = list(Tenant.objects.filter(primary_name=t_name).values_list('id', flat=True))
    if not all_tenant_ids:
        all_tenant_ids = [tenant.id]

    rent_records = RentDetail.objects.filter(
        tenant_id__in=all_tenant_ids,
        month=current_month
    ).select_related('room', 'room__building').order_by('room__room_number')

    if not rent_records.exists():
        rent_records = RentDetail.objects.filter(
            tenant_id__in=all_tenant_ids
        ).select_related('room', 'room__building').order_by('room__room_number')

    total_rent = Decimal('0.00')
    total_maintenance = Decimal('0.00')
    total_electricity = Decimal('0.00')
    total_lmb = Decimal('0.00')
    grand_total = Decimal('0.00')
    total_paid = Decimal('0.00')
    total_upi = Decimal('0.00')
    total_cash = Decimal('0.00')
    total_pending = Decimal('0.00')
    latest_coll_date = None

    bill_date_str = current_month.strftime("%d/%m/%Y")
    whatsapp_lines = [
        f"Tenant Name: {t_name}",
        f"Date: {bill_date_str}"
    ]

    for r in rent_records:
        is_shifted = (
            (r.last_month_balance or Decimal('0.00')) > Decimal('0.00') and
            (r.current_balance_due or Decimal('0.00')) == Decimal('0.00') and
            (r.paid_amount or Decimal('0.00')) < (r.total_amount or Decimal('0.00'))
        )
        recalculate_rent_record(r, room=r.room, preserve_pending=is_shifted)

        if r.collection_date and (not latest_coll_date or r.collection_date > latest_coll_date):
            latest_coll_date = r.collection_date

        r_rent = r.rent_amount or Decimal('0.00')
        r_maint = r.maintenance_charge or Decimal('0.00')
        r_eb = r.electricity_charge or Decimal('0.00')
        r_lmb = r.last_month_balance or Decimal('0.00')
        r_tot = r.total_amount or Decimal('0.00')
        r_pend = r.current_balance_due or Decimal('0.00')

        total_rent += r_rent
        total_maintenance += r_maint
        total_electricity += r_eb
        total_lmb += r_lmb
        grand_total += r_tot
        total_paid += (r.paid_amount or Decimal('0.00'))
        total_upi += (r.upi_amount or Decimal('0.00'))
        total_cash += (r.cash_amount or Decimal('0.00'))
        total_pending += r_pend

        whatsapp_lines.append(f"Room No: {r.room.room_number}")
        whatsapp_lines.append(f"{r.room.room_number} Rent: ₹{r_rent}")
        whatsapp_lines.append(f"Maintenance: ₹{r_maint}")
        whatsapp_lines.append(f"Electricity Charges: ₹{r_eb}")
        whatsapp_lines.append(f"Last Month Balance: ₹{r_lmb}")
        whatsapp_lines.append(f"Subtotal: ₹{r_tot}")

    coll_date_str = latest_coll_date.strftime("%d/%m/%Y") if latest_coll_date else "-"

    whatsapp_lines.append(f"Total Bill: ₹{grand_total}")
    whatsapp_lines.append(f"Total Received: ₹{total_paid}")
    whatsapp_lines.append(f"Pending Balance: ₹{total_pending}")
    whatsapp_lines.append(f"Received via UPI: ₹{total_upi}")
    whatsapp_lines.append(f"Received via Cash: ₹{total_cash}")
    whatsapp_lines.append(f"Collection Date: {coll_date_str}")
    

    whatsapp_text_encoded = urllib.parse.quote("\n".join(whatsapp_lines))

    context = {
        'tenant': tenant,
        'rent_records': rent_records,
        'billing_month': current_month,
        'bill_date': bill_date_str,
        'collection_date_str': coll_date_str,
        'total_rent': total_rent,
        'total_maintenance': total_maintenance,
        'total_electricity': total_electricity,
        'total_lmb': total_lmb,
        'grand_total': grand_total,
        'total_paid': total_paid,
        'total_upi': total_upi,
        'total_cash': total_cash,
        'total_pending': total_pending,
        'whatsapp_text_encoded': whatsapp_text_encoded,
    }
    return render(request, 'Smartnestapp/combined_bill.html', context)
@login_required
def room_details_view(request):
    close_old_connections()

    if request.method == 'POST':
        room_id = request.POST.get('room_id')
        room = get_object_or_404(Room, id=room_id)

        # 1. Handle Inline Rent Edit Modal (1. Per Room vs 2. Per Member)
        if 'update_room_rent' in request.POST:
            rent_type = request.POST.get('rent_type', 'PER_ROOM')
            room.rent_type = rent_type
            if rent_type == 'PER_MEMBER':
                room.rent_rate_per_member = Decimal(str(request.POST.get('rent_rate_per_member', '0.00') or 0))
            else:
                room.monthly_rent = Decimal(str(request.POST.get('monthly_rent', '0.00') or 0))
            room.save(update_fields=['rent_type', 'monthly_rent', 'rent_rate_per_member'])
            messages.success(request, f"Room {room.room_number}: Rent updated.")
            return redirect(request.path)

        # 2. Handle Modify Room Modal (Target Advance & Maintenance)
        if 'modify_room' in request.POST:
            room.target_advance_amount = Decimal(str(request.POST.get('target_advance_amount', '0.00') or 0))
            maint_type = request.POST.get('maintenance_type', 'PER_ROOM')
            room.maintenance_type = maint_type
            if maint_type == 'PER_MEMBER':
                room.maintenance_rate_per_member = Decimal(str(request.POST.get('maintenance_rate_per_member', '0.00') or 0))
            else:
                room.maintenance_charges = Decimal(str(request.POST.get('maintenance_charges', '0.00') or 0))
            room.save(update_fields=[
                'target_advance_amount',
                'maintenance_type',
                'maintenance_charges',
                'maintenance_rate_per_member'
            ])
            messages.success(request, f"Room {room.room_number}: Details updated.")
            return redirect(request.path)

    all_rooms = list(Room.objects.select_related('building').all().order_by('room_number'))
    buildings = list(Building.objects.all())

    building_data = [
        {
            'building': b,
            'rooms': [r for r in all_rooms if r.building_id == b.id]
        }
        for b in buildings
    ]

    return render(request, 'Smartnestapp/room.html', {
        'building_data': building_data,
        'buildings': buildings,
        'rooms': all_rooms,
        'all_rooms': all_rooms,
    })