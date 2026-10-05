"""Rank Card Generator — async Pillow-based image generator for Discord rank cards."""

from __future__ import annotations

import asyncio
import io

from PIL import Image, ImageDraw, ImageFont


def _generate_rank_card_sync(
    username: str,
    avatar_bytes: bytes | None,
    level: int,
    current_xp: int,
    xp_needed: int,
    rank: int,
    streak: int,
) -> io.BytesIO:
    """Synchronous rank card generation (run in thread)."""
    width, height = 900, 260
    img = Image.new('RGB', (width, height), '#121216')
    draw = ImageDraw.Draw(img)

    # Dark gradient background (simple two-tone)
    for y in range(height):
        ratio = y / height
        r = int(0x12 + (0x1E - 0x12) * ratio)
        g = int(0x12 + (0x1F - 0x12) * ratio)
        b = int(0x16 + (0x28 - 0x16) * ratio)
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    # --- Avatar (circular with orange border) ---
    avatar_size = 160
    avatar_x, avatar_y = 30, (height - avatar_size) // 2
    if avatar_bytes:
        try:
            avatar_stream = io.BytesIO(avatar_bytes)
            avatar = Image.open(avatar_stream).convert('RGBA')
            avatar = avatar.resize((avatar_size, avatar_size), Image.LANCZOS)

            # Create circular mask
            mask = Image.new('L', (avatar_size, avatar_size), 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.ellipse((0, 0, avatar_size - 1, avatar_size - 1), fill=255)
            avatar.putalpha(mask)

            # Orange border ring
            border = 4
            ring = Image.new('RGBA', (avatar_size + border * 2, avatar_size + border * 2), (0, 0, 0, 0))
            ring_draw = ImageDraw.Draw(ring)
            ring_draw.ellipse(
                (0, 0, avatar_size + border * 2 - 1, avatar_size + border * 2 - 1),
                outline=(0xFF, 0x6B, 0x00, 255),
                width=border,
            )
            img.paste(
                ring,
                (avatar_x - border, avatar_y - border),
                ring,
            )
            img.paste(avatar, (avatar_x, avatar_y), avatar)
        except Exception:
            # Fallback: draw a placeholder circle
            draw.ellipse(
                (avatar_x, avatar_y, avatar_x + avatar_size, avatar_y + avatar_size),
                fill='#2C2F33',
                outline='#FF6B00',
                width=4,
            )
    else:
        draw.ellipse(
            (avatar_x, avatar_y, avatar_x + avatar_size, avatar_y + avatar_size),
            fill='#2C2F33',
            outline='#FF6B00',
            width=4,
        )

    # --- Text area ---
    text_x = avatar_x + avatar_size + 30
    orange = (0xFF, 0x6B, 0x00)
    white = (0xFF, 0xFF, 0xFF)
    gray = (0x99, 0x99, 0x99)

    # Try to load a nice font, fall back to default
    try:
        font_large = ImageFont.truetype('arial.ttf', 32)
        font_medium = ImageFont.truetype('arial.ttf', 22)
        font_small = ImageFont.truetype('arial.ttf', 18)
    except OSError:
        try:
            font_large = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 32)
            font_medium = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 22)
            font_small = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 18)
        except OSError:
            font_large = ImageFont.load_default()
            font_medium = ImageFont.load_default()
            font_small = ImageFont.load_default()

    # Username
    display_name = username[:20] + ('...' if len(username) > 20 else '')
    draw.text((text_x, 40), display_name, fill=white, font=font_large)

    # Rank badge
    rank_text = f'#{rank}' if rank else 'Unranked'
    draw.text((text_x, 82), rank_text, fill=orange, font=font_medium)

    # Level
    draw.text((text_x, 115), f'Level {level}', fill=gray, font=font_medium)

    # Streak
    if streak > 0:
        draw.text((text_x + 150, 115), f'\U0001f525 {streak}d', fill=orange, font=font_medium)

    # --- Progress bar ---
    bar_x = text_x
    bar_y = 170
    bar_width = width - text_x - 40
    bar_height = 24
    bar_radius = bar_height // 2

    # Background bar
    draw.rounded_rectangle(
        (bar_x, bar_y, bar_x + bar_width, bar_y + bar_height),
        radius=bar_radius,
        fill='#1A1A2E',
    )

    # Filled portion
    progress = min(1.0, current_xp / xp_needed) if xp_needed > 0 else 0
    filled_width = max(0, int(progress * bar_width))
    if filled_width > 0:
        # Gradient effect (solid orange)
        draw.rounded_rectangle(
            (bar_x, bar_y, bar_x + filled_width, bar_y + bar_height),
            radius=bar_radius,
            fill=orange,
        )

    # XP text on bar
    xp_text = f'{current_xp:,} / {xp_needed:,} XP'
    bbox = draw.textbbox((0, 0), xp_text, font=font_small)
    text_w = bbox[2] - bbox[0]
    text_x_center = bar_x + (bar_width - text_w) // 2
    draw.text((text_x_center, bar_y + 3), xp_text, fill=white, font=font_small)

    # Export to BytesIO
    buffer = io.BytesIO()
    img.save(buffer, format='PNG', quality=95)
    buffer.seek(0)
    return buffer


async def generate_rank_card(
    username: str,
    avatar_bytes: bytes | None,
    level: int,
    current_xp: int,
    xp_needed: int,
    rank: int,
    streak: int,
) -> io.BytesIO:
    """Generate a rank card image asynchronously."""
    return await asyncio.to_thread(
        _generate_rank_card_sync,
        username,
        avatar_bytes,
        level,
        current_xp,
        xp_needed,
        rank,
        streak,
    )


def _generate_welcome_card_sync(
    username: str,
    avatar_bytes: bytes | None,
    server_name: str,
    member_count: int,
    server_icon_bytes: bytes | None = None,
) -> io.BytesIO:
    """Synchronous welcome card generation (run in thread)."""
    width, height = 900, 300
    img = Image.new('RGB', (width, height), '#121216')
    draw = ImageDraw.Draw(img)

    # Dark gradient background
    for y in range(height):
        ratio = y / height
        r = int(0x12 + (0x1E - 0x12) * ratio)
        g = int(0x12 + (0x1F - 0x12) * ratio)
        b = int(0x16 + (0x28 - 0x16) * ratio)
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    # Server icon (small, top-left corner as background accent)
    if server_icon_bytes:
        try:
            icon_stream = io.BytesIO(server_icon_bytes)
            icon = Image.open(icon_stream).convert('RGBA')
            icon = icon.resize((120, 120), Image.LANCZOS)
            icon_mask = Image.new('L', (120, 120), 0)
            icon_mask_draw = ImageDraw.Draw(icon_mask)
            icon_mask_draw.ellipse((0, 0, 119, 119), fill=255)
            icon.putalpha(icon_mask)
            # Dimmed background placement
            dimmed = Image.new('RGBA', (120, 120), (0, 0, 0, 80))
            img.paste(dimmed, (width - 150, 20), icon_mask)
            img.paste(icon, (width - 150, 20), icon)
        except Exception:
            pass

    # User avatar (circular with orange border)
    avatar_size = 160
    avatar_x, avatar_y = 30, (height - avatar_size) // 2
    if avatar_bytes:
        try:
            avatar_stream = io.BytesIO(avatar_bytes)
            avatar = Image.open(avatar_stream).convert('RGBA')
            avatar = avatar.resize((avatar_size, avatar_size), Image.LANCZOS)

            mask = Image.new('L', (avatar_size, avatar_size), 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.ellipse((0, 0, avatar_size - 1, avatar_size - 1), fill=255)
            avatar.putalpha(mask)

            border = 4
            ring = Image.new('RGBA', (avatar_size + border * 2, avatar_size + border * 2), (0, 0, 0, 0))
            ring_draw = ImageDraw.Draw(ring)
            ring_draw.ellipse(
                (0, 0, avatar_size + border * 2 - 1, avatar_size + border * 2 - 1),
                outline=(0xFF, 0x6B, 0x00, 255),
                width=border,
            )
            img.paste(ring, (avatar_x - border, avatar_y - border), ring)
            img.paste(avatar, (avatar_x, avatar_y), avatar)
        except Exception:
            draw.ellipse(
                (avatar_x, avatar_y, avatar_x + avatar_size, avatar_y + avatar_size),
                fill='#2C2F33',
                outline='#FF6B00',
                width=4,
            )
    else:
        draw.ellipse(
            (avatar_x, avatar_y, avatar_x + avatar_size, avatar_y + avatar_size),
            fill='#2C2F33',
            outline='#FF6B00',
            width=4,
        )

    # Text area
    text_x = avatar_x + avatar_size + 30
    orange = (0xFF, 0x6B, 0x00)
    white = (0xFF, 0xFF, 0xFF)
    gray = (0x99, 0x99, 0x99)

    try:
        font_large = ImageFont.truetype('arial.ttf', 36)
        font_medium = ImageFont.truetype('arial.ttf', 24)
        font_small = ImageFont.truetype('arial.ttf', 18)
    except OSError:
        try:
            font_large = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 36)
            font_medium = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 24)
            font_small = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 18)
        except OSError:
            font_large = ImageFont.load_default()
            font_medium = ImageFont.load_default()
            font_small = ImageFont.load_default()

    # Welcome text
    draw.text((text_x, 40), 'Welcome to', fill=gray, font=font_medium)
    draw.text((text_x, 72), server_name[:30], fill=orange, font=font_large)

    # Username
    display_name = username[:25] + ('...' if len(username) > 25 else '')
    draw.text((text_x, 125), display_name, fill=white, font=font_medium)

    # Member count badge
    count_text = f'Member #{member_count:,}'
    bbox = draw.textbbox((0, 0), count_text, font=font_small)
    badge_w = bbox[2] - bbox[0] + 20
    badge_h = bbox[3] - bbox[1] + 12
    badge_x = text_x
    badge_y = 170
    draw.rounded_rectangle(
        (badge_x, badge_y, badge_x + badge_w, badge_y + badge_h),
        radius=badge_h // 2,
        fill=orange,
    )
    draw.text((badge_x + 10, badge_y + 4), count_text, fill=white, font=font_small)

    # Export
    buffer = io.BytesIO()
    img.save(buffer, format='PNG', quality=95)
    buffer.seek(0)
    return buffer


async def generate_welcome_card(
    username: str,
    avatar_bytes: bytes | None,
    server_name: str,
    member_count: int,
    server_icon_bytes: bytes | None = None,
) -> io.BytesIO:
    """Generate a welcome card image asynchronously."""
    return await asyncio.to_thread(
        _generate_welcome_card_sync,
        username,
        avatar_bytes,
        server_name,
        member_count,
        server_icon_bytes,
    )
