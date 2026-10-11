"""Run the dashboard API: ``python -m src.api`` (host/port from API_HOST/API_PORT)."""

import os

import uvicorn
from dotenv import load_dotenv

if __name__ == '__main__':
    load_dotenv()
    uvicorn.run(
        'src.api.app:app',
        host=os.getenv('API_HOST', '0.0.0.0'),  # noqa: S104 - container networking
        port=int(os.getenv('API_PORT', '8080')),
        proxy_headers=False,
        access_log=False,  # access logs would include query strings; auth headers are never logged
    )
