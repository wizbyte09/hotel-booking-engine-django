from django.contrib import admin

from .models import Reservation, Room


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ('name', 'room_number', 'room_type', 'capacity', 'base_price_per_night', 'is_available')
    list_filter = ('room_type', 'is_available')
    search_fields = ('name', 'room_number')
    list_editable = ('is_available', 'base_price_per_night')


@admin.register(Reservation)
class ReservationAdmin(admin.ModelAdmin):
    list_display = ('guest_name', 'room', 'check_in', 'check_out', 'guests', 'status', 'total_price')
    list_filter = ('status', 'room__room_type', 'check_in')
    search_fields = ('guest_name', 'guest_email', 'room__name', 'room__room_number')
    date_hierarchy = 'check_in'
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        ('Guest Details', {'fields': ('guest_name', 'guest_email', 'guests')}),
        ('Stay Details', {'fields': ('room', 'check_in', 'check_out', 'status', 'total_price')}),
        ('Audit', {'fields': ('created_at', 'updated_at')}),
    )
