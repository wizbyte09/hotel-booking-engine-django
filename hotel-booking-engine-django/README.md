# hotel-booking-engine-django
Transactional hotel reservation backend built with Python and Django. Reservation creation locks the room row with `select_for_update()` inside `transaction.atomic()`, then repeats the overlap check before insert. Run production bookings on MySQL or PostgreSQL; SQLite is suitable for local development but does not provide the same row-locking guarantees under concurrent traffic.

## Customer authentication

Customer registration and login use an Indian mobile number in `+91` format and a six-digit OTP. In local development, the OTP is printed in the Django terminal and shown on the verification screen while `DEBUG=True`. Production should connect `_issue_otp` in `bookings/views.py` to an Indian SMS provider and set `OTP_DEBUG_SHOW_CODE=False`.

Google sign-in is available through `/accounts/google/login/`. Configure a Google OAuth web client with the redirect URI `http://127.0.0.1:8000/accounts/google/login/callback/`, then set `GOOGLE_OAUTH_CLIENT_ID` and `GOOGLE_OAUTH_CLIENT_SECRET` from `.env.example`. A SocialApp for Google must also be created in the database and assigned to the local Site (`example.com`) before using the provider in a deployed environment.

After setting those variables, configure the local SocialApp with:

```powershell
python manage.py migrate
python manage.py configure_google_oauth
```
