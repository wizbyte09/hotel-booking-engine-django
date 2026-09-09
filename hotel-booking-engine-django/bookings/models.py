from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver


class Room(models.Model):
    ROOM_TYPES = [
        ('economy', 'Economy'),
        ('standard', 'Standard'),
        ('deluxe', 'Deluxe'),
        ('executive', 'Executive'),
        ('premium', 'Premium'),
        ('suite', 'Suite'),
        ('family', 'Family'),
        ('villa', 'Villa'),
        ('presidential', 'Presidential'),
    ]

    name = models.CharField(max_length=120)
    room_number = models.CharField(max_length=20, unique=True)
    room_type = models.CharField(max_length=20, choices=ROOM_TYPES, default='deluxe')
    capacity = models.PositiveIntegerField(default=2)
    base_price_per_night = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    is_available = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['room_number']

    def __str__(self):
        return f'{self.name} ({self.room_number})'

    @classmethod
    def available_for(cls, check_in, check_out, guests=1):
        if check_in >= check_out:
            return cls.objects.none()

        overlapping = Reservation.objects.filter(
            status__in=['confirmed', 'pending'],
            check_in__lt=check_out,
            check_out__gt=check_in,
        ).values_list('room_id', flat=True)

        queryset = cls.objects.filter(is_available=True).exclude(id__in=overlapping)
        if guests:
            queryset = queryset.filter(capacity__gte=guests)
        return queryset.order_by('room_number')


class Reservation(models.Model):
    STATUS_CHOICES = [
        ('confirmed', 'Confirmed'),
        ('pending', 'Pending'),
        ('cancelled', 'Cancelled'),
    ]

    room = models.ForeignKey(Room, related_name='reservations', on_delete=models.CASCADE)
    customer_user = models.ForeignKey(settings.AUTH_USER_MODEL, related_name='reservations', on_delete=models.SET_NULL, null=True, blank=True)
    guest_name = models.CharField(max_length=120)
    guest_email = models.EmailField()
    check_in = models.DateField()
    check_out = models.DateField()
    guests = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='confirmed')
    total_price = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['check_in']
        constraints = [
            models.CheckConstraint(
                condition=models.Q(check_out__gt=models.F('check_in')),
                name='reservation_end_after_start',
            )
        ]

    def __str__(self):
        return f'{self.guest_name} - {self.room.name}'

    @property
    def night_count(self):
        return (self.check_out - self.check_in).days

    def clean(self):
        if self.check_out <= self.check_in:
            raise ValidationError({'check_out': 'Check-out date must be after check-in date.'})
        if self.guests > self.room.capacity:
            raise ValidationError({'guests': 'Guest count exceeds room capacity.'})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    @classmethod
    def overlaps_room(cls, room_id, check_in, check_out, exclude_id=None):
        query = cls.objects.filter(
            room_id=room_id,
            status__in=['confirmed', 'pending'],
            check_in__lt=check_out,
            check_out__gt=check_in,
        )
        if exclude_id:
            query = query.exclude(id=exclude_id)
        return query.exists()


class ContactInquiry(models.Model):
    name = models.CharField(max_length=120)
    email = models.EmailField()
    subject = models.CharField(max_length=160, blank=True)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.name} - {self.subject or "General query"}'


class CustomerProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, related_name='customer_profile', on_delete=models.CASCADE)
    phone_number = models.CharField(max_length=15, unique=True, blank=True, null=True)
    phone_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.user.get_full_name() or self.user.email or self.user.username


class OTPChallenge(models.Model):
    PURPOSE_CHOICES = [('login', 'Login'), ('register', 'Registration')]

    identifier = models.CharField(max_length=254)
    purpose = models.CharField(max_length=20, choices=PURPOSE_CHOICES)
    code_hash = models.CharField(max_length=128)
    expires_at = models.DateTimeField()
    attempts = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.identifier} ({self.purpose})'


@receiver(post_save, sender=get_user_model())
def create_customer_profile(sender, instance, created, **kwargs):
    if created and not instance.is_staff:
        CustomerProfile.objects.get_or_create(user=instance)
