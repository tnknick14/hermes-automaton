#!/usr/bin/env python3
"""
Multi-source revenue scanner for Hermes Agent
Continuously scans GitHub, freelance platforms, job boards, Reddit, and crypto bounties.
"""

import json
import os
import time
import requests
from datetime import datetime
from typing import Optional, Dict, Any, List
from pathlib import Path


# Revenue scanner - XML parsing is safe here (trusted RSS feeds only: Upwork, WWR)
# lgtm[python/xxe]

class RevenueScanner:
    """Base class for revenue scanners"""
    
    def __init__(self, agent):
        self.agent = agent
        self.api_key = agent.api_key
        self.api_base = agent.api_base
        self.model = agent.model
    
    def think(self, system_prompt: str, user_message: str, max_tokens: int = 2000) -> Optional[str]:
        """Call LongCat API for reasoning"""
        try:
            resp = requests.post(
                f"{self.api_base}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message}
                    ],
                    "max_tokens": max_tokens
                },
                timeout=60
            )
            if resp.status_code == 200:
                data = resp.json()
                # Handle both content and reasoning_content
                msg = data["choices"][0]["message"]
                content = msg.get("content") or msg.get("reasoning_content") or ""
                usage = data.get("usage", {})
                tokens = usage.get("total_tokens", 0)
                cost = (tokens / 1000) * 0.002
                self.agent.record_expense("inference", f"{self.__class__.__name__} ({tokens} tokens)", cost)
                return content if content else None
            self.agent.log("error", f"API {resp.status_code}: {resp.text[:200]}")
            return None
        except Exception as e:
            self.agent.log("error", f"Inference failed: {e}")
            return None


# ── GitHub Scanner ────────────────────────────────────────────

class GitHubScanner(RevenueScanner):
    """Scans GitHub for bounty issues and paid contributions"""
    
    def scan(self) -> List[dict]:
        opportunities = []
        queries = [
            "label:bounty state:open",
            "label:\"good first issue\" state:open",
            "label:\"help wanted\" state:open",
            "label:paid state:open",
            "label:money state:open",
        ]
        
        for query in queries:
            try:
                url = "https://api.github.com/search/issues"
                params = {
                    "q": query,
                    "sort": "created",
                    "order": "desc",
                    "per_page": 10
                }
                headers = {}
                github_token = os.environ.get("GITHUB_TOKEN", "")
                if github_token:
                    headers["Authorization"] = f"token {github_token}"
                
                resp = requests.get(url, params=params, headers=headers, timeout=15)
                if resp.status_code == 200:
                    data = resp.json()
                    for item in data.get("items", []):
                        opportunities.append({
                            "source": "github",
                            "type": "bounty",
                            "title": item["title"],
                            "url": item["html_url"],
                            "repo": item["repository_url"].split("/")[-1],
                            "created": item["created_at"],
                            "labels": [l["name"] for l in item.get("labels", [])],
                            "body": (item.get("body") or "")[:500]
                        })
                time.sleep(1)
            except Exception as e:
                self.agent.log("error", f"GitHub scan failed: {e}")
        
        return opportunities


# ── Freelance Platform Scanner ────────────────────────────────

class FreelanceScanner(RevenueScanner):
    """Scans Upwork, Freelancer, Fiverr for relevant jobs"""
    
    def scan(self) -> List[dict]:
        opportunities = []
        
        # Upwork RSS feeds
        upwork_categories = [
            "https://www.upwork.com/ab/feed/jobs/rss?q=python+automation&sort=recency",
            "https://www.upwork.com/ab/feed/jobs/rss?q=web+scraping&sort=recency",
            "https://www.upwork.com/ab/feed/jobs/rss?q=api+development&sort=recency",
            "https://www.upwork.com/ab/feed/jobs/rss?q=trading+bot&sort=recency",
        ]
        
        for feed_url in upwork_categories:
            try:
                resp = requests.get(feed_url, timeout=15)
                if resp.status_code == 200:
                    import xml.etree.ElementTree as ET
                    root = ET.fromstring(resp.content)
                    for item in root.findall('.//item')[:5]:
                        title = item.find('title')
                        link = item.find('link')
                        desc = item.find('description')
                        
                        if title is not None and link is not None:
                            opportunities.append({
                                "source": "upwork",
                                "type": "freelance_job",
                                "title": title.text[:200] if title.text else "",
                                "url": link.text,
                                "description": desc.text[:500] if desc is not None and desc.text else "",
                                "created": datetime.now().isoformat()
                            })
                time.sleep(1)
            except Exception as e:
                self.agent.log("error", f"Upwork scan failed: {e}")
        
        return opportunities


# ── Remote Job Board Scanner ──────────────────────────────────

class JobBoardScanner(RevenueScanner):
    """Scans remote job boards for contract/freelance work"""
    
    def scan(self) -> List[dict]:
        opportunities = []
        
        # RemoteOK
        try:
            resp = requests.get("https://remoteok.com/api", timeout=15)
            if resp.status_code == 200:
                jobs = resp.json()
                for job in jobs[:10]:
                    tags = job.get('tags', [])
                    if isinstance(tags, list) and any(t in ['python', 'automation', 'api', 'bot', 'crypto', 'trading'] for t in tags):
                        opportunities.append({
                            "source": "remoteok",
                            "type": "remote_job",
                            "title": job.get('position', ''),
                            "company": job.get('company', ''),
                            "url": job.get('url', ''),
                            "tags": tags,
                            "salary": job.get('salary', ''),
                            "created": datetime.now().isoformat()
                        })
        except Exception as e:
            self.agent.log("error", f"RemoteOK scan failed: {e}")
        
        # We Work Remotely (RSS)
        try:
            resp = requests.get("https://weworkremotely.com/remote-jobs.rss", timeout=15)
            if resp.status_code == 200:
                import xml.etree.ElementTree as ET
                root = ET.fromstring(resp.content)
                categories_of_interest = ['programming', 'backend', 'python', 'automation', 'crypto']
                for item in root.findall('.//item')[:10]:
                    title = item.find('title')
                    link = item.find('link')
                    category = item.find('category')
                    
                    if title is not None:
                        cat_text = category.text.lower() if category is not None else ''
                        title_text = title.text.lower() if title.text else ''
                        
                        if any(c in cat_text or c in title_text for c in categories_of_interest):
                            opportunities.append({
                                "source": "weworkremotely",
                                "type": "remote_job",
                                "title": title.text[:200] if title.text else "",
                                "url": link.text if link is not None else "",
                                "category": category.text if category is not None else "",
                                "created": datetime.now().isoformat()
                            })
        except Exception as e:
            self.agent.log("error", f"WWR scan failed: {e}")
        
        return opportunities


# ── Reddit Scanner ────────────────────────────────────────────

class RedditScanner(RevenueScanner):
    """Scans Reddit for paid opportunities"""
    
    def scan(self) -> List[dict]:
        opportunities = []
        
        subreddits = [
            "forhire",
            "slavelabour",
            "freelance",
            "hireawriter",
            "jobs4bitcoin",
            "cryptojobs",
        ]
        
        for sub in subreddits:
            try:
                url = f"https://www.reddit.com/r/{sub}/new.json"
                headers = {"User-Agent": "Hermes-Agent/1.0"}
                params = {"limit": 10}
                
                resp = requests.get(url, params=params, headers=headers, timeout=15)
                if resp.status_code == 200:
                    data = resp.json()
                    for post in data.get("data", {}).get("children", []):
                        p = post.get("data", {})
                        title = p.get("title", "").lower()
                        
                        # Filter for paid opportunities
                        if any(kw in title for kw in ["paid", "hiring", "freelance", "contract", "$", "usd", "money"]):
                            opportunities.append({
                                "source": "reddit",
                                "subreddit": sub,
                                "type": "paid_work",
                                "title": p.get("title", ""),
                                "url": f"https://reddit.com{p.get('permalink', '')}",
                                "selftext": p.get("selftext", "")[:300],
                                "created": datetime.fromtimestamp(p.get("created_utc", 0)).isoformat(),
                                "score": p.get("score", 0)
                            })
                time.sleep(2)  # Reddit rate limit
            except Exception as e:
                self.agent.log("error", f"Reddit r/{sub} scan failed: {e}")
        
        return opportunities


# ── Crypto Bounty Scanner ────────────────────────────────────

class CryptoBountyScanner(RevenueScanner):
    """Scans Gitcoin, Immunefi, and crypto bounty platforms"""
    
    def scan(self) -> List[dict]:
        opportunities = []
        
        # Gitcoin bounties
        try:
            url = "https://gitcoin.co/api/v0.1/bounties"
            params = {
                "network": "mainnet",
                "category": "all",
                "ordering": "-web3_created",
                "page": 1,
                "page_size": 10
            }
            resp = requests.get(url, params=params, timeout=15)
            if resp.status_code == 200:
                bounties = resp.json()
                if isinstance(bounties, list):
                    for bounty in bounties[:5]:
                        opportunities.append({
                            "source": "gitcoin",
                            "type": "crypto_bounty",
                            "title": bounty.get('title', ''),
                            "value": bounty.get('value_in_usdt', 0),
                            "url": bounty.get('url', ''),
                            "created": bounty.get('web3_created', ''),
                            "status": bounty.get('status', '')
                        })
        except Exception as e:
            self.agent.log("error", f"Gitcoin scan failed: {e}")
        
        # HackerOne (public bounties)
        try:
            url = "https://www.hackerone.com/disclosures.json"
            params = {"sort_field": "latest_disclosure_public", "sort_direction": "DESC", "page": 1}
            resp = requests.get(url, params=params, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                for item in data.get("data", [])[:5]:
                    opportunities.append({
                        "source": "hackerone",
                        "type": "security_bounty",
                        "title": item.get("name", ""),
                        "url": f"https://hackerone.com{item.get('url', '')}",
                        "bounties": item.get("bounties_count", 0),
                        "created": datetime.now().isoformat()
                    })
        except Exception as e:
            self.agent.log("error", f"HackerOne scan failed: {e}")
        
        return opportunities


# ── Hacker News Scanner ──────────────────────────────────────

class HNScanner(RevenueScanner):
    """Scans Hacker News for 'Who is Hiring' posts and freelance opportunities"""
    
    def scan(self) -> List[dict]:
        opportunities = []
        
        # Search Algolia HN for "who is hiring"
        try:
            url = "https://hn.algolia.com/api/v1/search_by_date"
            params = {
                "query": "who is hiring",
                "tags": "story",
                "hitsPerPage": 10
            }
            resp = requests.get(url, params=params, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                for hit in data.get("hits", []):
                    opportunities.append({
                        "source": "hackernews",
                        "type": "hiring_thread",
                        "title": hit.get("title", ""),
                        "url": hit.get("url", f"https://news.ycombinator.com/item?id={hit.get('objectID', '')}"),
                        "points": hit.get("points", 0),
                        "created": hit.get("created_at", "")
                    })
        except Exception as e:
            self.agent.log("error", f"HN scan failed: {e}")
        
        return opportunities


# ── Content Revenue Scanner ──────────────────────────────────

class ContentRevenueScanner(RevenueScanner):
    """Scans platforms where content can generate revenue"""
    
    def scan(self) -> List[dict]:
        opportunities = []
        
        # Dev.to - check trending topics
        try:
            resp = requests.get("https://dev.to/api/articles?top=30", timeout=15)
            if resp.status_code == 200:
                articles = resp.json()
                trending_tags = {}
                for article in articles:
                    for tag in article.get("tags", []):
                        trending_tags[tag] = trending_tags.get(tag, 0) + 1
                
                # Get top trending tags
                top_tags = sorted(trending_tags.items(), key=lambda x: x[1], reverse=True)[:10]
                for tag, count in top_tags:
                    opportunities.append({
                        "source": "devto",
                        "type": "content_opportunity",
                        "tag": tag,
                        "article_count": count,
                        "url": f"https://dev.to/t/{tag}",
                        "potential_revenue": "Medium Partner Program"
                    })
        except Exception as e:
            self.agent.log("error", f"Dev.to scan failed: {e}")
        
        return opportunities


# ── Unified Revenue Scanner ──────────────────────────────────

class UnifiedRevenueScanner(RevenueScanner):
    """Master scanner that runs all revenue source scanners"""
    
    def __init__(self, agent):
        super().__init__(agent)
        self.scanners = [
            GitHubScanner(agent),
            FreelanceScanner(agent),
            JobBoardScanner(agent),
            RedditScanner(agent),
            CryptoBountyScanner(agent),
            HNScanner(agent),
            ContentRevenueScanner(agent),
        ]
    
    def scan_all(self) -> List[dict]:
        """Scan all revenue sources"""
        all_opportunities = []
        
        for scanner in self.scanners:
            try:
                results = scanner.scan()
                all_opportunities.extend(results)
                self.agent.log("scan", f"{scanner.__class__.__name__}: {len(results)} found")
                time.sleep(1)  # Rate limit between sources
            except Exception as e:
                self.agent.log("error", f"{scanner.__class__.__name__} failed: {e}")
        
        return all_opportunities
    
    def analyze_opportunity(self, opp: dict) -> dict:
        """Analyze a single opportunity and score it"""
        system_prompt = """You are a pragmatic freelancer evaluating paid opportunities.
Score 0-100 based on:
- Payment certainty (will you actually get paid?)
- Skill fit (can you do this quickly?)
- Time to payment (how fast will you earn?)
- Competition (how many others want this?)

Return JSON: {"score": N, "reasoning": "...", "estimated_earnings_usd": N, "estimated_hours": N, "should_pursue": true/false}"""

        user_message = f"""Evaluate:
Source: {opp.get('source')}
Type: {opp.get('type')}
Title: {opp.get('title')}
Description: {opp.get('description', opp.get('selftext', opp.get('body', '')))[:300]}
Value: {opp.get('value', opp.get('salary', 'Unknown'))}
URL: {opp.get('url')}"""

        response = self.think(system_prompt, user_message, max_tokens=400)
        if response:
            try:
                import re
                json_match = re.search(r'\{.*\}', response, re.DOTALL)
                if json_match:
                    return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass
        return {"score": 0, "reasoning": "Analysis failed", "estimated_earnings_usd": 0, "estimated_hours": 0, "should_pursue": False}
    
    def run_full_scan(self) -> List[dict]:
        """Full scan pipeline: scan → analyze → filter → queue"""
        self.agent.log("work", "Starting full revenue scan across all sources...")
        
        # 1. Scan all sources
        all_opps = self.scan_all()
        self.agent.log("work", f"Total opportunities found: {len(all_opps)}")
        
        # 2. Analyze top opportunities (limit API spend)
        analyzed = []
        for opp in all_opps[:20]:  # Analyze top 20
            result = self.analyze_opportunity(opp)
            opp["analysis"] = result
            analyzed.append(opp)
        
        # 3. Sort by score
        analyzed.sort(key=lambda x: x.get("analysis", {}).get("score", 0), reverse=True)
        
        # Queue high-scoring opportunities (>= 20 to start — we need volume)
        queued = 0
        for opp in analyzed:
            score = opp.get("analysis", {}).get("score", 0)
            if score >= 20:
                self.agent.tasks["queue"].append({
                    "type": opp["type"],
                    "source": opp["source"],
                    "status": "queued",
                    "title": opp["title"][:200],
                    "url": opp["url"],
                    "score": opp["analysis"]["score"],
                    "created": datetime.now().isoformat()
                })
                queued += 1
        
        self.agent.log("work", f"Queued {queued} high-scoring opportunities")
        self.agent.save_state()
        
        return analyzed


# ── Main entry point ──────────────────────────────────────────

def scan_all_revenue_sources(agent):
    """Main function called by the agent's daily loop"""
    scanner = UnifiedRevenueScanner(agent)
    return scanner.run_full_scan()
