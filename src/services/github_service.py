from typing import Optional, Dict, List
import aiohttp
import datetime
from ..config.config import Config
from ..database.mongodb import MongoDatabase

class GitHubService:
    def __init__(self):
        self.config = Config()
        self.db = MongoDatabase()
        self.client_id = self.config.get("github_client_id")
        self.client_secret = self.config.get("github_client_secret")
        self.redirect_uri = self.config.get("github_redirect_uri")
        self.api_base = "https://api.github.com"

    def get_oauth_url(self, user_id: int) -> str:
        """Generate GitHub OAuth URL for user authorization"""
        state = f"github_{user_id}"  # State parameter for security
        return (
            f"https://github.com/login/oauth/authorize"
            f"?client_id={self.client_id}"
            f"&redirect_uri={self.redirect_uri}"
            f"&state={state}"
            f"&scope=repo user"
        )

    async def exchange_code(self, code: str) -> Optional[str]:
        """Exchange OAuth code for access token"""
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://github.com/login/oauth/access_token",
                json={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "code": code,
                    "redirect_uri": self.redirect_uri
                },
                headers={"Accept": "application/json"}
            ) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("access_token")
        return None

    async def get_user_stats(self, access_token: str) -> Optional[Dict]:
        """Get user's GitHub statistics"""
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github.v3+json"
        }

        async with aiohttp.ClientSession() as session:
            # Get user profile
            async with session.get(
                f"{self.api_base}/user",
                headers=headers
            ) as response:
                if response.status != 200:
                    return None
                user_data = await response.json()

            # Get repositories
            async with session.get(
                f"{self.api_base}/user/repos",
                params={"per_page": 100, "type": "owner"},
                headers=headers
            ) as response:
                if response.status != 200:
                    return None
                repos = await response.json()

            language_commits = {}
            total_commits = 0
            top_languages = []

            # Analyze each repository
            for repo in repos:
                # Get languages
                async with session.get(
                    repo["languages_url"],
                    headers=headers
                ) as response:
                    if response.status == 200:
                        languages = await response.json()
                        for lang, bytes_count in languages.items():
                            if lang not in language_commits:
                                language_commits[lang] = 0

                # Get commit count
                async with session.get(
                    f"{self.api_base}/repos/{repo['full_name']}/commits",
                    params={"author": user_data["login"], "per_page": 1},
                    headers=headers
                ) as response:
                    if response.status == 200:
                        commit_count = int(response.headers.get("Link", "").split('page=')[-1].split('>')[0]) if "Link" in response.headers else 1
                        total_commits += commit_count
                        
                        # Add commits to language counts
                        for lang in languages.keys():
                            language_commits[lang] += commit_count

            # Sort languages by commit count
            top_languages = sorted(
                language_commits.keys(),
                key=lambda x: language_commits[x],
                reverse=True
            )

            return {
                "username": user_data["login"],
                "name": user_data["name"],
                "avatar_url": user_data["avatar_url"],
                "public_repos": user_data["public_repos"],
                "followers": user_data["followers"],
                "total_commits": total_commits,
                "repo_count": len(repos),
                "language_commits": language_commits,
                "top_languages": top_languages,
                "updated_at": datetime.datetime.utcnow()
            }

    async def verify_user(self, user_id: int) -> bool:
        """Verify if the user's GitHub account meets minimum criteria"""
        token_doc = await self.db.oauth_tokens.find_one({
            "user_id": user_id,
            "platform": "github"
        })
        
        if not token_doc:
            return False

        stats = await self.get_user_stats(token_doc["access_token"])
        if not stats:
            return False

        # Define verification criteria
        MIN_REPOS = 3
        MIN_COMMITS = 100
        MIN_ACCOUNT_AGE_DAYS = 90

        # Check if user meets criteria
        account_age = datetime.datetime.utcnow() - datetime.datetime.strptime(
            stats["created_at"],
            "%Y-%m-%dT%H:%M:%SZ"
        )

        return (
            stats["public_repos"] >= MIN_REPOS and
            stats["total_commits"] >= MIN_COMMITS and
            account_age.days >= MIN_ACCOUNT_AGE_DAYS
        )