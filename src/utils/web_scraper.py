import aiohttp
from bs4 import BeautifulSoup
import os
from dotenv import load_dotenv
from typing import Dict, Any, List, Optional, Tuple
from loguru import logger
from datetime import datetime, timezone, timedelta
import re
from urllib.parse import urljoin, urlparse
import json
import motor.motor_asyncio
from pymongo import DESCENDING
import matplotlib.pyplot as plt
import io
import pandas as pd
import seaborn as sns

load_dotenv()

class WebScraper:
    def __init__(self, db: motor.motor_asyncio.AsyncIOMotorDatabase):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
        }
        
        # Define supported Indian retailers
        self.supported_sites = {
            'amazon.in': {
                'price_selector': '#priceblock_ourprice, .a-price-whole',
                'title_selector': '#productTitle',
                'stock_selector': '#availability span',
                'region': 'India'
            },
            'flipkart.com': {
                'price_selector': '._30jeq3',
                'title_selector': '.B_NuCI',
                'stock_selector': '._16FRp0',
                'region': 'India'
            },
            'mdcomputers.in': {
                'price_selector': '#price-special, #price',
                'title_selector': '.title-product',
                'stock_selector': '.stock span',
                'region': 'India'
            }
            # Add more sites with their selectors
        }

        self.db = db
        self.price_history = self.db.price_history
        self.price_alerts = self.db.price_alerts

        self.alert_thresholds = {
            "price_drop": 5,  # 5% price drop
            "price_increase": 10,  # 10% price increase
            "stock_change": True,  # Alert on stock status change
        }

    async def track_price(self, url: str, user_id: int = None) -> Dict[str, Any]:
        try:
            logger.info(f"Starting price tracking for URL: {url}")
            
            domain = urlparse(url).netloc.lower()
            if domain not in self.supported_sites:
                return {"error": f"Website not supported. Supported sites: {', '.join(self.supported_sites.keys())}"}

            site_config = self.supported_sites[domain]
            
            async with aiohttp.ClientSession(headers=self.headers) as session:
                async with session.get(url) as response:
                    if response.status != 200:
                        return {"error": f"Failed to fetch webpage (Status: {response.status})"}
                    
                    html = await response.text()
                    soup = BeautifulSoup(html, 'lxml')
                    
                    # Extract product details
                    price = self._extract_price(soup, site_config['price_selector'])
                    title = self._extract_text(soup, site_config['title_selector'])
                    stock = self._extract_stock_status(soup, site_config['stock_selector'])
                    
                    result = {
                        "title": title,
                        "url": url,
                        "current_price": price,
                        "stock_status": stock,
                        "region": site_config['region'],
                        "timestamp": datetime.now(timezone.utc),
                        "domain": domain
                    }
                    
                    # Store price history
                    if price:
                        await self.price_history.insert_one({
                            "url": url,
                            "price": price,
                            "timestamp": result["timestamp"],
                            "user_id": user_id,
                            "title": title,
                            "domain": domain,
                            "region": site_config['region']
                        })
                    
                    # Get historical data
                    history = await self._get_price_history(url)
                    if history:
                        result["price_history"] = history
                        result["price_stats"] = await self._calculate_price_stats(url)
                    
                    logger.info(f"Successfully tracked price for {url}")
                    return result

        except Exception as e:
            logger.error(f"Price tracking error: {str(e)}")
            return {"error": "Failed to track price"}

    def _extract_price(self, soup: BeautifulSoup, selector: str) -> Optional[float]:
        try:
            price_elem = soup.select_one(selector)
            if not price_elem:
                return None
            
            # Extract numbers from string
            price_text = re.sub(r'[^\d.]', '', price_elem.text.strip())
            return float(price_text) if price_text else None
            
        except Exception as e:
            logger.error(f"Price extraction error: {str(e)}")
            return None

    def _extract_text(self, soup: BeautifulSoup, selector: str) -> str:
        try:
            elem = soup.select_one(selector)
            return elem.text.strip() if elem else "Unknown Product"
        except Exception:
            return "Unknown Product"

    def _extract_stock_status(self, soup: BeautifulSoup, selector: str) -> str:
        try:
            stock_elem = soup.select_one(selector)
            if not stock_elem:
                return "Unknown"
            
            text = stock_elem.text.lower()
            if any(word in text for word in ['in stock', 'available']):
                return "In Stock"
            elif any(word in text for word in ['out of stock', 'unavailable']):
                return "Out of Stock"
            return "Unknown"
            
        except Exception:
            return "Unknown"

    async def _get_price_history(self, url: str) -> List[Dict[str, Any]]:
        try:
            cursor = self.price_history.find(
                {"url": url},
                {"price": 1, "timestamp": 1, "_id": 0}
            ).sort("timestamp", DESCENDING).limit(30)  # Last 30 records
            
            return await cursor.to_list(length=30)
        except Exception as e:
            logger.error(f"Error fetching price history: {str(e)}")
            return []

    async def _calculate_price_stats(self, url: str) -> Dict[str, Any]:
        try:
            pipeline = [
                {"$match": {"url": url}},
                {"$group": {
                    "_id": None,
                    "avg_price": {"$avg": "$price"},
                    "min_price": {"$min": "$price"},
                    "max_price": {"$max": "$price"},
                    "total_records": {"$sum": 1}
                }}
            ]
            
            result = await self.price_history.aggregate(pipeline).to_list(length=1)
            if not result:
                return {}
                
            stats = result[0]
            return {
                "average": round(stats["avg_price"], 2),
                "lowest": stats["min_price"],
                "highest": stats["max_price"],
                "total_tracked": stats["total_records"]
            }
            
        except Exception as e:
            logger.error(f"Error calculating price stats: {str(e)}")
            return {}

    async def scrape_and_summarize(self, url: str, extract_links: bool = False, 
                                 extract_images: bool = False) -> Dict[str, Any]:
        try:
            logger.info(f"Starting web scraping for URL: {url}")
            
            # Validate URL and domain
            if not self._is_valid_url(url):
                return {"error": "Invalid URL or domain not allowed"}

            async with aiohttp.ClientSession(headers=self.headers) as session:
                logger.info("Fetching webpage content...")
                async with session.get(url) as response:
                    if response.status != 200:
                        return {"error": f"Failed to fetch webpage (Status: {response.status})"}
                    
                    html = await response.text()
                    soup = BeautifulSoup(html, 'lxml')
                    
                    result = {
                        "title": soup.title.string if soup.title else "Web Summary",
                        "url": url,
                        "scrape_time": datetime.now(timezone.utc).isoformat(),
                        "metadata": self._extract_metadata(soup),
                        "content": self._extract_content(soup),
                        "text_stats": self._analyze_text(soup),
                    }

                    if extract_links:
                        result["links"] = self._extract_links(soup, url)
                    
                    if extract_images:
                        result["images"] = self._extract_images(soup, url)

                    if not result["content"]:
                        return {"error": "No meaningful content found on webpage"}

                    result["summary"] = await self._get_summary(result["content"][:2000])
                    logger.info("Web scraping completed successfully")
                    return result

        except aiohttp.ClientError as e:
            logger.error(f"Network error during scraping: {str(e)}")
            return {"error": "Failed to connect to webpage"}
        except Exception as e:
            logger.error(f"Scraping error: {str(e)}")
            return {"error": "Failed to process the webpage"}

    def _is_valid_url(self, url: str) -> bool:
        try:
            parsed = urlparse(url)
            if not parsed.scheme or not parsed.netloc:
                return False
            domain = parsed.netloc.lower()
            return any(allowed in domain for allowed in self.supported_sites.keys())
        except:
            return False

    def _analyze_text(self, soup: BeautifulSoup) -> Dict[str, int]:
        text = soup.get_text()
        return {
            "word_count": len(text.split()),
            "character_count": len(text),
            "paragraph_count": len(soup.find_all('p')),
            "heading_count": len(soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']))
        }

    def _extract_links(self, soup: BeautifulSoup, base_url: str) -> List[Dict[str, str]]:
        links = []
        for a in soup.find_all('a', href=True):
            href = a.get('href')
            if href:
                absolute_url = urljoin(base_url, href)
                links.append({
                    "text": a.get_text().strip(),
                    "url": absolute_url,
                    "type": "internal" if urlparse(base_url).netloc in absolute_url else "external"
                })
        return links[:10]  # Limit to 10 links

    def _extract_images(self, soup: BeautifulSoup, base_url: str) -> List[Dict[str, str]]:
        images = []
        for img in soup.find_all('img', src=True):
            src = img.get('src')
            if src:
                images.append({
                    "url": urljoin(base_url, src),
                    "alt": img.get('alt', ''),
                    "title": img.get('title', '')
                })
        return images[:5]  # Limit to 5 images

    def _extract_content(self, soup: BeautifulSoup) -> str:
        # Extract main content (customize based on needs)
        content = []
        for p in soup.find_all(['p', 'article', 'section']):
            content.append(p.get_text().strip())
        return "\n".join(filter(None, content))

    def _extract_metadata(self, soup: BeautifulSoup) -> Dict[str, str]:
        metadata = {}
        meta_tags = soup.find_all('meta', attrs={'name': ['description', 'keywords', 'author']})
        for tag in meta_tags:
            name = tag.get('name', '').capitalize()
            content = tag.get('content', '')[:100]
            if content:
                metadata[name] = content
        return metadata

    async def _get_summary(self, text: str) -> str:
        if not self.openai_api_key:
            return "Error: OpenAI API key not configured"
            
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.openai_api_key}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "model": "gpt-3.5-turbo",
                        "messages": [{
                            "role": "user",
                            "content": f"Summarize this text in 3-4 sentences: {text}"
                        }],
                        "max_tokens": 150
                    }
                ) as response:
                    if response.status != 200:
                        return "Failed to generate summary"
                    
                    data = await response.json()
                    return data['choices'][0]['message']['content']
                    
        except Exception as e:
            logger.error(f"Summary generation error: {str(e)}")
            return "Failed to generate summary"

    async def set_price_alert(self, url: str, user_id: int, target_price: float, 
                            channel_id: int) -> Dict[str, Any]:
        try:
            # Validate current price first
            current_data = await self.track_price(url, user_id)
            if current_data.get("error"):
                return current_data

            alert_data = {
                "url": url,
                "user_id": user_id,
                "target_price": target_price,
                "channel_id": channel_id,
                "current_price": current_data["current_price"],
                "title": current_data["title"],
                "created_at": datetime.now(timezone.utc),
                "last_checked": datetime.now(timezone.utc),
                "status": "active"
            }

            await self.price_alerts.insert_one(alert_data)
            return {"success": True, "data": alert_data}

        except Exception as e:
            logger.error(f"Error setting price alert: {str(e)}")
            return {"error": "Failed to set price alert"}

    async def check_price_alerts(self) -> List[Dict[str, Any]]:
        try:
            alerts = await self.price_alerts.find({"status": "active"}).to_list(length=None)
            triggered_alerts = []

            for alert in alerts:
                current_data = await self.track_price(alert["url"])
                if current_data.get("error"):
                    continue

                current_price = current_data["current_price"]
                if current_price <= alert["target_price"]:
                    triggered_alerts.append({
                        "alert": alert,
                        "current_price": current_price,
                        "price_diff": alert["current_price"] - current_price
                    })
                    
                    # Update alert status
                    await self.price_alerts.update_one(
                        {"_id": alert["_id"]},
                        {
                            "$set": {
                                "status": "triggered",
                                "triggered_at": datetime.now(timezone.utc),
                                "trigger_price": current_price
                            }
                        }
                    )

            return triggered_alerts

        except Exception as e:
            logger.error(f"Error checking price alerts: {str(e)}")
            return []

    async def analyze_price_trends(self, url: str, timeframe: str = "week") -> Dict[str, Any]:
        try:
            # Get historical data
            threshold = datetime.now(timezone.utc) - self._get_timeframe_delta(timeframe)
            cursor = self.price_history.find(
                {"url": url, "timestamp": {"$gte": threshold}},
                {"price": 1, "timestamp": 1, "_id": 0}
            ).sort("timestamp", DESCENDING)
            
            history = await cursor.to_list(length=None)
            if not history:
                return {"error": "No price history available"}

            df = pd.DataFrame(history)
            
            # Generate trend visualization
            plt.figure(figsize=(10, 6))
            sns.set_style("darkgrid")
            sns.lineplot(data=df, x="timestamp", y="price")
            plt.title("Price Trend Analysis")
            plt.xlabel("Date")
            plt.ylabel("Price (₹)")
            
            # Save plot to bytes
            buf = io.BytesIO()
            plt.savefig(buf, format='png')
            buf.seek(0)
            plt.close()

            # Calculate statistics
            stats = {
                "current_price": history[0]["price"],
                "avg_price": df["price"].mean(),
                "min_price": df["price"].min(),
                "max_price": df["price"].max(),
                "price_volatility": df["price"].std(),
                "trend": self._calculate_trend(df["price"].tolist()),
                "plot": buf
            }

            return stats

        except Exception as e:
            logger.error(f"Error analyzing price trends: {str(e)}")
            return {"error": "Failed to analyze price trends"}

    def _calculate_trend(self, prices: List[float]) -> str:
        if len(prices) < 2:
            return "Insufficient data"
        
        first, last = prices[-1], prices[0]
        change = ((last - first) / first) * 100
        
        if change > 5:
            return "Strong Upward"
        elif change > 0:
            return "Slight Upward"
        elif change < -5:
            return "Strong Downward"
        elif change < 0:
            return "Slight Downward"
        return "Stable"

    def _get_timeframe_delta(self, timeframe: str) -> timedelta:
        return {
            "day": timedelta(days=1),
            "week": timedelta(days=7),
            "month": timedelta(days=30),
            "year": timedelta(days=365)
        }.get(timeframe, timedelta(days=7)) 