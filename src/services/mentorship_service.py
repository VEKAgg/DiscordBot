"""Canonical guild-scoped mentorship. No automatic legacy binding/import/credit."""

import json

from src.config.config import MENTORSHIP_CATEGORIES
from src.database.database import db
from src.services.networking_service import normalize_skills
from src.utils.embed_limits import text_units
from src.utils.safety import ValidationError


def _guild(guild_id: int) -> None:
    if type(guild_id) is not int or not 0 < guild_id < 2**63:
        raise ValidationError('Use mentorship commands in a server.')


def _page(page: int) -> int:
    if type(page) is not int or not 1 <= page <= 1000:
        raise ValidationError('Page must be 1–1000.')
    return (page - 1) * 5


class MentorshipService:
    def __init__(self, bot=None, *, database=None):
        self.bot = bot
        self.db = database if database is not None else db

    async def _resolve_user_id(self, discord_id: str) -> int:
        row = await self.db.fetch_one(
            'INSERT INTO users (discord_id) VALUES ($1) ON CONFLICT (discord_id) '
            'DO UPDATE SET discord_id = EXCLUDED.discord_id RETURNING id',
            discord_id,
        )
        assert row is not None
        return row['id']

    @staticmethod
    async def _lock_users(conn, ids: list[int]):
        # Match ActivityService's lock order (text discord_id), not creation-order internal PKs.
        return await conn.fetch(
            'SELECT id, discord_id FROM users WHERE id = ANY($1::int[]) ORDER BY discord_id FOR UPDATE', ids
        )

    @staticmethod
    async def _audit(conn, guild_id, actor, action, details):
        await conn.execute(
            "INSERT INTO audit_logs (user_id,guild_id,action,details,severity) VALUES ($1,$2,$3,$4::jsonb,'info')",
            str(actor),
            str(guild_id),
            action,
            json.dumps(details),
        )

    async def register_mentor(
        self, guild_id: int, user_id: str, skills: str | None = None, bio: str | None = None, *, categories=None
    ):
        _guild(guild_id)
        try:
            skills_list = normalize_skills(skills)
        except ValueError as exc:
            raise ValidationError(str(exc)) from None
        bio_value = (bio or '').strip()
        if text_units(bio_value) > 1000:
            raise ValidationError('Mentor bio must be at most 1000 characters.')
        categories_supplied = categories is not None
        categories = list(dict.fromkeys(categories if categories is not None else MENTORSHIP_CATEGORIES))
        if not categories or any(category not in MENTORSHIP_CATEGORIES for category in categories):
            raise ValidationError('Choose valid mentorship categories.')
        resolved = await self._resolve_user_id(user_id)
        async with self.db.transaction() as conn:
            await self._lock_users(conn, [resolved])
            row = await conn.fetchrow(
                'INSERT INTO mentor_registrations (guild_id,user_id,skills,bio,categories) VALUES ($1,$2,$3,$4,$5) '
                'ON CONFLICT (guild_id,user_id) DO UPDATE SET skills=CASE WHEN $6::bool THEN EXCLUDED.skills ELSE mentor_registrations.skills END,'
                'bio=CASE WHEN $7::bool THEN EXCLUDED.bio ELSE mentor_registrations.bio END,'
                'categories=CASE WHEN $8::bool THEN EXCLUDED.categories ELSE mentor_registrations.categories END,available=TRUE,updated_at=NOW() RETURNING *',
                guild_id,
                resolved,
                skills_list,
                bio_value,
                categories,
                skills is not None,
                bio is not None,
                categories_supplied,
            )
            await self._audit(conn, guild_id, user_id, 'mentor_registered', {'categories': categories})
        return dict(row)

    async def set_availability(self, guild_id: int, user_id: str, available: bool):
        _guild(guild_id)
        if type(available) is not bool:
            raise ValidationError('Availability must be true or false.')
        resolved = await self._resolve_user_id(user_id)
        async with self.db.transaction() as conn:
            await self._lock_users(conn, [resolved])
            row = await conn.fetchrow(
                'UPDATE mentor_registrations SET available=$3,updated_at=NOW() WHERE guild_id=$1 AND user_id=$2 RETURNING *',
                guild_id,
                resolved,
                available,
            )
            if row is None:
                raise ValidationError('Register as a mentor first.')
            await self._audit(conn, guild_id, user_id, 'mentor_availability', {'available': available})
        return dict(row)

    async def find_mentors(self, guild_id: int, category: str | None = None, page: int = 1):
        _guild(guild_id)
        offset = _page(page)
        if category is not None and category not in MENTORSHIP_CATEGORIES:
            raise ValidationError('Unknown mentorship category.')
        return await self.db.fetch(
            'SELECT r.*,u.discord_id FROM mentor_registrations r JOIN users u ON u.id=r.user_id '
            'WHERE r.guild_id=$1 AND r.available AND ($2::text IS NULL OR $2=ANY(r.categories)) '
            'ORDER BY r.user_id LIMIT 6 OFFSET $3',
            guild_id,
            category,
            offset,
        )

    async def create_mentorship_request(
        self, guild_id: int, mentor_id: str, mentee_id: str, category: str, message: str = ''
    ):
        _guild(guild_id)
        if mentor_id == mentee_id:
            raise ValidationError('You cannot mentor yourself.')
        if category not in MENTORSHIP_CATEGORIES or text_units(message) > 1000:
            raise ValidationError('Choose a valid category and request message of at most 1000 characters.')
        mentor, mentee = await self._resolve_user_id(mentor_id), await self._resolve_user_id(mentee_id)
        async with self.db.transaction() as conn:
            await self._lock_users(conn, [mentor, mentee])
            await conn.execute(
                'SELECT pg_advisory_xact_lock(hashtextextended($1::text,0))',
                f'mentorship:{guild_id}:{min(mentor, mentee)}:{max(mentor, mentee)}',
            )
            eligible = await conn.fetchval(
                'SELECT 1 FROM mentor_registrations WHERE guild_id=$1 AND user_id=$2 AND available AND $3=ANY(categories)',
                guild_id,
                mentor,
                category,
            )
            if not eligible:
                raise ValidationError('This mentor is not available for that category in this server.')
            exists = await conn.fetchval(
                "SELECT 1 FROM mentorships WHERE guild_id=$1 AND status IN ('pending','active') "
                'AND LEAST(mentor_id,mentee_id)=LEAST($2::int,$3::int) AND GREATEST(mentor_id,mentee_id)=GREATEST($2::int,$3::int)',
                guild_id,
                mentor,
                mentee,
            )
            if exists:
                raise ValidationError('A live mentorship already exists between these members in this server.')
            row = await conn.fetchrow(
                'INSERT INTO mentorships (guild_id,mentor_id,mentee_id,category,request_message,reward_eligible,created_at_utc,updated_at_utc) '
                'VALUES ($1,$2,$3,$4,$5,TRUE,NOW(),NOW()) RETURNING *',
                guild_id,
                mentor,
                mentee,
                category,
                message.strip(),
            )
            await self._audit(
                conn, guild_id, mentee_id, 'mentorship_requested', {'id': row['id'], 'category': category}
            )
        return dict(row)

    async def transition(self, guild_id: int, mentorship_id: int, actor: str, action: str, outcome: str = 'successful'):
        _guild(guild_id)
        if type(mentorship_id) is not int or not 0 < mentorship_id < 2**31:
            raise ValidationError('Use a valid canonical mentorship ID.')
        if action not in {'accept', 'end'} or outcome not in {'successful', 'incomplete', 'cancelled'}:
            raise ValidationError('Invalid mentorship action/outcome.')
        row = await self.db.fetch_one(
            'SELECT mentor_id,mentee_id FROM mentorships WHERE id=$1 AND guild_id=$2', mentorship_id, guild_id
        )
        if row is None:
            raise ValidationError('Mentorship not found in this server (legacy history is read-only).')
        async with self.db.transaction() as conn:
            users = await self._lock_users(conn, [row['mentor_id'], row['mentee_id']])
            current = await conn.fetchrow(
                'SELECT * FROM mentorships WHERE id=$1 AND guild_id=$2 FOR UPDATE', mentorship_id, guild_id
            )
            if current is None:
                raise ValidationError('Mentorship not found.')
            if (current['mentor_id'], current['mentee_id']) != (row['mentor_id'], row['mentee_id']) or len(users) != 2:
                raise ValidationError('Participants changed; retry this action.')
            ids = {user['discord_id']: user['id'] for user in users}
            actor_id = ids.get(actor)
            if actor_id not in {current['mentor_id'], current['mentee_id']}:
                raise ValidationError('Only a participant can change this mentorship.')
            awards = []
            if action == 'accept':
                if actor_id != current['mentor_id'] or current['status'] != 'pending':
                    raise ValidationError('Only the mentor can accept a pending request.')
                row = await conn.fetchrow(
                    "UPDATE mentorships SET status='active',started_at=NOW(),updated_at=NOW(),updated_at_utc=NOW() "
                    "WHERE id=$1 AND guild_id=$2 AND mentor_id=$3 AND status='pending' RETURNING *",
                    mentorship_id,
                    guild_id,
                    actor_id,
                )
                if row is None:
                    raise ValidationError('Request changed; retry.')
            else:
                cancelling = outcome == 'cancelled'
                if current['status'] not in ({'pending', 'active'} if cancelling else {'active'}):
                    raise ValidationError('This mentorship is already closed or is not active.')
                if not cancelling and actor_id != current['mentor_id']:
                    raise ValidationError('Only the mentor can certify completion.')
                status = 'cancelled' if cancelling else 'completed'
                row = await conn.fetchrow(
                    'UPDATE mentorships SET status=$2,outcome=$3,ended_at=NOW(),updated_at=NOW(),updated_at_utc=NOW() '
                    'WHERE id=$1 AND guild_id=$4 AND status=$5 AND ($6=mentor_id OR $6=mentee_id) '
                    "AND ($3='cancelled' OR $6=mentor_id) RETURNING *",
                    mentorship_id,
                    status,
                    outcome,
                    guild_id,
                    current['status'],
                    actor_id,
                )
                if row is None:
                    raise ValidationError('Engagement changed; retry.')
                if outcome == 'successful' and current['reward_eligible']:
                    for user in users:  # already locked, in the same canonical order as activity/privacy
                        points = 50 if user['id'] == current['mentor_id'] else 25
                        await conn.execute(
                            'INSERT INTO mentorship_awards (mentorship_id,user_id,points) VALUES ($1,$2,$3)',
                            mentorship_id,
                            user['id'],
                            points,
                        )
                        await conn.execute(
                            'UPDATE users SET points=COALESCE(points,0)+$2,experience=COALESCE(experience,0)+$2,'
                            'level=floor(sqrt(GREATEST(COALESCE(points,0)+$2,0)/100.0))::int WHERE id=$1',
                            user['id'],
                            points,
                        )
                        await conn.execute(
                            "INSERT INTO user_activity_daily (user_id,guild_id,activity_date,xp_earned) VALUES ($1,$2,(NOW() AT TIME ZONE 'UTC')::date,$3) "
                            'ON CONFLICT (user_id,guild_id,activity_date) DO UPDATE SET xp_earned=user_activity_daily.xp_earned+EXCLUDED.xp_earned,updated_at=NOW()',
                            int(user['discord_id']),
                            guild_id,
                            points,
                        )
                        awards.append({'discord_id': user['discord_id'], 'points': points})
            await self._audit(
                conn,
                guild_id,
                actor,
                'mentorship_changed',
                {
                    'id': mentorship_id,
                    'before': current['status'],
                    'after': row['status'],
                    'outcome': row['outcome'],
                    'awards': awards,
                },
            )
        by_id = {user['id']: user['discord_id'] for user in users}
        return dict(row) | {
            'awards': awards,
            'mentor_discord_id': by_id[row['mentor_id']],
            'mentee_discord_id': by_id[row['mentee_id']],
        }

    async def find_live_pair(self, guild_id: int, mentor_id: str, mentee_id: str, status: str):
        _guild(guild_id)
        return await self.db.fetch_one(
            'SELECT m.id FROM mentorships m JOIN users a ON a.id=m.mentor_id JOIN users b ON b.id=m.mentee_id '
            'WHERE m.guild_id=$1 AND a.discord_id=$2 AND b.discord_id=$3 AND m.status=$4',
            guild_id,
            mentor_id,
            mentee_id,
            status,
        )

    async def get_user_mentorships(self, user_id: str, guild_id: int | None, page: int = 1):
        if guild_id is not None:
            _guild(guild_id)
        return await self.db.fetch(
            'SELECT m.*,a.discord_id AS mentor_discord_id,b.discord_id AS mentee_discord_id FROM mentorships m '
            'LEFT JOIN users a ON a.id=m.mentor_id LEFT JOIN users b ON b.id=m.mentee_id '
            'WHERE m.guild_id IS NOT DISTINCT FROM $1::bigint AND (a.discord_id=$2 OR b.discord_id=$2) ORDER BY m.id DESC LIMIT 6 OFFSET $3',
            guild_id,
            user_id,
            _page(page),
        )

    async def get_mentorship_stats(self, guild_id: int):
        _guild(guild_id)
        return await self.db.fetch_one(
            "SELECT COUNT(*) AS total,COUNT(*) FILTER (WHERE status='active') AS active,"
            "COUNT(*) FILTER (WHERE status='completed') AS completed FROM mentorships WHERE guild_id=$1",
            guild_id,
        )

    async def set_reminders(self, guild_id: int, user_id: str, enabled: bool):
        _guild(guild_id)
        if type(enabled) is not bool:
            raise ValidationError('Reminder preference must be true or false.')
        resolved = await self._resolve_user_id(user_id)
        async with self.db.transaction() as conn:
            await self._lock_users(conn, [resolved])
            await conn.execute(
                "INSERT INTO mentorship_notification_preferences (guild_id,user_id,enabled,next_attempt_at) VALUES ($1,$2,$3,NOW()+INTERVAL '7 days') "
                'ON CONFLICT (guild_id,user_id) DO UPDATE SET enabled=$3,revision=mentorship_notification_preferences.revision+1,'
                "next_attempt_at=NOW()+INTERVAL '7 days',updated_at=NOW()",
                guild_id,
                resolved,
                enabled,
            )
            await self._audit(conn, guild_id, user_id, 'mentorship_reminders', {'enabled': enabled})

    async def due_reminders(self):
        return await self.db.fetch(
            'WITH recipients AS (SELECT p.*,u.discord_id FROM mentorship_notification_preferences p JOIN users u ON u.id=p.user_id '
            'WHERE p.enabled AND p.next_attempt_at<=NOW() AND EXISTS (SELECT 1 FROM mentorships a '
            "WHERE a.guild_id=p.guild_id AND a.status='active' AND a.reward_eligible AND a.started_at<=NOW()-INTERVAL '7 days' "
            'AND (a.mentor_id=p.user_id OR a.mentee_id=p.user_id)) ORDER BY p.next_attempt_at,p.guild_id,p.user_id LIMIT 12) '
            'SELECT p.guild_id,p.user_id,p.discord_id,p.revision,m.id,m.category FROM recipients p JOIN LATERAL '
            "(SELECT id,category FROM mentorships WHERE guild_id=p.guild_id AND status='active' AND reward_eligible AND started_at<=NOW()-INTERVAL '7 days' "
            'AND (mentor_id=p.user_id OR mentee_id=p.user_id) ORDER BY id LIMIT 10) m ON TRUE',
        )

    async def claim_reminder(self, guild_id: int, user_id: int, revision: int) -> bool:
        return bool(
            await self.db.fetchval(
                "UPDATE mentorship_notification_preferences SET next_attempt_at=NOW()+INTERVAL '1 day' "
                'WHERE guild_id=$1 AND user_id=$2 AND enabled AND revision=$3 AND next_attempt_at<=NOW() RETURNING 1',
                guild_id,
                user_id,
                revision,
            )
        )

    async def current_reminder_matches(self, guild_id: int, user_id: int, revision: int):
        # Re-read consent AND active status at the transport boundary; do not send stale candidate rows.
        return await self.db.fetch(
            'SELECT m.id,m.category FROM mentorships m JOIN mentorship_notification_preferences p '
            'ON p.guild_id=m.guild_id AND (m.mentor_id=p.user_id OR m.mentee_id=p.user_id) '
            'WHERE p.guild_id=$1 AND p.user_id=$2 AND p.enabled AND p.revision=$3 '
            "AND m.status='active' AND m.reward_eligible AND m.started_at<=NOW()-INTERVAL '7 days' ORDER BY m.id LIMIT 10",
            guild_id,
            user_id,
            revision,
        )

    async def reminder_current(self, guild_id: int, user_id: int, revision: int) -> bool:
        return bool(
            await self.db.fetchval(
                'SELECT 1 FROM mentorship_notification_preferences WHERE guild_id=$1 AND user_id=$2 AND enabled AND revision=$3',
                guild_id,
                user_id,
                revision,
            )
        )

    async def finish_reminder(self, guild_id: int, user_id: int, revision: int, delivered: bool):
        await self.db.execute(
            "UPDATE mentorship_notification_preferences SET next_attempt_at=NOW()+CASE WHEN $4 THEN INTERVAL '7 days' ELSE INTERVAL '1 day' END,"
            'last_sent_at=CASE WHEN $4 THEN NOW() ELSE last_sent_at END WHERE guild_id=$1 AND user_id=$2 AND enabled AND revision=$3',
            guild_id,
            user_id,
            revision,
            delivered,
        )
