# hotel-booking-engine-django
ACID-compliant hotel reservation backend built with Python, Django, and MySQL, designed to eliminate race conditions and double-booking during concurrent checkouts.

## Customer authentication

Customer registration and login use an Indian mobile number in `+91` format and a six-digit OTP. In local development, the OTP is printed in the Django terminal and shown on the verification screen while `DEBUG=True`. Production should connect `_issue_otp` in `bookings/views.py` to an Indian SMS provider and set `OTP_DEBUG_SHOW_CODE=False`.

Google sign-in is available through `/accounts/google/login/`. Configure a Google OAuth web client with the redirect URI `http://127.0.0.1:8000/accounts/google/login/callback/`, then set `GOOGLE_OAUTH_CLIENT_ID` and `GOOGLE_OAUTH_CLIENT_SECRET` from `.env.example`. A SocialApp for Google must also be created in the database and assigned to the local Site (`example.com`) before using the provider in a deployed environment.

After setting those variables, configure the local SocialApp with:

```powershell
python manage.py migrate
python manage.py configure_google_oauth
```
