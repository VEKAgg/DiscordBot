from typing import Optional, Dict, List
import aiohttp
import datetime
from ..config.config import Config
from ..database.mongodb import MongoDatabase
from google.oauth2.credentials import Credentials
from google.oauth2 import id_token
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
import pytz

class CalendarService:
    def __init__(self):
        self.config = Config()
        self.db = MongoDatabase()
        self.client_id = self.config.get("google_client_id")
        self.client_secret = self.config.get("google_client_secret")
        self.redirect_uri = self.config.get("google_redirect_uri")

    def get_oauth_url(self, user_id: int) -> str:
        """Generate Google Calendar OAuth URL"""
        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": [self.redirect_uri]
                }
            },
            scopes=["https://www.googleapis.com/auth/calendar"]
        )
        flow.redirect_uri = self.redirect_uri

        authorization_url, state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            state=f"calendar_{user_id}"
        )

        return authorization_url

    async def exchange_code(self, code: str) -> Optional[Dict]:
        """Exchange OAuth code for tokens"""
        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": [self.redirect_uri]
                }
            },
            scopes=["https://www.googleapis.com/auth/calendar"]
        )
        flow.redirect_uri = self.redirect_uri

        try:
            flow.fetch_token(code=code)
            credentials = flow.credentials
            
            return {
                "token": credentials.token,
                "refresh_token": credentials.refresh_token,
                "token_uri": credentials.token_uri,
                "client_id": credentials.client_id,
                "client_secret": credentials.client_secret,
                "scopes": credentials.scopes
            }
        except Exception as e:
            print(f"Error exchanging code: {e}")
            return None

    async def create_event(
        self,
        title: str,
        description: str,
        start_time: datetime.datetime,
        duration: int,
        timezone: str = "UTC",
        max_participants: Optional[int] = None,
        location: Optional[str] = None
    ) -> Optional[str]:
        """Create a calendar event"""
        # Convert timezone
        tz = pytz.timezone(timezone)
        start_time = tz.localize(start_time)
        end_time = start_time + datetime.timedelta(minutes=duration)

        # Event body
        event = {
            "summary": title,
            "description": description,
            "start": {
                "dateTime": start_time.isoformat(),
                "timeZone": timezone
            },
            "end": {
                "dateTime": end_time.isoformat(),
                "timeZone": timezone
            }
        }

        if location:
            event["location"] = location

        if max_participants:
            event["attendees"] = []  # Will be filled as people join
            event["guestsCanSeeOtherGuests"] = True
            event["guestsCanInviteOthers"] = False
            event["maxAttendees"] = max_participants

        credentials = await self._get_service_account_credentials()
        if not credentials:
            return None

        try:
            service = build("calendar", "v3", credentials=credentials)
            calendar_id = "primary"  # Use primary calendar
            
            event = service.events().insert(
                calendarId=calendar_id,
                body=event,
                sendNotifications=True
            ).execute()
            
            return event.get("id")
        except Exception as e:
            print(f"Error creating event: {e}")
            return None

    async def add_attendee(
        self,
        event_id: str,
        user_id: int,
        calendar_id: str = "primary"
    ) -> bool:
        """Add an attendee to a calendar event"""
        # Get user's email from database
        user = await self.db.users.find_one({"user_id": user_id})
        if not user or not user.get("email"):
            return False

        credentials = await self._get_service_account_credentials()
        if not credentials:
            return False

        try:
            service = build("calendar", "v3", credentials=credentials)
            
            # Get current event
            event = service.events().get(
                calendarId=calendar_id,
                eventId=event_id
            ).execute()
            
            # Add new attendee
            attendees = event.get("attendees", [])
            attendees.append({"email": user["email"]})
            event["attendees"] = attendees
            
            # Update event
            updated_event = service.events().update(
                calendarId=calendar_id,
                eventId=event_id,
                body=event,
                sendNotifications=True
            ).execute()
            
            return True
        except Exception as e:
            print(f"Error adding attendee: {e}")
            return False

    async def remove_attendee(
        self,
        event_id: str,
        user_id: int,
        calendar_id: str = "primary"
    ) -> bool:
        """Remove an attendee from a calendar event"""
        # Get user's email from database
        user = await self.db.users.find_one({"user_id": user_id})
        if not user or not user.get("email"):
            return False

        credentials = await self._get_service_account_credentials()
        if not credentials:
            return False

        try:
            service = build("calendar", "v3", credentials=credentials)
            
            # Get current event
            event = service.events().get(
                calendarId=calendar_id,
                eventId=event_id
            ).execute()
            
            # Remove attendee
            attendees = event.get("attendees", [])
            attendees = [a for a in attendees if a.get("email") != user["email"]]
            event["attendees"] = attendees
            
            # Update event
            updated_event = service.events().update(
                calendarId=calendar_id,
                eventId=event_id,
                body=event,
                sendNotifications=True
            ).execute()
            
            return True
        except Exception as e:
            print(f"Error removing attendee: {e}")
            return False

    async def delete_event(
        self,
        event_id: str,
        calendar_id: str = "primary"
    ) -> bool:
        """Delete a calendar event"""
        credentials = await self._get_service_account_credentials()
        if not credentials:
            return False

        try:
            service = build("calendar", "v3", credentials=credentials)
            
            service.events().delete(
                calendarId=calendar_id,
                eventId=event_id,
                sendNotifications=True
            ).execute()
            
            return True
        except Exception as e:
            print(f"Error deleting event: {e}")
            return False

    async def _get_service_account_credentials(self) -> Optional[Credentials]:
        """Get service account credentials from config"""
        try:
            service_account_info = self.config.get("google_service_account")
            if not service_account_info:
                return None
                
            credentials = Credentials.from_service_account_info(
                service_account_info,
                scopes=["https://www.googleapis.com/auth/calendar"]
            )
            
            return credentials
        except Exception as e:
            print(f"Error getting service account credentials: {e}")
            return None