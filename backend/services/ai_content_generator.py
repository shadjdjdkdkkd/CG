"""
AI Content Generator Service - For generating SEO-optimized blog content
"""
import os
import json
import uuid
import re
from datetime import datetime, timezone
from emergentintegrations.llm.chat import LlmChat, UserMessage
from services.gemini_llm import GeminiChat

# AI Content Generator Class
class AIContentGenerator:
    def __init__(self, db):
        self.db = db
        self.api_key = os.environ.get('GEMINI_API_KEY') or os.environ.get('EMERGENT_LLM_KEY')
        
    async def generate_blog_article(self, topic: str, keywords: list = None, target_audience: str = "Indian adults 28+"):
        """Generate a complete SEO-optimized blog article about anti-aging skincare"""
        
        if not self.api_key:
            raise ValueError("No AI key configured (set GEMINI_API_KEY)")
        
        keywords_str = ", ".join(keywords) if keywords else "anti-aging, skincare, serum, wrinkles, fine lines"
        
        system_message = """You are an expert skincare and beauty content writer specializing in anti-aging products for the Indian market. 
        You write engaging, SEO-optimized blog articles that are informative yet accessible.
        Always include practical tips and relate content to Celesta Glow Anti-Aging Serum where appropriate.
        Write in a warm, professional tone that resonates with Indian readers."""
        
        prompt = f"""Write a comprehensive, SEO-optimized blog article about: {topic}

Target Audience: {target_audience}
Target Keywords: {keywords_str}

Please provide the response in the following JSON format:
{{
    "title": "Compelling SEO-friendly title (50-60 characters)",
    "meta_description": "Engaging meta description (150-160 characters)",
    "content": "Full HTML-formatted article content with h2, h3, p, ul, li tags. Include 800-1200 words.",
    "keywords": ["keyword1", "keyword2", "keyword3", "keyword4", "keyword5"],
    "suggested_internal_links": ["related topic 1", "related topic 2"]
}}

Make the content:
1. Informative and backed by skincare science
2. Naturally incorporate the target keywords
3. Include practical tips and actionable advice
4. Reference how Celesta Glow can help (subtly, not pushy)
5. Optimized for Indian readers and climate considerations
6. Use proper HTML formatting for headings, paragraphs, and lists"""

        try:
            chat = GeminiChat(
                api_key=self.api_key,
                session_id=f"blog-gen-{uuid.uuid4().hex[:8]}",
                system_message=system_message
            ).with_model("gemini", "gemini-2.5-flash")
            
            user_message = UserMessage(text=prompt)
            response = await chat.send_message(user_message)
            
            # Parse JSON from response
            # Try to extract JSON from the response
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                article_data = json.loads(json_match.group())
            else:
                raise ValueError("Could not parse JSON from AI response")
            
            return {
                "success": True,
                "article": article_data,
                "generated_at": datetime.now(timezone.utc).isoformat()
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    async def generate_location_content(self, state: str, city: str = None):
        """Generate location-specific content for SEO pages"""
        
        if not self.api_key:
            raise ValueError("No AI key configured (set GEMINI_API_KEY)")
        
        location = f"{city}, {state}" if city else state
        
        system_message = """You are a skincare expert who understands how different Indian climates and environments affect skin health.
        You create localized content that resonates with people from specific regions of India."""
        
        prompt = f"""Create location-specific skincare content for {location}, India.

Please provide the response in the following JSON format:
{{
    "title": "Anti-Aging Skincare in {location}",
    "description": "2-3 sentences about skincare needs specific to {location}",
    "climate": "Brief description of the local climate",
    "skin_issues": ["common skin issue 1", "common skin issue 2", "common skin issue 3"],
    "recommendations": "Personalized skincare advice for people in {location}",
    "local_tips": "1-2 tips specific to the local environment"
}}

Consider:
1. Local climate (humidity, pollution, sun exposure)
2. Common skin concerns in that region
3. How Celesta Glow's ingredients address local needs"""

        try:
            chat = GeminiChat(
                api_key=self.api_key,
                session_id=f"location-gen-{uuid.uuid4().hex[:8]}",
                system_message=system_message
            ).with_model("gemini", "gemini-2.5-flash")
            
            user_message = UserMessage(text=prompt)
            response = await chat.send_message(user_message)
            
            # Parse JSON from response
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                location_data = json.loads(json_match.group())
            else:
                raise ValueError("Could not parse JSON from AI response")
            
            return {
                "success": True,
                "content": location_data,
                "generated_at": datetime.now(timezone.utc).isoformat()
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    async def suggest_blog_topics(self, count: int = 5, format: str = "full"):
        """Generate blog topic suggestions based on trending skincare topics
        
        Args:
            count: Number of topics to generate
            format: 'full' for objects with description, 'simple' for title strings only
        """
        
        if not self.api_key:
            raise ValueError("No AI key configured (set GEMINI_API_KEY)")
        
        from datetime import datetime
        current_month = datetime.now().strftime("%B %Y")
        current_day = datetime.now().strftime("%A")
        current_hour = datetime.now().hour
        current_date = datetime.now().strftime("%d %B %Y")
        
        # Time of day context for more relevant topics
        time_context = "morning" if 6 <= current_hour < 12 else "afternoon" if 12 <= current_hour < 17 else "evening" if 17 <= current_hour < 21 else "night"
        
        if format == "simple":
            # Simple format - just topic titles as strings
            prompt = f"""Generate exactly {count} FRESH and UNIQUE skincare blog topic titles for RIGHT NOW - {current_day}, {current_date}, {time_context} time in India.

Requirements:
- Target audience: Indian men AND women aged 25-55
- Topics: anti-aging, skincare tips, celebrity beauty secrets, ingredient education
- Each title should be catchy, specific, and SEO-friendly (50-70 characters)
- Mix different types: celebrity secrets, DIY remedies, seasonal tips, ingredient guides, routines
- MUST be relevant to current trends and season
- Include at least one topic specifically for men's anti-aging

IMPORTANT: 
1. These topics must be DIFFERENT from previous suggestions - generate completely NEW ideas
2. Return ONLY a JSON array of topic title strings. Example:
["Celebrity Beauty Secret: How Deepika Maintains Youthful Skin", "Men's Anti-Aging Guide: Varun Dhawan's Skincare Routine"]

Do NOT return objects or explanations - ONLY an array of {count} topic title strings."""
            system_msg = "You return ONLY JSON arrays of strings. No objects, no explanations. Generate UNIQUE topics each time."
        else:
            # Full format - objects with topic, description, keywords
            prompt = f"""Generate {count} FRESH and UNIQUE skincare blog topic ideas for Indian men AND women aged 25-55.

Current context: {current_day}, {current_date}, {time_context} time in India.

Return ONLY a valid JSON array with this exact structure (no extra text):
[
  {{"topic": "Title here", "description": "Brief description", "keywords": ["kw1", "kw2"], "difficulty": "easy"}},
  {{"topic": "Title 2", "description": "Description 2", "keywords": ["kw1"], "difficulty": "medium"}}
]

Topics should:
- Cover anti-aging, skincare trends, celebrity secrets (both male & female), ingredient guides
- Be relevant to current trends and season
- Include at least one topic for men's skincare
- Be COMPLETELY DIFFERENT from any previous suggestions

Current date context: {current_day}, {current_date}"""
            system_msg = "You return ONLY valid JSON arrays. No markdown, no explanation. Generate UNIQUE topics each time."

        try:
            chat = GeminiChat(
                api_key=self.api_key,
                session_id=f"topics-gen-{uuid.uuid4().hex[:8]}",
                system_message=system_msg
            ).with_model("gemini", "gemini-2.5-flash")
            
            user_message = UserMessage(text=prompt)
            response = await chat.send_message(user_message)
            
            # Parse JSON array from response - use greedy match to get full array
            json_match = re.search(r'\[[\s\S]*\]', response)
            if json_match:
                json_str = json_match.group()
                
                # Clean up common JSON issues
                json_str = re.sub(r',\s*]', ']', json_str)  # Remove trailing commas before ]
                json_str = re.sub(r',\s*}', '}', json_str)  # Remove trailing commas before }
                json_str = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', json_str)  # Remove control characters
                json_str = json_str.replace('\n', ' ').replace('\r', '')  # Remove newlines in strings
                
                try:
                    topics_raw = json.loads(json_str)
                except json.JSONDecodeError as e:
                    # If still fails, return error with details
                    return {"success": False, "error": f"JSON parse error: {str(e)}", "raw": json_str[:200]}
                
                if format == "simple":
                    # Extract simple strings from any complex structure
                    topics = []
                    for t in topics_raw:
                        if isinstance(t, str):
                            topics.append(t)
                        elif isinstance(t, dict):
                            topics.append(t.get('topic', t.get('title', str(t))))
                    return {"success": True, "topics": topics}
                else:
                    # Return full objects - ensure each has required fields
                    topics = []
                    for t in topics_raw:
                        if isinstance(t, dict):
                            topics.append({
                                "topic": t.get('topic', t.get('title', 'Untitled')),
                                "description": t.get('description', ''),
                                "keywords": t.get('keywords', []),
                                "difficulty": t.get('difficulty', 'medium')
                            })
                        elif isinstance(t, str):
                            topics.append({
                                "topic": t,
                                "description": "",
                                "keywords": [],
                                "difficulty": "medium"
                            })
                    return {"success": True, "topics": topics}
            else:
                raise ValueError("Could not parse JSON from AI response")
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }



# --- Module-level helper used by product creation routes ---------------------
_REVIEW_NAMES = [
    "Priya S.", "Riya M.", "Anjali K.", "Sneha R.", "Kavya P.", "Neha T.",
    "Meera J.", "Ishita R.", "Divya M.", "Tanvi K.", "Pooja G.", "Shruti V.",
]
_REVIEW_CITIES = ["Mumbai", "Delhi", "Bengaluru", "Hyderabad", "Pune", "Chennai", "Jaipur", "Kolkata"]


async def generate_product_reviews(name: str, niche: str = "skincare",
                                   key_ingredients: str = "", benefits: list = None) -> list:
    """Generate a small set of personalised product reviews.

    Tries the AI first; on any failure (e.g. exhausted key) falls back to a
    deterministic, product-tailored template set so product creation NEVER
    breaks and never burns extra credits. Returns a list of review dicts.
    """
    import random as _r
    benefits = benefits or []

    def _mk(body: str) -> dict:
        return {
            "id": uuid.uuid4().hex[:12],
            "name": _r.choice(_REVIEW_NAMES),
            "location": _r.choice(_REVIEW_CITIES),
            "rating": 5 if _r.random() < 0.85 else 4,
            "body": body,
            "tag": niche or "skincare",
            "days": _r.randint(7, 90),
            "age": _r.choice([None, 25, 28, 31, 34, 38, 42, 45]),
            "verified": True,
        }

    benefit_txt = (benefits[0] if benefits else "healthier skin")
    # AI attempt (best-effort; cheap single text call)
    api_key = os.environ.get('GEMINI_API_KEY') or os.environ.get('EMERGENT_LLM_KEY')
    if api_key:
        try:
            chat = GeminiChat(
                api_key=api_key,
                session_id=f"rev-{uuid.uuid4().hex[:8]}",
                system_message="You write short, genuine-sounding product reviews.",
            ).with_model("gemini", "gemini-2.5-flash")
            prompt = (
                f"Write 4 short, realistic, positive customer reviews (1-2 sentences each) for the Indian "
                f"skincare product '{name}' (key ingredients: {key_ingredients or 'gentle actives'}; main benefit: "
                f"{benefit_txt}). Return STRICT JSON only: {{\"reviews\": [\"...\", \"...\", \"...\", \"...\"]}}. "
                "Sound like real Indian customers, mention visible results, no medical claims."
            )
            resp = await chat.send_message(UserMessage(text=prompt))
            m = re.search(r"\{[\s\S]*\}", resp or "")
            if m:
                data = json.loads(m.group(0))
                bodies = [str(b)[:300] for b in (data.get("reviews") or []) if str(b).strip()][:4]
                if bodies:
                    return [_mk(b) for b in bodies]
        except Exception:
            pass  # fall through to templates

    # Deterministic fallback (no credits spent)
    templates = [
        f"Been using the {name} for 3 weeks and my skin feels so much better. {benefit_txt} is real!",
        f"Love the texture of this {name}. Absorbs quickly and my skin looks brighter already.",
        f"Gentle yet effective. The {name} has become a permanent part of my routine.",
        f"Visible difference in about two weeks. Definitely recommend the {name}.",
    ]
    return [_mk(t) for t in templates]
