"""
TikTok API client — authenticated HTTP calls using cookies from DB.
"""
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

logger = logging.getLogger(__name__)

TIKTOK_BASE = "https://www.tiktok.com"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/152.0.0.0 Safari/537.36"
)


class TikTokAPI:
    def __init__(self, cookies: list):
        self._cookie_header = "; ".join(
            f"{c['name']}={c['value']}"
            for c in cookies
            if c.get("name") and c.get("value")
        )

    def _get(self, path: str, params: Optional[dict] = None, timeout: int = 15) -> dict:
        url = f"{TIKTOK_BASE}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
        req = urllib.request.Request(url, headers={
            "Cookie": self._cookie_header,
            "User-Agent": UA,
            "Referer": f"{TIKTOK_BASE}/tiktokstudio/",
            "Accept": "application/json",
            "x-tt-request-tag": "n=1;b=0",
        })
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            body = e.read()
            try:
                return json.loads(body)
            except Exception:
                return {"error": f"HTTP {e.code}"}
        except Exception as e:
            logger.warning("TikTokAPI request failed: %s", e)
            return {"error": str(e)}

    def get_profile(self) -> dict:
        """Full user profile from TikTok Studio."""
        data = self._get(
            "/tiktokstudio/api/web/user",
            params={"needIsVerified": "true", "needProfileBio": "true", "aid": "1988"},
        )
        if data.get("statusCode") != 0:
            return {"error": data.get("error", "Failed to fetch profile")}

        ub = data.get("userBaseInfo", {}).get("UserProfile", {})
        base = ub.get("UserBase", {})
        stats = ub.get("Stats", {})
        extra = data.get("userExtra", {})

        avatar_url = ""
        avatar_uris = base.get("AvatarUris", {})
        # Prefer full Google avatar URL (key "6"), fallback to TikTok CDN (key "1")
        for key in ("6", "1"):
            if key in avatar_uris:
                uri = avatar_uris[key]
                if uri.startswith("http"):
                    avatar_url = uri
                elif uri:
                    avatar_url = f"https://p16-sign.tiktokcdn-us.com/{uri}"
                break

        region_obj = base.get("Region", {})
        reg_country = (region_obj.get("RegistrationCountry") or region_obj.get("Region") or "").upper()

        # Stats no longer returned by Studio API — fetch from analytics
        followers = 0
        try:
            ar = self._get("/tiktok/v1/analytics/insights/", params={
                "locale": "en", "aid": "1988", "region": reg_country,
                "app_name": "tiktok_creator_center", "app_language": "en",
                "device_platform": "web_pc", "channel": "tiktok_web", "os": "mac",
                "type_requests": json.dumps([{"insight_type": 160, "data_date_range": 1}]),
                "time_offset": "10800", "is_dark_mode": "false",
            })
            ft = ar.get("analytics_follower_total_followers", {})
            tot = ft.get("total")
            if isinstance(tot, dict):
                followers = tot.get("value") or 0
            elif isinstance(tot, (int, float)):
                followers = int(tot)
        except Exception:
            pass

        return {
            "user_id": base.get("Id", ""),
            "nickname": base.get("NickName", ""),
            "unique_id": base.get("UniqId", ""),
            "sec_uid": base.get("SecUid", ""),
            "region": region_obj.get("Region", ""),
            "registration_country": region_obj.get("RegistrationCountry", ""),
            "language": base.get("Language", {}).get("Language", ""),
            "avatar_url": avatar_url,
            "is_verified": extra.get("isVerified", False),
            "is_private": extra.get("isPrivate", False),
            "bio": extra.get("profileBio", ""),
            "created_at_ts": int(base.get("CreateTime", 0)),
            "modified_at_ts": int(base.get("ModifyTime", 0)),
            "followers": followers,
            "following": None,
            "likes": None,
            "video_count": None,
            "has_cert": base.get("CertInfo", {}).get("HasCert", False),
        }

    def get_upload_settings(self) -> dict:
        """Creator upload settings."""
        data = self._get(
            "/api/v1/user/profile/upload/",
            params={"aid": "1988", "enter_post_page_from": "8"},
        )
        if data.get("status_code") != 0:
            return {"error": data.get("status_msg", "Failed")}
        u = data.get("user", {})

        SETTING_LABELS = {0: "Все", 1: "Друзья", 2: "Выкл"}

        return {
            "uid": u.get("uid", ""),
            "nickname": u.get("nickname", ""),
            "unique_id": u.get("unique_id", ""),
            "max_video_duration_sec": u.get("max_video_duration_in_sec", 0),
            "longvideo_permission": u.get("longvideo_permission", False),
            "schedule_enable": u.get("schedule_enable", False),
            "schedule_storage": u.get("schedule_storage", False),
            "bulk_upload_enable": u.get("bulk_upload_enable", False),
            "comment_setting": u.get("comment_setting", 0),
            "comment_setting_label": SETTING_LABELS.get(u.get("comment_setting", 0), "?"),
            "duet_setting": u.get("duet_setting", 0),
            "duet_setting_label": SETTING_LABELS.get(u.get("duet_setting", 0), "?"),
            "stitch_setting": u.get("stitch_setting", 0),
            "stitch_setting_label": SETTING_LABELS.get(u.get("stitch_setting", 0), "?"),
            "geofencing_enabled": u.get("geofencing_enabled", False),
            "geofencing_regions": [r for r in u.get("geofencing_regions", []) if r],
            "playlist_enable": u.get("playlist_enable", False),
            "draft_cloud_enable": u.get("draft_settings", {}).get("cloud_draft_enable", False),
            "draft_limitation": u.get("draft_settings", {}).get("draft_limitation", 0),
            "video_split_count_limit": u.get("video_split_count_limit", 0),
            "age_interval": u.get("age_interval", 0),
        }

    def get_analytics(self, days: int = 28) -> dict:
        """Legacy analytics insights (kept for compat)."""
        return {}

    def get_deep_analytics(self, days: int = 28) -> dict:
        """Fetch analytics from TikTok Studio analytics API."""
        # Exact insight_type → response key mapping (discovered by scanning live API)
        # Types 121-166 are the ones that actually return data
        INSIGHT_TYPES = [
            121,  # analytics_overview_views
            122,  # analytics_overview_profile_views
            123,  # analytics_overview_likes
            124,  # analytics_overview_comments
            125,  # analytics_overview_shares
            140,  # analytics_viewer_new_viewer
            141,  # analytics_viewer_total_viewer
            145,  # analytics_viewer_active_days
            146,  # analytics_viewer_active_hours
            160,  # analytics_follower_total_followers
            161,  # analytics_follower_net_followers
        ]

        # Fetch user profile to get region/locale for correct API params
        try:
            profile = self.get_profile()
            region = profile.get("region") or ""
            reg_country = profile.get("registration_country") or region or ""
        except Exception:
            region = ""
            reg_country = ""

        type_requests = [{"insight_type": t, "data_date_range": days} for t in INSIGHT_TYPES]

        raw = self._get(
            "/tiktok/v1/analytics/insights/",
            params={
                "locale": "en",
                "aid": "1988",
                "region": reg_country.upper() if reg_country else "",
                "app_name": "tiktok_creator_center",
                "app_language": "en",
                "device_platform": "web_pc",
                "channel": "tiktok_web",
                "os": "mac",
                "type_requests": json.dumps(type_requests),
                "time_offset": "10800",
                "is_dark_mode": "false",
            },
        )

        if raw.get("status_code") not in (0, None):
            return {"error": raw.get("status_msg", "Analytics fetch failed")}

        def parse_series(obj):
            """Extract time series.
            API returns: {"list": {"value": [{"message": {"timestamp": N}, "value": V}, ...]}}
            """
            import datetime
            if not obj or not isinstance(obj, dict):
                return []
            # New format: list is a dict with a "value" array
            list_obj = obj.get("list")
            if isinstance(list_obj, dict):
                items = list_obj.get("value") or []
            elif isinstance(list_obj, list):
                items = list_obj
            else:
                items = obj.get("key_value") or []
            result = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                # {message: {timestamp: N}, value: V}
                if "message" in item:
                    ts = item["message"].get("timestamp", 0)
                    if ts > 1e12:
                        ts = ts // 1000
                    try:
                        d = datetime.datetime.utcfromtimestamp(ts)
                        date_key = d.strftime("%Y%m%d")
                    except Exception:
                        date_key = str(ts)
                    result.append({"date": date_key, "value": item.get("value", 0)})
                # key_value format: {key: "20260910", value: 123}
                elif "key" in item:
                    result.append({"date": item["key"], "value": item.get("value", 0)})
            return result

        def _scalar(d):
            """Extract scalar value from {value: N} or {value: {value: N}} or N."""
            if d is None:
                return None
            if isinstance(d, (int, float)):
                return d
            if isinstance(d, dict):
                v = d.get("value")
                if isinstance(v, (int, float)):
                    return v
                if isinstance(v, dict):
                    return v.get("value")
            return None

        def parse_total(obj):
            if not obj or not isinstance(obj, dict):
                return None
            return _scalar(obj.get("total"))

        def parse_delta(obj):
            if not obj or not isinstance(obj, dict):
                return None
            return _scalar(obj.get("delta_change"))

        def parse_pct(obj):
            if not obj or not isinstance(obj, dict):
                return None
            return _scalar(obj.get("percent_change"))

        # Map API response keys to our friendly keys
        KEY_MAP = {
            "analytics_overview_views":           "views",
            "analytics_overview_likes":           "likes",
            "analytics_overview_shares":          "shares",
            "analytics_overview_comments":        "comments",
            "analytics_overview_profile_views":   "profile_views",
            "analytics_follower_total_followers": "followers",
            "analytics_follower_net_followers":   "net_followers",
            "analytics_viewer_active_days":       "active_days",
            "analytics_viewer_active_hours":      "active_hours",
            "analytics_viewer_new_viewer":        "new_viewers",
            "analytics_viewer_total_viewer":      "total_viewers",
        }

        result = {}
        for api_key, our_key in KEY_MAP.items():
            obj = raw.get(api_key)
            if obj:
                result[our_key] = {
                    "series": parse_series(obj),
                    "total": parse_total(obj),
                    "delta": parse_delta(obj),
                    "pct_change": parse_pct(obj),
                }

        # Parse active_hours into 24-slot array for heatmap
        if "active_hours" in result:
            hours_raw = raw.get("analytics_viewer_active_hours", {})
            hours_agg = [0] * 24
            # list is {value: [{message:{timestamp}, value: [{key: "0", value: N}, ...]}]}
            list_obj = hours_raw.get("list", {})
            day_items = list_obj.get("value") if isinstance(list_obj, dict) else (list_obj or [])
            for day_entry in (day_items or []):
                if not isinstance(day_entry, dict):
                    continue
                hour_list = day_entry.get("value")
                if isinstance(hour_list, list):
                    for hour_entry in hour_list:
                        if isinstance(hour_entry, dict):
                            try:
                                h = int(hour_entry.get("key", -1))
                                v = hour_entry.get("value", 0) or 0
                                if 0 <= h < 24:
                                    hours_agg[h] += v
                            except Exception:
                                pass
            result["active_hours"]["hourly"] = hours_agg

        result["days"] = days
        return result

    def get_video_list(self, max_count: int = 200) -> list:
        """NOTE: TikTok requires X-Bogus/X-Gnarly JS signatures for this endpoint.
        This method always returns [] — use TikTokUploader.get_video_list() (Selenium) instead."""
        videos = []
        cursor = 0
        page_size = 20

        while len(videos) < max_count:
            data = self._get(
                "/tiktokstudio/api/web/content/post/list",
                params={
                    "aid": "1988",
                    "count": page_size,
                    "cursor": cursor,
                    "type": "0",  # 0 = all posts
                },
                timeout=20,
            )

            status = data.get("statusCode") or data.get("status_code") or data.get("code")
            if status not in (0, None, 200) and status is not None:
                logger.warning("get_video_list API error: %s", data)
                break

            posts = data.get("posts") or data.get("items") or data.get("videoList") or []
            if not posts:
                break

            for post in posts:
                video_id = str(post.get("itemId") or post.get("id") or post.get("videoId") or "")
                if not video_id:
                    continue

                # Stats
                stats = post.get("stats") or post.get("statistics") or {}
                views   = stats.get("playCount") or stats.get("viewCount") or stats.get("play_count") or 0
                likes   = stats.get("diggCount") or stats.get("likeCount") or stats.get("digg_count") or 0
                comments = stats.get("commentCount") or stats.get("comment_count") or 0
                shares  = stats.get("shareCount") or stats.get("share_count") or 0

                # Meta
                desc = post.get("desc") or post.get("description") or post.get("text") or ""
                create_time = post.get("createTime") or post.get("create_time") or 0
                if create_time:
                    import datetime
                    dt = datetime.datetime.utcfromtimestamp(int(create_time))
                    date_str = dt.strftime("%b %d, %Y")
                else:
                    date_str = ""

                # Thumbnail
                video_info = post.get("video") or {}
                cover = video_info.get("cover") or video_info.get("originCover") or video_info.get("dynamicCover") or ""
                if not cover:
                    cover = post.get("cover") or post.get("thumbnail") or ""

                # Duration
                duration_sec = video_info.get("duration") or post.get("duration") or 0
                if duration_sec:
                    m, s = divmod(int(duration_sec), 60)
                    duration_str = f"{m}:{s:02d}"
                else:
                    duration_str = ""

                # Privacy
                privacy_map = {0: "Public", 1: "Friends", 2: "Only me", 3: "Followers only"}
                privacy_val = post.get("privacy") or post.get("privacyLevel") or post.get("privacy_level") or 0
                privacy = privacy_map.get(int(privacy_val), str(privacy_val))

                videos.append({
                    "video_id": video_id,
                    "url": f"https://www.tiktok.com/@_/video/{video_id}",
                    "description": desc,
                    "date": date_str,
                    "thumbnail": cover,
                    "duration": duration_str,
                    "privacy": privacy,
                    "views": views,
                    "likes": likes,
                    "comments": comments,
                    "shares": shares,
                })

            has_more = data.get("hasMore") or data.get("has_more") or data.get("cursor") not in (None, 0)
            next_cursor = data.get("cursor") or data.get("nextCursor") or 0
            if not has_more or next_cursor == cursor or not posts:
                break
            cursor = next_cursor

        return videos

    def get_all(self) -> dict:
        """Fetch all available data."""
        profile = self.get_profile()
        settings = self.get_upload_settings()
        analytics = self.get_analytics()
        return {
            "profile": profile,
            "settings": settings,
            "analytics": analytics,
            "fetched_at": int(time.time()),
        }
