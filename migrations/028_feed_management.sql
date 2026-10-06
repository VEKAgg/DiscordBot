-- Dynamic feed management; preserve configured subscriptions and delivery history.
ALTER TABLE feed_subscriptions
    ADD COLUMN IF NOT EXISTS paused BOOLEAN NOT NULL DEFAULT FALSE;

-- Historical seeds were never configured: remove only these known placeholder rows.
DELETE FROM feed_subscriptions
WHERE channel_id = 0 AND guild_id = 1088553066334273537
  AND feed_url IN (
    'https://feeds.feedburner.com/TechCrunch',
    'https://www.wired.com/feed/rss',
    'https://www.theverge.com/rss/index.xml',
    'https://stackoverflow.com/jobs/feed',
    'https://remoteok.io/remote-jobs.rss',
    'https://weworkremotely.com/categories/remote-programming-jobs.rss',
    'https://dev.to/feed',
    'https://medium.com/feed/tag/programming',
    'https://blog.github.com/all.atom'
  );
