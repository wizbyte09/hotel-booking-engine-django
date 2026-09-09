from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import ContactInquiry, Reservation, Room


class BookingHomePageTests(TestCase):
    def test_home_page_returns_success(self):
        response = self.client.get(reverse('home'))
        self.assertEqual(response.status_code, 200)

    def test_room_cards_open_separate_detail_pages(self):
        response = self.client.get(reverse('room-detail', args=['garden-suite']))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Garden Suite')
        self.assertContains(response, 'room_type=suite')

    def test_home_page_contains_availability_form(self):
        response = self.client.get(reverse('home'))
        self.assertContains(response, 'name="check_in"')
        self.assertContains(response, 'name="check_out"')
        self.assertContains(response, 'name="guests"')
        self.assertContains(response, 'name="room_type"')
        self.assertContains(response, 'All room types')
        self.assertContains(response, 'Corporate meetings')
        self.assertContains(response, 'Banquet halls')
        self.assertContains(response, 'Cancellation policy')

    def test_customer_can_submit_a_query(self):
        response = self.client.post(reverse('contact-submit'), {
            'name': 'Alex Guest',
            'email': 'alex@example.com',
            'subject': 'Airport transfer',
            'message': 'Can you arrange a transfer from the airport?',
        })

        self.assertRedirects(response, '/#contact')
        self.assertEqual(ContactInquiry.objects.count(), 1)
        self.assertEqual(ContactInquiry.objects.get().email, 'alex@example.com')


class AdminRoomManagementTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user(username='manager', password='test-pass', is_staff=True)
        self.client.force_login(self.staff)

    def test_staff_can_open_room_management_pages(self):
        self.assertEqual(self.client.get(reverse('admin-rooms')).status_code, 200)
        response = self.client.get(reverse('admin-room-create'))
        self.assertContains(response, 'Room name')
        self.assertContains(response, 'Economy')
        self.assertContains(response, 'Presidential')

    def test_staff_can_add_room_with_price(self):
        response = self.client.post(reverse('admin-room-create'), {
            'name': 'Ocean Suite',
            'room_number': '201',
            'room_type': 'suite',
            'capacity': '3',
            'base_price_per_night': '18500.00',
            'is_available': 'on',
        })

        self.assertRedirects(response, reverse('admin-rooms'))
        room = Room.objects.get(room_number='201')
        self.assertEqual(room.base_price_per_night, 18500)
        self.assertTrue(room.is_available)

    def test_staff_can_edit_price_and_toggle_availability(self):
        room = Room.objects.create(name='Garden Room', room_number='202', base_price_per_night=9000)
        response = self.client.post(reverse('admin-room-edit', args=[room.id]), {
            'name': 'Garden Suite',
            'room_number': '202',
            'room_type': 'suite',
            'capacity': '3',
            'base_price_per_night': '12000.00',
            'is_available': 'on',
        })
        self.assertRedirects(response, reverse('admin-rooms'))
        room.refresh_from_db()
        self.assertEqual(room.name, 'Garden Suite')
        self.assertEqual(room.base_price_per_night, 12000)

        self.client.post(reverse('admin-room-toggle-availability', args=[room.id]))
        room.refresh_from_db()
        self.assertFalse(room.is_available)


class BookingApiTests(TestCase):
    def setUp(self):
        self.room = Room.objects.create(
            name='Deluxe King',
            room_number='101',
            room_type='deluxe',
            capacity=2,
            base_price_per_night=120.00,
        )

    def test_health_endpoint_returns_ok(self):
        response = self.client.get(reverse('health-check'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'ok')

    def test_bookings_endpoint_returns_empty_list(self):
        response = self.client.get(reverse('booking-list'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_availability_search_returns_available_room(self):
        check_in = date.today() + timedelta(days=7)
        check_out = check_in + timedelta(days=3)

        response = self.client.get(
            reverse('availability-search'),
            {'check_in': check_in.isoformat(), 'check_out': check_out.isoformat(), 'guests': 2},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()['rooms']), 1)
        self.assertEqual(response.json()['rooms'][0]['id'], self.room.id)
        self.assertEqual(response.json()['rooms'][0]['room_type_label'], 'Deluxe')

    def test_availability_search_filters_by_room_type(self):
        check_in = date.today() + timedelta(days=7)
        check_out = check_in + timedelta(days=3)

        response = self.client.get(
            reverse('availability-search'),
            {'check_in': check_in.isoformat(), 'check_out': check_out.isoformat(), 'guests': 2, 'room_type': 'suite'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['rooms'], [])

    def test_availability_search_excludes_booked_room(self):
        check_in = date.today() + timedelta(days=14)
        check_out = check_in + timedelta(days=2)
        Reservation.objects.create(
            room=self.room,
            guest_name='Jane Doe',
            guest_email='jane@example.com',
            check_in=check_in,
            check_out=check_out,
            status='confirmed',
            total_price=240.00,
        )

        response = self.client.get(
            reverse('availability-search'),
            {'check_in': check_in.isoformat(), 'check_out': check_out.isoformat(), 'guests': 2},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['rooms'], [])

    def test_booking_creation_success(self):
        check_in = date.today() + timedelta(days=20)
        check_out = check_in + timedelta(days=2)

        response = self.client.post(
            reverse('booking-create'),
            {
                'room': self.room.id,
                'guest_name': 'John Smith',
                'guest_email': 'john@example.com',
                'check_in': check_in.isoformat(),
                'check_out': check_out.isoformat(),
                'guests': 2,
            },
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(Reservation.objects.count(), 1)
        self.assertEqual(response.json()['guest_name'], 'John Smith')

    def test_checkout_page_creates_reservation(self):
        check_in = date.today() + timedelta(days=40)
        check_out = check_in + timedelta(days=2)
        response = self.client.post(reverse('checkout'), {
            'room': self.room.id,
            'check_in': check_in.isoformat(),
            'check_out': check_out.isoformat(),
            'guests': 2,
            'guest_name': 'Checkout Guest',
            'guest_email': 'checkout@example.com',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Reservation confirmed')
        self.assertEqual(Reservation.objects.get().guest_name, 'Checkout Guest')

    def test_booking_creation_rejects_overlapping_reservation(self):
        check_in = date.today() + timedelta(days=30)
        check_out = check_in + timedelta(days=3)
        Reservation.objects.create(
            room=self.room,
            guest_name='Booked Guest',
            guest_email='booked@example.com',
            check_in=check_in,
            check_out=check_out,
            status='confirmed',
            total_price=360.00,
        )

        response = self.client.post(
            reverse('booking-create'),
            {
                'room': self.room.id,
                'guest_name': 'New Guest',
                'guest_email': 'new@example.com',
                'check_in': check_in.isoformat(),
                'check_out': (check_in + timedelta(days=1)).isoformat(),
                'guests': 2,
            },
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn('room', response.json())
