from datetime import datetime
from decimal import Decimal
from decimal import InvalidOperation
import re
import secrets
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.models import User
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db.models import Count, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from allauth.socialaccount.models import SocialApp
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import ContactInquiry, CustomerProfile, OTPChallenge, Reservation, Room


def normalize_indian_phone(value):
    digits = re.sub(r'\D', '', value or '')
    if digits.startswith('91') and len(digits) == 12:
        digits = digits[2:]
    if len(digits) != 10 or digits[0] not in '6789':
        return None
    return f'+91{digits}'


def _issue_otp(identifier, purpose):
    code = f'{secrets.randbelow(1000000):06d}'
    OTPChallenge.objects.filter(identifier=identifier, purpose=purpose).delete()
    OTPChallenge.objects.create(
        identifier=identifier,
        purpose=purpose,
        code_hash=make_password(code),
        expires_at=timezone.now() + timedelta(seconds=settings.OTP_TIMEOUT_SECONDS),
    )
    print(f'OTP for {identifier}: {code}')
    if settings.OTP_DEBUG_SHOW_CODE:
        return code
    return code


def customer_login(request):
    if request.user.is_authenticated and not request.user.is_staff:
        return redirect('home')
    if request.method == 'POST':
        phone = normalize_indian_phone(request.POST.get('phone'))
        if not phone:
                return render(request, 'bookings/customer_auth.html', {'mode': 'login', 'error': 'Enter a valid Indian mobile number.'})
        profile = CustomerProfile.objects.filter(phone_number=phone, phone_verified=True).select_related('user').first()
        if not profile:
                return render(request, 'bookings/customer_auth.html', {'mode': 'login', 'error': 'No verified account exists for this number.'})
        code = _issue_otp(phone, 'login')
        request.session['otp_identifier'] = phone
        request.session['otp_purpose'] = 'login'
        request.session['dev_otp'] = code
        return redirect('customer-verify-otp')
    return render(request, 'bookings/customer_auth.html', {'mode': 'login'})


def customer_register(request):
    if request.user.is_authenticated and not request.user.is_staff:
        return redirect('home')
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        email = request.POST.get('email', '').strip().lower()
        phone = normalize_indian_phone(request.POST.get('phone'))
        if not name or not email or not phone:
                return render(request, 'bookings/customer_auth.html', {'mode': 'register', 'error': 'Name, email, and a valid Indian mobile number are required.'})
        if CustomerProfile.objects.filter(phone_number=phone).exists() or User.objects.filter(email=email).exists():
                return render(request, 'bookings/customer_auth.html', {'mode': 'register', 'error': 'An account already exists for this email or mobile number.'})
        request.session['pending_customer'] = {'name': name, 'email': email, 'phone': phone}
        code = _issue_otp(phone, 'register')
        request.session['otp_identifier'] = phone
        request.session['otp_purpose'] = 'register'
        request.session['dev_otp'] = code
        return redirect('customer-verify-otp')
    return render(request, 'bookings/customer_auth.html', {'mode': 'register'})


def customer_verify_otp(request):
    identifier = request.session.get('otp_identifier')
    purpose = request.session.get('otp_purpose')
    if not identifier or not purpose:
        return redirect('customer-login')
    challenge = OTPChallenge.objects.filter(identifier=identifier, purpose=purpose).first()
    if request.method == 'POST':
        code = request.POST.get('otp', '').strip()
        if not challenge or challenge.expires_at <= timezone.now() or challenge.attempts >= settings.OTP_MAX_ATTEMPTS:
            return render(request, 'bookings/customer_verify_otp.html', {'error': 'This OTP has expired. Request a new one.'})
        challenge.attempts += 1
        challenge.save(update_fields=['attempts'])
        if not check_password(code, challenge.code_hash):
            return render(request, 'bookings/customer_verify_otp.html', {'error': 'Incorrect OTP. Please try again.'})
        if purpose == 'register':
            pending = request.session.get('pending_customer', {})
            user = User.objects.create_user(username=identifier, email=pending['email'], first_name=pending['name'])
            profile, _ = CustomerProfile.objects.get_or_create(user=user)
            profile.phone_number = identifier
            profile.phone_verified = True
            profile.save(update_fields=['phone_number', 'phone_verified'])
            request.session.pop('pending_customer', None)
        else:
            user = CustomerProfile.objects.get(phone_number=identifier).user
        login(request, user, backend='django.contrib.auth.backends.ModelBackend')
        request.session.pop('otp_identifier', None)
        request.session.pop('otp_purpose', None)
        request.session.pop('dev_otp', None)
        challenge.delete()
        return redirect('home')
    return render(request, 'bookings/customer_verify_otp.html', {'identifier': identifier, 'show_dev_code': settings.OTP_DEBUG_SHOW_CODE, 'dev_code': request.session.get('dev_otp')})


def customer_logout(request):
    logout(request)
    return redirect('home')


def google_login(request):
    if not SocialApp.objects.filter(provider='google').exists():
            return render(request, 'bookings/customer_auth.html', {
            'mode': 'login',
                'error': 'Google sign-in is not configured yet. Use mobile OTP or ask the site administrator to add OAuth credentials.',
        })
    return redirect('/accounts/google/login/')


def staff_required(view):
    return login_required(user_passes_test(lambda user: user.is_staff)(view))


def admin_login(request):
    if request.user.is_authenticated and request.user.is_staff:
        return redirect('admin-dashboard')

    if request.method == 'POST':
        user = authenticate(
            request,
            username=request.POST.get('username', '').strip(),
            password=request.POST.get('password', ''),
        )
        if user is not None and user.is_staff:
            login(request, user)
            return redirect('admin-dashboard')
        messages.error(request, 'The username or password was not recognised.')

    return render(request, 'bookings/admin_login.html')


@staff_required
def admin_dashboard(request):
    today = timezone.localdate()
    reservations = Reservation.objects.select_related('room')
    context = {
        'active_page': 'overview',
        'today': today,
        'total_rooms': Room.objects.count(),
        'available_rooms': Room.objects.filter(is_available=True).count(),
        'pending_count': reservations.filter(status='pending').count(),
        'confirmed_count': reservations.filter(status='confirmed').count(),
        'revenue': reservations.filter(status__in=['confirmed', 'pending']).aggregate(total=Sum('total_price'))['total'] or Decimal('0.00'),
        'upcoming_reservations': reservations.filter(check_out__gte=today).order_by('check_in')[:8],
    }
    return render(request, 'bookings/admin_dashboard.html', context)


@staff_required
def admin_reservations(request):
    status = request.GET.get('status', '')
    reservations = Reservation.objects.select_related('room').all()
    if status in {'confirmed', 'pending', 'cancelled'}:
        reservations = reservations.filter(status=status)
    return render(request, 'bookings/admin_reservations.html', {
        'active_page': 'reservations',
        'reservations': reservations,
        'selected_status': status,
    })


@staff_required
def admin_rooms(request):
    rooms = Room.objects.annotate(reservation_count=Count('reservations')).all()
    return render(request, 'bookings/admin_rooms.html', {
        'active_page': 'rooms',
        'rooms': rooms,
    })


def _room_form_data(request, room=None):
    name = request.POST.get('name', '').strip()
    room_number = request.POST.get('room_number', '').strip()
    room_type = request.POST.get('room_type', 'deluxe')
    capacity_value = request.POST.get('capacity', '').strip()
    price_value = request.POST.get('base_price_per_night', '').strip()
    is_available = request.POST.get('is_available') == 'on'

    if not name or not room_number or not capacity_value or not price_value:
        return None, 'Name, room number, capacity, and nightly price are required.'
    if room_type not in dict(Room.ROOM_TYPES):
        return None, 'Choose a valid room type.'

    try:
        capacity = int(capacity_value)
        price = Decimal(price_value)
    except (InvalidOperation, ValueError):
        return None, 'Capacity must be a whole number and price must be a valid amount.'

    if capacity < 1 or price < 0:
        return None, 'Capacity must be at least 1 and price cannot be negative.'

    room = room or Room()
    room.name = name
    room.room_number = room_number
    room.room_type = room_type
    room.capacity = capacity
    room.base_price_per_night = price
    room.is_available = is_available
    try:
        room.full_clean()
    except ValidationError as error:
        return None, '; '.join(error.messages)
    return room, None


@staff_required
def admin_room_create(request):
    room = Room(is_available=True)
    if request.method == 'POST':
        room, error = _room_form_data(request, room)
        if error:
            return render(request, 'bookings/admin_room_form.html', {
                'active_page': 'rooms',
                'room': room,
                'form_error': error,
                'is_create': True,
            })
        room.save()
        messages.success(request, f'{room.name} was added to the room catalogue.')
        return redirect('admin-rooms')
    return render(request, 'bookings/admin_room_form.html', {
        'active_page': 'rooms',
        'room': room,
        'is_create': True,
    })


@staff_required
def admin_room_edit(request, room_id):
    room = get_object_or_404(Room, id=room_id)
    if request.method == 'POST':
        room, error = _room_form_data(request, room)
        if error:
            return render(request, 'bookings/admin_room_form.html', {
                'active_page': 'rooms',
                'room': room,
                'form_error': error,
                'is_create': False,
            })
        room.save()
        messages.success(request, f'{room.name} was updated.')
        return redirect('admin-rooms')
    return render(request, 'bookings/admin_room_form.html', {
        'active_page': 'rooms',
        'room': room,
        'is_create': False,
    })


@staff_required
def admin_room_toggle_availability(request, room_id):
    room = get_object_or_404(Room, id=room_id)
    if request.method == 'POST':
        room.is_available = not room.is_available
        room.save(update_fields=['is_available', 'updated_at'])
        state = 'available' if room.is_available else 'offline'
        messages.success(request, f'{room.name} is now {state}.')
    return redirect('admin-rooms')


@staff_required
def admin_inquiries(request):
    return render(request, 'bookings/admin_inquiries.html', {
        'active_page': 'inquiries',
        'inquiries': ContactInquiry.objects.all(),
    })


@staff_required
def admin_update_reservation(request, reservation_id):
    if request.method == 'POST':
        reservation = get_object_or_404(Reservation, id=reservation_id)
        status = request.POST.get('status')
        if status in dict(Reservation.STATUS_CHOICES):
            reservation.status = status
            reservation.save()
            messages.success(request, f'Reservation #{reservation.id} updated.')
    return redirect(request.POST.get('next') or 'admin-reservations')


def admin_logout(request):
    logout(request)
    return redirect('admin-login')


def home(request):
    return render(request, 'bookings/home.html', {
        'page_title': 'Hotel Booking Engine',
        'room_types': Room.ROOM_TYPES,
        'today': '2026-09-05',
        'stats': {
            'available_rooms': 12,
            'pending_bookings': 3,
            'occupancy_rate': '78%',
        },
    })


ROOM_DETAILS = {
    'deluxe-king': {
        'name': 'Deluxe King',
        'room_type': 'deluxe',
        'type': 'Deluxe',
        'price': '12,500',
        'capacity': '2 guests',
        'size': '35 sq m',
        'view': 'Sea view',
        'image': 'https://images.unsplash.com/photo-1505693416388-ac5ce068fe85?auto=format&fit=crop&w=1400&q=85',
        'description': 'A calm, light-filled room with warm timber finishes, a private balcony, and room for slow sunrise breakfasts.',
        'features': ['King bed', 'Private balcony', 'Sea-facing outlook', 'Breakfast available'],
    },
    'garden-suite': {
        'name': 'Garden Suite',
        'room_type': 'suite',
        'type': 'Suite',
        'price': '16,800',
        'capacity': '3 guests',
        'size': '46 sq m',
        'view': 'Garden patio',
        'image': 'https://images.unsplash.com/photo-1520250497591-112f2f40a3f4?auto=format&fit=crop&w=1400&q=85',
        'description': 'A generous suite with lounge seating, a garden-facing patio, and quiet corners made for longer stays.',
        'features': ['King bed', 'Separate lounge', 'Garden patio', 'Room service'],
    },
    'presidential-villa': {
        'name': 'Presidential Villa',
        'room_type': 'villa',
        'type': 'Villa',
        'price': '28,000',
        'capacity': '4 guests',
        'size': '78 sq m',
        'view': 'Private pool',
        'image': 'https://images.unsplash.com/photo-1551882547-ff40c63fe5fa?auto=format&fit=crop&w=1400&q=85',
        'description': 'Our signature private villa with elevated finishes, a plunge pool, and attentive service throughout the stay.',
        'features': ['Private plunge pool', 'Two sleeping areas', 'Dedicated host', 'In-villa dining'],
    },
}


def room_detail(request, slug):
    room = ROOM_DETAILS.get(slug)
    if room is None:
        return render(request, 'bookings/room_detail.html', status=404)
    return render(request, 'bookings/room_detail.html', {'room': room, 'slug': slug})


def checkout(request):
    room_id = request.POST.get('room') or request.GET.get('room')
    check_in = request.POST.get('check_in') or request.GET.get('check_in')
    check_out = request.POST.get('check_out') or request.GET.get('check_out')
    guests_value = request.POST.get('guests') or request.GET.get('guests', '1')

    try:
        room = Room.objects.get(id=room_id)
        check_in_date = datetime.strptime(check_in, '%Y-%m-%d').date()
        check_out_date = datetime.strptime(check_out, '%Y-%m-%d').date()
        guests_count = int(guests_value)
    except (Room.DoesNotExist, TypeError, ValueError):
        return render(request, 'bookings/checkout.html', {'error': 'Please return to availability and choose a valid room and stay.'})

    if check_out_date <= check_in_date or guests_count < 1 or guests_count > room.capacity:
        return render(request, 'bookings/checkout.html', {'error': 'The selected dates or guest count are not valid.'})

    nights = (check_out_date - check_in_date).days
    checkout_context = {
        'room': room,
        'check_in': check_in_date,
        'check_out': check_out_date,
        'guests': guests_count,
        'nights': nights,
        'total_price': room.base_price_per_night * nights,
    }

    if request.method == 'POST':
        guest_name = request.POST.get('guest_name', '').strip()
        guest_email = request.POST.get('guest_email', '').strip()
        if not guest_name or not guest_email:
            checkout_context['error'] = 'Please provide your name and email address.'
            return render(request, 'bookings/checkout.html', checkout_context)

        if not room.is_available or Reservation.overlaps_room(room.id, check_in_date, check_out_date):
            checkout_context['error'] = 'This room is no longer available for the selected dates.'
            return render(request, 'bookings/checkout.html', checkout_context)

        reservation = Reservation.objects.create(
            room=room,
                customer_user=request.user if request.user.is_authenticated and not request.user.is_staff else None,
            guest_name=guest_name,
            guest_email=guest_email,
            check_in=check_in_date,
            check_out=check_out_date,
            guests=guests_count,
            status='confirmed',
            total_price=checkout_context['total_price'],
        )
        return render(request, 'bookings/checkout.html', {'reservation': reservation})

    return render(request, 'bookings/checkout.html', checkout_context)


def contact_submit(request):
    if request.method != 'POST':
        return redirect('home')

    name = request.POST.get('name', '').strip()
    email = request.POST.get('email', '').strip()
    subject = request.POST.get('subject', '').strip()
    message = request.POST.get('message', '').strip()

    if not name or not email or not message:
        messages.error(request, 'Please provide your name, email, and query.')
        return redirect('/#contact')

    ContactInquiry.objects.create(name=name, email=email, subject=subject, message=message)
    messages.success(request, 'Thanks for reaching out. Our team will get back to you shortly.')
    return redirect('/#contact')


@api_view(['GET'])
def health_check(request):
    return Response({'status': 'ok'})


@api_view(['GET'])
def booking_list(request):
    reservations = Reservation.objects.select_related('room').all()
    data = [
        {
            'id': reservation.id,
            'room': reservation.room.name,
            'guest_name': reservation.guest_name,
            'guest_email': reservation.guest_email,
            'check_in': reservation.check_in.isoformat(),
            'check_out': reservation.check_out.isoformat(),
            'status': reservation.status,
            'total_price': str(reservation.total_price),
        }
        for reservation in reservations
    ]
    return Response(data)


@api_view(['GET'])
def availability_search(request):
    check_in = request.query_params.get('check_in')
    check_out = request.query_params.get('check_out')
    guests = request.query_params.get('guests', 1)
    room_type = request.query_params.get('room_type', '').strip()

    errors = {}
    if not check_in:
        errors['check_in'] = ['This field is required.']
    if not check_out:
        errors['check_out'] = ['This field is required.']
    try:
        guests = int(guests)
    except (TypeError, ValueError):
        errors['guests'] = ['Guests must be a valid integer.']

    if errors:
        return Response(errors, status=400)

    if room_type and room_type not in dict(Room.ROOM_TYPES):
        return Response({'room_type': ['Room type is not valid.']}, status=400)

    try:
        check_in_date = datetime.strptime(check_in, '%Y-%m-%d').date()
        check_out_date = datetime.strptime(check_out, '%Y-%m-%d').date()
    except ValueError:
        return Response({'dates': ['Dates must use YYYY-MM-DD format.']}, status=400)

    rooms = Room.available_for(check_in_date, check_out_date, guests)
    if room_type:
        rooms = rooms.filter(room_type=room_type)
    response = {
        'check_in': check_in_date.isoformat(),
        'check_out': check_out_date.isoformat(),
        'guests': guests,
        'rooms': [
            {
                'id': room.id,
                'name': room.name,
                'room_number': room.room_number,
                'room_type': room.room_type,
                'room_type_label': room.get_room_type_display(),
                'capacity': room.capacity,
                'base_price_per_night': str(room.base_price_per_night),
            }
            for room in rooms
        ],
    }
    return Response(response)


@api_view(['POST'])
def booking_create(request):
    data = request.data
    room_id = data.get('room')
    guest_name = data.get('guest_name')
    guest_email = data.get('guest_email')
    check_in = data.get('check_in')
    check_out = data.get('check_out')
    guests = data.get('guests', 1)

    errors = {}
    if not room_id:
        errors['room'] = ['Room is required.']
    if not guest_name:
        errors['guest_name'] = ['Guest name is required.']
    if not guest_email:
        errors['guest_email'] = ['Guest email is required.']
    if not check_in:
        errors['check_in'] = ['Check-in date is required.']
    if not check_out:
        errors['check_out'] = ['Check-out date is required.']

    if errors:
        return Response(errors, status=400)

    try:
        room = Room.objects.get(id=room_id)
    except Room.DoesNotExist:
        return Response({'room': ['Room does not exist.']}, status=400)

    try:
        check_in_date = datetime.strptime(check_in, '%Y-%m-%d').date()
        check_out_date = datetime.strptime(check_out, '%Y-%m-%d').date()
    except ValueError:
        return Response({'dates': ['Dates must use YYYY-MM-DD format.']}, status=400)

    try:
        guests_count = int(guests)
    except (TypeError, ValueError):
        return Response({'guests': ['Guests must be a valid integer.']}, status=400)

    if check_out_date <= check_in_date:
        return Response({'check_out': ['Check-out date must be after check-in date.']}, status=400)

    if not room.is_available:
        return Response({'room': ['This room is currently unavailable.']}, status=400)

    if guests_count > room.capacity:
        return Response({'guests': ['Guest count exceeds room capacity.']}, status=400)

    if Reservation.overlaps_room(room.id, check_in_date, check_out_date):
        return Response({'room': ['This room is not available for the selected dates.']}, status=400)

    night_count = (check_out_date - check_in_date).days
    total_price = room.base_price_per_night * Decimal(night_count)

    reservation = Reservation.objects.create(
        room=room,
        customer_user=request.user if request.user.is_authenticated and not request.user.is_staff else None,
        guest_name=guest_name,
        guest_email=guest_email,
        check_in=check_in_date,
        check_out=check_out_date,
        guests=guests_count,
        status='confirmed',
        total_price=total_price,
    )

    return Response(
        {
            'id': reservation.id,
            'room': reservation.room.name,
            'guest_name': reservation.guest_name,
            'guest_email': reservation.guest_email,
            'check_in': reservation.check_in.isoformat(),
            'check_out': reservation.check_out.isoformat(),
            'guests': reservation.guests,
            'status': reservation.status,
            'total_price': str(reservation.total_price),
        },
        status=201,
    )
